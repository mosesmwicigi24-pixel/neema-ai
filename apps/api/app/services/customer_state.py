"""Customer state — what the customer's own words mean for what we do next
(Stage 3, audit 2026-11-05).

Until now Neema's REPLIES understood intent (the model reads the whole
conversation) but her DECISIONS to speak unprompted did not: a scheduler saw
"quiet for 4 h" and "cart with items", never "he said he will compare prices
in Arusha". This module makes the understanding visible to the schedulers:

  · a DETERMINISTIC FLOOR for the phrases that must never be missed — asking
    for time, comparing prices, consulting a bishop / spouse / committee, a
    payment claim, a polite close, an opt-out — in English, Swahili and French;
  · a light-model NOTE after each real turn (no tools, a few hundred tokens)
    that reads the same conversation and answers five questions: who are we
    waiting on, what did the customer say, until when, in which language, is
    an item under confirmation;
  · one `apply()` that stores the result where the schedulers and the next
    turn read it: a HOLD on the deal (`deal.next_action["hold"]`, with the
    date), the customer's language and latest state on the person
    (`persons.state`), a payment claim as `deal.blocking` text.

What it never does: mark an order paid (the hub does that), overwrite a
colleague's team check, or speak. Speculative model readings only ever set
state the dispatcher treats as "wait" or "ask a person" — never "send".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.core.config import settings

_log = logging.getLogger("neema.state")

HOLD_STATES = ("needs_time", "comparing", "consulting")
STATES = ("exploring", "quoting", "comparing", "consulting", "needs_time", "ready",
          "paid_claim", "complaint", "closing", "stop", "none")
# Languages an automated message may be composed in; anything else goes to a
# person (the live turn still answers in the customer's language).
AUTOMATED_LANGUAGES = frozenset({"en", "sw", "fr"})
_HOLD_LABEL = {"needs_time": "Asked for time", "comparing": "Comparing prices",
               "consulting": "Consulting someone"}

# ── the floor ────────────────────────────────────────────────────────────────
_NEEDS_TIME_RE = re.compile(
    r"\b(?:get back to you|come back to you|let you know|let me think|think about it|"
    r"not (?:yet )?ready|not now|later on|give me (?:some )?time|i(?:'ll| will) (?:revert|decide)|"
    r"nitakujulisha|nitarudi|nitakuambia|nitawasiliana|nipe muda|si sasa|baadaye|"
    r"je reviens vers vous|je vous tiens au courant|laissez[- ]moi r[ée]fl[ée]chir|pas (?:encore|maintenant))\b",
    re.IGNORECASE)
_COMPARING_RE = re.compile(
    r"\b(?:compar\w*|other (?:supplier|shop|price|quot\w+)s?|check (?:other )?prices|shop around|"
    r"look around|see (?:elsewhere|other options)|kulinganisha|bei (?:nyingine|za wengine)|"
    r"wanaouza|maduka mengine|comparer|d'autres (?:prix|fournisseurs))\b",
    re.IGNORECASE)
_CONSULTING_RE = re.compile(
    r"\b(?:consult|ask|discuss(?: it)? with|talk (?:to|with)|check with|confirm with|"
    r"nimuulize|nitamuuliza|niulize|tuzungumze na|niongee na|demander [àa]|en parler [àa]|consulter)\b"
    r"[^.?!\n]{0,40}?\b(?:bishop|pastor|reverend|priest|father|husband|wife|spouse|committee|"
    r"board|council|church|parish|team|family|boss|director|treasurer|elders?|"
    r"askofu|mchungaji|padri|mume|mke|kamati|kanisa|familia|bodi|"
    r"[ée]v[êe]que|pasteur|mari|femme|comit[ée]|paroisse)\b",
    re.IGNORECASE)
_PAID_RE = re.compile(
    r"\b(?:i(?:'ve| have)? (?:already )?paid|payment (?:is )?(?:done|made|sent)|(?:i )?sent the money|"
    r"money sent|nimelipa|nimeshalipa|nimetuma pesa|j'ai (?:d[ée]j[àa] )?pay[ée]|paiement effectu[ée])\b",
    re.IGNORECASE)
_READY_RE = re.compile(
    r"\b(?:go ahead|proceed|place the order|i(?:'ll| will) take (?:it|them)|let's do it|confirm(?:ed)? the order|"
    r"endelea|nachukua|tuendelee|weka oda|allons-y|je (?:le |la |les )?prends)\b", re.IGNORECASE)
_COMPLAINT_RE = re.compile(
    r"\b(?:complain\w*|disappoint\w*|refund|wrong (?:item|size|colour|color)|damaged|torn|late|"
    r"never arrived|not (?:yet )?received|poor quality|sijapokea|imechelewa|imeharibika|"
    r"r[ée]clamation|rembours\w+|d[ée]çu)\b", re.IGNORECASE)


def floor(text: str | None, *, now: datetime | None = None) -> dict | None:
    """The deterministic reading of one customer message, or None when the
    words say nothing the schedulers must act on. Precedence: stop > paid
    claim > complaint > consulting > comparing > needs time > ready > closing."""
    t = " ".join((text or "").split())
    if not t:
        return None
    from app.services.intent import is_opt_out
    if is_opt_out(t):
        return {"customer_said": "stop", "matched": "opt-out"}
    if _PAID_RE.search(t):
        return {"customer_said": "paid_claim", "matched": _PAID_RE.search(t).group(0)}
    if _COMPLAINT_RE.search(t) and "?" not in t:
        return {"customer_said": "complaint", "matched": _COMPLAINT_RE.search(t).group(0)}
    until = None
    try:
        from app.services.deals import detect_customer_promise
        cp = detect_customer_promise(t, now=now)
        if cp:
            until = cp[0]
    except Exception:
        until = None
    for state, rx in (("consulting", _CONSULTING_RE), ("comparing", _COMPARING_RE),
                      ("needs_time", _NEEDS_TIME_RE)):
        m = rx.search(t)
        if m and not (state == "comparing" and "?" in t):      # "if I compare two sizes?" asks us
            return {"customer_said": state, "matched": m.group(0),
                    "hold_until": until.isoformat() if until else None}
    if until is not None:
        return {"customer_said": "needs_time", "matched": "named a time", "hold_until": until.isoformat()}
    if _READY_RE.search(t) and "?" not in t:
        return {"customer_said": "ready", "matched": _READY_RE.search(t).group(0)}
    try:
        from app.agent.runtime import is_closer
        if is_closer(t):
            return {"customer_said": "closing", "matched": "closer"}
    except Exception:
        pass
    return None


_SW_VERB_RE = re.compile(r"^(?:ni|u|a|tu|m|wa|si|ha)(?:ta|me|na|li|ki|ka|ja|sha)[a-z]{3,}$")
_SW_EXTRA = frozenset("""
    jumatatu jumanne jumatano alhamisi ijumaa jumamosi jumapili wiki mwezi baadaye kwanza
    bado tena ujumbe asante sawa habari karibu pole ndugu mchungaji askofu kanisa bei
    nitakujulisha nitarudi nitawasiliana nimelipa nimeshalipa
