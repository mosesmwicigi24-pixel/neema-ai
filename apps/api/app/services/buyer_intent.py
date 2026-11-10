"""WHAT THIS PERSON WANTS FROM THE CONVERSATION — and when to close kindly.

Owner's directive, 2026-11-10 ("Intent Discernment & Graceful Close"). Neema
sells to a buyer, helps a buyer who is short of money, bargains with a
negotiator — and to someone who is asking for goods, money or credit without
payment she gives ONE kind boundary, then closes, instead of trading appeals
message for message.

What existed before (and stays): the prompt's gift/hardship rule (the
Bangladesh thread, 2026-08-08), `pause_conversation` (two hours), the closer
gate and pacing (agent/cooling). Those were all the model's to remember, and
nothing outlived the two-hour pause: the next morning the same appeal began
the same exchange again. This module adds the two things that were missing:

  · a NEUTRAL, REVERSIBLE RECORD on the person (`persons.state["intent"]`):
    the reading, how sure, since when, why, and how many times the boundary
    has been given — evidence, never a verdict on character;
  · a LADDER the live turn follows before any token is bought:
      1st request  → the writer is told to give the one kind boundary;
      2nd request  → one brief acknowledgment, and the request is closed;
      3rd and on   → no automatic reply TO THAT REQUEST (silence).
    Anything else from the same person — a price, an order, a question about
    a product, a complaint, a payment — is answered as always, and a buying
    step reopens the record at once.

A reading comes from two places: a deterministic floor for the explicit ask
("give me one for free", "naomba msaada", "sponsor our church") and the light
model's note after each turn (services/customer_state), which reads the whole
conversation — behaviour, not keywords. The floor alone never closes anyone:
it takes two separate requests, each after an answer, with no purchase step
between them.

Never read from here: poverty, nationality, religion, ministry, hardship or
not being able to afford something. Asking for a lower price, for time, to pay
bit by bit or on credit is a BUYER talking and is not counted at all.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

_log = logging.getLogger("neema.intent")

READINGS = ("buyer", "constrained", "negotiator", "assistance", "social", "unclear")
CONFIDENCE = ("high", "probable", "possible")
# A boundary older than this is history: the next request is answered afresh.
WINDOW_DAYS = 30
HISTORY_MAX = 8

# ── the floor ────────────────────────────────────────────────────────────────
# A purchase step in the same message: they are buying, bargaining or asking
# how to pay. Deliberately WITHOUT product nouns ("a free cassock" names a
# product and is still a request for a gift).
_PURCHASE_RE = re.compile(
    r"(?<![a-z])(?:how much|price|prices|pricing|cost|costs|quote|quotation|invoice|discount|"
    r"last price|best price|reduce|negotiat\w*|instal?ments?|deposit|down ?payment|"
    r"pay|pays|paying|payment|payments|paid|"
    r"buy|buying|purchase|purchasing|order|orders|ordering|ordered|"
    r"paybill|m-?pesa|till number|bulk|wholesale|\d+ (?:pieces|pcs|sets)|"
    r"bei|ngapi|nitalipa|nitanunua|kununua|kulipa|nimelipa|punguz\w*|lipa|malipo|agiza|oda|"
    r"combien|prix|acheter|commander|payer|paiement|r[ée]duction|"
    r"quanto custa|pre[çc]o|comprar|pagar|pagamento|desconto)(?![a-z])", re.IGNORECASE)
# "I can't pay", "without paying", "nothing to pay with" are the opposite of a
# purchase step — read before the purchase words are looked for.
_NO_PAY_RE = re.compile(
    r"\b(?:can(?:'?t|not)|could ?n'?t|unable to|not able to|no (?:money|means|way|funds) to|nothing to|"
    r"do(?:n'?t| not) have (?:money |anything |the money |any money )?to|have no money to) (?:pay|buy|purchase|afford)\w*"
    r"|\bwithout (?:pay(?:ing|ment)?|buying|money|any cost|cost)\b|\bno (?:pay(?:ment)?|cost|charge)\b"
    r"|\bsina (?:pesa|hela) (?:ya|za) (?:kulipa|kununua)\b|\bsiwezi (?:kulipa|kununua)\b", re.IGNORECASE)

_ITEMS = (r"(?:cassocks?|albs?|stoles?|chasubles?|copes?|robes?|gowns?|shirts?|collars?|vestments?|bibles?|items?|"
          r"samples?|one|ones|clothes|clothing|garments?|uniforms?|communion (?:sets?|trays?|cups?)|chalices?|sets?|"
          r"things?|products?|goods)")

# The explicit ask: goods, money or a loan with no payment.
_ASK_RE = re.compile(
    r"(?:"
    # English
    r"\bfor free\b|\bfree of (?:charge|cost)\b|\bat no (?:cost|charge)\b|\bfree " + _ITEMS + r"\b|"
    r"\b(?:donate|sponsor|gift) (?:me|us|to (?:me|us)|our (?:church|ministry|choir|congregation|pastors?|orphans?|"
    r"children)|my (?:church|ministry|choir|congregation))\b|"
    r"\bbless (?:me|us|our (?:church|ministry)|my (?:church|ministry)) with\b|"
    r"\b(?:give|send|grant|get|receive|asking (?:you )?for|ask(?:ing)? for|request(?:ing)?(?: for)?|beg(?:ging)?(?: for)?)"
    r"(?: (?:me|us|you))?(?: (?:a|an|some|any|your|one))? (?:free )?(?:gift|donation|sponsorship|charity|offering|"
    r"help in kind|financial (?:help|support|assistance|aid))\b(?! (?:set|box|card|voucher|wrap|shop|idea|item)s?\b)|"
    r"\b(?:as|like) a (?:gift|donation|blessing|seed|token of love)\b|"
    r"\b(?:donat(?:e|ion|ions|ing)|sponsorship|alms|handouts?)\b|"
    r"\b(?:lend|loan) (?:me|us)\b|\bsend (?:me|us) (?:some )?(?:money|cash|funds|dollars|usd|kes|shillings)\b|"
    r"\b(?:help|support|assist) (?:me|us|our (?:church|ministry)|my (?:church|ministry)) financially\b|"
    r"\b(?:financial|material) (?:help|support|assistance|aid)\b|"
    # Swahili
    r"\b(?:naomba|tunaomba|nipe|tupe|nisaidie|tusaidie|nipatie|unipe|mnipe)\b[^.?!\n]{0,30}\b(?:bure|zawadi|sadaka|"
    r"mchango|pesa|hela)\b|\bbure\b|\bmsaada wa (?:pesa|kifedha|fedha)\b|\bmchango\b|"
    # French / Portuguese
    r"\bgratuit(?:e|es|s|ement)?\b|\boffrez[- ](?:moi|nous)\b|\b(?:un|des) dons?\b|\baide financi[èe]re\b|"
    r"\bde gra[çc]a\b|\bgr[áa]tis\b|\bdoa[çc][ãa]o\b|"
    # Urdu / Hindi (romanised)
    r"\b(?:muft|imdad|khairat|sadqa|zakat)\b"
    r")", re.IGNORECASE)

# Not an ask, whatever the words: delivery, sizes, a gift they are BUYING for
# someone, someone who wants to GIVE, a refusal of charity.
_ASK_NEG_RE = re.compile(
    r"\bfree (?:delivery|shipping|size|sizes|sizing|fitting|consultation|alterations?|returns?|pickup|pick up|"
    r"today|now|tomorrow|this|next|on|at|to (?:talk|call|come|meet)|time)\b|"
    r"\b(?:is|are|will) (?:it|they|delivery|shipping|the delivery|the shipping) (?:be )?free\b|"
    r"\b(?:livraison|entrega|frete|envio) (?:est[- ]elle |est |[ée] )?(?:gratuit\w*|gr[áa]tis|de gra[çc]a)\b|"
    r"\b(?:gift|present|zawadi|donation) (?:for|to|ya|kwa) (?:my|our|the|a|his|her|their)\b|"
    r"\b(?:looking for|want|need|wanting|needing|shopping for|choosing|chose|picked) (?:a |an |some )?(?:gift|present)\b|"
    r"\b(?:it|this|one|them|these|that)(?: is|'s| as| will be)? a (?:gift|present)\b|\bas a (?:gift|present) (?:for|to)\b|"
    r"\b(?:not|n't|never) (?:asking|begging|looking|want(?:ing)?)(?: you)?(?: for)?(?: it| anything| a| any)?(?: for)? ?(?:free|"
    r"charity|donations?|handouts?|a gift)\b|\bi am free\b|\bfeel free\b|\bfree (?:hand|will)\b|gluten[- ]free|"
    r"\b(?:we|i|he|she|they)(?: would like| want| wish| plan| are going| am going|'d like)? to (?:donate|sponsor|give|gift)\b|"
    r"\bmy sponsors?\b|\bour sponsors?\b|\b(?:the|a) sponsor (?:will|is|has|can)\b|"
    # a SAMPLE or swatch is how a buyer checks the cloth before ordering
    r"\b(?:free |a |any |some |fabric |cloth |colou?r )*(?:samples?|swatch(?:es)?|sample (?:piece|fabric|cloth))\b|"
    # complimentary things that come WITH a purchase, and promotions
    r"\bfree (?:gift|stole|collar|belt|cincture|bag|cover|item|one|shirt|cross)s? (?:with|when|if|on|for (?:every|each|orders?))\b|"
    r"\b(?:comes?|come|included?|includes?|including|bundled?) (?:with |as )?(?:a |an |any )?(?:free|complimentary)\b|"
    r"\b(?:complimentary|bonus|promo(?:tion|tional)?s?|offers?|deals?|giveaway|free gift with|buy (?:one|two|\d+)|"
    r"get (?:one|two|\d+) free|\d+ free|free for (?:orders?|bulk|every|each|\d+))\b|"
    # asking WHETHER something is free is a question about the terms, not a request
    r"\b(?:is|are|was|were|does|do|will|would) (?:the |this |that |it |they |there )?[\w ]{0,24}?\b(?:free|complimentary|included)\b[^.!\n]{0,12}\?|"
    # someone who gives, or buys in order to give
    r"\b(?:for|as|towards?) (?:a |our |the |my )?(?:donation to|donations to|charity (?:drive|event|project)|outreach|mission (?:trip|drive)|"
    r"fundrais\w+)\b|\b(?:donating|sponsoring|gifting) (?:to|for|a|an|the|some|\d+)\b|"
    r"\b(?:we|i)(?:'re|'m| are| am| will be| have been)? (?:donating|sponsoring|gifting)\b|"
    r"\b(?:do you|can (?:we|i)|how (?:do|can) (?:we|i)) (?:accept|take|receive) donations?\b|"
    r"\b(?:tax|charity|church|ngo|non-?profit) (?:exempt\w*|rate|pricing|invoice|registration)\b",
    re.IGNORECASE)

# A hardship appeal with no explicit ask in it. It counts ONLY while the
# record already reads assistance — on its own it says nothing: a buyer who
# is short of money writes the same words.
_APPEAL_RE = re.compile(
    r"\b(?:poor|poverty|no money|have no(?:thing| funds| income| salary| job| support)|can(?:'?t|not) afford|"
    r"orphans?|widows?|struggl\w+|suffering|persecut\w+|please (?:help|consider|remember|have mercy)|"
    r"have mercy|kindly (?:help|consider|assist)|remember (?:me|us)|god will (?:bless|reward|repay) you|"
    r"small (?:church|ministry|congregation)|village (?:church|pastor)|mission field|we are (?:in need|needy)|"
    r"i am (?:in need|needy|jobless|unemployed|a poor)|"
    r"sina (?:pesa|hela|uwezo|kitu|kazi)|hali (?:ni )?ngumu|maskini|yatima|tafadhali (?:nisaidie|tusaidie)|"
    r"pas d'argent|pauvre|sans (?:argent|moyens)|sem dinheiro|pobre|gareeb|ghareeb|majboor)\b", re.IGNORECASE)


def has_purchase_step(text: str | None) -> bool:
    """A price, an order, a discount, a way to pay — they are buying or
    bargaining, whatever else the message says."""
    t = _NO_PAY_RE.sub(" ", " ".join((text or "").split()))
    return bool(_PURCHASE_RE.search(t))


def is_ask(text: str | None) -> bool:
    """An explicit request for goods, money or a loan with no payment, and no
    purchase step beside it. "Can I pay on Sunday?" is not one; nor is "a
    gift for my bishop"."""
    t = " ".join((text or "").split())
    if not t or has_purchase_step(t):
        return False
    return bool(_ASK_RE.search(_ASK_NEG_RE.sub(" ", t)))


