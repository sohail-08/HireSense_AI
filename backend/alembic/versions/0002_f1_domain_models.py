"""Add F1/F2/F3 domain tables.

Revision ID: 0002_f1_domain_models
Revises: 0001_baseline
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_f1_domain_models"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _enum(name: str, values: list[str]) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "requirement_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("preferred_skills", sa.JSON(), nullable=False),
        sa.Column("qualifications", sa.JSON(), nullable=False),
        sa.Column("min_years_experience", sa.Integer(), nullable=True),
        sa.Column("selection_criteria", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "requirementprofilestatus",
                ["draft", "confirmed", "archived"],
            ),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_requirement_profiles_status",
        "requirement_profiles",
        ["status"],
    )

    op.create_table(
        "job_descriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requirement_profile_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_content", sa.JSON(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "jobdescriptionstatus",
                ["draft", "approved", "archived"],
            ),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["requirement_profile_id"],
            ["requirement_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_descriptions_requirement_profile_id",
        "job_descriptions",
        ["requirement_profile_id"],
    )
    op.create_index(
        "ix_job_descriptions_status",
        "job_descriptions",
        ["status"],
    )

    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_description_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("application_url", sa.String(length=2048), nullable=True),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "status",
            _enum(
                "jobpostingstatus",
                ["draft", "published", "closed", "failed"],
            ),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_description_id"],
            ["job_descriptions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_postings_status", "job_postings", ["status"])
    op.create_index("ix_job_postings_platform", "job_postings", ["platform"])

    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("linkedin_url", sa.String(length=2048), nullable=True),
        sa.Column("portfolio_url", sa.String(length=2048), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"])

    op.create_table(
        "candidate_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            _enum(
                "applicationsource",
                ["direct_upload", "google_form", "import"],
            ),
            nullable=False,
        ),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            _enum(
                "applicationstatus",
                [
                    "received",
                    "screening",
                    "reviewed",
                    "shortlisted",
                    "rejected",
                    "withdrawn",
                ],
            ),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
        ),
        sa.ForeignKeyConstraint(
            ["job_posting_id"],
            ["job_postings.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_applications_job_posting_id",
        "candidate_applications",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_candidate_applications_status",
        "candidate_applications",
        ["status"],
    )

    op.create_table(
        "cv_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "source",
            _enum(
                "cvapplicationsource",
                ["direct_upload", "google_form", "import"],
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum(
                "cvprocessingstatus",
                [
                    "received",
                    "validated",
                    "processing",
                    "processed",
                    "rejected",
                    "failed",
                ],
            ),
            nullable=False,
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_data", sa.JSON(), nullable=True),
        sa.Column("extraction_warnings", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["candidate_applications.id"],
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cv_documents_application_id",
        "cv_documents",
        ["application_id"],
    )
    op.create_index("ix_cv_documents_status", "cv_documents", ["status"])
    op.create_index("ix_cv_documents_sha256", "cv_documents", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_cv_documents_sha256", table_name="cv_documents")
    op.drop_index("ix_cv_documents_status", table_name="cv_documents")
    op.drop_index("ix_cv_documents_application_id", table_name="cv_documents")
    op.drop_table("cv_documents")

    op.drop_index(
        "ix_candidate_applications_status",
        table_name="candidate_applications",
    )
    op.drop_index(
        "ix_candidate_applications_job_posting_id",
        table_name="candidate_applications",
    )
    op.drop_table("candidate_applications")

    op.drop_index("ix_candidates_email", table_name="candidates")
    op.drop_table("candidates")

    op.drop_index("ix_job_postings_platform", table_name="job_postings")
    op.drop_index("ix_job_postings_status", table_name="job_postings")
    op.drop_table("job_postings")

    op.drop_index(
        "ix_job_descriptions_status",
        table_name="job_descriptions",
    )
    op.drop_index(
        "ix_job_descriptions_requirement_profile_id",
        table_name="job_descriptions",
    )
    op.drop_table("job_descriptions")

    op.drop_index(
        "ix_requirement_profiles_status",
        table_name="requirement_profiles",
    )
    op.drop_table("requirement_profiles")
