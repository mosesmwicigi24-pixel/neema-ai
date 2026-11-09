"""WHERE A CUSTOMER IS, with the evidence kept.

Owner's directive (2026-11-09, "Unified Customer Intelligence, Geographic
Discovery & Commercial Profiling"): a customer's geography is several facts,
not one field — the country their telephone number belongs to, the country
they are probably in now, the residence someone confirmed, where their parcels
go, their city, their language — each with its source, its confidence and
when it was last seen, and a short history when two readings disagree. The
Bahrain / Kenya screenshot is the case: a +973 number (telephone country
Bahrain) whose owner said they are in Kenya. Neither is wrong; they are
different attributes, and until this module the market read only the number.

The record lives on `persons.state["geo"]`:

    geo = {
      "telephone_country":   {"value": "BH", "by": "phone", "confidence": "confirmed",
                              "at": "...", "detail": "+973"},
      "probable_country":    {"value": "KE", "by": "stated", "confidence": "high",
                              "at": "...", "detail": "Nairobi"},
      "confirmed_residence": {"value": "KE", "by": "operator", "confidence": "confirmed", ...},
      "shipping_country":    {"value": "KE", "by": "order", "confidence": "probable", ...},
      "city":                {"value": "Nairobi", "by": "stated", ...},
      "history": [{"attr": ..., "previous": ..., "value": ..., "by": ..., "at": ...}, ...],
    }

Confidence is the directive's five-level scale, never a made-up number:
confirmed > high > probable > possible > unknown. A reading replaces an
earlier one of the same attribute only when its confidence is at least as
high (a stated town outranks an IP guess; an IP guess never overwrites what
the customer said); the earlier reading is kept in the history.

THE ONE DECISION — `decide()` — is what the market, the profile and the
reports read: confirmed residence, then a probable country of at least
"probable" confidence, then the telephone country. A "possible" reading (a
Facebook locale) never decides anything; it only fills an empty profile hint,
exactly as before. The telephone country is read with the phone-numbers
library, so a shared dialling code (+1, +7, +44) names the right country; the
prefix table is the fallback for a number the library cannot place.

Compatibility: `users.country / country_iso / flag_url` keep working and are
written from the same decision (`mirror_user`), so every existing reader —
the inbox flag, the country tag, the leads list — sees the country Neema
treats the customer as being in, while `geo.telephone_country` keeps what the
number says. Nothing is removed; no migration (JSONB on the person).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.countries import (flag_url_for, iso_from_text, name_for_iso,
                                resolve_country)
from app.core.phone import is_plausible_phone, region_of

_log = logging.getLogger("neema.geography")

# The directive's scale, strongest first. Rank is only for comparison.
LEVELS = ("confirmed", "high", "probable", "possible", "unknown")
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
LEVEL_LABELS = {"confirmed": "Confirmed", "high": "High confidence", "probable": "Probable",
                "possible": "Possible", "unknown": "Unknown"}

# The attributes, and which of them may decide the market.
ATTRS = ("telephone_country", "probable_country", "confirmed_residence",
         "shipping_country", "city")
_DECIDING = ("confirmed_residence", "probable_country", "telephone_country")
_MIN_DECIDING = {"confirmed_residence": "confirmed", "probable_country": "probable",
                 "telephone_country": "probable"}

# Sources, in plain words for the profile.
SOURCE_LABELS = {
    "phone": "the telephone number",
    "stated": "what the customer said",
    "operator": "an operator",
    "ip": "the website visitor's connection",
    "locale": "the Facebook profile locale",
    "order": "an order's delivery notes",
    "merge": "a merged profile",
}

HISTORY_CAP = 12


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def rank(confidence: str | None) -> int:
    """Lower is stronger; an unknown word reads as 'unknown'."""
    return _RANK.get((confidence or "unknown").lower(), _RANK["unknown"])


def reading(value, *, by: str, confidence: str, detail: str | None = None,
            now: datetime | None = None) -> dict:
    """One attribute's record: what, from where, how sure, when."""
    r = {"value": value, "by": by, "confidence": confidence if confidence in _RANK else "unknown",
         "at": _now_iso(now)}
    if detail:
        r["detail"] = str(detail)[:120]
    return r


# ── the telephone country ─────────────────────────────────────────────────────

