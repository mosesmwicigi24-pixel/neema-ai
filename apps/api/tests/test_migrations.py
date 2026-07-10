"""Migration integrity: the chain must replay on a FRESH database, and the
fully-migrated schema must contain every model column.

This is the net that would have caught the messages.comment_context outage (a
model column shipped with no migration → prod 500s invisible to /api/health) and
the fresh-DB replay break (legacy `custom_roles` drops). Skips cleanly when no
database is reachable, so `pytest` stays green outside the Docker harness.
"""
import os
import uuid

import pytest
import sqlalchemy as sa

def _sync_url() -> str | None:
    return os.environ.get("DATABASE_URL_SYNC")


def _reachable(url: str) -> bool:
    try:
        eng = sa.create_engine(url, connect_args={"connect_timeout": 3})
        with eng.connect():
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                    reason="needs a reachable Postgres (run in the Docker verify harness)")
def test_chain_replays_fresh_and_schema_matches_models():
    base_url = _sync_url()
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    dbname = f"migtest_{uuid.uuid4().hex[:10]}"
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    try:
        fresh_url = base_url.rsplit("/", 1)[0] + f"/{dbname}"
        # alembic/env.py reads the app settings (not alembic.ini), so run the
        # upgrade in a subprocess with DATABASE_URL_SYNC pointed at the fresh DB —
        # exactly how the box runs migrations.
        import subprocess, sys
        env = {**os.environ, "DATABASE_URL_SYNC": fresh_url}
        r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, f"fresh-DB replay failed:\n{r.stderr[-2000:]}"

        # Drift: every model table/column must exist in the migrated schema.
        # Import the whole app so EVERY model registers (a hand-picked import
        # list silently exempts new models — that's how production_enquiries
        # initially slipped past the standalone run).
        import app.main  # noqa: F401
        from app.models import Base
        insp = sa.inspect(sa.create_engine(fresh_url))
        db_tables = set(insp.get_table_names())
        missing = []
        for t in Base.metadata.sorted_tables:
            if t.name not in db_tables:
                missing.append(f"TABLE {t.name}")
                continue
            cols = {c["name"] for c in insp.get_columns(t.name)}
            missing += [f"{t.name}.{c.name}" for c in t.columns if c.name not in cols]
        assert not missing, f"model↔migration drift (write a migration!): {missing}"
    finally:
        with admin.connect() as c:
            c.execute(sa.text(
                f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
