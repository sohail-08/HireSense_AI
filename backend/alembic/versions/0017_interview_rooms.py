"""Secure candidate room access and hashed candidate sessions; preserve schedules."""
from alembic import op
import sqlalchemy as sa

revision = "0017_interview_rooms"
down_revision = "0016_interview_scheduling"
branch_labels = None
depends_on = None

FIELDS = [
    sa.Column("room_name", sa.String(100)), sa.Column("join_token_hash", sa.String(64)),
    sa.Column("join_token_nonce", sa.String(64)), sa.Column("join_token_expires_at", sa.DateTime(timezone=True)),
    sa.Column("join_base_url", sa.String(2048)),
    sa.Column("join_token_id", sa.String(32)),
    sa.Column("media_cleanup_rooms", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("join_token_revoked_at", sa.DateTime(timezone=True)),
    sa.Column("join_generation", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("room_status", sa.String(20), nullable=False, server_default="scheduled"),
    sa.Column("room_version", sa.Integer(), nullable=False, server_default="1"),
    *[sa.Column(name, sa.DateTime(timezone=True)) for name in (
        "candidate_waiting_at", "candidate_last_seen_at", "candidate_admitted_at", "candidate_joined_at",
        "interviewer_joined_at", "interview_started_at", "end_requested_at", "interview_ended_at")],
    sa.Column("ended_by_user_id", sa.Integer()),
]


def upgrade():
    with op.batch_alter_table("interview_schedules") as batch:
        for column in FIELDS:
            batch.add_column(column)
        batch.create_foreign_key("fk_interview_ended_by", "users", ["ended_by_user_id"], ["id"])
        batch.create_check_constraint("ck_interview_room_status", "room_status IN ('scheduled','waiting','ready','active','ending','ended','cancelled')")
    op.create_index("uq_interview_room_name", "interview_schedules", ["room_name"], unique=True)
    op.create_index("uq_interview_join_hash", "interview_schedules", ["join_token_hash"], unique=True)
    op.execute("UPDATE interview_schedules SET room_status = CASE WHEN status = 'cancelled' THEN 'cancelled' WHEN status = 'completed' THEN 'ended' ELSE 'scheduled' END")
    op.add_column("interview_deliveries", sa.Column("join_material", sa.JSON()))
    op.create_table("candidate_interview_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("join_generation", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_candidate_interview_sessions_interview_id", "candidate_interview_sessions", ["interview_id"])
    op.create_index("ix_candidate_interview_sessions_application_id", "candidate_interview_sessions", ["application_id"])


def downgrade():
    op.drop_table("candidate_interview_sessions")
    op.drop_column("interview_deliveries", "join_material")
    op.drop_index("uq_interview_room_name", "interview_schedules")
    op.drop_index("uq_interview_join_hash", "interview_schedules")
    with op.batch_alter_table("interview_schedules") as batch:
        batch.drop_constraint("ck_interview_room_status", type_="check")
        batch.drop_constraint("fk_interview_ended_by", type_="foreignkey")
        for column in reversed(FIELDS):
            batch.drop_column(column.name)