def telephone_country(handle: str | None) -> dict | None:
    """{iso, country, flag_url, code} for a WhatsApp handle or phone, or None
    when it is not a plausible number. The phone-numbers library decides a
    shared code (+1 212 → US, not Canada; +7 495 → RU, not Kazakhstan); the
    prefix table is the fallback for a number it cannot place."""
    if not handle or not is_plausible_phone(str(handle)):
        return None
    table = resolve_country(str(handle)) or {}
    iso = None
    try:
        iso = region_of(str(handle))
    except Exception:
        iso = None
    if iso and name_for_iso(iso):
        return {"iso": iso, "country": name_for_iso(iso), "flag_url": flag_url_for(iso),
                "code": table.get("code")}
    if table.get("country_iso"):
        return {"iso": table["country_iso"], "country": table["country"],
                "flag_url": table["flag_url"], "code": table.get("code")}
    return None


def country_from_words(text: str | None) -> tuple[str | None, str | None]:
    """(iso, city) read from a stated location. The city is the text itself
    when it is not just a country name ('Nairobi' → ('KE', 'Nairobi');
    'Kenya' → ('KE', None); 'Kampala, Uganda' → ('UG', 'Kampala, Uganda'))."""
    t = " ".join(str(text or "").split())
    if not t:
        return None, None
    iso = iso_from_text(t)
    if not iso:
        return None, (t[:120] or None)
    name = (name_for_iso(iso) or "").lower()
    city = None if t.lower().strip(" .,") == name else t[:120]
    return iso, city


# ── writing a reading ─────────────────────────────────────────────────────────

def observe(state: dict | None, attr: str, value, *, by: str, confidence: str,
            detail: str | None = None, now: datetime | None = None) -> tuple[dict, bool]:
    """A new reading of `attr` applied to a person's state. Pure: returns
    (new_state, changed). Rules:
      · no value → nothing happens;
      · the same value → the record is refreshed only when the new reading is
        at least as confident (a weaker echo never rewrites a stronger one);
      · a different value → it replaces the record when at least as confident,
        and the previous reading is appended to the history; a weaker,
        conflicting reading is recorded in the history only, so the conflict
        is visible without moving the decision."""
    if attr not in ATTRS or value in (None, ""):
        return dict(state or {}), False
    st = dict(state or {})
    geo = dict(st.get("geo") or {})
    new = reading(value, by=by, confidence=confidence, detail=detail, now=now)
    cur = geo.get(attr)
    hist = list(geo.get("history") or [])
    if cur and cur.get("value") == value:
        if rank(new["confidence"]) <= rank(cur.get("confidence")):
            geo[attr] = new
            st["geo"] = geo
            return st, (cur.get("by") != by or cur.get("confidence") != new["confidence"]
                        or cur.get("detail") != new.get("detail"))
        return st, False
    entry = {"attr": attr, "value": value, "by": by, "confidence": new["confidence"],
             "at": new["at"]}
    if cur:
        entry["previous"] = {"value": cur.get("value"), "by": cur.get("by"),
                             "confidence": cur.get("confidence"), "at": cur.get("at")}
    if cur and rank(new["confidence"]) > rank(cur.get("confidence")):
        entry["kept"] = "previous"            # the conflict is recorded, not applied
        hist.append(entry)
        geo["history"] = hist[-HISTORY_CAP:]
        st["geo"] = geo
        return st, True
    geo[attr] = new
    if cur:
        hist.append(entry)
        geo["history"] = hist[-HISTORY_CAP:]
    st["geo"] = geo
    return st, True


def observe_many(state: dict | None, readings: list[tuple]) -> tuple[dict, bool]:
    """Several `observe` calls in order; (new_state, any_changed)."""
    st, any_changed = dict(state or {}), False
    for attr, value, kw in readings:
        st, ch = observe(st, attr, value, **kw)
        any_changed = any_changed or ch
    return st, any_changed


# ── the one decision ──────────────────────────────────────────────────────────

