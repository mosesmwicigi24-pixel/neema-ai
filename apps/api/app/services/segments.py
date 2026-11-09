"""WHO THE CUSTOMERS ARE, IN AGGREGATE — by market, language and channel.

Owner's directive (2026-11-09, Phase 4: "geographic / market aggregation");
audit (`CUSTOMER_INTELLIGENCE_AUDIT.md` §7): no endpoint or page aggregated
customers by country or language. This module does, from the records the
earlier slices made honest:

  · market  — the geography decision per customer (services/geography:
              confirmed residence → probable country → telephone country →
              the number); CONFIRMED means a person said or confirmed it
              (stated / operator), INFERRED means the number, the connection
              or a locale decided; UNKNOWN means nothing placed them;
  · language — `contact_preferences.language`, as the scribe reads it;
  · channel  — the channels the customer has written on (one customer counts
              once per channel).

Counts only: no handle, name or message text leaves this module.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from app.core.countries import name_for_iso
from app.services import geography as _geo

CONFIRMED_SOURCES = {"stated", "operator"}
LANGUAGE_NAMES = {"en": "English", "sw": "Swahili", "fr": "French", "pt": "Portuguese",
                  "hi": "Hindi", "ar": "Arabic", "am": "Amharic", "zh": "Chinese",
                  "es": "Spanish", "de": "German", "id": "Indonesian"}


def place(user, person_state: dict | None) -> dict:
    """{iso, name, basis} for one customer: basis is 'confirmed', 'inferred'
    or 'unknown'."""
    handle = getattr(user, "wa_id", None) or getattr(user, "phone", None)
    tel = _geo.telephone_country(handle) if handle else None
    d = _geo.decide(person_state, fallback_iso=(tel["iso"] if tel else None))
    iso = d.get("country_iso") or (getattr(user, "country_iso", None) or "").upper() or None
    if not iso:
        return {"iso": None, "name": None, "basis": "unknown"}
    by = d.get("by") if d.get("country_iso") else "profile"
    basis = "confirmed" if by in CONFIRMED_SOURCES else "inferred"
    return {"iso": iso, "name": name_for_iso(iso) or iso, "basis": basis}


def summarise(users, persons: dict, channels_by_user: dict | None = None,
              *, now: datetime | None = None) -> dict:
    """The aggregates for a list of live users. `persons` maps person id →
    state dict; `channels_by_user` maps user id → an iterable of channel
    names. Pure."""
    now = now or datetime.now(timezone.utc)
    by_country: dict = defaultdict(lambda: {"customers": 0, "confirmed": 0, "inferred": 0})
    by_language: dict = defaultdict(int)
    by_channel: dict = defaultdict(int)
    unknown_market = 0
    total = 0
    for u in users:
        total += 1
        ps = persons.get(getattr(u, "person_id", None)) or {}
        p = place(u, ps)
        if p["iso"]:
            row = by_country[p["iso"]]
            row["customers"] += 1
            row[p["basis"]] += 1
            row["name"] = p["name"]
        else:
            unknown_market += 1
        lang = ((ps.get("contact_preferences") or {}).get("language")) if isinstance(ps, dict) else None
        by_language[(lang or "unknown").lower()] += 1
        for ch in set(channels_by_user.get(getattr(u, "id", None), ()) if channels_by_user else ()):
            by_channel[ch or "whatsapp"] += 1
    countries = sorted(({"iso": iso, **row} for iso, row in by_country.items()),
                       key=lambda r: (-r["customers"], r["iso"]))
    languages = sorted(({"code": code, "name": LANGUAGE_NAMES.get(code, code.upper() if code != "unknown" else "Unknown"),
                         "customers": n} for code, n in by_language.items()),
                       key=lambda r: (-r["customers"], r["code"]))
    channels = sorted(({"channel": ch, "customers": n} for ch, n in by_channel.items()),
                      key=lambda r: (-r["customers"], r["channel"]))
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "customers": total,
        "countries": countries,
        "unknown_market": unknown_market,
        "confirmed_market": sum(r["confirmed"] for r in countries),
        "inferred_market": sum(r["inferred"] for r in countries),
        "languages": languages,
        "channels": channels,
        "basis": {
            "market": "the geography decision per customer (confirmed residence → stated country → "
                      "telephone country → the number); confirmed = said or confirmed by a person, "
                      "inferred = the number, the connection or a profile locale",
            "language": "the language the customer writes in, as the scribe reads it",
            "channel": "a customer counts once per channel they have written on",
        },
    }


async def report(db) -> dict:
    """Read the live customers (merged-away rows excluded), their persons and
    their channels, in three bulk queries, and summarise."""
    from sqlalchemy import or_, select
    from app.models.conversation import Conversation
    from app.models.person import Person
    from app.models.user import User
    users = list((await db.execute(select(User))).scalars().all())
    tomb = set((await db.execute(select(Person.id).where(Person.merged_into_id.isnot(None)))).scalars().all())
    live = [u for u in users if not (u.state or {}).get("merged_into") and u.person_id not in tomb]
    pids = {u.person_id for u in live if u.person_id is not None}
    persons = {}
    if pids:
        for p in (await db.execute(select(Person).where(Person.id.in_(pids)))).scalars().all():
            persons[p.id] = p.state or {}
    wa_ids = {u.wa_id for u in live if u.wa_id}
    by_wa, by_person = defaultdict(set), defaultdict(set)
    if wa_ids or pids:
        import uuid as _uuid
        conds = []
        if wa_ids:
            conds.append(Conversation.wa_id.in_(wa_ids))
        if pids:
            conds.append(Conversation.person_id.in_(pids))
        else:
            conds.append(Conversation.person_id == _uuid.uuid4())
        for c in (await db.execute(select(Conversation.wa_id, Conversation.person_id, Conversation.channel)
                                   .where(or_(*conds)))).all():
            wa, pid, ch = c
            if wa:
                by_wa[wa].add(ch or "whatsapp")
            if pid is not None:
                by_person[pid].add(ch or "whatsapp")
    channels_by_user = {u.id: (by_wa.get(u.wa_id, set()) | by_person.get(u.person_id, set())) for u in live}
    return summarise(live, persons, channels_by_user)
