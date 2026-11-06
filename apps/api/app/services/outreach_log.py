"""Who sent what, and why — the record every unprompted message leaves.

Until now an outbound row could not say which component produced it; the
inbox showed the words and nothing else, and no sender could ask "has anyone
written to this customer today?". Every unprompted sender now stamps the row's
`raw_meta` (an existing JSONB column — no migration) through `stamp()`, and
every decision NOT to send is logged through `decision()` with the contact
masked. The trace CLI (app/jobs/outreach_trace.py) reads both.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

_log = logging.getLogger("neema.outreach")

KIND = "outreach"

# Message classes (audit §4): what the message IS for the customer. Decisions
# in later stages are made per class; today the class is recorded.
ROUTINE = "routine"              # a sales follow-up nobody asked for
PROMISE = "promise"              # a check-in on a day the customer or Neema named
TRANSACTIONAL = "transactional"  # order / payment / care about their own order
ANSWER = "answer"                # a reply to something they asked


def stamp(source: str, cls: str, *, action_id=None, kind: str | None = None,
          reference: str | None = None, template: dict | None = None,
          delivery: dict | None = None) -> dict:
    """raw_meta for a stored outbound row."""
    m: dict = {"kind": KIND, "source": source, "class": cls,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if action_id is not None:
        m["action_id"] = str(action_id)
    if kind:
        m["action_kind"] = kind
    if reference:
        m["reference"] = str(reference)[:80]
    if template:
        m["template"] = template
    if delivery:
        m["delivery"] = delivery
    return m


def decision(source: str, channel: str, key: str, verdict: str, reason: str,
             **facts) -> None:
    """One line per decision — send, suppress, defer, hold — contact masked."""
    masked = f"…{str(key)[-4:]}" if key else "…"
    extra = " ".join(f"{k}={v}" for k, v in facts.items() if v is not None)
    _log.info("outreach %s %s/%s %s: %s %s", source, channel, masked, verdict, reason, extra)