def is_appeal(text: str | None) -> bool:
    """A hardship appeal without an explicit ask and without a purchase step."""
    t = " ".join((text or "").split())
    return bool(t) and not has_purchase_step(t) and bool(_APPEAL_RE.search(t))


# ── the record ───────────────────────────────────────────────────────────────

def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(v) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def record(state: dict | None) -> dict:
    """The stored intent record (a copy), or {}."""
    r = (state or {}).get("intent")
    return dict(r) if isinstance(r, dict) else {}


def boundary(rec: dict | None, *, now: datetime | None = None) -> dict:
    """{count, closed, last_at} for the request loop still in its window —
    zeros once the last boundary is older than WINDOW_DAYS."""
    b = (rec or {}).get("boundary")
    if not isinstance(b, dict):
        return {"count": 0, "closed": False, "last_at": None}
    last = _parse(b.get("last_at"))
    if last is None or _now(now) - last > timedelta(days=WINDOW_DAYS):
        return {"count": 0, "closed": False, "last_at": None}
    return {"count": int(b.get("count") or 0), "closed": bool(b.get("closed")), "last_at": b.get("last_at")}


def observe(state: dict | None, reading: str, *, confidence: str = "probable", by: str = "note",
            reason: str | None = None, now: datetime | None = None) -> tuple[dict, bool]:
    """A new reading applied to a person's state. Pure: (new_state, changed).
    The boundary count is left alone here — only `step` and `reopen` move it.
    A weaker source never overwrites a firmer assistance reading with
    'unclear' or 'social' (silence is not a change of mind); any buying
    reading always replaces it."""
    if reading not in READINGS:
        return dict(state or {}), False
    st = dict(state or {})
    rec = record(st)
    prev = rec.get("reading")
    if prev == "assistance" and reading in ("unclear", "social"):
        return st, False
    if prev == reading and rec.get("confidence") == confidence:
        return st, False
    at = _now(now).isoformat(timespec="seconds")
    hist = list(rec.get("history") or [])
    if prev and prev != reading:
        hist.append({"reading": prev, "at": rec.get("at"), "reason": rec.get("reason")})
    rec.update({"reading": reading, "confidence": confidence if confidence in CONFIDENCE else "possible",
                "by": by, "at": at, "reason": (reason or "")[:160] or None, "history": hist[-HISTORY_MAX:]})
    st["intent"] = rec
    return st, True


