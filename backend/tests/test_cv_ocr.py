"""Local OCR tests; no provider calls or business-database writes."""
from types import SimpleNamespace
import hashlib
import shutil
import subprocess
import time

import pytest
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models.screening import ScreeningRun, ScreeningRunStatus
from app.screening.ocr import LocalCVOCR, OCRReadError
from app.screening.parsing import CVParser, CVReviewRequired
from app.services.screening_service import ScreeningService
from test_screening import _settings, _records, _application_with_docx, FakeScreeningAI


def words_tsv(confidences=None):
    words = "Built Python applications with FastAPI and Docker for production services".split()
    confidences = confidences or [95] * len(words)
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tconf\ttext\n"
    return header + "\n".join(f"5\t1\t1\t1\t{1 if i < 5 else 2}\t{i}\t{value}\t{word}" for i,(word,value) in enumerate(zip(words,confidences)))


def test_word_confidence_gate_and_line_order(tmp_path):
    ocr = LocalCVOCR(_settings(tmp_path))
    text, details = ocr.parse_words(words_tsv(), 2, {"version": "test"})
    assert text.startswith("Built Python applications with FastAPI\nand Docker")
    assert details["page"] == 2 and details["mean_confidence"] == 95
    assert details["uncertain_character_ratio"] == 0


@pytest.mark.parametrize("confidences", [[30]*10, [99]*5 + [0]*5, [float("nan")]*10, [-1]*10])
def test_low_confidence_or_invalid_words_never_reach_scoring(tmp_path, confidences):
    with pytest.raises(OCRReadError):
        LocalCVOCR(_settings(tmp_path)).parse_words(words_tsv(confidences), 1, {})


def test_empty_and_malformed_ocr_output_is_rejected(tmp_path):
    for text in ("", "wrong\theader\n1\t2", "level\ttext\n5\tprivate text"):
        with pytest.raises(OCRReadError):
            LocalCVOCR(_settings(tmp_path)).parse_words(text, 1, {})


@pytest.mark.parametrize("data", [None, {}, {"parser": None}, {"parser": "legacy"},
    {"parser": {"parser": "pypdf+tesseract", "ocr": None}},
    {"parser": {"parser": "pypdf+tesseract", "ocr": {"pages": [None]}}}])
def test_missing_or_malformed_ocr_trace_keeps_warning_blocking(data):
    from app.screening.ocr import blocking_extraction_warnings, ocr_page_notice
    warnings = [ocr_page_notice(1)]
    document = SimpleNamespace(extraction_data=data, extraction_warnings=warnings)
    assert blocking_extraction_warnings(document) == warnings


def test_missing_dependencies_and_disabled_ocr_are_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(OCRReadError, match="Install Tesseract"):
        LocalCVOCR(_settings(tmp_path)).identity()
    settings = _settings(tmp_path).model_copy(update={"cv_ocr_enabled": False})
    with pytest.raises(OCRReadError, match="disabled"):
        LocalCVOCR(settings).identity()


class PageOCR:
    def __init__(self, fail=False): self.calls, self.fail = [], fail
    def identity(self): return {"policy": {"version": "synthetic-ocr-v1"}}
    def read_page(self, path, page_number, **kwargs):
        self.calls.append(page_number)
        if self.fail: raise OCRReadError("CV OCR confidence is too low on PDF page 2; upload a clearer scan")
        return "Built Python APIs with FastAPI. " * 4, {"page": page_number, "mean_confidence": 96, "identity": self.identity()}


def test_mixed_pdf_keeps_native_pages_and_ocr_page_references(tmp_path, monkeypatch):
    import app.screening.parsing as module
    native = "Native Python experience and qualifications. " * 4
    pages = [SimpleNamespace(extract_text=lambda: native, images=[]), SimpleNamespace(extract_text=lambda: "", images=[object()])]
    monkeypatch.setattr(module, "PdfReader", lambda path: SimpleNamespace(is_encrypted=False, pages=pages))
    ocr = PageOCR()
    parsed = CVParser(_settings(tmp_path), ocr=ocr)._parse_pdf(tmp_path / "cv.pdf")
    assert ocr.calls == [2]
    assert [b.id for b in parsed.blocks] == ["pdf-page-1", "pdf-page-2"]
    assert [b.locator for b in parsed.blocks] == ["PDF page 1", "PDF page 2 (OCR)"]
    assert parsed.blocks[0].text == native.strip()
    assert parsed.parser == "pypdf+tesseract" and parsed.ocr["pages"][0]["mean_confidence"] == 96


def test_sparse_native_header_does_not_hide_scanned_body(tmp_path, monkeypatch):
    import app.screening.parsing as module
    page = SimpleNamespace(extract_text=lambda: "CV header", images=[object()])
    monkeypatch.setattr(module, "PdfReader", lambda path: SimpleNamespace(is_encrypted=False, pages=[page]))
    ocr = PageOCR(); parsed = CVParser(_settings(tmp_path), ocr=ocr)._parse_pdf(tmp_path / "cv.pdf")
    assert ocr.calls == [1] and "CV header" not in parsed.text


def test_native_pages_and_truly_blank_pages_need_no_ocr_tools(tmp_path, monkeypatch):
    import app.screening.parsing as module
    native = "Native Python experience and qualifications. " * 4
    pages = [SimpleNamespace(extract_text=lambda: native, images=[]),
        SimpleNamespace(extract_text=lambda: "", images=[], get_contents=lambda: None)]
    monkeypatch.setattr(module, "PdfReader", lambda path: SimpleNamespace(is_encrypted=False, pages=pages))
    ocr = PageOCR(fail=True)
    parsed = CVParser(_settings(tmp_path), ocr=ocr)._parse_pdf(tmp_path / "cv.pdf")
    assert ocr.calls == [] and parsed.ocr == {} and parsed.parser == "pypdf"
    assert len(parsed.blocks) == 1 and parsed.blocks[0].locator == "PDF page 1"


