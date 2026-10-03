"""The migration chain must run from an empty database.

`20260323_0001_initial` builds the schema with `Base.metadata.create_all`
rather than explicit DDL, so every later revision has to tolerate the objects
it adds already existing. Nothing caught that before: production is stamped
past those revisions and the other tests build their schema with `create_all`
directly, never touching Alembic. This test walks the real chain.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.base import Base
import app.models  # noqa: F401  (registers every mapped class on Base.metadata)

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_single_head() -> None:
    """A branched chain would make `upgrade head` ambiguous."""
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    assert len(script.get_heads()) == 1, f"expected one head, found {script.get_heads()}"


def test_upgrade_head_from_empty_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "migrations.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("RMS_DATABASE_URL", url)
    monkeypatch.setenv("RMS_SECRET_KEY", "test-secret")

    command.upgrade(_alembic_config(url), "head")

    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        actual_tables = set(inspector.get_table_names())

        missing_tables = {t for t in Base.metadata.tables if t not in actual_tables}
        assert not missing_tables, f"tables declared by the models but not migrated: {sorted(missing_tables)}"

        for name, table in Base.metadata.tables.items():
            actual_columns = {col["name"] for col in inspector.get_columns(name)}
            expected_columns = {col.name for col in table.columns}
            missing = expected_columns - actual_columns
            assert not missing, f"{name}: columns declared by the model but not migrated: {sorted(missing)}"
    finally:
        engine.dispose()