def step(state: dict | None, *, reason: str, now: datetime | None = None) -> tuple[dict, int]:
    """One more request for goods without payment, answered or closed.
    Returns (new_state, the count AFTER this one). The second closes the
    request; later ones keep it closed."""
    st, _ = observe(state, "assistance", confidence="high", by="behaviour", reason=reason, now=now)
    rec = record(st)
    b = boundary(rec, now=now)
    at = _now(now).isoformat(timespec="seconds")
    n = b["count"] + 1
    prior = rec.get("boundary") if isinstance(rec.get("boundary"), dict) else {}
    rec["boundary"] = {"count": n, "closed": n >= 2, "last_at": at,
                       "first_at": (prior.get("first_at") if b["count"] else None) or at}
    st["intent"] = rec
    return st, n


def reopen(state: dict | None, *, reading: str = "buyer", reason: str, now: datetime | None = None) -> tuple[dict, bool]:
    """They came back with a purchase step: the request loop is over and the
    record reads as a buyer. Nothing is erased — the history keeps what was."""
    rec0 = record(state)
    if rec0.get("reading") != "assistance" and not boundary(rec0, now=now)["count"]:
        return dict(state or {}), False
    st, _ = observe(state, reading, confidence="high", by="behaviour", reason=reason, now=now)
    rec = record(st)
    b = rec.get("boundary") if isinstance(rec.get("boundary"), dict) else None
    if b:
        rec["boundary"] = {"count": 0, "closed": False, "last_at": None,
                           "first_at": None, "given_before": True}
    st["intent"] = rec
    return st, True


