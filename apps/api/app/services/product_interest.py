"""What "this product" means — the customer's recently-discussed products.

The +885 thread (2026-08-19): a customer returned saying "Is this product now
available? Last time we checked it was yet to be re-stocked" — and Neema, who
had personally told them it was out of stock, asked "which item?". The reason
is structural: the original ask was made with a PHOTO, and photos leave no
product name in the text history — `_history` skips empty-text rows entirely,
so a returning "this product" points at nothing the model can see.

But the system DID know. Every turn, `search_catalog` collects the full hub
rows the agent actually surfaced into `ctx.seen_products`. This module makes
that knowledge durable: after each real turn the surfaced products are
remembered per contact (name, slug, whether they were in stock AT THE TIME,
and when), and every future turn carries them back into the per-customer
context — so "is it available now?" resolves to the exact product, across
weeks, across photo-only asks, without asking the customer to start over.

Redis-backed, keyed by (channel, contact), newest first, deduped by slug,
capped at 5, kept 120 days. Best-effort everywhere: memory must never cost a
reply. Read-only turns (copilot drafts, briefings, bridges) READ this but
never write it — a preview must not pollute the record.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_log = logging.getLogger("neema.agent")

_KEEP = 5
_TTL = 120 * 86400


def _key(channel: str, contact: str) -> str:
    return f"interest:{channel}:{contact}"


async def remember(redis, channel: str, contact: str, products: list) -> None:
    """Fold this turn's surfaced products into the contact's memory."""
    rows = [{"name": (p.get("name") or "").strip(),
             "slug": (p.get("slug") or "").strip(),
             "in_stock": bool(p.get("in_stock", True)),
             "at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
            for p in (products or [])
            if isinstance(p, dict) and (p.get("name") or "").strip()
            and (p.get("slug") or "").strip()]
    if redis is None or not rows:
        return
    try:
        merged: list[dict] = []
        seen: set[str] = set()
        old = await recall(redis, channel, contact)
        for r in rows + old:                     # this turn's first = newest wins
            if r["slug"] in seen:
                continue
            seen.add(r["slug"])
            merged.append(r)
        await redis.set(_key(channel, contact), json.dumps(merged[:_KEEP]),
                        ex=_TTL)
    except Exception:
        pass                                     # memory must never cost a reply


async def recall(redis, channel: str, contact: str) -> list[dict]:
    if redis is None:
        return []
    try:
        raw = await redis.get(_key(channel, contact))
        if not raw:
            return []
        out = json.loads(raw if isinstance(raw, str) else raw.decode())
        return [r for r in out if isinstance(r, dict) and r.get("name")] \
            if isinstance(out, list) else []
    except Exception:
        return []


def context_block(items: list[dict]) -> str:
    """The per-customer tail section that makes "this product" resolvable."""
    if not items:
        return ""
    lines = []
    for r in items[:_KEEP]:
        when = f" ({r['at']})" if r.get("at") else ""
        stock = " — was OUT OF STOCK when last discussed" if not r.get("in_stock", True) else ""
        lines.append(f"- {r['name']}{stock}{when}")
    return (
        "\n\nPRODUCTS RECENTLY DISCUSSED WITH THIS CUSTOMER (newest first — "
        "from earlier conversations, including photo-only asks whose text "
        "history shows nothing):\n" + "\n".join(lines) + "\n"
        "When they return saying \"this product\" / \"is it available now\" / "
        "\"that one\" WITHOUT naming it, they mean the newest matching item "
        "above — especially one marked OUT OF STOCK if they're asking about "
        "availability. Do NOT ask them to re-explain from nothing: name it "
        "yourself (\"You asked about the Brass Thurible —\"), `search_catalog` "
        "it fresh, answer per the availability rules (availability is "
        "confirmed, never denied), and show its card. Only ask which item "
        "when this list is empty or two entries genuinely both fit."
    )
