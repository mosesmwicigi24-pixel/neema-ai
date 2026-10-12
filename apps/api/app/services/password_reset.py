"""Self-serve password recovery — the reset link goes to the business
recovery inbox (owner, 2026-10-12: "develop the way to recover when forgotten,
sent to info@bethanyhouse.co.ke"): the office hands it to the person, so a
lost phone or a forgotten mailbox never locks anyone out, and nobody resets a
colleague's account unseen.

- `request_reset`: one single-use token (32 random bytes — only its SHA-256 is
  kept, in redis, for PASSWORD_RESET_TTL_MINUTES) and one mail to
  PASSWORD_RESET_INBOX naming the account (plus the account's own address when
  PASSWORD_RESET_COPY_AGENT). The answer is the same whether or not the email
  is an account (no enumeration). 3 requests an hour per email and 10 per
  caller address → 429. Mail not set up → 503, saying who can reset instead.
- `complete_reset`: the token is consumed on first use (a second use is a
  400), the password must be 8+ characters, the hash is replaced.
"""
import hashlib
import logging
import secrets

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.agent import Agent

_log = logging.getLogger("neema.auth")

TOKEN_PREFIX = "pwreset:tok:"
RL_PREFIX = "pwreset:rl:"
PER_EMAIL_PER_HOUR = 3
PER_IP_PER_HOUR = 10
MIN_PASSWORD = 8

# The sentence the person reads either way (an account or not).
SENT_MESSAGE = ("If that email belongs to a Neema account, a reset link has been sent to the "
                "Bethany House recovery inbox ({inbox}). Ask the office for it — it works once "
                "and expires in {ttl} minutes.")
NOT_SET_UP = ("Password recovery by email isn't set up on the server yet. An admin can reset "
              "your password in Settings → Team, or ask the office.")


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def token_key(token: str) -> str:
    return TOKEN_PREFIX + hashlib.sha256((token or "").encode()).hexdigest()


async def _limited(redis, key: str, limit: int, ttl_s: int = 3600) -> bool:
    """True when `key` was already used `limit` times this hour. Counted with
    get/set (what every redis double here speaks); the hour restarts on each
    attempt, which only makes the limit stricter."""
    raw = await redis.get(key)
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= limit:
        return True
    await redis.set(key, n + 1, ex=ttl_s)
    return False


def reset_link(base_url: str, token: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/reset-password?token={token}"


def mail_text(agent: Agent, link: str, ttl: int, requested_from: str) -> tuple[str, str]:
    name = (agent.name or "").strip() or agent.email
    subject = f"Neema password reset for {name}"
    text = (f"A password reset was requested for the Neema account of {name} ({agent.email}).\n\n"
            f"Reset link (works once, expires in {ttl} minutes):\n{link}\n\n"
            f"Hand this link to {name} if they asked for it. If nobody did, ignore this mail — "
            f"the password stays as it is.\n\nRequested from: {requested_from or 'unknown'}\n")
    return subject, text


async def request_reset(db: AsyncSession, redis, email: str, ip: str, base_url: str) -> dict:
    from app.services import mailer
    if not mailer.configured():
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    if redis is None:
        raise HTTPException(status_code=503, detail="Password recovery isn't available right now — try again shortly.")
    email = norm_email(email)
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Enter the email address of your Neema account.")
    if await _limited(redis, f"{RL_PREFIX}email:{email}", PER_EMAIL_PER_HOUR) or (
            ip and await _limited(redis, f"{RL_PREFIX}ip:{ip}", PER_IP_PER_HOUR)):
        raise HTTPException(status_code=429, detail="Too many reset requests — try again in an hour, or ask the office.")
    ttl = max(5, int(settings.password_reset_ttl_minutes or 60))
    message = SENT_MESSAGE.format(inbox=settings.password_reset_inbox, ttl=ttl)
    agent = (await db.execute(select(Agent).where(func.lower(Agent.email) == email))).scalar_one_or_none()
    if agent is None:
        _log.info("password reset asked for an unknown email")
        return {"ok": True, "message": message, "sent": False}
    token = secrets.token_urlsafe(32)
    await redis.set(token_key(token), str(agent.id), ex=ttl * 60)
    to = [settings.password_reset_inbox]
    if settings.password_reset_copy_agent and agent.email:
        to.append(agent.email)
    subject, text = mail_text(agent, reset_link(base_url, token), ttl, ip)
    try:
        await mailer.send(to, subject, text)
    except mailer.MailError as exc:
        await redis.delete(token_key(token))
        _log.warning("password reset mail failed for agent %s: %s", agent.id, exc)
        raise HTTPException(status_code=502, detail=f"The reset mail could not be sent: {exc}. Ask the office to reset it in Settings → Team.")
    _log.info("password reset link sent for agent %s to %s", agent.id, ", ".join(to))
    return {"ok": True, "message": message, "sent": True}


async def complete_reset(db: AsyncSession, redis, token: str, password: str) -> dict:
    if redis is None:
        raise HTTPException(status_code=503, detail="Password recovery isn't available right now — try again shortly.")
    password = str(password or "")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Password must be at least {MIN_PASSWORD} characters")
    key = token_key(token)
    agent_id = await redis.get(key) if (token or "").strip() else None
    if not agent_id:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired — ask for a new one.")
    await redis.delete(key)                      # one use, even if what follows fails
    if isinstance(agent_id, bytes):
        agent_id = agent_id.decode()
    agent = (await db.execute(select(Agent).where(Agent.id == str(agent_id)))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=400, detail="This reset link no longer matches an account.")
    agent.password_hash = hash_password(password)
    await db.commit()
    _log.info("password reset completed for agent %s", agent.id)
    return {"ok": True, "email": agent.email}
