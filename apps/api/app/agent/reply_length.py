"""THE REPLY-LENGTH TARGET (audit, 2026-11-05).

The brevity contract lived only as prose — ~900 lines into the prompt,
ranked fourth, beside worked examples three times its own length — and
nothing in code ever measured a reply. Owner: "if a client is brief and the
answer requires a brief answer, we don't have to do an essay."

Here the target is COMPUTED from the customer's message before the model
writes — a short ask earns a short reply, a request for detail earns room,
an order summary is never capped — and handed to the writer as one line on
the current message. After the reply goes out, its length is measured
against the target and a long one is RECORDED (Reports → Pacing, decision
"long"), once per contact per day. Record-only: nothing here changes what
the customer receives. A trim pass is a later decision, on the evidence.
"""
from __future__ import annotations

import re

from app.core.config import settings

# Words, by the kind of message that came in.
TARGETS = {
    "ack": 12,        # thanks / ok / amen / a greeting alone
    "short": 25,      # a few words, a yes-or-no, a bare price ask
    "question": 35,   # one plain question
    "default": 45,
    "complaint": 60,  # care first, then the fix
    "detail": 75,     # "tell me about", "what's in it", several questions, a list asked for
}
# What a turn DID that earns an uncapped reply: an order or quote summary,
# a cart change (the line and the new total), measurements saved back.
UNCAPPED_TOOLS = frozenset({"create_order", "prepare_quotation", "update_cart",
                            "save_measurements", "whatsapp_checkout_link"})

_DETAIL_RE = re.compile(
    r"\b(?:tell me (?:more|about)|explain|details?|describe|what(?:'s| is) (?:in|included)|"
    r"what (?:does|do) (?:it|they) (?:come|include)|all (?:the )?(?:options|prices|items|colou?rs|sizes)|"
    r"price ?list|catalou?g(?:ue)?|everything|full (?:list|set|details)|options|"
    r"nielezee|maelezo|orodha|bei zote|vipi kuhusu)\b", re.I)
_PRICE_ASK_RE = re.compile(
    r"\b(?:how much|price|bei|ngapi|cost|pesa ngapi)\b", re.I)
_YESNO_RE = re.compile(
    r"^(?:is|are|do|does|did|can|could|will|would|have|has|shall|should|je)\b", re.I)


def target_for(user_text: str, *, closer: bool = False, greeting: bool = False,
               negative: bool = False) -> dict:
    """{'words', 'kind', 'why'} for this message. Pure; no I/O."""
    t = " ".join((user_text or "").split())
    n = len(t.split())
    qmarks = t.count("?")
    if closer or (greeting and n <= 4):
        kind = "ack"
    elif negative:
        kind = "complaint"
    elif _DETAIL_RE.search(t) or qmarks >= 2:
        kind = "detail"
    elif n <= 6 or _YESNO_RE.match(t) or (_PRICE_ASK_RE.search(t) and n <= 10):
        kind = "short"
    elif qmarks == 1 and n <= 20:
        kind = "question"
    else:
        kind = "default"
    words = TARGETS[kind]
    why = {
        "ack": "a bare thank-you or greeting",
        "short": f"a {n}-word ask",
        "question": "one plain question",
        "default": f"a {n}-word message",
        "complaint": "a complaint — care, then the fix",
        "detail": "they asked for detail",
    }[kind]
    return {"words": words, "kind": kind, "why": why}


def note(target: dict) -> str:
    """The one line the writer gets on the current message."""
    if not target or not settings.reply_length_note:
        return ""
    w = int(target.get("words") or 0)
    if w <= 0:
        return ""
    return (f"\n\n(LENGTH: {target.get('why')} — answer in at most {w} words, the fact first; "
            "more only for a list they asked for, an order or quote summary, or measurements. "
            "A shared fact is said once; end with a question only when it moves the order.)")


def measure(reply: str) -> dict:
    t = " ".join((reply or "").split())
    words = len(t.split())
    sentences = len([s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]) if t else 0
    return {"words": words, "sentences": sentences, "questions": t.count("?")}


def uncapped(tool_log: list | None) -> bool:
    """A turn that made an order, a quote, a cart change or saved measurements
    is allowed its summary."""
    for e in tool_log or []:
        if str((e or {}).get("tool") or "") in UNCAPPED_TOOLS:
            out = (e or {}).get("out") or {}
            if not (isinstance(out, dict) and out.get("error")):
                return True
    return False


def is_long(reply: str, target: dict, tool_log: list | None = None) -> dict | None:
    """The finding when the reply ran past the target by the slack, or None."""
    if not reply or not target or uncapped(tool_log):
        return None
    m = measure(reply)
    limit = int(target.get("words") or 0)
    slack = float(getattr(settings, "reply_length_slack", 1.5) or 1.5)
    if limit <= 0 or m["words"] <= limit * slack:
        return None
    return {**m, "target": limit, "kind": target.get("kind"), "why": target.get("why")}


async def record(redis, db, *, channel: str, key: str, reply: str, target: dict,
                 tool_log: list | None) -> dict | None:
    """Record a long reply (Reports → Pacing, decision 'long'), once per
    contact per day. Record-only; best-effort; never touches the reply."""
    if not settings.reply_length_record or redis is None:
        return None
    hit = is_long(reply, target, tool_log)
    if hit is None:
        return None
    try:
        from app.agent import conversation_budget as _cb
        head = " ".join((reply or "").split())[:140]
        reasons = [f"{hit['words']} words for {hit['why']} (target {hit['target']}, "
                   f"{hit['sentences']} sentences, {hit['questions']} question marks)",
                   f"reply began: {head}"]
        await _cb._record_all(redis, db, channel, key, [("long", reasons)],
                              {"turns": hit["words"], "budget": hit["target"]})
    except Exception:
        return hit
    return hit
