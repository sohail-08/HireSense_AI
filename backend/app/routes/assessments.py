from fastapi import APIRouter, Depends, Response, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.candidate import CandidateApplication
from app.models.job import JobPosting, JobDescription
from app.schemas.assessment import GenerateAssessment, CompareAssessments, ReviewAssessment, ExportReport, BuildFinalRanking
from app.security import require_interviewer
from app.routes.interview_rooms import run, sensitive
from app.services.assessment_service import AssessmentService
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/assessments", tags=["Consolidated assessments"])


def service(): return AssessmentService()
def reports(): return ReportService()


@router.get("/jobs/{job_id}/ranking")
def final_ranking(job_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    from app.services.final_ranking_service import FinalRankingService
    sensitive(response)
    return run(db, lambda: FinalRankingService().read(db, user.id, job_id))


@router.post("/jobs/{job_id}/ranking", status_code=202)
def calculate_ranking(job_id: int, data: BuildFinalRanking, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    from app.services.final_ranking_service import FinalRankingService
    sensitive(response)
    return run(db, lambda: FinalRankingService().start(db, user.id, job_id))


@router.get("/applications")
def applications(response: Response, job_posting_id: int = Query(gt=0), db: Session = Depends(get_db),
                 user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    def operation():
        owned = db.scalar(select(JobPosting.id).join(JobDescription).where(JobPosting.id == job_posting_id,
            JobDescription.created_by_user_id == user.id))
        if not owned: raise LookupError("Job posting not found")
        ids = db.scalars(select(CandidateApplication.id).where(CandidateApplication.job_posting_id == job_posting_id).order_by(CandidateApplication.id))
        return [assessment.list_application(db, user.id, i) for i in ids]
    return run(db, operation)


@router.get("/applications/{application_id}")
def application(application_id: int, response: Response, db: Session = Depends(get_db),
                user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    return run(db, lambda: assessment.list_application(db, user.id, application_id))


@router.post("/applications/{application_id}", status_code=202)
def generate(application_id: int, data: GenerateAssessment, response: Response, db: Session = Depends(get_db),
             user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    def operation():
        item = assessment.enqueue(db, user.id, application_id, data)
        return {"id": item.id, "version": item.version, "status": item.status}
    return run(db, operation)


@router.get("/runs/{run_id}")
def read(run_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    return run(db, lambda: assessment.read(db, user.id, run_id))


@router.post("/runs/{run_id}/reviews")
def review(run_id: int, data: ReviewAssessment, response: Response, db: Session = Depends(get_db),
           user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    return run(db, lambda: assessment.review(db, user.id, run_id, data))


@router.post("/comparisons", status_code=201)
def compare(data: CompareAssessments, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    return run(db, lambda: assessment.compare(db, user.id, data.assessment_ids))


@router.get("/comparisons/{comparison_id}")
def comparison(comparison_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), assessment=Depends(service)):
    sensitive(response)
    return run(db, lambda: assessment.read_comparison(db, user.id, comparison_id))


@router.post("/runs/{run_id}/exports", status_code=202)
def export(run_id: int, data: ExportReport, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), renderer=Depends(reports)):
    sensitive(response)
    return run(db, lambda: renderer.request(db, user.id, data, assessment_id=run_id))


@router.post("/comparisons/{comparison_id}/exports", status_code=202)
def export_comparison(comparison_id: int, data: ExportReport, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), renderer=Depends(reports)):
    sensitive(response)
    return run(db, lambda: renderer.request(db, user.id, data, comparison_id=comparison_id))


@router.get("/exports/{artifact_id}")
def export_status(artifact_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), renderer=Depends(reports)):
    sensitive(response)
    return run(db, lambda: renderer.read(db, user.id, artifact_id))


@router.get("/exports/{artifact_id}/download")
def download(artifact_id: int, db: Session = Depends(get_db), user: User = Depends(require_interviewer), renderer=Depends(reports)):
    def operation():
        path, format = renderer.download(db, user.id, artifact_id)
        return FileResponse(path, media_type="application/pdf" if format == "pdf" else "text/html; charset=utf-8",
            filename=f"hiresense-report-{artifact_id}.{format}", headers={"Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})
    return run(db, operation)