def suppresses_promotion(state: dict | None, *, now: datetime | None = None) -> bool:
    """True while the record reads assistance and a boundary was ever given:
    unprompted SALES messages wait until the person themselves takes a
    purchase step (`reopen`). Time alone never lifts it — the 30-day window
    ages the reply ladder, not this (owner, 2026-11-10: "the expiry must not
    independently reactivate unsolicited promotional messaging"). Order,
    payment and delivery messages are never held by this."""
    rec = record(state)
    b = rec.get("boundary") if isinstance(rec.get("boundary"), dict) else {}
    return rec.get("reading") == "assistance" and bool(b.get("first_at") or b.get("count"))


# ── what is never closed on ──────────────────────────────────────────────────

def protected(text: str | None) -> str | None:
    """Why this message is never part of the request ladder, whatever else it
    says — or None. A complaint, a payment claim, a request for a person or an
    opt-out is answered by its own path, even with "and a free stole for the
    delay" beside it (a customer asking for redress is not asking for a gift)."""
    t = " ".join((text or "").split())
    if not t:
        return None
    try:
        from app.services.intent import is_opt_out, wants_a_person
        if is_opt_out(t):
            return "opt-out"
        if wants_a_person(t):
            return "asks for a person"
    except Exception:
        pass
    try:
        from app.services import customer_state as _cs
        if _cs._COMPLAINT_STRONG_RE.search(t) or _cs._COMPLAINT_RE.search(t):
            return "complaint"
        if _cs._PAID_RE.search(t) and not _cs._PAID_NEG_RE.search(t):
            return "payment claim"
    except Exception:
        pass
    return None


