"""Create or adopt the existing authentication schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-05
"""
from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


EXPECTED_USER_COLUMNS: set[str] = {
    "id",
    "name",
    "email",
    "password_hash",
    "role",
    "is_active",
    "created_at",
}


def _index_names(indexes: Iterable[dict]) -> set[str]:
    return {index["name"] for index in indexes if index.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    role_type = sa.Enum(
        "interviewer",
        "candidate",
        name="userrole",
        native_enum=False,
        create_constraint=True,
    )

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("email", sa.String(length=254), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("role", role_type, nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    else:
        existing_columns = {
            column["name"] for column in inspector.get_columns("users")
        }
        missing = EXPECTED_USER_COLUMNS - existing_columns
        if missing:
            raise RuntimeError(
                "Existing users table is missing required columns: "
                + ", ".join(sorted(missing))
            )

        existing_indexes = _index_names(inspector.get_indexes("users"))
        if "ix_users_email" not in existing_indexes:
            op.create_index("ix_users_email", "users", ["email"], unique=True)

    existing_indexes = _index_names(inspector.get_indexes("users"))
    if "uq_single_interviewer" not in existing_indexes:
        op.create_index(
            "uq_single_interviewer",
            "users",
            ["role"],
            unique=True,
            postgresql_where=sa.text("role = 'interviewer'"),
            sqlite_where=sa.text("role = 'interviewer'"),
        )


def downgrade() -> None:
    op.drop_index("uq_single_interviewer", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
