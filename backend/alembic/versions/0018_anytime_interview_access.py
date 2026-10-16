"""Decouple still-valid interview invitations from legacy scheduled windows."""
import os
from datetime import datetime, timedelta, timezone
from alembic import op
import sqlalchemy as sa

revision = "0018_anytime_interview_access"
down_revision = "0017_interview_rooms"
branch_labels = None
depends_on = None


def upgrade():
    days = int(os.environ.get("INTERVIEW_LINK_MAX_DAYS", "30"))
    if not 1 <= days <= 365:
        raise ValueError("INTERVIEW_LINK_MAX_DAYS must be between 1 and 365")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days)
    schedules = sa.table("interview_schedules",
        sa.column("status", sa.String), sa.column("room_status", sa.String),
        sa.column("join_token_hash", sa.String),
        sa.column("join_token_revoked_at", sa.DateTime(timezone=True)),
        sa.column("join_token_expires_at", sa.DateTime(timezone=True)),
        sa.column("version", sa.Integer), sa.column("room_version", sa.Integer))
    # Same hash/nonce means the emailed URL remains unchanged. Never resurrect an
    # expired/revoked link or grant access to completed/cancelled/ending interviews.
    op.execute(schedules.update().where(
        schedules.c.status.in_(["scheduled", "rescheduled"]),
        schedules.c.room_status.in_(["scheduled", "waiting", "ready", "active"]),
        schedules.c.join_token_hash.is_not(None),
        schedules.c.join_token_revoked_at.is_(None),
        schedules.c.join_token_expires_at > now,
        schedules.c.join_token_expires_at < expires,
    ).values(join_token_expires_at=expires,
        version=schedules.c.version + 1, room_version=schedules.c.room_version + 1))


def downgrade():
    # Original expirations cannot be reconstructed reliably. Preserve credentials
    # rather than silently shortening them or changing their bearer identities.
    pass
