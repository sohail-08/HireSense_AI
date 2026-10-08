import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from app.config import Settings
from app.models.candidate import CVDocument


SUPPORTED_SUFFIXES = {".pdf", ".docx"}


class CVReviewRequired(ValueError):
    """The document cannot receive a reliable automatic assessment."""


@dataclass(frozen=True)
class SourceBlock:
    id: str
    locator: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "locator": self.locator, "text": self.text}


@dataclass(frozen=True)
class ParsedCV:
    text: str
    blocks: list[SourceBlock]
    parser: str
    page_count: int | None
    warnings: list[str]


class CVParser:
    def __init__(self, settings: Settings):
        self.settings = settings

    def parse(self, document: CVDocument) -> ParsedCV:
        path = self._trusted_path(document.storage_path)
        self._validate_file(path, document)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            parsed = self._parse_pdf(path)
        elif suffix == ".docx":
            parsed = self._parse_docx(path)
        else:
            raise CVReviewRequired("Only PDF and DOCX CV files are supported")
        normalized = parsed.text.strip()
        if len(normalized) < self.settings.cv_min_extract_characters:
            raise CVReviewRequired(
                "The CV contains too little extractable text. It may be scanned, "
                "encrypted, empty, or corrupt; review it manually."
            )
        if len(normalized) > self.settings.cv_max_characters:
            raise CVReviewRequired(
                "The CV exceeds the configured extraction complexity limit; "
                "review it manually instead of silently truncating it."
            )
        return parsed

    def _trusted_path(self, relative_path: str) -> Path:
        root = Path(self.settings.storage_root).expanduser().resolve()
        cv_root = (root / "cvs").resolve()
        path = (root / relative_path).resolve()
        if path != cv_root and cv_root not in path.parents:
            raise CVReviewRequired("The saved CV reference is outside private storage")
        if not path.is_file():
            raise CVReviewRequired("The saved CV file is missing from private storage")
        return path

    def _validate_file(self, path: Path, document: CVDocument) -> None:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise CVReviewRequired("Only PDF and DOCX CV files are supported")
        size = path.stat().st_size
        max_bytes = self.settings.cv_max_file_size_mb * 1024 * 1024
        if size == 0:
            raise CVReviewRequired("The saved CV file is empty")
        if size > max_bytes:
            raise CVReviewRequired(
                f"The CV exceeds the {self.settings.cv_max_file_size_mb} MB limit"
            )
        if suffix == ".pdf":
            with path.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    raise CVReviewRequired("The file extension is PDF but its content is not")
        elif not zipfile.is_zipfile(path):
            raise CVReviewRequired("The file extension is DOCX but its content is not")

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if document.sha256 and digest.hexdigest() != document.sha256:
            raise CVReviewRequired(
                "The locally stored CV no longer matches its recorded checksum"
            )

    def _parse_pdf(self, path: Path) -> ParsedCV:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise CVReviewRequired("Encrypted PDFs require manual review")
            if len(reader.pages) > self.settings.cv_max_pages:
                raise CVReviewRequired(
                    f"The PDF exceeds the {self.settings.cv_max_pages}-page limit"
                )
            blocks: list[SourceBlock] = []
            warnings: list[str] = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = self._clean_text(page.extract_text() or "")
                if text:
                    blocks.append(
                        SourceBlock(
                            id=f"pdf-page-{page_number}",
                            locator=f"PDF page {page_number}",
                            text=text,
                        )
                    )
                else:
                    warnings.append(f"No text was extracted from PDF page {page_number}")
        except CVReviewRequired:
            raise
        except Exception as exc:
            raise CVReviewRequired("The PDF is corrupt or unreadable") from exc
        return ParsedCV(
            text="\n\n".join(block.text for block in blocks),
            blocks=blocks,
            parser="pypdf",
            page_count=len(reader.pages),
            warnings=warnings,
        )

    def _parse_docx(self, path: Path) -> ParsedCV:
        try:
            source = Document(str(path))
            blocks: list[SourceBlock] = []
            for index, paragraph in enumerate(source.paragraphs, start=1):
                text = self._clean_text(paragraph.text)
                if text:
                    blocks.append(
                        SourceBlock(
                            id=f"docx-paragraph-{index}",
                            locator=f"DOCX paragraph {index}",
                            text=text,
                        )
                    )
            for table_index, table in enumerate(source.tables, start=1):
                for row_index, row in enumerate(table.rows, start=1):
                    values = [self._clean_text(cell.text) for cell in row.cells]
                    text = " | ".join(value for value in values if value)
                    if text:
                        blocks.append(
                            SourceBlock(
                                id=f"docx-table-{table_index}-row-{row_index}",
                                locator=(
                                    f"DOCX table {table_index}, row {row_index}"
                                ),
                                text=text,
                            )
                        )
        except Exception as exc:
            raise CVReviewRequired("The DOCX file is corrupt or unreadable") from exc
        return ParsedCV(
            text="\n\n".join(block.text for block in blocks),
            blocks=blocks,
            parser="python-docx",
            page_count=None,
            warnings=[],
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        value = value.replace("\x00", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()
