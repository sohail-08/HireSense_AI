import hashlib
from uuid import uuid4
from sqlalchemy import select, update
from app.database import SessionLocal
from app.agents.interview_analysis import digest
from app.models.assessment import ReportArtifact
from app.assessments.reports import TEMPLATE_VERSION, render_html, render_pdf
from app.services.assessment_service import AssessmentService
from app.storage import private_storage_path


class ReportService:
    def __init__(self, session_factory=None, pdf_renderer=None):
        self.factory = session_factory or SessionLocal
        self.pdf_renderer = pdf_renderer or render_pdf

    def request(self, db, user_id, request, *, assessment_id=None, comparison_id=None):
        service = AssessmentService()
        if assessment_id:
            report = service.read(db, user_id, assessment_id)
            if report["status"] != "completed": raise ValueError("Wait for assessment generation before exporting")
            payload = {"kind": "individual", "reports": [report]}
        else:
            comparison = service.read_comparison(db, user_id, comparison_id)
            if comparison["snapshot"].get("status", "completed") != "completed":
                raise ValueError("Wait for the final ranking before exporting")
            payload = {"kind": "comparison", "comparison": comparison, "reports": comparison["snapshot"]["assessments"]}
        key = digest([TEMPLATE_VERSION, request.format, payload])
        artifact = db.scalar(select(ReportArtifact).where(ReportArtifact.fingerprint == key))
        if artifact:
            if artifact.status == "completed" and request.retry:
                path = private_storage_path(artifact.storage_key) if artifact.storage_key else None
                if not path or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
                    artifact.status = "failed"
            if artifact.status == "failed" and request.retry:
                if artifact.storage_key:
                    db.info.setdefault("deleted_report_paths", set()).add(private_storage_path(artifact.storage_key))
                artifact.storage_key, artifact.sha256 = None, None
                artifact.status, artifact.error = "queued", None
                db.commit()
            return self.read(db, user_id, artifact.id)
        artifact = ReportArtifact(assessment_id=assessment_id, comparison_id=comparison_id,
            format=request.format, template_version=TEMPLATE_VERSION, fingerprint=key, payload=payload, status="queued", created_by=user_id)
        db.add(artifact)
        db.commit()
        return self.read(db, user_id, artifact.id)

    @staticmethod
    def owned(db, user_id, artifact_id):
        row = db.get(ReportArtifact, artifact_id)
        if not row: raise LookupError("Report export not found")
        service = AssessmentService()
        if row.assessment_id: service.owned_run(db, user_id, row.assessment_id)
        else: service.read_comparison(db, user_id, row.comparison_id)
        return row

    def read(self, db, user_id, artifact_id):
        row = self.owned(db, user_id, artifact_id)
        return {"id": row.id, "status": row.status, "format": row.format, "template_version": row.template_version,
            "sha256": row.sha256, "error": row.error, "download_path": f"/assessments/exports/{row.id}/download" if row.status == "completed" else None}

    def download(self, db, user_id, artifact_id):
        row = self.owned(db, user_id, artifact_id)
        if row.status != "completed" or not row.storage_key: raise ValueError("Report export is not ready")
        path = private_storage_path(row.storage_key)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256:
            raise ValueError("Report file is unavailable or its integrity check failed; request a new export")
        return path, row.format

    def tick(self):
        with self.factory() as db:
            row_id = db.scalar(select(ReportArtifact.id).where(ReportArtifact.status == "queued").order_by(ReportArtifact.id).limit(1))
        if row_id is not None: self.process(row_id)

    def process(self, artifact_id):
        path = None
        try:
            with self.factory() as db:
                if db.execute(update(ReportArtifact).where(ReportArtifact.id == artifact_id, ReportArtifact.status == "queued").values(status="processing")).rowcount != 1:
                    db.rollback()
                    return
                db.commit()
                row = db.get(ReportArtifact, artifact_id)
                self.owned(db, row.created_by, row.id)
                payload, format = row.payload, row.format
            html = render_html(payload)
            content = html.encode("utf-8") if format == "html" else self.pdf_renderer(html, landscape=payload["kind"] == "comparison")
            key = f"reports/{uuid4().hex}.{format}"
            path = private_storage_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o600)
            with self.factory() as db:
                row = db.get(ReportArtifact, artifact_id)
                if not row:
                    path.unlink(missing_ok=True)
                    return
                self.owned(db, row.created_by, row.id)
                row.storage_key, row.sha256, row.status = key, hashlib.sha256(content).hexdigest(), "completed"
                db.commit()
        except Exception:
            if path: path.unlink(missing_ok=True)
            with self.factory() as db:
                db.execute(update(ReportArtifact).where(ReportArtifact.id == artifact_id).values(status="failed",
                    error="Export could not be rendered. HTML remains available independently; retry this format."))
                db.commit()