_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*")


def new_subject(text: str | None) -> bool:
    """True when the message also asks something that is NOT the request — a
    real question beside the appeal ("…and where is your shop?"). Such a
    message is never met with silence."""
    for m in _SENTENCE_RE.finditer(" ".join((text or "").split())):
        part = m.group(0).strip()
        if "?" not in part or len(part.split()) < 3:
            continue
        if _ASK_RE.search(_ASK_NEG_RE.sub(" ", part)) or _APPEAL_RE.search(part):
            continue
        return True
    return False


# ── what the writer is told ──────────────────────────────────────────────────

FIRST_NOTE = (
    "(INTENT: this message reads as a request for goods, money or credit without payment, with nothing in "
    "it that moves toward an order. Read it in the WHOLE conversation first: if it is in fact a commercial "
    "question — a sample to check the cloth, something complimentary with an order, a promotion, delivery, "
    "a donation THEY are making or buying for — answer that question normally and ignore the rest of this "
    "note. Otherwise answer with ONE kind boundary, two or three short sentences: acknowledge what "
    "they shared with real warmth; say plainly that Bethany House is a business, so we cannot give items "
    "free, donate, lend, or send anything before it is paid for; say we will be glad to serve them whenever "
    "they are ready to order. Stop there. No question. No list of cheaper items. No promise that anyone will "
    "consider it. No programme, discount, instalment plan or approval that is not already ours to offer. "
    "Never question or judge their circumstances. Do not call pause_conversation.)")

