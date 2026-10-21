from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import Base
from app.models.user import User


ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


def run_upgrade(database_url: str, revision: str = "head") -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = database_url
    command.upgrade(config, revision)


def test_baseline_migration_creates_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"

    run_upgrade(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert "users" in inspector.get_table_names()
    assert "alembic_version" in inspector.get_table_names()
    assert "cv_passages" in inspector.get_table_names()
    assert {"input_fingerprint", "processing_metadata"}.issubset(c["name"] for c in inspector.get_columns("screening_runs"))
    assert {"scoring_configurations", "scoring_runs", "candidate_scores", "scoring_request_keys"}.issubset(inspector.get_table_names())
    assert {"interview_schedules", "interview_batches", "interview_deliveries"}.issubset(inspector.get_table_names())
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
        "application_import_exclusions",
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
    assert "response_data" in {
        column["name"]
        for column in inspector.get_columns("candidate_applications")
    }
    assert "uq_candidate_applications_source_reference" in {
        index["name"]
        for index in inspector.get_indexes("candidate_applications")
    }
    assert {
        "heading",
        "reviewed_content",
        "discord_payload",
        "job_description_version",
        "external_server_id",
        "external_channel_id",
        "attempt_started_at",
        "error_code",
    }.issubset(
        {column["name"] for column in inspector.get_columns("job_postings")}
    )


def test_screening_migration_creates_batches_matches_and_rankings(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'screening-migration.db'}"

    run_upgrade(database_url)

    inspector = inspect(create_engine(database_url))
    assert {
        "screening_batches",
        "screening_batch_items",
        "screening_runs",
        "requirement_matches",
        "ranking_snapshots",
        "ranking_entries",
    }.issubset(inspector.get_table_names())
    assert {
        "application_id",
        "cv_sha256",
        "requirement_snapshot_hash",
        "extracted_profile",
        "requirement_coverage",
        "review_flags",
        "prompt_version",
        "calculation_version",
    }.issubset(
        {column["name"] for column in inspector.get_columns("screening_runs")}
    )
    assert {
        "requirement_key",
        "status",
        "evidence",
        "evidence_gaps",
        "review_flags",
    }.issubset(
        {
            column["name"]
            for column in inspector.get_columns("requirement_matches")
        }
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

    assert "supervisor_sessions" in inspector.get_table_names()
    assert {
        "id",
        "interviewer_user_id",
        "requirement_session_id",
        "requirement_profile_id",
        "job_description_id",
        "job_posting_id",
        "phase",
        "state_json",
    }.issubset(
        {
            column["name"]
            for column in inspector.get_columns("supervisor_sessions")
        }
    )

    assert {
        "source_references",
        "generation_metadata",
        "interviewer_overrides",
    }.issubset(
        {
            column["name"]
            for column in inspector.get_columns("requirement_profiles")
        }
    )


def test_knowledge_source_migration_unifies_existing_records(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'unified-knowledge.db'}"
    run_upgrade(database_url, "0005_requirement_provenance")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge_documents "
                "(title, source_type, content_hash, metadata_json, "
                "created_at, updated_at) VALUES "
                "('Legacy source', 'company_policy', :content_hash, '{}', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"content_hash": "a" * 64},
        )

    run_upgrade(database_url)

    with engine.begin() as connection:
        source_type = connection.scalar(
            text(
                "SELECT source_type FROM knowledge_documents "
                "WHERE title = 'Legacy source'"
            )
        )
        assert source_type == "previous_job_description"

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge_documents "
                    "(title, source_type, content_hash, metadata_json, "
                    "created_at, updated_at) VALUES "
                    "('Invalid source', 'company_policy', :content_hash, '{}', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"content_hash": "b" * 64},
            )
