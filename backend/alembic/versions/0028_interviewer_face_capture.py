"""Short-lived interviewer-initiated camera capture requests."""
from alembic import op
import sqlalchemy as sa

revision = "0028_interviewer_face_capture"
down_revision = "0027_candidate_identity"
branch_labels = depends_on = None


def upgrade():
    op.add_column("candidate_identity_checks", sa.Column("capture_requested_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("candidate_identity_checks", "capture_requested_at")
