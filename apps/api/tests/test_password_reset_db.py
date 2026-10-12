"""Password recovery on a real database (owner, 2026-10-12: "develop the way
to recover when forgotten, sent to info@bethanyhouse.co.ke").

The reset link goes to the business recovery inbox, named for the account;
the answer never says whether the email is an account; three asks an hour per
email; the token works once; the new password signs in; mail not set up → 503
that names the way out (Settings → Team)."""
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not (_sync_url() and _reachable(_sync_url())),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

INBOX = "info@bethanyhouse.co.ke"


class FakeRedis:
    def __init__(self):
        self.store: dict = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def world(fresh_db):  # noqa: F811
    eng = sa.create_engine(fresh_db)
    ids = {"moses": str(uuid.uuid4())}
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE calls, conversations, agents CASCADE"))
        from app.core.security import hash_password
        c.execute(sa.text(
            "INSERT INTO agents (id, name, email, password_hash, role, is_available, is_superuser, "
            "active_convs, created_at) VALUES (:id, 'Moses Mwicigi', 'Moses@Example.co.ke', :h, 'admin', "
            "TRUE, FALSE, 0, NOW())"), {"id": ids["moses"], "h": hash_password("old-password-1")})
    eng.dispose()
    return ids


@pytest.fixture
def env(fresh_db, monkeypatch):  # noqa: F811
    """The auth router on the fresh database, a fake redis, a recording mailer."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.core.config import settings
    from app.database import get_db
    from app.routers import auth
    from app.services import mailer

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_user", "neema@example.test")
    monkeypatch.setattr(settings, "smtp_password", "not-logged")
    monkeypatch.setattr(settings, "password_reset_inbox", INBOX)
    monkeypatch.setattr(settings, "password_reset_copy_agent", False)
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example.test")
    sent: list[dict] = []

    async def send(to, subject, text, html=None):
        sent.append({"to": list(to), "subject": subject, "text": text})
    monkeypatch.setattr(mailer, "send", send)

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.dependency_overrides[get_db] = _db
    app.state.redis = FakeRedis()
    with TestClient(app) as c:
        c.sent = sent
        c.redis = app.state.redis
        yield c


def _link(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("https://"))


def test_the_reset_link_goes_to_the_recovery_inbox_named_for_the_account_and_works_once(env, world):
    r = env.post("/api/auth/forgot-password", json={"email": "  moses@example.co.ke "},
                 headers={"x-forwarded-for": "41.90.1.1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["inbox"] == INBOX and INBOX in body["message"] and "60 minutes" in body["message"]
    assert len(env.sent) == 1
    mail = env.sent[0]
    assert mail["to"] == [INBOX]                                  # the office, not the person
    assert mail["subject"] == "Neema password reset for Moses Mwicigi"
    assert "Moses Mwicigi (Moses@Example.co.ke)" in mail["text"] and "41.90.1.1" in mail["text"]
    link = _link(mail["text"])
    assert link.startswith("https://neema.example.test/reset-password?token=")
    token = link.split("token=", 1)[1]
    assert len(token) >= 40 and token not in str(env.redis.store)   # only the hash is stored

    # a weak password is refused and the token survives
    r = env.post("/api/auth/reset-password", json={"token": token, "password": "short"})
    assert r.status_code == 422
    r = env.post("/api/auth/reset-password", json={"token": token, "password": "new-password-9"})
    assert r.status_code == 200 and r.json() == {"ok": True, "email": "Moses@Example.co.ke"}
    # the token is spent
    r = env.post("/api/auth/reset-password", json={"token": token, "password": "another-pass-9"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    # the new password signs in, the old one does not
    assert env.post("/api/auth/login", json={"email": "Moses@Example.co.ke", "password": "new-password-9"}).status_code == 200
    assert env.post("/api/auth/login", json={"email": "Moses@Example.co.ke", "password": "old-password-1"}).status_code == 401


def test_an_unknown_email_gets_the_same_answer_and_no_mail(env, world):
    r = env.post("/api/auth/forgot-password", json={"email": "nobody@example.co.ke"})
    assert r.status_code == 200 and INBOX in r.json()["message"]
    assert env.sent == []
    assert env.post("/api/auth/forgot-password", json={"email": "not-an-email"}).status_code == 422


def test_three_asks_an_hour_per_email_then_429(env, world):
    for _ in range(3):
        assert env.post("/api/auth/forgot-password", json={"email": "moses@example.co.ke"}).status_code == 200
    r = env.post("/api/auth/forgot-password", json={"email": "moses@example.co.ke"})
    assert r.status_code == 429 and "hour" in r.json()["detail"]
    assert len(env.sent) == 3


def test_a_bad_or_missing_token_is_refused(env, world):
    assert env.post("/api/auth/reset-password", json={"token": "nope", "password": "long-enough-9"}).status_code == 400
    assert env.post("/api/auth/reset-password", json={"token": "", "password": "long-enough-9"}).status_code == 400


def test_mail_not_set_up_says_who_can_reset_instead(env, world, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_host", "")
    r = env.post("/api/auth/forgot-password", json={"email": "moses@example.co.ke"})
    assert r.status_code == 503 and "Settings → Team" in r.json()["detail"]
    assert env.sent == []


def test_a_mail_failure_withdraws_the_token_and_names_the_way_out(env, world, monkeypatch):
    from app.services import mailer

    async def failing(to, subject, text, html=None):
        raise mailer.MailError("the mail server refused our login — check SMTP_USER / SMTP_PASSWORD")
    monkeypatch.setattr(mailer, "send", failing)
    r = env.post("/api/auth/forgot-password", json={"email": "moses@example.co.ke"})
    assert r.status_code == 502 and "refused our login" in r.json()["detail"] and "Settings → Team" in r.json()["detail"]
    assert not [k for k in env.redis.store if k.startswith("pwreset:tok:")]


def test_the_agents_own_address_is_copied_only_when_switched_on(env, world, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "password_reset_copy_agent", True)
    assert env.post("/api/auth/forgot-password", json={"email": "moses@example.co.ke"}).status_code == 200
    assert env.sent[0]["to"] == [INBOX, "Moses@Example.co.ke"]
