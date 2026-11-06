"""Minimal automatic schema upgrades.

create_all() makes missing tables but never changes existing ones, so a
deploy that adds a column would crash on a live database. This adds any
model column missing from the database (as NULL-able, with the model's
default backfilled). It never drops or alters anything. Bigger changes
(renames, type changes) still need a proper migration.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base

log = logging.getLogger(__name__)


def _literal(value) -> str | None:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def add_missing_columns(engine: Engine) -> list[str]:
    insp = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                lit = _literal(default)
                if lit is not None:
                    conn.execute(text(f'UPDATE "{table.name}" SET "{col.name}" = {lit}'))
                added.append(f"{table.name}.{col.name}")
    if added:
        log.info("Added columns: %s", ", ".join(added))
    return added
