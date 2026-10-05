from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.database import Base
from app.models.user import User


ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


def run_upgrade(database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def test_baseline_migration_creates_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"

    run_upgrade(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert "users" in inspector.get_table_names()
    assert "alembic_version" in inspector.get_table_names()
    assert {
        column["name"] for column in inspector.get_columns("users")
    } == {
        "id",
        "name",
        "email",
        "password_hash",
        "role",
        "is_active",
        "created_at",
    }


def test_baseline_migration_adopts_existing_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(database_url)
    User.__table__.create(engine)

    run_upgrade(database_url)

    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names()
    assert "users" in inspector.get_table_names()


def test_domain_migration_creates_f1_f2_f3_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'domain.db'}"

    run_upgrade(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert {
        "requirement_profiles",
        "job_descriptions",
        "job_postings",
        "candidates",
        "candidate_applications",
        "cv_documents",
    }.issubset(inspector.get_table_names())

    assert {
        "id",
        "title",
        "required_skills",
        "preferred_skills",
        "qualifications",
        "selection_criteria",
        "status",
    }.issubset(
        {column["name"] for column in inspector.get_columns("requirement_profiles")}
    )
    assert {
        "application_id",
        "candidate_id",
        "storage_path",
        "sha256",
        "status",
    }.issubset(
        {column["name"] for column in inspector.get_columns("cv_documents")}
    )


def test_knowledge_base_migration_creates_document_and_chunk_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'knowledge.db'}"

    run_upgrade(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert {
        "knowledge_documents",
        "knowledge_chunks",
    }.issubset(inspector.get_table_names())
    assert {
        "title",
        "source_type",
        "content_hash",
        "metadata_json",
    }.issubset(
        {
            column["name"]
            for column in inspector.get_columns("knowledge_documents")
        }
    )
    assert {
        "document_id",
        "chunk_index",
        "content",
        "embedding",
    }.issubset(
        {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    )


def test_requirement_discovery_migration_creates_session_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'requirement-session.db'}"

    run_upgrade(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert "requirement_discovery_sessions" in inspector.get_table_names()
    assert {
        "id",
        "interviewer_user_id",
        "requirement_profile_id",
        "status",
        "state_json",
    }.issubset(
        {
            column["name"]
            for column in inspector.get_columns("requirement_discovery_sessions")
        }
    )
