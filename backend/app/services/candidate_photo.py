"""Private, on-demand application-photo display; no biometric retention or inference."""
import tempfile
from pathlib import Path

from app.config import get_settings
from app.identity.face import image_bytes
from app.integrations.google_workspace import GoogleServiceAccountReader
from app.models.candidate import CandidateApplication, ApplicationSource
from app.services.google_forms_intake_service import GoogleFormsIntakeService
from app.services.interview_rooms import InterviewRooms


class CandidatePhotoUnavailable(RuntimeError):
    pass


class CandidatePhotoService:
    def __init__(self, settings=None, reader=None, rooms=None):
        self.settings = settings or get_settings()
        self.reader = reader
        self.rooms = rooms or InterviewRooms(self.settings)

    def source(self, db, user_id, interview_id):
        # Authorize before constructing a Google client or touching remote files.
        interview = self.rooms.owned(db, user_id, interview_id)
        application = db.get(CandidateApplication, interview.application_id)
        if not application or application.source != ApplicationSource.GOOGLE_FORM:
            raise LookupError("Candidate photo is not available")
        record = application.response_data or {}
        headers = [key for key in record if not str(key).startswith("_")]
        column = GoogleFormsIntakeService._find_header(headers, self.settings.google_forms_photo_column,
            ("candidate photo", "upload your photo"))
        ids = GoogleFormsIntakeService._drive_file_ids(str(record[headers[column]] or "")) if column is not None else []
        if len(ids) != 1:
            raise LookupError("Candidate photo is not available")
        return application.id, ids[0]

    def photo(self, db, user_id, interview_id):
        source = self.source(db, user_id, interview_id)
        db.rollback()  # Do not hold database transactions while downloading.
        try:
            reader = self.reader or GoogleServiceAccountReader(self.settings.google_service_account_file,
                sheet_timeout_seconds=15, file_timeout_seconds=15)
            metadata = reader.get_file(source[1])
            limit = 3 * 1024 * 1024
            if metadata.mime_type not in {"image/jpeg", "image/png"} or (metadata.size is not None and not 0 < metadata.size <= limit):
                raise ValueError()
            with tempfile.TemporaryDirectory(prefix="hiresense-profile-photo-") as temporary:
                path = Path(temporary) / "photo"
                reader.download_file(file_id=source[1], destination=path, max_bytes=limit)
                # Validate real bytes, strip EXIF/location data and bound dimensions.
                # This sanitizes an ordinary profile image; it never makes a template.
                result = image_bytes(path.read_bytes())
        except Exception:
            raise CandidatePhotoUnavailable("Candidate photo is temporarily unavailable") from None
        # Recheck access/source after I/O in case an application was deleted or changed.
        if self.source(db, user_id, interview_id) != source:
            raise LookupError("Candidate photo changed; refresh the candidate information")
        return result
