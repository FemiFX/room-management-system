"""Idempotency guards for migrations.

``20260323_0001_initial`` builds the schema with ``Base.metadata.create_all``
rather than explicit DDL, so on an empty database it creates whatever the
*current* models declare -- including columns and tables that later revisions
were written to add. Without guards, ``alembic upgrade head`` from zero fails
on the first duplicate column.

Production is stamped well past those revisions, so they never re-run there;
these helpers exist so a fresh install (and the migration test) can walk the
whole chain. Every new migration should use them too, for the same reason: the
column it adds already exists on a database built by 0001.

All helpers inspect the live bind, so they answer for the dialect actually in
use and degrade to ``False`` where a dialect cannot introspect a feature.

Lives under ``app/db`` rather than ``alembic/`` deliberately: ``alembic.ini``
sets ``prepend_sys_path = .``, so a module inside the local ``alembic/``
directory would shadow the installed ``alembic`` library.
"""

from __future__ import annotations

import warnings

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return any(col["name"] == column for col in _inspector().get_columns(table))


def _index_exists_in_catalog(index: str) -> bool:
    """Name lookup straight against the dialect's catalog.

    Reflection cannot see expression-based indexes (``lower(email)``) -- it
    skips them with a warning -- so a reflection-only guard would report a
    missing index that is really there and try to create it twice.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        query = sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :name")
    elif dialect == "postgresql":
        query = sa.text("SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = :name")
    else:
        return False
    return bind.execute(query, {"name": index}).first() is not None


def has_index(table: str, index: str) -> bool:
    if not has_table(table):
        return False
    inspector = _inspector()
    with warnings.catch_warnings():
        # Reflecting a table that has an expression index warns; we fall back
        # to the catalog for exactly that case, so the warning is noise.
        warnings.simplefilter("ignore", sa.exc.SAWarning)
        if any(existing["name"] == index for existing in inspector.get_indexes(table)):
            return True
        # A UNIQUE constraint and a unique index are the same object on some
        # dialects and distinct on others; check both so the guard is not
        # dialect-dependent.
        if any(existing["name"] == index for existing in inspector.get_unique_constraints(table)):
            return True
    return _index_exists_in_catalog(index)


def has_constraint(table: str, name: str, kind: str) -> bool:
    """``kind`` is one of ``unique``, ``check``, ``foreignkey``, ``primary``."""
    if not has_table(table):
        return False
    inspector = _inspector()
    getters = {
        "unique": inspector.get_unique_constraints,
        "check": inspector.get_check_constraints,
        "foreignkey": inspector.get_foreign_keys,
    }
    if kind == "primary":
        pk = inspector.get_pk_constraint(table)
        return pk.get("name") == name
    getter = getters.get(kind)
    if getter is None:
        raise ValueError(f"Unsupported constraint kind: {kind!r}")
    try:
        constraints = getter(table)
    except NotImplementedError:
        # Older SQLite drivers cannot report check constraints.
        return False
    return any(constraint.get("name") == name for constraint in constraints)


def has_foreign_key_on(table: str, column: str, *, referred_table: str | None = None) -> bool:
    """True when *any* foreign key constrains ``column``, whatever its name.

    ``create_all`` lets the dialect auto-name foreign keys, so a name-based
    check would miss an equivalent constraint and create a duplicate.
    """
    if not has_table(table):
        return False
    for fk in _inspector().get_foreign_keys(table):
        if column not in fk.get("constrained_columns", []):
            continue
        if referred_table is None or fk.get("referred_table") == referred_table:
            return True
    return False
