"""THE CUSTOMER'S TIMELINE — two levels, grouped, from the ledger it already has.

Owner's directive (2026-11-09, Phase 5): the Activity tab must read as a
customer timeline — what happened to this customer — with the system's own
steps available but not in the way. The audit (`CUSTOMER_INTELLIGENCE_AUDIT.md`
§6) found one ledger (`GET /conversations/{id}/activity`) with every source
flattened to one level: eleven "Searched the catalogue" rows beside the order
they led to, and nothing at all for a discovery, a stage change or a promised
check. This module gives every event a `level`, folds repeated technical
steps into one line, and names the events the trail now writes.

Levels:
  · customer  — something that happened to or for the customer: a message
                picked up or escalated, a check-in sent, an order, a call, a
                deal opened, a promise, a discovery about them, a stage
                change, a promised check and its escalation or answer, a
                hold, a hand-over, measurements saved, details captured;
  · technical — how Neema got there: a catalogue search, cards shown, a cart
                edit, a check-in planned or vetoed, a catalogue link, a
                calendar read, a remembered fact.

Grouping folds consecutive technical rows with the same label inside a short
window into one row with a count ("Searched the catalogue ×4") and the first
few details. Customer-level rows are never folded.

Pure functions; the endpoint applies them. No storage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

GROUP_WINDOW = timedelta(minutes=10)
GROUP_DETAILS = 3

# Tool rows (kind "tool", keyed by the trail's label) that are customer-level.
_CUSTOMER_TOOL_LABELS = {
    "Created an order", "Order NOT placed", "Saved customer details", "Saved measurements",
    "Handed the conversation to a human", "Escalated to a human",
    "Paused the conversation (2h cooldown)", "Asked the team to confirm availability",
    "Sent a product video", "Shared the WhatsApp checkout link",
    # the events the trail writes for state changes (this slice)
    "Placed the customer", "Stage moved", "Promised check escalated", "Promised check answered",
    "Asked for time", "Comparing prices", "Consulting someone", "Says they have paid",
    "Has a complaint", "Asked us to stop",
}
_CUSTOMER_KINDS = {"escalated", "flag", "intercept", "release", "transfer", "pause",
                   "approve_draft", "checkin_sent", "deal", "promise", "order", "call",
                   "geography", "stage", "commitment", "customer_state"}
_TECHNICAL_KINDS = {"checkin_planned", "checkin_vetoed", "checkin_needs_approval",
                    "checkin_failed"}


def level_of(event: dict) -> str:
    """'customer' or 'technical' for one ledger event."""
    kind = str(event.get("kind") or "")
    if kind in _TECHNICAL_KINDS:
        return "technical"
    if kind == "tool":
        label = str(event.get("label") or "")
        if label in _CUSTOMER_TOOL_LABELS:
            return "customer"
        if label.startswith(("Stage moved", "Promised check", "Placed the customer")):
            return "customer"
        return "technical"
    if kind in _CUSTOMER_KINDS or kind.startswith("checkin_sent"):
        return "customer"
    return "technical" if kind.startswith("checkin_") else "customer"


def _at(event: dict) -> datetime | None:
    v = event.get("at")
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def group(events: list[dict]) -> list[dict]:
    """Fold runs of technical rows with the same label (newest-first input,
    newest-first output). A folded row carries `count`, the first details,
    and `members` (the ids it stands for)."""
    out: list[dict] = []
    for e in events:
        prev = out[-1] if out else None
        if (prev is not None and e.get("level") == "technical" and prev.get("level") == "technical"
                and e.get("label") == prev.get("label")):
            a, b = _at(prev), _at(e)
            if a is not None and b is not None and abs(a - b) <= GROUP_WINDOW:
                prev["count"] = int(prev.get("count") or 1) + 1
                prev.setdefault("members", [prev["id"]]).append(e["id"])
                details = list(prev.get("details") or ([prev["detail"]] if prev.get("detail") else []))
                if e.get("detail") and e["detail"] not in details:
                    details.append(e["detail"])
                prev["details"] = details[:GROUP_DETAILS]
                prev["detail"] = " · ".join(prev["details"]) + (
                    f" · +{prev['count'] - len(prev['details'])} more"
                    if prev["count"] > len(prev["details"]) and len(prev["details"]) >= GROUP_DETAILS
                    else "")
                prev["first_at"] = e.get("at")
                continue
        out.append(dict(e))
    return out


def annotate(events: list[dict], *, level: str | None = None, fold: bool = True) -> dict:
    """Levels on every event, the counts per level, the optional filter and
    the folding. `level` is 'customer', 'technical' or None (both)."""
    for e in events:
        e["level"] = level_of(e)
    counts = {"customer": sum(1 for e in events if e["level"] == "customer"),
              "technical": sum(1 for e in events if e["level"] == "technical")}
    shown = [e for e in events if level in (None, "", "all") or e["level"] == level]
    if fold:
        shown = group(shown)
    return {"events": shown, "levels": counts}


# ── the events the trail now writes for state changes ────────────────────────

async def note(db, *, channel: str, contact: str, kind: str, summary: str,
               detail: str | None = None, args: dict | None = None) -> None:
    """One customer-level row through the activity trail (its own commit,
    best-effort). `kind` becomes the row's tool column: stage · commitment ·
    customer_state. Call after the caller's own commit."""
    try:
        from app.services import activity_trail
        await activity_trail.record(db, channel=channel, contact=contact, tool=kind,
                                    args=dict(args or {}), out={"summary": summary, "detail": detail})
    except Exception:
        pass
