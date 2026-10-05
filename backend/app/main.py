import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, engine, get_db
from app.logging_config import configure_logging
from app.routes.auth import router as auth_router
from app.routes.job_descriptions import router as job_descriptions_router
from app.routes.requirements import router as requirements_router
from app.seed_interviewer import seed_interviewer
from app.storage import ensure_storage_root


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_storage_root()

    with SessionLocal() as db:
        seed_interviewer(db)

    logger.info(
        "Database initialized and interviewer account ready"
    )

    yield

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
app.include_router(job_descriptions_router)
app.include_router(requirements_router)


@app.get("/api/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