def test_scanned_page_limit_prevents_partial_assessment(tmp_path, monkeypatch):
    import app.screening.parsing as module
    pages = [SimpleNamespace(extract_text=lambda: "", images=[object()])]*2
    monkeypatch.setattr(module, "PdfReader", lambda path: SimpleNamespace(is_encrypted=False, pages=pages))
    settings = _settings(tmp_path).model_copy(update={"cv_ocr_max_pages": 1})
    with pytest.raises(CVReviewRequired, match="scanned-page limit"):
        CVParser(settings, ocr=PageOCR())._parse_pdf(tmp_path / "cv.pdf")


def test_timeout_does_not_expose_paths_or_leave_temp_files(tmp_path, monkeypatch):
    import app.screening.ocr as module
    ocr = LocalCVOCR(_settings(tmp_path)); ocr._identity = {"policy": ocr.policy()}
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired("PRIVATE candidate path", 1)
    monkeypatch.setattr(module.subprocess, "run", timeout)
    monkeypatch.setattr(module.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(OCRReadError, match="time limit") as failure:
        ocr.read_page(tmp_path / "private.pdf", 1, deadline=time.monotonic()+10)
    assert "PRIVATE" not in str(failure.value)
    assert list(tmp_path.iterdir()) == []


def test_unreadable_scanned_cv_never_calls_ai_or_gets_a_zero_score(tmp_path, monkeypatch):
    engine = create_engine("sqlite://"); Base.metadata.create_all(engine)
    ai = FakeScreeningAI()
    ai.extract_profile = lambda **kw: pytest.fail("Unreliable OCR must not reach the model")
    with Session(engine) as db:
        owner, _, posting = _records(db)
        app, _ = _application_with_docx(db, tmp_path, posting, 1); db.commit()
        parser = CVParser(_settings(tmp_path))
        monkeypatch.setattr(parser, "parse", lambda document: (_ for _ in ()).throw(CVReviewRequired("CV OCR confidence is too low; upload a clearer scan")))
        service = ScreeningService(_settings(tmp_path), ai=ai, parser=parser)
        batch = service.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=[app.id])
        service.process_batch(db, batch_id=batch.id)
        run = db.scalar(select(ScreeningRun).where(ScreeningRun.application_id == app.id))
        assert run.status == ScreeningRunStatus.FAILED and run.requirement_coverage is None
        assert "OCR confidence" in run.error_message
    engine.dispose()


@pytest.mark.skipif(not (shutil.which("tesseract") and shutil.which("pdftoppm")), reason="Needs local OCR tools (included in backend Docker image)")
def test_real_scanned_pdf_round_trip_preserves_file_and_reads_evidence(tmp_path):
    root = tmp_path / "cvs"; root.mkdir()
    image = Image.new("RGB", (1600, 1800), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 35)
    lines = ["BACKEND ENGINEER", "Skills: Python, FastAPI, SQL, Docker", "Experience: Built Python APIs with FastAPI.",
        "Developed reliable production services.", "Qualifications: Degree in Computer Science."]
    for i,line in enumerate(lines): draw.text((100, 120+i*160), line, font=font, fill="black")
    path = root / "scanned.pdf"; image.save(path, "PDF", resolution=150)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = SimpleNamespace(storage_path="cvs/scanned.pdf", sha256=before)
    parsed = CVParser(_settings(tmp_path)).parse(doc)
    assert "Python" in parsed.text and "FastAPI" in parsed.text
    assert parsed.blocks[0].locator == "PDF page 1 (OCR)"
    assert parsed.ocr["pages"][0]["mean_confidence"] >= 80
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    # A real scanned PDF also completes the existing evidence pipeline; only the
    # scoring provider is mocked, never a business candidate's assessment.
    from app.screening.ai import CVProfile
    class PageAI(FakeScreeningAI):
        def extract_profile(self, *, blocks):
            assert blocks[0]["locator"] == "PDF page 1 (OCR)"
            return CVProfile(skills=["Python", "FastAPI"])
    engine = create_engine("sqlite://"); Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner, _, posting = _records(db)
        app, document = _application_with_docx(db, tmp_path, posting, 1)
        document.storage_path, document.sha256 = "cvs/scanned.pdf", before
        document.mime_type, document.original_filename = "application/pdf", "scanned.pdf"
        document.file_size_bytes = path.stat().st_size
        db.commit()
        service = ScreeningService(_settings(tmp_path), ai=PageAI())
        batch = service.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=[app.id])
        service.process_batch(db, batch_id=batch.id)
        run = db.scalar(select(ScreeningRun).where(ScreeningRun.application_id == app.id))
        assert run.status == ScreeningRunStatus.COMPLETED
        assert run.processing_metadata["evidence"]["ocr"]["pages"][0]["mean_confidence"] >= 80
        assert document.extraction_data["source_blocks"][0]["locator"] == "PDF page 1 (OCR)"
        assert service._compatible_run(db, application_id=app.id, cv_sha256=before, requirement_snapshot_hash=run.requirement_snapshot_hash).id == run.id
        service.parser.ocr._identity = {"policy": {"version": "changed-policy"}}
        assert service._compatible_run(db, application_id=app.id, cv_sha256=before, requirement_snapshot_hash=run.requirement_snapshot_hash) is None
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    engine.dispose()
