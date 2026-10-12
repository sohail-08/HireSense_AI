"""Interview schedules, invitation batches and durable email deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "0016_interview_scheduling"
down_revision = "0015_deterministic_scoring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("interview_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ranking_run_id", sa.Integer(), sa.ForeignKey("scoring_runs.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("confirmation_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128)), sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_interview_batch_request"),
        sa.UniqueConstraint("created_by_user_id", "confirmation_hash", name="uq_interview_confirmation"))
    op.create_table("interview_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("interview_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False), sa.Column("start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_utc", sa.DateTime(timezone=True), nullable=False), sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("local_start", sa.String(40), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), nullable=False), sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("calendar_uid", sa.String(200), nullable=False, unique=True),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("meeting_url", sa.String(2048)), sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_active_interview_stage", "interview_schedules", ["application_id", "stage"], unique=True,
        postgresql_where=sa.text("status IN ('scheduled', 'rescheduled')"), sqlite_where=sa.text("status IN ('scheduled', 'rescheduled')"))
    op.create_table("interview_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("interview_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(254), nullable=False), sa.Column("template_version", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(250), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("calendar_text", sa.Text(), nullable=False), sa.Column("calendar_checksum", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("in_flight", sa.Boolean(), nullable=False), sa.Column("provider_message_id", sa.String(200)),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error_category", sa.String(80)),
        sa.Column("sent_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("schedule_id", "sequence", name="uq_interview_delivery_sequence"))
    for table, columns in [("interview_batches", ["job_posting_id", "created_by_user_id"]),
        ("interview_schedules", ["job_posting_id", "application_id", "created_by_user_id", "start_utc"]),
        ("interview_deliveries", ["batch_id"])]:
        for column in columns:
            op.create_index("ix_" + table + "_" + column, table, [column])


def downgrade():
    op.drop_table("interview_deliveries")
    op.drop_table("interview_schedules")
    op.drop_table("interview_batches")
