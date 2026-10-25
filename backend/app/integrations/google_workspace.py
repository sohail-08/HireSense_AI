from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google_auth_httplib2 import AuthorizedHttp
from httplib2 import Http


GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)


@dataclass(frozen=True)
class GoogleDriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None


class GoogleWorkspaceReader(Protocol):
    def read_sheet(
        self,
        *,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> list[list[str]]:
        ...

    def get_file(self, file_id: str) -> GoogleDriveFile:
        ...

    def C(
        self,
        *,
        file_id: str,
        destination: Path,
        max_bytes: int,
    ) -> int:
        ...


class GoogleServiceAccountReader:
    def __init__(self, credential_file: str | Path, *, sheet_timeout_seconds: int | None = None, file_timeout_seconds: int | None = None):
        path = Path(credential_file).expanduser()
        if not path.is_file():
            raise RuntimeError(
                f"Google service-account file not found at {path}"
            )
        try:
            credentials = service_account.Credentials.from_service_account_file(
                str(path),
                scopes=GOOGLE_SCOPES,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "Google service-account credentials could not be loaded"
            ) from exc

        sheet_transport = ({"http": AuthorizedHttp(credentials, http=Http(timeout=sheet_timeout_seconds))}
            if sheet_timeout_seconds is not None else {"credentials": credentials})
        self._sheets = build(
            "sheets",
            "v4",
            **sheet_transport,
            cache_discovery=False,
        )
        file_transport = ({"http": AuthorizedHttp(credentials, http=Http(timeout=file_timeout_seconds))}
            if file_timeout_seconds is not None else {"credentials": credentials})
        self._drive = build(
            "drive",
            "v3",
            **file_transport,
            cache_discovery=False,
        )

    def read_sheet(
        self,
        *,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> list[list[str]]:
        safe_sheet_name = sheet_name.replace("'", "''")
        try:
            result = (
                self._sheets.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{safe_sheet_name}'",
                    majorDimension="ROWS",
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(
                "Google Sheets could not be read. Share the response sheet "
                "with the service-account email and verify the spreadsheet ID."
            ) from exc
        return result.get("values", [])

    def get_file(self, file_id: str) -> GoogleDriveFile:
        try:
            data = (
                self._drive.files()
                .get(fileId=file_id, fields="id,name,mimeType,size")
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(
                "A CV file could not be accessed in Google Drive. Share the "
                "Form upload folder with the service-account email."
            ) from exc
        raw_size = data.get("size")
        return GoogleDriveFile(
            id=data["id"],
            name=data.get("name") or f"{file_id}.bin",
            mime_type=data.get("mimeType") or "application/octet-stream",
            size=int(raw_size) if raw_size is not None else None,
        )

    def download_file(
        self,
        *,
        file_id: str,
        destination: Path,
        max_bytes: int,
    ) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            request = self._drive.files().get_media(fileId=file_id)
            with temporary.open("wb") as target:
                downloader = MediaIoBaseDownload(
                    target,
                    request,
                    chunksize=min(1024 * 1024, max_bytes),
                )
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                    if target.tell() > max_bytes:
                        raise ValueError("CV exceeds the configured file-size limit")
            size = temporary.stat().st_size
            if size == 0:
                raise ValueError("Google Drive returned an empty CV file")
            temporary.replace(destination)
            return size
        except HttpError as exc:
            raise RuntimeError("A CV file could not be downloaded from Drive") from exc
        finally:
            temporary.unlink(missing_ok=True)
