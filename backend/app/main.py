import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
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
from app.routes.supervisor import router as supervisor_router
from app.seed_interviewer import seed_interviewer
from app.services.screening_service import ScreeningService
from app.services.interview_service import InterviewService
from app.storage import (
    ensure_cv_storage_root,
    ensure_knowledge_storage_root,
    ensure_storage_root,
)


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_storage_root()
    ensure_cv_storage_root()
    ensure_knowledge_storage_root()

    with SessionLocal() as db:
        seed_interviewer(db)
        ScreeningService.recover_interrupted(db)
        pending_invites = InterviewService.recover_interrupted(db)

    # Resume only previously confirmed, never-attempted deliveries. Uncertain
    # attempts remain uncertain; no automatic retry is performed for them.
    delivery_tasks = [asyncio.create_task(asyncio.to_thread(InterviewService().deliver_batch, batch_id)) for batch_id in pending_invites]

    logger.info(
        "Database initialized and interviewer account ready"
    )

    yield

    if delivery_tasks:
        await asyncio.gather(*delivery_tasks, return_exceptions=True)
    engine.dispose()


app = FastAPI(
    title="HireSense API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_url],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
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
app.include_router(supervisor_router)


@app.get("/api/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
