"""WHERE A CUSTOMER IS — and so which money they are quoted.

Owner (2026-09-05): quote KES only when the EVIDENCE says Kenya —
  · the website visitor's IP (web_chat geolocates it onto their user row);
  · a WhatsApp message from a +254 number (the number itself);
  · a Facebook / Messenger / Instagram / TikTok id MERGED with a +254
    WhatsApp number — a linked WhatsApp identity, the WhatsApp user row, or
    a phone they gave us WITH its country code;
  · their own words — a captured Kenyan location, or a panel edit.
Anyone we cannot place is quoted USD. One currency, never two; no country
question, ever. The prices themselves are the hub's own rows in that money.

NOT evidence: a Facebook profile locale (a hint for the CRM flag only), a
name, the page they wrote on, or a phone whose country we ASSUMED because it
came without a code ("0712…" parsed as Kenyan by default).

This module is the ONLY place the decision lives, so the chat turn, the
public comment engine and the shared catalogue link always agree.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.countries import resolve_country, iso_from_text, market_currency
from app.core.phone import is_plausible_phone
from app.models.user import User

_log = logging.getLogger("neema.market")

WHATSAPP = "whatsapp"


def _from_phone(value) -> tuple[str | None, str]:
    r = resolve_country(str(value or "")) or {}
    return r.get("country_iso"), (r.get("country") or "")


async def users_for_person(db, person_id) -> list:
    """Every User row on this person, phone-anchored rows first.

    A merge leaves the Messenger shim row beside the WhatsApp row (both point
    at the surviving person). Reading "the" user with scalar_one_or_none then
    raised MultipleResultsFound — and the whole market lookup fell to USD for
    exactly the customer who had just proved they were Kenyan."""
    rows = list((await db.execute(
        select(User).where(User.person_id == person_id))).scalars().all() or [])
    rows.sort(key=lambda u: 0 if is_plausible_phone(getattr(u, "wa_id", None)) else 1)
    return rows


async def evidence_for_person(db, ident, person) -> dict:
    """The evidence chain for a social identity (Meta / TikTok), in order:
      1. their own words — a captured location on the person or a user row;
      2. a country already on a user row (IP geolocation, a real prefix, a
         panel edit);
      3. a phone on a user row, or a WhatsApp identity merged with this
         person (its number IS the evidence);
      4. a phone identifier they gave us — with its country code, never one
         whose region we assumed.
    Returns {country_iso, country, evidence, users, siblings}; country_iso is
    None when nothing places them. The query order is fixed — users, then
    siblings, then identifiers — and the tests script it."""
    from app.models.person import Identity, Identifier
    users = await users_for_person(db, ident.person_id)
    sibs = list((await db.execute(select(Identity).where(
        Identity.person_id == ident.person_id))).scalars().all() or [])
    iso, country, how = None, "", ""
    # 1. their own words
    words = [((person.state or {}).get("location") if person is not None else None)]
    words += [getattr(u, "location", None) for u in users]
    for w in words:
        w_iso = iso_from_text(w) if w else None
        if w_iso:
            iso, country, how = w_iso, w, "their words"
            break
    # 2. a country already on a user row
    if not iso:
        for u in users:
            ci = (getattr(u, "country_iso", None) or "").strip().upper()
            if ci:
                iso, country, how = ci, (getattr(u, "country", None) or ci), "profile country"
                break
    # 3. a phone on a user row, or a merged WhatsApp identity
    if not iso:
        for u in users:
            if getattr(u, "phone", None):
                iso, country = _from_phone(u.phone)
                if iso:
                    how = "profile phone"
                    break
    if not iso:
        for s in sibs:
            if getattr(s, "channel", "") == WHATSAPP:
                iso, country = _from_phone(getattr(s, "external_id", ""))
                if iso:
                    how = "merged WhatsApp number"
                    break
    # 4. a phone identifier that carried its own country code
    if not iso:
        phones = list((await db.execute(select(Identifier).where(
            Identifier.person_id == ident.person_id,
            Identifier.type == "phone"))).scalars().all() or [])
        for ph in phones:
            if (getattr(ph, "raw", None) or {}).get("region_assumed"):
                continue                       # we guessed the country: not evidence
            iso, country = _from_phone(getattr(ph, "value", ""))
            if iso:
                how = "phone identifier"
                break
    return {"country_iso": iso, "country": (country or iso or ""), "evidence": how,
            "users": users, "siblings": sibs}


async def customer_market(db, channel: str, key: str) -> tuple[str, dict]:
    """(currency, loc) for ANY customer key — a WhatsApp number (its prefix),
    a web session (the IP-geolocated user row), or a social id (the evidence
    chain above). ("USD", {}) when nothing places them."""
    from app.models.person import Identity, Person
    iso, country = None, ""
    key = str(key or "")
    if channel in (WHATSAPP, "sms") or key.startswith("web_"):
        if is_plausible_phone(key):
            iso, country = _from_phone(key)
        else:
            u = (await db.execute(select(User).where(User.wa_id == key))).scalars().first()
            if u is not None and getattr(u, "country_iso", None):
                iso, country = u.country_iso, (getattr(u, "country", None) or u.country_iso)
    else:
        ident = (await db.execute(select(Identity).where(
            Identity.channel == channel,
            Identity.external_id == key))).scalar_one_or_none()
        if ident is not None:
            person = await db.get(Person, ident.person_id)
            ev = await evidence_for_person(db, ident, person)
            iso, country = ev.get("country_iso"), ev.get("country") or ""
    if not iso:
        return "USD", {}
    return market_currency(iso), {"country_iso": iso, "country": country or iso}
