"""Private, opt-in photo references and interview identity results."""
from alembic import op
import sqlalchemy as sa

revision = "0027_candidate_identity"
down_revision = "0026_practical_llm_scoring"
branch_labels = depends_on = None


def upgrade():
    op.create_table("candidate_face_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), unique=True, nullable=False),
        *[sa.Column(name, sa.String(length), nullable=False) for name, length in [("status",30),("consent",20),("notice_version",40),("source_hash",64),("generation",32)]],
        sa.Column("consented_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("photo_cipher", sa.Text()), sa.Column("embedding_cipher", sa.Text()),
        sa.Column("model_version", sa.String(160)), sa.Column("error", sa.String(80)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_candidate_face_references_expires_at", "candidate_face_references", ["expires_at"])
    op.create_table("candidate_identity_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("reference_generation", sa.String(32)), sa.Column("join_generation", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("candidate_interview_sessions.id", ondelete="SET NULL")),
        sa.Column("live_consent_at", sa.DateTime(timezone=True)), sa.Column("notice_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("similarity", sa.Float()), sa.Column("threshold", sa.Float()), sa.Column("model_version", sa.String(160)),
        sa.Column("checked_at", sa.DateTime(timezone=True)), sa.Column("manual_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("manual_note", sa.String(500)), sa.Column("version", sa.Integer(), nullable=False))


def downgrade():
    op.drop_table("candidate_identity_checks")
    op.drop_table("candidate_face_references")
