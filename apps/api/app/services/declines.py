"""Has the customer just said no? — so no automatic message chases them.

Evidence (owner review, 2026-10-29): after "I will not order, we can't
afford", "zu teuer, ich kaufe es hier günstiger", "no enough cash" and a flat
"NO", Neema's reply offered a cheaper item or said "understood" — and then a
quote follow-up ("Shall I reserve it?") or the afternoon check-in went out
anyway, sometimes both. A customer who said no gets Neema's in-turn answer
(a cheaper option, paying little by little) and is then LEFT ALONE until they
write again.

Deliberately narrow — a false positive costs a sale, a false negative one
nudge: a message that asks something ("how much is the aluminium one?") is
never a decline, and only a flat refusal, "not now / next time", or a clear
price refusal counts. "The price is very high" (still bargaining) does not.
"""
from __future__ import annotations

import re

# The whole message, once punctuation and emoji are stripped.
_FLAT = {
    "no", "nope", "nop", "nah", "no thanks", "no thank you", "no thanx", "no sir",
    "not interested", "no not now", "not now", "not now thanks", "maybe next time",
    "next time", "hapana", "hapana asante", "sitaki", "nein", "nein danke",
    "wag na", "wag na muna", "wag na muna po", "hindi po", "huwag na",
}

_PHRASES = re.compile(
    r"\b(?:"
    r"can ?not aff?ord|can'?t aff?ord|cant aff?ord|not aff?ord|unable to aff?ord|"
    r"too expensive|too costly|too much for me|expens\w*\s+(?:for|to) me|"
    r"beyond my budget|out of my budget|over my budget|"
    r"(?:no|not) enough (?:cash|money)|don'?t have (?:the )?money|"
    r"not interested|no longer interested|no longer need|"
    r"not now|next time|wag na|zu teuer|ghali sana"
    r")\b",
    re.IGNORECASE)

_QUESTION = re.compile(r"\?|\b(?:how much|bei gani|ngapi|price of|what about|do you have)\b",
                       re.IGNORECASE)


def _flat(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']|_", " ", text.lower()).split())


def customer_declined(text: str | None) -> bool:
    """True when this customer message is a clear no (see module doc)."""
    t = (text or "").strip()
    if not t or len(t) > 280 or _QUESTION.search(t):
        return False
    return _flat(t) in _FLAT or bool(_PHRASES.search(t))
