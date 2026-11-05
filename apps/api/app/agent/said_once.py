"""SAID ONCE — what this customer has already been told (audit, 2026-11-05).

Mama Beth was told what the Bishop's set comes with three times, because
every turn re-derived it from scratch: the search row says "comes with …",
the post context says it, the set rule says it — and nothing remembered that
she had already heard it. The owner: "if we say a set has a cassock, a shirt,
a collar, stole, cinch belt, then we cannot be repeating every time."

This module keeps, per conversation, the facts a reply has already carried —
a set's contents, a price, our address, our payment lines — and hands the
next turn one short note: refer by name, do not re-list, a price again only
if they ask. The search tool marks a set row whose contents were already told.
It records from the reply that actually went out and never changes a reply.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.core.config import settings

_log = logging.getLogger("neema.said_once")

TTL = 14 * 86400
MAX_FACTS = 24
_ADDRESS_RE = re.compile(r"sonalux|moi\s+avenue", re.I)


def _key(channel: str, key: str) -> str:
    return f"said:{channel}:{key}"


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _payment_tails() -> list[str]:
    tails = []
    for raw in (settings.official_mpesa_numbers, settings.official_airtel_numbers):
        for n in str(raw or "").split(","):
            d = _digits(n)
            if len(d) >= 9:
                tails.append(d[-9:])
    return tails


def facts_in_reply(reply: str, seen: list, catalog: list | None = None,
                   currency: str = "KES") -> list[tuple[str, str]]:
    """(fact key, label) for every fact this reply carried that need not be
    said again: `set:<slug>` with its contents, `price:<slug>`, `address`,
    `payment`."""
    from app.agent import review as _rv
    from app.services.post_catalog import is_set_row, set_components
    text = " ".join((reply or "").split())
    low = text.lower()
    if not low:
        return []
    out: list[tuple[str, str]] = []
    figures = _rv.money_figures(text)
    for row in _rv.products_named(text, seen):
        slug = str(row.get("slug") or "").strip()
        name = str(row.get("name") or "").strip()
        if not slug or not name:
            continue
        if is_set_row(row):
            comps = set_components(row, catalog)
            told = [c for c in comps if c.lower() in low]
            if comps and len(told) >= 2:
                out.append((f"set:{slug}", f"{name} comes with {', '.join(comps)}"))
        if figures and any(_rv._close(f, v) for f in figures
                           for v in _rv._row_figures(row, currency)):
            shown = next((f for f in figures
                          if any(_rv._close(f, v) for v in _rv._row_figures(row, currency))), None)
            if shown is not None:
                out.append((f"price:{slug}", f"{name} at {_fmt(shown)}"))
    if _ADDRESS_RE.search(text):
        out.append(("address", "our shop address"))
    d = _digits(text)
    if any(t in d for t in _payment_tails()):
        out.append(("payment", "our payment lines"))
    return out


def _fmt(v: float) -> str:
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"


async def remember(redis, channel: str, key: str, facts: list[tuple[str, str]]) -> None:
    """Record the facts a sent reply carried. Best-effort."""
    if redis is None or not facts:
        return
    k = _key(channel, key)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        for fact, label in facts[:MAX_FACTS]:
            await redis.hset(k, fact, f"{stamp}|{label}")
        await redis.expire(k, TTL)
    except Exception as exc:
        _log.info("said-once record skipped for %s/%s: %s", channel, key, exc)


async def told(redis, channel: str, key: str) -> dict[str, str]:
    """{fact key: label} — what this customer has already been told."""
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(_key(channel, key))
    except Exception:
        return {}
    out: dict[str, str] = {}
    for f, v in (raw or {}).items():
        f = f.decode() if isinstance(f, bytes) else str(f)
        v = v.decode() if isinstance(v, bytes) else str(v)
        out[f] = v.split("|", 1)[1] if "|" in v else v
    return out


def note(said: dict[str, str]) -> str:
    """The turn note: refer by name, do not re-list, a price again only if
    asked. "" when nothing has been told yet."""
    if not said:
        return ""
    sets = [v for k, v in said.items() if k.startswith("set:")]
    prices = [v for k, v in said.items() if k.startswith("price:")]
    other = [v for k, v in said.items() if k in ("address", "payment")]
    parts = []
    if sets:
        parts.append("contents already listed — say 'the set' and its price, never the list again "
                     "unless they ask what is in it: " + "; ".join(sets[:4]))
    if prices:
        parts.append("prices already given — repeat one only if they ask for it again: "
                     + "; ".join(prices[:6]))
    if other:
        parts.append("already given: " + ", ".join(other))
    return ("\n\n(ALREADY TOLD THIS CUSTOMER — a shared fact is said once; refer to it by "
            "name: " + " | ".join(parts) + ")")


def set_keys(said: dict[str, str]) -> frozenset:
    return frozenset(k for k in said if k.startswith("set:"))