def decide(state: dict | None, *, fallback_iso: str | None = None,
           fallback_by: str = "phone") -> dict:
    """Where Neema treats this customer as being: the confirmed residence,
    else a probable country of at least 'probable' confidence, else the
    telephone country, else `fallback_iso` (a prefix read by the caller).
    Returns {country_iso, country, flag_url, by, confidence, attribute};
    country_iso is None when nothing places them."""
    geo = ((state or {}).get("geo") or {})
    for attr in _DECIDING:
        r = geo.get(attr) or {}
        iso = (r.get("value") or "").strip().upper() if isinstance(r.get("value"), str) else None
        if not iso:
            continue
        if rank(r.get("confidence")) > rank(_MIN_DECIDING[attr]):
            continue
        return {"country_iso": iso, "country": name_for_iso(iso) or iso,
                "flag_url": flag_url_for(iso), "by": r.get("by"),
                "confidence": r.get("confidence"), "attribute": attr}
    if fallback_iso:
        iso = fallback_iso.strip().upper()
        return {"country_iso": iso, "country": name_for_iso(iso) or iso,
                "flag_url": flag_url_for(iso), "by": fallback_by,
                "confidence": "probable", "attribute": "telephone_country"}
    return {"country_iso": None, "country": None, "flag_url": None, "by": None,
            "confidence": "unknown", "attribute": None}


def view(state: dict | None, *, handle: str | None = None,
         language: str | None = None) -> dict:
    """The profile's geography block: every attribute with its provenance,
    the decision, and whether the telephone country and the decided country
    disagree (the only case that earns a clarification mark). A telephone
    country not yet recorded is read from `handle` so older profiles show it
    too. `language` is the person's preferred language, read by the caller
    from contact_preferences (its writer is the scribe; this only reports)."""
    geo = dict(((state or {}).get("geo") or {}))
    tel = geo.get("telephone_country")
    if not tel and handle:
        t = telephone_country(handle)
        if t:
            tel = reading(t["iso"], by="phone", confidence="confirmed",
                          detail=(f"+{t['code']}" if t.get("code") else None))
            tel["at"] = None               # derived now, never written
    out = {}
    for attr in ATTRS:
        r = tel if attr == "telephone_country" else geo.get(attr)
        if r:
            val = r.get("value")
            out[attr] = {**r, "label": (name_for_iso(val) or val) if attr != "city" else val,
                         "source": SOURCE_LABELS.get(r.get("by"), r.get("by")),
                         "confidence_label": LEVEL_LABELS.get(r.get("confidence"), "Unknown")}
        else:
            out[attr] = None
    fallback = (tel or {}).get("value")
    decision = decide(state, fallback_iso=fallback)
    out["decision"] = {**decision,
                       "source": SOURCE_LABELS.get(decision.get("by"), decision.get("by")),
                       "confidence_label": LEVEL_LABELS.get(decision.get("confidence"), "Unknown")}
    tel_iso = (tel or {}).get("value")
    out["discrepancy"] = bool(tel_iso and decision.get("country_iso")
                              and tel_iso != decision["country_iso"])
    out["preferred_language"] = ({"value": language, "by": "messages", "confidence": "probable",
                                  "source": "the customer's messages",
                                  "confidence_label": "Probable"} if language else None)
    out["history"] = list(geo.get("history") or [])
    return out


# ── persisting on the person, mirroring on the user ───────────────────────────

async def place(db, person, readings: list[tuple], *, user=None) -> dict | None:
    """Apply `readings` ([(attr, value, {by, confidence, detail})]) to the
    person's state under the row lock, mirror the decision on the user row
    when given, and return a change summary ({before, after, changed}) or
    None when nothing changed. Caller owns the commit. Never raises: a
    geography write must never cost a reply."""
    if person is None:
        return None
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.services.state_lock import lock_for_write
        before = decide(person.state)
        new_state, changed = observe_many(person.state, readings)
        if not changed:
            return None
        locked = await lock_for_write(db, person)
        if locked is None:
            return None
        new_state, changed = observe_many(locked.state, readings)
        if not changed:
            return None
        locked.state = new_state
        flag_modified(locked, "state")
        after = decide(new_state)
        if user is not None:
            mirror_user(user, after)
        return {"before": before, "after": after,
                "changed": [a for a, _v, _k in readings],
                "moved": before.get("country_iso") != after.get("country_iso")}
    except Exception:
        _log.warning("geography write failed", exc_info=True)
        return None


def mirror_user(user, decision: dict) -> bool:
    """`users.country*` follow the decision (compatibility store for every
    existing reader). Returns whether anything changed."""
    iso = decision.get("country_iso")
    if user is None or not iso:
        return False
    if (getattr(user, "country_iso", None) == iso
            and getattr(user, "country", None) == decision.get("country")):
        return False
    user.country_iso = iso
    user.country = decision.get("country") or iso
    user.flag_url = decision.get("flag_url") or flag_url_for(iso)
    return True