SECOND_NOTE = (
    "(INTENT: they have repeated the same request after your boundary. If this message instead asks "
    "something new — an item, a price, an order, a problem — answer that and ignore this note. Otherwise "
    "ONE brief line only: acknowledge it "
    "kindly and wish them well. Do not explain again, do not decline at length, no question, no offer, no "
    "second blessing. This closes that request; if they later ask about an item or an order, serve them "
    "as any customer, with no mention of this.)")

STANDING_NOTE = (
    "(INTENT: earlier they asked for goods without payment and you gave the boundary. Do not repeat it and "
    "do not refer to it. They are now asking something else — answer that, as you would any customer.)")


# ── the live turn ────────────────────────────────────────────────────────────

async def _active_business(db, conv) -> bool:
    """An order, a payment claim, a complaint or a promised check on this
    thread: never closed, whatever else is said (directive §3, exception)."""
    try:
        async with db.begin_nested():
            from sqlalchemy import select
            from app.models.order_event import OrderEvent
            key = getattr(conv, "wa_id", None) or getattr(conv, "external_id", None)
            since = datetime.now(timezone.utc) - timedelta(days=60)
            row = (await db.execute(select(OrderEvent.id).where(
                OrderEvent.wa_id == key, OrderEvent.created_at > since).limit(1))).scalar_one_or_none()
            if row:
                return True
    except Exception:
        pass
    try:
        async with db.begin_nested():
            from app.agent import cart as cartmod
            key = getattr(conv, "wa_id", None) or getattr(conv, "external_id", None)
            cart = await cartmod.get_cart(db, key, getattr(conv, "channel", None) or "whatsapp")
            if cart and (cart.get("items") or []):
                return True
    except Exception:
        pass
    try:
        async with db.begin_nested():
            from app.services.deals import open_deal_for, team_check_open
            deal = await open_deal_for(db, conversation_id=conv.id)
            if deal is not None:
                if team_check_open(deal):
                    return True
                if (deal.blocking or "").startswith("Says they have paid"):
                    return True
    except Exception:
        pass
    return False


