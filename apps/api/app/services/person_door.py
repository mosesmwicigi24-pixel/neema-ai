"""THE PERSON DOOR (owner's decision, 2026-11-07).

"Explicit human request: mandatory direct handover. Detect and route before
normal AI generation. Never make customers argue with Neema to reach a
person. If staff are unavailable, acknowledge that transparently and queue
accountable follow-up."

The door sits beside the opt-out door in the inbound path (runtime
`schedule_reply` / the Meta twin): when `intent.wants_a_person` reads the
message, no model turn runs. The thread goes to human mode, the team is
flagged and rung (the same bell the unclaimed sweeper re-rings every
`unclaimed_alert_minutes` until someone is assigned — that sweeper is the
accountable follow-up), and the customer gets ONE honest line in their
language: a colleague is taking over, or — out of staffed hours or with no
colleague marked available — that the team is away until the next staffed
start and this chat is already with them. Idempotent per message; a second
request re-rings and re-acknowledges rather than being ignored (a person who
asks twice is a person waiting).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

_log = logging.getLogger("neema.person_door")

_ACK = {
    "en": {
        "now": "Of course — a colleague will take over this chat shortly.",
        "later": "Of course. Our team is away right now and back at {when}; this chat is "
                 "already with them and a colleague will pick it up first thing.",
    },
    "sw": {
        "now": "Sawa — mwenzangu wa timu atachukua mazungumzo haya hivi karibuni.",
        "later": "Sawa. Timu yetu haipo kwa sasa na itarudi saa {when}; mazungumzo haya tayari "
                 "yako kwao na mwenzangu atayachukua mara ya kwanza.",
    },
    "fr": {
        "now": "Bien sûr — un collègue va prendre le relais sous peu.",
        "later": "Bien sûr. Notre équipe est absente pour le moment et revient à {when} ; cette "
                 "conversation leur est déjà transmise et un collègue la reprendra en premier.",
    },
    "pt": {
        "now": "Claro — um colega vai assumir esta conversa em breve.",
        "later": "Claro. A nossa equipa está ausente agora e volta às {when}; esta conversa já "
                 "está com eles e um colega vai retomá-la logo que entrar.",
    },
}


def language_for(text: str | None) -> str:
    from app.agent.voice import looks_swahili
    t = (text or "").lower()
    if looks_swahili(text or "") or re.search(r"\b(nataka|naomba|nahitaji|roboti|mtu)\b", t):
        return "sw"
    if re.search(r"\b(parler|quelqu|robot\b.*\b(est|c'est)|je veux|humain|conseiller)\b", t):
        return "fr"
    if re.search(r"\b(falar com|quero|alguém|atendente|humano)\b", t):
        return "pt"
    return "en"


def acknowledgement(text: str | None, *, staffed: bool, when: str) -> str:
    lang = language_for(text)
    return _ACK[lang]["now"] if staffed else _ACK[lang]["later"].format(when=when)


async def _someone_available(db) -> bool:
    try:
        from sqlalchemy import func, select
        from app.models.agent import Agent
        n = (await db.execute(select(func.count()).select_from(Agent).where(Agent.is_available.is_(True)))).scalar()
        return bool(n)
    except Exception:
        return True                      # unknown is not "nobody"


async def route(db, redis, conv, text: str, *, channel: str, key: str,
                now: datetime | None = None) -> str:
    """Set human mode, flag, ring; return the acknowledgement to send.
    Never raises on the bell or the flag — the hand-over itself is the point."""
    from app.models.conversation import InterceptMode
    from app.services import commitments as _cm
    now = now or datetime.now(timezone.utc)
    staffed = _cm.staffed_now(now) and await _someone_available(db)
    when = (_cm.next_staffed_start(now) + _cm._NAIROBI).strftime("%H:%M")
    already = getattr(conv, "intercept_mode", None) == InterceptMode.human
    if getattr(conv, "id", None) is not None:
        conv.intercept_mode = InterceptMode.human
        try:
            from app.models.intercept import Intercept, InterceptAction
            words = " ".join((text or "").split())[:140]
            db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag, note=(
                f"🙋 THE CUSTOMER ASKED FOR A PERSON — “{words}”. Neema has stepped back; the next "
                f"reply here is yours. " + ("They asked again: they are waiting. " if already else "")
                + ("" if staffed else f"Out of staffed hours: they were told the team is back at {when}."))[:2000]))
        except Exception:
            _log.info("person-door flag not recorded", exc_info=True)
        await db.commit()
    ext = getattr(conv, "wa_id", None) or getattr(conv, "external_id", None) or key
    if redis is not None:
        try:
            await redis.publish("ws:channel:agents:all", json.dumps({
                "event": "notification", "type": "human_transfer",
                "title": ("🙋 Asked for a person again — still waiting" if already
                          else "🙋 A customer asked for a person"),
                "body": (f"{channel} {ext} — “{' '.join((text or '').split())[:100]}”. Pick it up"
                         + ("" if staffed else f"; they were told the team is back at {when}")),
                "conversationId": str(getattr(conv, "id", "")), "conv_id": str(getattr(conv, "id", "")),
                "wa_id": str(ext),
            }))
        except Exception as exc:
            _log.info("person-door bell not sent for %s: %s", ext, exc)
    _log.info("person door: %s/…%s → human (%s)", channel, str(key)[-4:], "staffed" if staffed else f"back {when}")
    return acknowledgement(text, staffed=staffed, when=when)
