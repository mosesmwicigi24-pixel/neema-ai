"""The backfill runs on production as its own process:
`docker exec neema_api python -m app.scripts.backfill_transcripts --dry-run`.

In-process tests import app.main first, which loads every model, so they
could not see that a fresh interpreter couldn't resolve
Message.relationship("Conversation") — the first query raised
InvalidRequestError on production (2026-10-05). This runs the real command
in a fresh interpreter against a freshly migrated database.
"""
import os
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa


def _sync_url() -> str | None:
    return os.environ.get("DATABASE_URL_SYNC")


def _reachable(url: str) -> bool:
    try:
        with sa.create_engine(url, connect_args={"connect_timeout": 3}).connect():
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                    reason="needs a reachable Postgres (CI migrations job / Docker harness)")
def test_the_backfill_command_runs_in_a_fresh_process():
    base = _sync_url()
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    dbname = f"bftest_{uuid.uuid4().hex[:10]}"
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    try:
        sync = base.rsplit("/", 1)[0] + f"/{dbname}"
        env = {**os.environ, "DATABASE_URL_SYNC": sync,
               "DATABASE_URL": sync.replace("postgresql+psycopg2", "postgresql+asyncpg")}
        up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                            capture_output=True, text=True, env=env)
        assert up.returncode == 0, up.stderr[-2000:]
        r = subprocess.run(
            [sys.executable, "-m", "app.scripts.backfill_transcripts",
             "--dry-run", "--since", "30d"],
            capture_output=True, text=True, env=env, timeout=120)
        out = r.stdout + r.stderr
        assert "InvalidRequestError" not in out, out[-2000:]
        assert r.returncode == 0, out[-2000:]
    finally:
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))


# ── the class: every module that runs as its own process ─────────────────────

def _entrypoints():
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            src = open(path, encoding="utf-8").read()
            if '__name__ == "__main__"' in src or "__name__ == '__main__'" in src:
                rel = os.path.relpath(path, os.path.join(root, ".."))[:-3]
                yield rel.replace(os.sep, ".")


@pytest.mark.parametrize("module", sorted(_entrypoints()))
def test_every_standalone_entrypoint_resolves_all_models(module):
    """A fresh interpreter importing the entrypoint must configure every
    mapper — no database needed (configure_mappers is pure Python)."""
    code = (f"import {module}; from sqlalchemy.orm import configure_mappers; "
            "configure_mappers()")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=os.path.join(os.path.dirname(__file__), ".."), timeout=120)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