async def decide(db, redis, *, channel: str, key: str, text: str, has_media: bool = False,
                 campaign: bool = False, now: datetime | None = None) -> dict | None:
    """What the live turn does about intent, before any token is bought:

    None — nothing to add; answer as always.
    {"action": "note", "note", "boundary": 1|2} — the writer gives the
        boundary (1) or the one brief acknowledgment that closes it (2).
    {"action": "note", "note", "boundary": 0} — a closed request and a new
        subject: answer the new subject, say nothing of the old one.
    {"action": "silence", "why": "request closed"} — the same request again
        after it was closed: no automatic reply to it.

    Fails open: any error → None, and the turn runs as it always did."""
    t = " ".join((text or "").split())
    if not t or campaign:
        return None           # under a giveaway post, asking for the gift is the point
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.services.deals import _conversation_of
        conv = await _conversation_of(db, key, channel)
        if conv is None:
            return None
        person = await _person_of(db, conv, key)
        if person is None:
            return None
        rec = record(person.state)
        b = boundary(rec, now=now)
        standing = rec.get("reading") == "assistance"
        purchase = has_purchase_step(t)
        ask = is_ask(t)
        appeal = (not ask) and standing and is_appeal(t)

        async def _save(new_state):
            try:
                from app.services.state_lock import lock_for_write
                p = await lock_for_write(db, person)
            except Exception:
                p = person
            p.state = new_state
            try:
                flag_modified(p, "state")
            except Exception:
                pass
            await db.commit()

        if purchase:
            # A price, an order, a way to pay: a buyer, whatever was said
            # before. (A photo alone reopens nothing — photos are also sent
            # to persuade; the writer sees it and answers what it shows.)
            if standing or b["count"]:
                st, changed = reopen(person.state, reason="came back with a purchase step", now=now)
                if changed:
                    await _save(st)
                    await _timeline(db, conv, "Now asking to buy", "the earlier request is closed")
            return None
        if not (ask or appeal):
            if standing and b["count"] >= 1:
                return {"action": "note", "note": STANDING_NOTE, "boundary": 0}
            return None
        # A complaint, a payment claim, a request for a person or an opt-out is
        # answered by its own path at every step; so is anything on a thread
        # with an order, a cart or a promised check open.
        if protected(t) or await _active_business(db, conv):
            return None
        if b["count"] >= 2 or b["closed"]:
            # Silence is for the SAME request, already answered twice, and
            # nothing else in the message. A new question beside it is
            # answered (without repeating the boundary).
            if has_media or new_subject(t):
                return {"action": "note", "note": STANDING_NOTE, "boundary": 0}
            st, n = step(person.state, reason="the same request again after it was closed", now=now)
            await _save(st)
            return {"action": "silence", "why": "request closed", "boundary": n}
        why = "asked for goods, money or credit without payment" if ask else "repeated a hardship appeal"
        st, n = step(person.state, reason=why, now=now)
        await _save(st)
        await _timeline(db, conv, "Asked for goods without payment",
                        "the boundary was given" if n == 1 else "acknowledged once more; the request is closed")
        return {"action": "note", "note": FIRST_NOTE if n == 1 else SECOND_NOTE, "boundary": n}
    except Exception as exc:
        _log.warning("intent failed open for %s/%s: %s", channel, key, exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _person_of(db, conv, key: str | None = None):
    """The person behind a conversation: its own link, else the customer's
    user row (a thread opened moments ago is not linked yet)."""
    from app.models.person import Person
    pid = getattr(conv, "person_id", None)
    if pid is None:
        try:
            from sqlalchemy import select
            from app.models.user import User
            k = key or getattr(conv, "wa_id", None) or getattr(conv, "external_id", None)
            if k:
                pid = (await db.execute(select(User.person_id).where(User.wa_id == k).limit(1))).scalar_one_or_none()
        except Exception:
            pid = None
    return await db.get(Person, pid) if pid is not None else None


async def _timeline(db, conv, summary: str, detail: str) -> None:
    """One neutral customer-level line for the team (services/timeline)."""
    try:
        from app.services import timeline as _tl
        await _tl.note(db, channel=getattr(conv, "channel", None) or "whatsapp",
                       contact=(getattr(conv, "wa_id", None) or getattr(conv, "external_id", None) or ""),
                       kind="customer_state", summary=summary, detail=detail, args={"intent": True})
    except Exception:
        pass


async def apply_note(db, conv, reading: str | None, reason: str | None = None,
                     *, now: datetime | None = None) -> bool:
    """The light model's reading of the whole conversation, stored after the
    turn (customer_state.after_turn). It never moves the boundary count and
    never closes anything by itself."""
    if reading not in READINGS:
        return False
    try:
        from sqlalchemy.orm.attributes import flag_modified
        person = await _person_of(db, conv)
        if person is None:
            return False
        if reading in ("buyer", "constrained", "negotiator"):
            st, changed = reopen(person.state, reading=reading, reason=reason or "the conversation moved to buying", now=now)
            if not changed:
                st, changed = observe(person.state, reading, by="note", reason=reason, now=now)
        else:
            st, changed = observe(person.state, reading, by="note", reason=reason, now=now)
        if not changed:
            return False
        person.state = st
        try:
            flag_modified(person, "state")
        except Exception:
            pass
        await db.commit()
        return True
    except Exception as exc:
        _log.info("intent note skipped: %s", exc)
        return False
