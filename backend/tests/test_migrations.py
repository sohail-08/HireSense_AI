from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.database import Base


ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


def run_upgrade(database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def test_baseline_migration_creates_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"

    run_upgrade(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert "users" in inspector.get_table_names()
    assert "alembic_version" in inspector.get_table_names()
    assert {
        column["name"] for column in inspector.get_columns("users")
    } == {
        "id",
        "name",
        "email",
        "password_hash",
        "role",
        "is_active",
        "created_at",
    }


def test_baseline_migration_adopts_existing_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    run_upgrade(database_url)

    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names()
    assert "users" in inspector.get_table_names()
