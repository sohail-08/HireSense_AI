import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.mcp_config import resolve_mcp_server
from app.database import SessionLocal, engine, get_db
from app.logging_config import configure_logging
from app.routes.auth import router as auth_router
from app.routes.candidates import router as candidates_router
from app.routes.job_descriptions import router as job_descriptions_router
from app.routes.job_postings import router as job_postings_router
from app.routes.knowledge import router as knowledge_router
from app.routes.requirements import router as requirements_router
from app.routes.screening import router as screening_router
from app.routes.scoring import router as scoring_router
from app.routes.interviews import router as interviews_router
from app.routes.interview_rooms import router as interview_rooms_router
from app.routes.transcription import router as transcription_router, internal as transcription_internal_router
from app.routes.supervisor import router as supervisor_router
from app.seed_interviewer import seed_interviewer
from app.services.screening_service import ScreeningService
from app.services.interview_service import InterviewService
from app.services.interview_rooms import InterviewRooms
from app.routes.interview_analysis import router as interview_analysis_router
from app.services.interview_analysis import InterviewAnalysisService, analysis_worker
from app.services.assessment_service import AssessmentService
from app.routes.assessments import router as assessments_router
from app.routes.work_samples import router as work_samples_router
from app.services.work_sample import WorkSampleService, work_sample_worker
from app.routes.candidate_identity import router as identity_router, IdentityBodyLimit
from app.routes.candidate_photos import router as candidate_photos_router
from app.services.candidate_identity import CandidateIdentityService, identity_worker
from app.storage import (
    ensure_cv_storage_root,
    ensure_knowledge_storage_root,
    ensure_storage_root,
)


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate deployment configuration before initializing data or recovering
    # previously confirmed deliveries. This does not contact either MCP server.
    resolve_mcp_server("job_posting")
    resolve_mcp_server("interview_scheduling")
    ensure_storage_root()
    ensure_cv_storage_root()
    ensure_knowledge_storage_root()

    with SessionLocal() as db:
        seed_interviewer(db)
        ScreeningService.recover_interrupted(db)
        pending_invites = InterviewService.recover_interrupted(db)
        InterviewAnalysisService.recover(db)
        AssessmentService.recover(db)
        WorkSampleService.recover(db)
        CandidateIdentityService.recover(db)

    # Resume only previously confirmed, never-attempted deliveries. Uncertain
    # attempts remain uncertain; no automatic retry is performed for them.
    delivery_tasks = [asyncio.create_task(asyncio.to_thread(InterviewService().deliver_batch, batch_id)) for batch_id in pending_invites]
    room_recovery = asyncio.create_task(asyncio.to_thread(InterviewRooms().recover_ending, SessionLocal))
    analysis_stop = asyncio.Event()
    analysis_task = asyncio.create_task(analysis_worker(analysis_stop))
    exercise_task = asyncio.create_task(work_sample_worker(analysis_stop))
    identity_task = asyncio.create_task(identity_worker(analysis_stop))

    logger.info(
        "Database initialized and interviewer account ready"
    )

    yield

    analysis_stop.set()
    await analysis_task
    await exercise_task
    await identity_task
    if delivery_tasks:
        await asyncio.gather(*delivery_tasks, return_exceptions=True)
    await room_recovery
    engine.dispose()


app = FastAPI(
    title="HireSense API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(candidates_router)
app.include_router(job_descriptions_router)
app.include_router(job_postings_router)
app.include_router(knowledge_router)
app.include_router(requirements_router)
app.include_router(screening_router)
app.include_router(scoring_router)
app.include_router(interviews_router)
app.include_router(transcription_router)
app.include_router(transcription_internal_router)
app.include_router(interview_analysis_router)
app.include_router(interview_rooms_router)
app.include_router(supervisor_router)
app.include_router(assessments_router)
app.include_router(work_samples_router)
app.include_router(identity_router)
app.include_router(candidate_photos_router)
app.add_middleware(IdentityBodyLimit)


@app.exception_handler(RequestValidationError)
async def safe_candidate_validation(request, exc):
    if request.url.path.startswith(("/api/interview-rooms/candidate/", "/api/internal/transcription/")):
        return JSONResponse({"detail": "This interview access is not available.", "code": "invalid_link"},
            422, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return await request_validation_exception_handler(request, exc)


@app.get("/api/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
