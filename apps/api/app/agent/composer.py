"""What every message Neema composes WITHOUT a customer message in front of
her has in common (audit, 2026-11-05).

A scheduled check-in, a cart nudge, an order update and a team answer all ran
the live prompt — which opens a NEW conversation with the time-of-day greeting
— under a note that called the message "fresh". Three "Good morning, Judas"
in one morning followed. The note below is the one voice for all of them; the
greeting strip is the deterministic floor when the model greets anyway.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CONTINUATION_NOTE = (
    "[CONTINUATION, NOT A NEW CONVERSATION. You are writing into an open chat "
    "with this customer. No greeting, no welcome, no re-introduction and no "
    "time-of-day opener if we exchanged messages in the last 24 hours — their "
    "first name or title alone may open the message. Say in ONE sentence why "
    "you are writing now (the commitment kept, the fact that arrived, the thing "
    "they were deciding), in the language THEY last wrote in. Nothing already "
    "said is said again — no re-listing, no re-quoting unless the figure is the "
    "point. At most one question, only if it moves their matter forward. Never "
    "'just checking in', never 'I hope this finds you well', never pressure. If "
    "a colleague has already answered the matter, their answer stands: repeat "
    "its substance only if the customer has not seen it.]"
)

_TITLE = r"(?:dear|pastor|pst\.?|rev\.?|reverend|bishop|mch\.?|dr\.?|mr\.?|mrs\.?|ms\.?|madam|sir)"
_GREETING_RE = re.compile(
    r"^\s*(?:good\s+(?:morning|afternoon|evening|day)|habari(?:\s+za\s+\w+)?|"
    r"hello|hi|hey|jambo|salama|bonjour|bonsoir|shalom|jai\s+masih\s+ki|praise\s+(?:the\s+)?lord|"
    r"bwana\s+asifiwe|नमस्ते|जय\s+मसीह\s+की|सुप्रभात)"
    r"[\s,!.]*(?:(?:from\s+)?bethany\s+house[\s,!.]*)?"
    rf"(?P<name>(?:{_TITLE}\s+)*[A-Zऀ-ॿ][\w'’.-]{{1,19}})?[\s,!.:—\-🙏✨🙂😊🙌]*",
    re.IGNORECASE)
_LOWER_OPENERS = frozenset({
    "there's", "there", "your", "the", "we", "we're", "we've", "our", "just", "as", "a", "an",
    "this", "that", "it", "it's", "shall", "would", "here", "thank", "thanks",
    "following", "about", "on", "regarding", "to", "for", "my", "if", "when", "once",
})


def recently_spoke(last_outbound_at: datetime | None, *, hours: int = 24,
                   now: datetime | None = None) -> bool:
    if last_outbound_at is None:
        return False
    if last_outbound_at.tzinfo is None:
        last_outbound_at = last_outbound_at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - last_outbound_at < timedelta(hours=hours)


def strip_repeated_greeting(text: str, *, recent: bool) -> str:
    """When we spoke within the day, a leading time-of-day greeting comes off
    and the message starts at its substance; a name that followed the greeting
    is kept as the opener ("Good morning, Judas. There's no rush" →
    "Judas, there's no rush")."""
    if not recent or not text:
        return text
    m = _GREETING_RE.match(text)
    if not m:
        return text
    name = (m.group("name") or "").strip(" ,.!")
    # A capitalised word straight after the greeting is a name only when a
    # comma, stop or emoji follows it ("Good morning, Judas. …"); "Good morning
    # from Bethany House! Your trays shipped" keeps "Your" with its sentence.
    if name and not re.search(r"[,.!:—\-🙏✨🙂😊🙌]", text[m.start("name"):m.end()]):
        name, end = "", m.start("name")
    else:
        end = m.end()
    rest = text[end:].lstrip()
    if not rest:
        return text
    if name and name.lower() not in ("morning", "afternoon", "evening", "day", "house", "lord"):
        first = rest.split(" ", 1)[0]
        if first.lower() in _LOWER_OPENERS:
            rest = first.lower() + rest[len(first):]
        return f"{name}, {rest}"
    return rest[0].upper() + rest[1:]
