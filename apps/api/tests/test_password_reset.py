"""The mail sender and the reset helpers without a database or a network."""
import asyncio

import pytest

from app.services import mailer, password_reset


def test_mail_is_off_until_a_host_and_a_sender_exist(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_from", "")
    assert not mailer.configured()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    assert not mailer.configured()                   # a host alone: nobody to send as
    monkeypatch.setattr(settings, "smtp_user", "neema@example.test")
    assert mailer.configured() and mailer.sender() == "neema@example.test"
    monkeypatch.setattr(settings, "smtp_from", "no-reply@example.test")
    assert mailer.sender() == "no-reply@example.test"
    msg = mailer.build(["info@example.test"], "Hello", "Plain body")
    assert msg["To"] == "info@example.test" and msg["Subject"] == "Hello"
    assert "no-reply@example.test" in msg["From"] and msg.get_content().strip() == "Plain body"


def test_send_refuses_cleanly_when_off_or_unreachable(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_host", "")
    with pytest.raises(mailer.MailError, match="not configured"):
        asyncio.run(mailer.send(["a@example.test"], "s", "t"))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_user", "neema@example.test")
    with pytest.raises(mailer.MailError, match="no recipient"):
        asyncio.run(mailer.send([" "], "s", "t"))

    def boom(msg, to):
        raise OSError("connection refused")
    monkeypatch.setattr(mailer, "_send_sync", boom)
    with pytest.raises(mailer.MailError, match="could not be reached"):
        asyncio.run(mailer.send(["a@example.test"], "s", "t"))


def test_token_keys_links_and_mail_text():
    assert password_reset.norm_email("  Moses@Example.co.ke ") == "moses@example.co.ke"
    k = password_reset.token_key("abc")
    assert k.startswith("pwreset:tok:") and "abc" not in k and len(k) == len("pwreset:tok:") + 64
    assert password_reset.reset_link("https://neema.example.test/", "t0k") == "https://neema.example.test/reset-password?token=t0k"

    class A:
        name, email = "Ann Wanjiru", "ann@example.test"
    subject, text = password_reset.mail_text(A(), "https://x/reset-password?token=t", 60, "41.90.1.1")
    assert subject == "Neema password reset for Ann Wanjiru"
    assert "Ann Wanjiru (ann@example.test)" in text and "https://x/reset-password?token=t" in text
    assert "works once, expires in 60 minutes" in text and "41.90.1.1" in text
    assert "Settings → Team" in password_reset.NOT_SET_UP


def test_the_limiter_counts_with_get_and_set():
    class R:
        def __init__(self):
            self.store = {}

        async def get(self, k):
            return self.store.get(k)

        async def set(self, k, v, nx=False, ex=None):
            self.store[k] = v
            return True
    r = R()
    hits = [asyncio.run(password_reset._limited(r, "k", 3)) for _ in range(5)]
    assert hits == [False, False, False, True, True]
