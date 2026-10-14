"""Private interview copilot history and a separate question knowledge source."""
from alembic import op
import sqlalchemy as sa

revision = "0019_interview_copilot"
down_revision = "0018_anytime_interview_access"
branch_labels = None
depends_on = None

old_type = sa.Enum("previous_job_description", name="knowledgesourcetype", native_enum=False, create_constraint=True)
new_type = sa.Enum("previous_job_description", "interview_question", name="knowledgesourcetype", native_enum=False, create_constraint=True)


def upgrade():
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.alter_column("source_type", existing_type=old_type, type_=new_type, existing_nullable=False)
    op.add_column("interview_schedules", sa.Column("copilot_messages", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("interview_schedules", sa.Column("copilot_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    # Do not silently destroy question knowledge or private conversation history.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM knowledge_documents WHERE source_type = 'interview_question'")):
        raise RuntimeError("Remove interview-question knowledge explicitly before downgrading")
    if connection.scalar(sa.text("SELECT COUNT(*) FROM interview_schedules WHERE copilot_version > 0")):
        raise RuntimeError("Export and clear interview copilot history explicitly before downgrading")
    op.drop_column("interview_schedules", "copilot_version")
    op.drop_column("interview_schedules", "copilot_messages")
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.alter_column("source_type", existing_type=new_type, type_=old_type, existing_nullable=False)
