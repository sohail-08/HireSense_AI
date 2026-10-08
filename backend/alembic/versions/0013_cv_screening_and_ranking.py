"""Add persistent CV screening batches, matches, and rankings.

Revision ID: 0013_cv_screening_and_ranking
Revises: 0012_per_posting_google_forms
Create Date: 2026-10-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_cv_screening_and_ranking"
down_revision = "0012_per_posting_google_forms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screening_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=21), nullable=False),
        sa.Column("application_ids", sa.JSON(), nullable=False),
        sa.Column("total_applications", sa.Integer(), nullable=False),
        sa.Column("processed_applications", sa.Integer(), nullable=False),
        sa.Column("successful_applications", sa.Integer(), nullable=False),
        sa.Column("review_applications", sa.Integer(), nullable=False),
        sa.Column("failed_applications", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', "
            "'completed_with_errors', 'failed')",
            name="screeningbatchstatus",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_posting_id"], ["job_postings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_screening_batches_job_posting_id",
        "screening_batches",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_screening_batches_status", "screening_batches", ["status"]
    )

    op.create_table(
        "screening_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("cv_document_id", sa.Integer(), nullable=True),
        sa.Column("job_posting_id", sa.Integer(), nullable=False),
        sa.Column("requirement_profile_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=19), nullable=False),
        sa.Column("cv_sha256", sa.String(length=64), nullable=False),
        sa.Column("requirement_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("requirement_snapshot", sa.JSON(), nullable=False),
        sa.Column("extracted_profile", sa.JSON(), nullable=True),
        sa.Column("suitability_summary", sa.Text(), nullable=True),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("points_to_verify", sa.JSON(), nullable=False),
        sa.Column("requirement_coverage", sa.Float(), nullable=True),
        sa.Column("met_count", sa.Integer(), nullable=False),
        sa.Column("partially_met_count", sa.Integer(), nullable=False),
        sa.Column("unmet_count", sa.Integer(), nullable=False),
        sa.Column("uncertain_count", sa.Integer(), nullable=False),
        sa.Column("review_flags", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("calculation_version", sa.String(length=50), nullable=False),
        sa.Column("reused_from_run_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', "
            "'review_required', 'failed')",
            name="screeningrunstatus",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["candidate_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cv_document_id"], ["cv_documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_posting_id"], ["job_postings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_profile_id"],
            ["requirement_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reused_from_run_id"], ["screening_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_screening_runs_application_id", "screening_runs", ["application_id"]
    )
    op.create_index(
        "ix_screening_runs_job_posting_id",
        "screening_runs",
        ["job_posting_id"],
    )
    op.create_index("ix_screening_runs_status", "screening_runs", ["status"])
    op.create_index(
        "ix_screening_runs_compatibility",
        "screening_runs",
        ["application_id", "cv_sha256", "requirement_snapshot_hash"],
    )

    op.create_table(
        "screening_batch_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("screening_run_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=19), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', "
            "'review_required', 'failed')",
            name="screeningrunstatus",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["candidate_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["screening_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["screening_run_id"], ["screening_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_screening_batch_items_batch_application",
        "screening_batch_items",
        ["batch_id", "application_id"],
        unique=True,
    )
    op.create_index(
        "ix_screening_batch_items_status", "screening_batch_items", ["status"]
    )

    op.create_table(
        "requirement_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screening_run_id", sa.Integer(), nullable=False),
        sa.Column("requirement_key", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=19), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_gaps", sa.JSON(), nullable=False),
        sa.Column("review_flags", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('met', 'partially_met', 'unmet', "
            "'unable_to_determine')",
            name="requirementmatchstatus",
        ),
        sa.ForeignKeyConstraint(
            ["screening_run_id"], ["screening_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_requirement_matches_screening_run_id",
        "requirement_matches",
        ["screening_run_id"],
    )
    op.create_index(
        "ix_requirement_matches_status", "requirement_matches", ["status"]
    )

    op.create_table(
        "ranking_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), nullable=False),
        sa.Column("requirement_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("calculation_version", sa.String(length=50), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_posting_id"], ["job_postings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ranking_snapshots_job_posting_id",
        "ranking_snapshots",
        ["job_posting_id"],
    )

    op.create_table(
        "ranking_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ranking_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("screening_run_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("disposition", sa.String(length=6), nullable=False),
        sa.Column("requirement_coverage", sa.Float(), nullable=True),
        sa.Column("met_count", sa.Integer(), nullable=False),
        sa.Column("partially_met_count", sa.Integer(), nullable=False),
        sa.Column("unmet_count", sa.Integer(), nullable=False),
        sa.Column("uncertain_count", sa.Integer(), nullable=False),
        sa.Column("suitability_summary", sa.Text(), nullable=True),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("points_to_verify", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "disposition IN ('ranked', 'review')",
            name="rankingdisposition",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["candidate_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ranking_snapshot_id"],
            ["ranking_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["screening_run_id"], ["screening_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ranking_entries_snapshot_id",
        "ranking_entries",
        ["ranking_snapshot_id"],
    )
    op.create_index(
        "ix_ranking_entries_application_id",
        "ranking_entries",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ranking_entries_application_id", table_name="ranking_entries")
    op.drop_index("ix_ranking_entries_snapshot_id", table_name="ranking_entries")
    op.drop_table("ranking_entries")
    op.drop_index(
        "ix_ranking_snapshots_job_posting_id", table_name="ranking_snapshots"
    )
    op.drop_table("ranking_snapshots")
    op.drop_index(
        "ix_requirement_matches_status", table_name="requirement_matches"
    )
    op.drop_index(
        "ix_requirement_matches_screening_run_id",
        table_name="requirement_matches",
    )
    op.drop_table("requirement_matches")
    op.drop_index(
        "ix_screening_batch_items_status", table_name="screening_batch_items"
    )
    op.drop_index(
        "uq_screening_batch_items_batch_application",
        table_name="screening_batch_items",
    )
    op.drop_table("screening_batch_items")
    op.drop_index("ix_screening_runs_compatibility", table_name="screening_runs")
    op.drop_index("ix_screening_runs_status", table_name="screening_runs")
    op.drop_index(
        "ix_screening_runs_job_posting_id", table_name="screening_runs"
    )
    op.drop_index("ix_screening_runs_application_id", table_name="screening_runs")
    op.drop_table("screening_runs")
    op.drop_index("ix_screening_batches_status", table_name="screening_batches")
    op.drop_index(
        "ix_screening_batches_job_posting_id", table_name="screening_batches"
    )
    op.drop_table("screening_batches")