""".split())


def guess_language(text: str | None) -> str | None:
    """The customer's language from their own words, when it can be placed:
    script first (Devanagari → hi, Arabic → ar, Amharic → am), then Swahili,
    then French; English for an English message; None when unsure."""
    t = (text or "").strip()
    if not t:
        return None
    if re.search(r"[ऀ-ॿ]", t):
        return "hi"
    if re.search(r"[؀-ۿ]", t):
        return "ar"
    if re.search(r"[ሀ-፿]", t):
        return "am"
    from app.agent.voice import looks_swahili
    if looks_swahili(t):
        return "sw"
    toks = set(re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", t.lower()))
    en = {"the", "is", "how", "much", "price", "do", "you", "have", "want", "need", "please",
          "order", "can", "i", "my", "for", "and", "what", "when", "will", "thanks", "thank"}
    # Swahili by its verb shape (ni-ta-kujulisha, tu-me-pata) and its calendar
    # words — the short word list in voice.py misses a sentence with no price in it.
    sw_shape = sum(1 for w in toks if _SW_VERB_RE.match(w) or w in _SW_EXTRA)
    if sw_shape >= 1 and not (toks & en):
        return "sw"
    fr = {"bonjour", "bonsoir", "merci", "je", "vous", "votre", "vos", "est", "combien", "prix",
          "avec", "pour", "voulez", "souhaitez", "commande", "oui", "nous", "les", "des", "une",
          "sur", "c'est", "j'ai", "s'il", "plaît", "voudrais", "aimerais", "coûte"}
    if len(toks & fr) >= 2:
        return "fr"
    if len(toks & en) >= 2:
        return "en"
    return None


# ── the model's note ─────────────────────────────────────────────────────────

_NOTE_SYSTEM = (
    "You read a WhatsApp sales chat for Bethany House (church vestments and clothing) and "
    "state the customer's situation in JSON — nothing else. Fields:\n"
    '"waiting_on": "customer" | "us" | "team" | "none" — who owes the next move;\n'
    '"customer_said": one of exploring, quoting, comparing, consulting, needs_time, ready, '
    "paid_claim, complaint, closing, stop, none — what the customer's LAST message means "
    "(comparing = checking other prices; consulting = must ask a bishop/spouse/committee; "
    "needs_time = asked us to wait; ready = agreed to buy, not merely interested; "
    "paid_claim = says they paid; stop = asked for no more messages);\n"
    '"hold_until": "YYYY-MM-DD" when they named a day to come back, else null;\n'
    '"language": the ISO 639-1 code of the customer\'s last message (en, sw, fr, hi, …);\n'
    '"open_item_check": the item we told them we are confirming with the team, else null.\n'
    "Interest is not agreement. When unsure, choose none / null. Reply with the JSON object only."
)


def parse_note(raw: str | None) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    said = str(data.get("customer_said") or "none").strip().lower()
    out = {"waiting_on": str(data.get("waiting_on") or "none").strip().lower(),
           "customer_said": said if said in STATES else "none",
           "hold_until": None, "language": None,
           "open_item_check": (str(data.get("open_item_check")).strip()[:120]
                               if data.get("open_item_check") else None)}
    hu = str(data.get("hold_until") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", hu):
        out["hold_until"] = hu
    lang = str(data.get("language") or "").strip().lower()
    if re.match(r"^[a-z]{2}$", lang):
        out["language"] = lang
    return out


async def note(llm, transcript: list[tuple[str, str]], inbound_text: str, reply: str) -> dict | None:
    """One light completion, no tools. None when it cannot be read."""
    lines = [f"{'Customer' if r == 'customer' else ('Colleague' if r == 'team' else 'Neema')}: "
             f"{' '.join(t.split())[:300]}" for r, t in transcript[-12:]]
    if inbound_text:
        lines.append(f"Customer: {' '.join(inbound_text.split())[:400]}")
    if reply:
        lines.append(f"Neema: {' '.join(reply.split())[:300]}")
    today = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%A %Y-%m-%d")
    user = f"Today is {today} (Nairobi).\n\n" + "\n".join(lines)
    res = await llm.complete(system=_NOTE_SYSTEM, messages=[{"role": "user", "content": user}], tools=[])
    return parse_note(getattr(res, "text", None))


# ── storing and reading ──────────────────────────────────────────────────────

def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def hold_open(deal, *, now: datetime | None = None) -> tuple[datetime, str] | None:
    """(until, what they said) while the customer's own request for time
    stands — read by the dispatcher and the live turn."""
    nxt = getattr(deal, "next_action", None) or {}
    hold = nxt.get("hold") if isinstance(nxt, dict) else None
    if not isinstance(hold, dict) or not hold.get("until"):
        return None
    try:
        until = _aware(datetime.fromisoformat(hold["until"]))
    except (TypeError, ValueError):
        return None
    if until <= (now or datetime.now(timezone.utc)):
        return None
    return until, str(hold.get("said") or "needs_time")


def _default_until(now: datetime) -> datetime:
    days = int(getattr(settings, "customer_hold_days", 7) or 7)
    nbo = now + timedelta(hours=3)
    return (nbo + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(hours=3)


async def apply(db, conv, deal, reading: dict, *, source: str, inbound_text: str = "",
                now: datetime | None = None) -> dict:
    """Persist one reading (floor or model note). Returns what changed, for
    logs and tests. Commits. Never marks anything paid, never overwrites an
    open team check, never clears a hold on a reading that merely failed."""
    from sqlalchemy.orm.attributes import flag_modified
    now = now or datetime.now(timezone.utc)
    said = reading.get("customer_said") or "none"
    changed: dict = {"said": said, "source": source}

    # ── the person: language and the latest state ────────────────────────
    person = None
    if getattr(conv, "person_id", None) is not None:
        from app.models.person import Person
        person = await db.get(Person, conv.person_id)
    if person is not None:
        state = dict(person.state or {})
        prefs = dict(state.get("contact_preferences") or {})
        lang = reading.get("language") or guess_language(inbound_text)
        if lang and prefs.get("language") != lang:
            prefs["language"] = lang
            changed["language"] = lang
        state["contact_preferences"] = prefs
        state["customer_state"] = {"said": said, "waiting_on": reading.get("waiting_on"),
                                   "at": now.isoformat(timespec="seconds"), "source": source,
                                   "hold_until": reading.get("hold_until")}
        person.state = state
        try:
            flag_modified(person, "state")
        except Exception:
            pass

    # ── the deal: holds and claims ───────────────────────────────────────
    if deal is not None:
        nxt = dict(deal.next_action or {}) if isinstance(deal.next_action, dict) else {}
        if said in HOLD_STATES:
            until = None
            if reading.get("hold_until"):
                try:
                    until = _aware(datetime.fromisoformat(reading["hold_until"]))
                    if until.hour == 0 and until.minute == 0:
                        until = until.replace(hour=7)         # 10:00 Nairobi on their day
                except (TypeError, ValueError):
                    until = None
            until = until or _default_until(now)
            nxt["hold"] = {"until": until.isoformat(timespec="seconds"), "said": said,
                           "since": now.isoformat(timespec="seconds"), "source": source}
            deal.next_action = nxt
            if not (nxt.get("kind") == "team_check"):
                deal.blocking = f"{_HOLD_LABEL[said]} — until {(until + timedelta(hours=3)).strftime('%d %b')}"
            changed["hold_until"] = nxt["hold"]["until"]
        elif said in ("exploring", "quoting", "ready") and (inbound_text or "").strip() and nxt.get("hold"):
            # They came back with a real message: the time they asked for is over.
            nxt.pop("hold", None)
            deal.next_action = nxt or None
            if deal.blocking and deal.blocking.split(" — ")[0] in _HOLD_LABEL.values():
                deal.blocking = None
            changed["hold_cleared"] = True
        if said == "paid_claim":
            deal.blocking = "Says they have paid — awaiting the hub's confirmation (never mark paid by hand)"
            changed["paid_claim"] = True
        if reading.get("open_item_check") and nxt.get("kind") != "team_check":
            # The model noticed an item under confirmation the tool did not record.
            changed["open_item_check"] = reading["open_item_check"]
        try:
            flag_modified(deal, "next_action")
        except Exception:
            pass
    await db.commit()
    return changed


def language_of(person) -> str | None:
    from app.services.intent import preferences
    return (preferences(person) or {}).get("language") if person is not None else None


def turn_note(deal, person, *, now: datetime | None = None) -> str | None:
    """What the next LIVE turn must know, in one note: an open hold (do not
    re-ask for a date, do not re-pitch), a pending team check, a payment
    claim. None when nothing stands."""
    bits = []
    hold = hold_open(deal, now=now) if deal is not None else None
    if hold:
        until, said = hold
        bits.append(f"they asked for time ({_HOLD_LABEL.get(said, said).lower()}) until "
                    f"{(until + timedelta(hours=3)).strftime('%A %d %b')} — do NOT ask again when "
                    "they will decide, do NOT re-pitch or re-list; answer what they ask and wait")
    if deal is not None:
        try:
            from app.services.deals import team_check_open
            item = team_check_open(deal, now=now)
        except Exception:
            item = None
        if item:
            bits.append(f"the team is still confirming '{item}' — never ask them to start, confirm "
                        "or pay for that item until the answer is in this chat")
        if (deal.blocking or "").startswith("Says they have paid"):
            bits.append("they say they have paid and the hub has not confirmed it — thank them, "
                        "say the confirmation reaches them here automatically, never announce it as received")
    if not bits:
        return None
    return "(CUSTOMER STATE: " + "; ".join(bits) + ".)"


async def after_turn(db, conv, deal, *, inbound_text: str, reply: str, transcript=None,
                     llm=None, reading: dict | None = None, now: datetime | None = None) -> dict | None:
    """The scribe's hook: floor first, then the model's note when the floor
    found nothing and a model is given. Returns what was applied."""
    now = now or datetime.now(timezone.utc)
    if reading is None:
        reading = floor(inbound_text, now=now)
    source = "floor"
    if reading is None and llm is not None and (inbound_text or "").strip():
        try:
            if transcript is None:
                transcript = await _transcript(db, conv)
            reading = await note(llm, transcript or [], inbound_text, reply)
            source = "note"
        except Exception as exc:
            _log.info("state note skipped for %s: %s", getattr(conv, "id", "?"), exc)
            reading = None
    if reading is None:
        reading = {"customer_said": "none"}
        source = "none"
    if not reading.get("language"):
        reading["language"] = guess_language(inbound_text)
    return await apply(db, conv, deal, reading, source=source, inbound_text=inbound_text, now=now)


async def _transcript(db, conv, limit: int = 12) -> list[tuple[str, str]]:
    """The last turns as (role, text): customer / team / neema. Notes stay out."""
    from sqlalchemy import select
    from app.models.message import Message, MsgDirection, MsgSender
    rows = (await db.execute(
        select(Message.direction, Message.sender, Message.text)
        .where(Message.conversation_id == conv.id, Message.text.isnot(None),
               Message.media_type.is_(None) | (Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(limit))).all()
    out = []
    for direction, sender, text in reversed(rows):
        role = ("customer" if direction == MsgDirection.inbound
                else ("team" if sender == MsgSender.human_agent else "neema"))
        out.append((role, text or ""))
    return out


def note_llm():
    """The light model for the note — None when the note is off or no key is
    configured (tests, a box without the key): the floor alone then stands."""
    if not getattr(settings, "customer_state_note", True) or not getattr(settings, "anthropic_api_key", ""):
        return None
    try:
        from app.agent.runtime import build_llm
        return build_llm(model=getattr(settings, "tier2_model_light", None) or None, purpose="state")
    except Exception:
        return None


# ── what the dispatcher asks ─────────────────────────────────────────────────

async def hold_for(db, action, *, now: datetime | None = None) -> tuple[datetime, str] | None:
    """The open hold on the deal this row belongs to (or the conversation's
    open deal when the row names none) — (until, said) or None."""
    from app.services.deals import open_deal_for
    deal = None
    try:
        if getattr(action, "deal_id", None) is not None:
            from app.models.deal import Deal
            deal = await db.get(Deal, action.deal_id)
        if deal is None and getattr(action, "conversation_id", None) is not None:
            deal = await open_deal_for(db, conversation_id=action.conversation_id)
    except Exception:
        return None
    return hold_open(deal, now=now) if deal is not None else None


async def language_for(db, conv) -> str | None:
    """The customer's stored language, or None when nothing is known."""
    pid = getattr(conv, "person_id", None)
    if pid is None:
        return None
    try:
        from app.models.person import Person
        return language_of(await db.get(Person, pid))
    except Exception:
        return None


def automated_ok(lang: str | None) -> bool:
    return lang is None or lang in AUTOMATED_LANGUAGES


async def live_note(db, key: str, channel: str, *, now: datetime | None = None) -> str | None:
    """`turn_note` for the live turn, from the conversation key."""
    from app.services.deals import _conversation_of, open_deal_for
    conv = await _conversation_of(db, key, channel)
    if conv is None:
        return None
    deal = await open_deal_for(db, conversation_id=conv.id)
    person = None
    if getattr(conv, "person_id", None) is not None:
        from app.models.person import Person
        person = await db.get(Person, conv.person_id)
    return turn_note(deal, person, now=now)