def stated_readings(location: str | None, *, by: str = "stated",
                    confidence: str = "high") -> list[tuple]:
    """The readings a stated location yields: the probable country when the
    words name one (a Kenyan town names Kenya), and the city when the words
    are more than a country."""
    iso, city = country_from_words(location)
    out: list[tuple] = []
    if iso:
        out.append(("probable_country", iso, {"by": by, "confidence": confidence,
                                               "detail": " ".join(str(location).split())[:120]}))
    if city:
        out.append(("city", city, {"by": by, "confidence": confidence}))
    return out


def operator_readings(*, country_iso: str | None = None, country: str | None = None,
                      location: str | None = None) -> list[tuple]:
    """What an operator's edit confirms: the residence from an ISO, a country
    name or the location text; the city from the location text."""
    iso = (country_iso or "").strip().upper() or None
    if iso and not name_for_iso(iso):
        iso = None
    if not iso and country:
        iso = iso_from_text(country)
    loc_iso, city = country_from_words(location)
    if not iso:
        iso = loc_iso
    out: list[tuple] = []
    if iso:
        out.append(("confirmed_residence", iso, {"by": "operator", "confidence": "confirmed",
                                                  "detail": (location or country or None)}))
    if city:
        out.append(("city", city, {"by": "operator", "confidence": "confirmed"}))
    return out


def describe_change(change: dict | None) -> str | None:
    """One line for the activity trail: 'Placed in Kenya (what the customer
    said); the number is Bahraini'. None when the decision did not move."""
    if not change or not change.get("moved"):
        return None
    after, before = change.get("after") or {}, change.get("before") or {}
    line = f"Placed in {after.get('country') or after.get('country_iso')}"
    src = SOURCE_LABELS.get(after.get("by"), after.get("by"))
    if src:
        line += f" ({src})"
    if before.get("country_iso"):
        line += f"; was {before.get('country') or before.get('country_iso')}"
    return line


async def note(db, *, channel: str, contact: str, change: dict | None) -> None:
    """A customer-level event when the decision moved — through the activity
    trail (its own commit, best-effort). Call it after the caller's commit."""
    text = describe_change(change)
    if not text:
        return
    try:
        from app.services import activity_trail
        await activity_trail.record(db, channel=channel, contact=contact, tool="geography",
                                    args={"placed": change["after"].get("country_iso"),
                                          "by": change["after"].get("by"),
                                          "confidence": change["after"].get("confidence"),
                                          "was": (change.get("before") or {}).get("country_iso")},
                                    out={"summary": text})
    except Exception:
        _log.warning("geography note failed for %s/%s", channel, contact, exc_info=False)


def carry_on_merge(primary_state: dict | None, secondary_state: dict | None) -> tuple[dict, bool]:
    """A merge carries the secondary's geography onto the primary, attribute
    by attribute: a reading the primary lacks is taken; a stronger reading on
    the secondary replaces a weaker one (and the history keeps the weaker);
    an equal or weaker one is kept in the history only. Pure."""
    sec = ((secondary_state or {}).get("geo") or {})
    st, changed = dict(primary_state or {}), False
    for attr in ATTRS:
        r = sec.get(attr)
        if not r or r.get("value") in (None, ""):
            continue
        cur = ((st.get("geo") or {}).get(attr)) or None
        if cur and rank(r.get("confidence")) >= rank(cur.get("confidence")) \
                and cur.get("value") == r.get("value"):
            continue
        st, ch = observe(st, attr, r["value"], by=r.get("by") or "merge",
                         confidence=r.get("confidence") or "unknown", detail=r.get("detail"))
        changed = changed or ch
    sec_hist = list(sec.get("history") or [])
    if sec_hist:
        geo = dict(st.get("geo") or {})
        hist = list(geo.get("history") or [])
        for h in sec_hist:
            if h not in hist:
                hist.append(h)
        hist.sort(key=lambda h: str(h.get("at") or ""))
        if hist != list(geo.get("history") or []):
            geo["history"] = hist[-HISTORY_CAP:]
            st["geo"] = geo
            changed = True
    return st, changed
