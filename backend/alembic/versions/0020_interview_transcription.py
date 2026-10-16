"""Consent, transcription sessions, stream anchors and immutable final text."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_interview_transcription"
down_revision = "0019_interview_copilot"
branch_labels = depends_on = None
J = sa.JSON().with_variant(JSONB(), "postgresql")
D = sa.DateTime(timezone=True)


def upgrade():
    op.create_table("transcription_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(40), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("configuration", J, nullable=False),
        sa.Column("keyterms", J, nullable=False),
        sa.Column("started_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", D, nullable=False),
        sa.Column("stop_requested_at", D), sa.Column("ended_at", D),
        sa.Column("expires_at", D, nullable=False),
        sa.Column("failure_code", sa.String(60)),
        sa.Column("connection_status", sa.String(30), nullable=False),
        sa.Column("worker_identity", sa.String(100), nullable=False),
        sa.Column("claim_hash", sa.String(64)), sa.Column("heartbeat_at", D),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("metrics", J, nullable=False),
        sa.Column("created_at", D, nullable=False), sa.Column("updated_at", D, nullable=False))
    op.create_index("ix_transcription_sessions_interview_id", "transcription_sessions", ["interview_id"])
    op.create_index("ix_transcription_sessions_expires_at", "transcription_sessions", ["expires_at"])
    op.create_index("ix_transcription_interview_created", "transcription_sessions", ["interview_id", "created_at"])
    op.create_table("transcription_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("participant_reference", sa.Integer(), nullable=False),
        sa.Column("consented_at", D, nullable=False),
        sa.Column("notice_version", sa.String(40), nullable=False), sa.Column("revoked_at", D),
        sa.UniqueConstraint("interview_id", "role", name="uq_transcription_consent_role"))
    op.create_index("ix_transcription_consents_interview_id", "transcription_consents", ["interview_id"])
    op.create_table("transcription_streams",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("transcription_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaker", sa.String(20), nullable=False),
        sa.Column("participant_reference", sa.Integer(), nullable=False),
        sa.Column("participant_identity", sa.String(100), nullable=False),
        sa.Column("track_sid", sa.String(100), nullable=False),
        sa.Column("start_offset_ms", sa.Integer(), nullable=False),
        sa.Column("last_end_ms", sa.Integer(), nullable=False), sa.Column("created_at", D, nullable=False))
    op.create_index("ix_transcription_streams_session_id", "transcription_streams", ["session_id"])
    op.create_table("transcript_segments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("transcription_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stream_id", sa.String(32), sa.ForeignKey("transcription_streams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaker", sa.String(20), nullable=False), sa.Column("participant_reference", sa.Integer(), nullable=False),
        sa.Column("participant_identity", sa.String(100), nullable=False), sa.Column("track_sid", sa.String(100), nullable=False),
        sa.Column("provider_request_id", sa.String(100), nullable=False), sa.Column("provider_segment_id", sa.String(100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_offset_ms", sa.Integer(), nullable=False), sa.Column("end_offset_ms", sa.Integer(), nullable=False),
        sa.Column("stream_start_offset_ms", sa.Integer(), nullable=False),
        sa.Column("start_at", D, nullable=False), sa.Column("end_at", D, nullable=False),
        sa.Column("confidence", sa.Float()), sa.Column("language", sa.String(20), nullable=False),
        sa.Column("words", J, nullable=False), sa.Column("provider_timing", J, nullable=False), sa.Column("created_at", D, nullable=False),
        sa.UniqueConstraint("session_id", "sequence", name="uq_transcript_sequence"),
        sa.UniqueConstraint("stream_id", "provider_segment_id", name="uq_transcript_provider_segment"))
    op.create_index("ix_transcript_interview_time", "transcript_segments", ["interview_id", "start_at", "sequence"])
    op.create_index("ix_transcript_session_time", "transcript_segments", ["session_id", "start_offset_ms"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM transcription_sessions")):
        raise RuntimeError("Explicitly export/delete transcription data before downgrading")
    for table in ("transcript_segments", "transcription_streams", "transcription_consents", "transcription_sessions"):
        op.drop_table(table)
