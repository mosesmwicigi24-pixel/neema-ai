"""Who the customer is called — one decision, with its evidence.

Owner, 2026-11-09: a customer showed as "John 14:14" — a Facebook display
name that is a Bible verse, stored, shown and greeted as if it were their
name. The audit had named the gap (CUSTOMER_KNOWLEDGE G4: "a profile name is
trusted as a person's name"); four stores held a name under three rules and
every screen picked its own.

This module is the one place that decides. Every name that reaches Neema is
recorded on the person WITH where it came from, and the canonical name is
chosen by the strength of that evidence:

  level      source                                          rank
  confirmed  staff typed or corrected it ("operator"); an       5
             earlier confirmed name ("legacy_confirmed")
  stated     the customer said it ("My name is Peter", or the    4
             writer's capture tool recording what they said)
  profile    their WhatsApp profile name                        3
  platform   Facebook / Messenger / Instagram / TikTok / a      2
             comment's author name / the public web form
  inferred   anything else (kept as a suggestion only)          1

A name that is not a person's name — a scripture reference ("John 14:14",
"Psalm 23"), a church or business ("Grace Ministries"), a handle or a
placeholder — is recorded and kept as the channel's display name, but it
ranks below every personal name, and Neema never greets anyone by it.

    persons.state["name"] = {
      "readings": {"whatsapp": {"value": "Mary W", "by": "whatsapp",
                                "level": "profile", "kind": "person", "at": ...},
                   "facebook": {"value": "John 14:14", "kind": "scripture", ...},
                   "stated":   {...}, "operator": {...}},
      "current":  {"value": "Mary W", "by": "whatsapp", "level": "profile",
                   "kind": "person", "at": ...},
      "history":  [{"previous": {...}, "value": ..., "by": ..., "at": ...}],
    }

The decision is mirrored on the legacy columns every screen already reads
(persons.display_name — the inbox; users.name — the profile, Android, iOS;
users.name_confirmed — "don't let a profile name overwrite this"), so all of
them agree. Each channel's own name stays on its identity row
(identities.display_name) and in `readings`. Nothing here merges people.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone

_log = logging.getLogger("neema.names")

# ── Evidence levels ──────────────────────────────────────────────────────────

LEVELS = {"confirmed": 5, "stated": 4, "profile": 3, "platform": 2, "inferred": 1}
LEVEL_LABELS = {"confirmed": "Confirmed by staff", "stated": "Said by the customer",
                "profile": "WhatsApp profile name", "platform": "Social profile name",
                "inferred": "Suggested"}
# Where a reading came from → its level.
SOURCE_LEVEL = {
    "operator": "confirmed", "legacy_confirmed": "confirmed",
    "stated": "stated",
    # The public made-to-order form is unauthenticated: anyone can type any
    # name beside any number, so it counts as a profile-grade hint, not as the
    # customer's own word.
    "web_form": "platform",
    "whatsapp": "profile",
    "facebook": "platform", "messenger": "platform", "instagram": "platform",
    "tiktok": "platform", "comment": "platform", "web_chat": "platform", "platform": "platform",
    "inferred": "inferred",
}
SOURCE_LABELS = {
    "operator": "Confirmed by staff", "legacy_confirmed": "Confirmed earlier",
    "stated": "Said by the customer", "web_form": "Typed by the customer on the website",
    "whatsapp": "WhatsApp profile", "facebook": "Facebook profile", "messenger": "Messenger profile",
    "instagram": "Instagram profile", "tiktok": "TikTok profile", "comment": "Comment author",
    "web_chat": "Website chat", "platform": "Social profile", "inferred": "Suggested",
}
HISTORY_CAP = 20


def channel_source(channel: str | None) -> str:
    """The source key for a channel's profile name."""
    c = (channel or "").lower()
    if c == "whatsapp":
        return "whatsapp"
    if c.startswith("facebook") or c == "fb_comment":
        return "comment" if "comment" in c else "facebook"
    if c.startswith("instagram") or c == "ig_comment":
        return "comment" if "comment" in c else "instagram"
    if c in SOURCE_LEVEL:
        return c
    return "platform"


# ── Is this a person's name? ─────────────────────────────────────────────────

# Books of the Bible (and common short forms), so "John 14:14", "Psalm 23",
# "1 Cor 13", "Phil 4:13" read as scripture, not as a person named John.
_BOOKS = (
    "genesis gen exodus exod ex leviticus lev numbers num deuteronomy deut joshua josh "
    "judges judg ruth samuel sam kings chronicles chron chr ezra nehemiah neh esther est "
    "job psalm psalms ps psa proverbs prov ecclesiastes eccl song songs isaiah isa "
    "jeremiah jer lamentations lam ezekiel ezek daniel dan hosea hos joel amos obadiah obad "
    "jonah micah mic nahum habakkuk hab zephaniah zeph haggai hag zechariah zech malachi mal "
    "matthew matt mt mark mk luke lk john jn acts romans rom corinthians cor galatians gal "
    "ephesians eph philippians phil colossians col thessalonians thess timothy tim titus "
    "philemon hebrews heb james jas peter pet jude revelation revelations rev"
).split()
_BOOK_RE = "|".join(sorted(set(_BOOKS), key=len, reverse=True))
_SCRIPTURE_RE = re.compile(
    rf"\b(?:[1-3]\s*)?(?:{_BOOK_RE})\.?\s*\d{{1,3}}(?:\s*[:.]\s*\d{{1,3}}(?:\s*[-–]\s*\d{{1,3}})?)?\b",
    re.IGNORECASE)
_VERSE_RE = re.compile(r"\b\d{1,3}\s*:\s*\d{1,3}\b")

_ORG_WORDS = set((
    "church churches ministry ministries cathedral parish chapel fellowship assembly assemblies "
    "tabernacle gospel mission missions diocese archdiocese choir congregation sanctuary "
    "temple mosque centre center ltd limited enterprise enterprises shop store stores boutique "
    "collections collection agency agencies company co inc llc plc group foundation trust "
    "school academy college university hospital clinic official tv radio fm media studio "
    "studios outfitters designs tailors tailoring wholesale supplies supplier suppliers "
    "investments services solutions team"
).split())
_PLACEHOLDERS = {
    "guest", "unknown", "customer", "user", "n/a", "na", "null", "none", "test", "anonymous",
    "whatsapp user", "facebook user", "instagram user", "messenger user", "no name", "noname",
    "walk-in", "walk in", "walkin", "bethany contact",
}
TITLES = (
    "Bishop", "Archbishop", "Pastor", "Reverend", "Rev", "Rev.", "Fr", "Fr.", "Father", "Sr",
    "Sr.", "Sister", "Brother", "Bro", "Bro.", "Dr", "Dr.", "Mr", "Mr.", "Mrs", "Mrs.", "Ms",
    "Ms.", "Apostle", "Prophet", "Prophetess", "Evangelist", "Deacon", "Deaconess", "Elder",
    "Canon", "Prof", "Prof.", "Mama", "Mzee", "Mchungaji", "Askofu", "Padre", "Mwalimu",
    "Bishop.", "Overseer", "Minister", "Lady",
)
_TITLE_SET = {t.lower().rstrip(".") for t in TITLES}
# Words that, right after "I am", are not a name ("I am the way", "I'm fine").
_NOT_NAMES = set((
    "the a an and or but so very just not here there fine good ok okay well happy glad "
    "interested looking asking writing calling coming going trying waiting ready sorry "
    "sure new back from in at on with also still now today kenyan zambian ugandan "
    "nigerian tanzanian african american british god jesus christ lord holy spirit alpha "
    "omega that who what your yours his her their our sent buying selling ordering "
    "inquiring enquiring a student married single available busy free satisfied done "
    "requesting please kindly hoping wondering"
).split())


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def classify(name: str | None) -> str:
    """'person' | 'scripture' | 'organization' | 'handle' | 'placeholder' | 'empty'."""
    s = _fold(name or "")
    if not s:
        return "empty"
    low = s.lower().strip(" .")
    if low in _PLACEHOLDERS or low.startswith("bethany contact"):
        return "placeholder"
    if _SCRIPTURE_RE.search(s) or _VERSE_RE.search(s):
        return "scripture"
    words = re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", s, re.UNICODE)
    if any(w.lower() in _ORG_WORDS for w in words):
        return "organization"
    letters = sum(ch.isalpha() for ch in s)
    if "@" in s or "_" in s or re.search(r"\w\.\w", s) or re.search(r"\d", s):
        return "handle"
    if letters < 2 or letters < 0.6 * len(re.sub(r"\s", "", s)):
        return "handle"            # emoji, symbols, initials only
    real = [w for w in words if w.lower().rstrip(".") not in _TITLE_SET]
    if not real or len(words) > 6:
        return "handle" if not real else "organization"
    return "person"


def is_personal(name: str | None) -> bool:
    return classify(name) == "person"


# ── "My name is Peter": self-introduction in what they wrote ─────────────────

_NAME_TOKEN = r"[^\W\d_][^\W\d_'’.-]*(?:['’-][^\W\d_]+)*\.?"
_NAME = rf"({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}})"
_TITLE_ALT = "|".join(re.escape(t) for t in sorted(TITLES, key=len, reverse=True))
_TITLED = rf"((?:{_TITLE_ALT})\s+{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}})"
# Each pattern: (regex, needs_capital) — a capital first letter is required
# where the phrase is also everyday speech ("I'm Peter" vs "I'm fine").
_INTRO = [
    (re.compile(rf"\bmy\s+(?:full\s+|real\s+)?name\s+is\s+{_NAME}", re.I), False),
    (re.compile(rf"\b(?:my\s+names?\s+are|names?\s*[:\-]\s*){_NAME}", re.I), False),
    (re.compile(rf"\b(?:you\s+can\s+)?call\s+me\s+{_NAME}", re.I), True),
    (re.compile(rf"\b(?:i\s+am|i'm|i’m|im)\s+{_TITLED}", re.I), True),
    (re.compile(rf"\b(?:this\s+is|it'?s|it’s)\s+{_TITLED}", re.I), True),
    (re.compile(rf"^\W*(?:hi|hello|hey|habari|good\s+\w+|greetings|praise\s+the\s+lord)?[\s,!.]*"
                rf"(?:i\s+am|i'm|i’m|im|this\s+is)\s+{_NAME}\s*(?:[,.!]|here\b|from\b|$)", re.I), True),
    # Swahili, French, Portuguese.
    (re.compile(rf"\b(?:naitwa|jina\s+langu\s+ni|majina\s+yangu\s+ni)\s+{_NAME}", re.I), False),
    (re.compile(rf"\bmimi\s+ni\s+{_TITLED}", re.I), True),
    (re.compile(rf"\b(?:je\s+m['’]appelle|mon\s+nom\s+est|je\s+suis)\s+{_NAME}", re.I), True),
    (re.compile(rf"\b(?:meu\s+nome\s+é|meu\s+nome\s+e|chamo-me|me\s+chamo)\s+{_NAME}", re.I), True),
]
# Words that end a name ("Peter from Nairobi", "Peter and I", "Peter here").
_STOP_AFTER = set((
    "from of and na here wa la de do da in at with for please kindly the i im i'm "
    "nimefurahi asante thanks thank"
).split())


def _trim_name(raw: str) -> str:
    words = raw.split()
    out = []
    for w in words:
        if w.lower().strip(".,!") in _STOP_AFTER:
            break
        out.append(w.strip(",!?;:"))
    name = " ".join(out).strip(" .,'’\"")
    return name


def _quoted(text: str, start: int) -> bool:
    """Inside a quotation ("…" or “…”) — a quote, not them."""
    before = text[:start]
    return before.count('"') % 2 == 1 or before.count("“") > before.count("”")


def self_introduction(text: str | None) -> str | None:
    """The name a customer gives for THEMSELVES in this message, or None.

    Reads "My name is Peter", "I'm Bishop Daniel", "This is Pastor James",
    "Naitwa Wanjiru", "Je m'appelle Jean", "Meu nome é Ana". Leaves alone:
    scripture and quotations ("I am the way", "I am Alpha and Omega", a verse
    in quotes), someone else's name ("my pastor's name is…"), and everyday
    speech ("I'm fine", "I'm interested", "I'm in Nairobi", "I'm Kenyan").
    """
    t = _fold(text or "")
    if not t or len(t) > 1200:
        return None
    for rx, needs_capital in _INTRO:
        for m in rx.finditer(t):
            if _quoted(t, m.start()):
                continue
            # "my pastor's name is…", "his name is…": not them.
            pre = t[max(0, m.start() - 12):m.start()].lower()
            if re.search(r"(?:'s|’s|his|her|their|our)\s*$", pre):
                continue
            name = _trim_name(m.group(1))
            if not name or re.search(r"['’]s\b", name):     # "I'm Peter's mother"
                continue
            first_real = next((w for w in name.split() if w.lower().rstrip(".") not in _TITLE_SET), "")
            if not first_real or first_real.lower().strip(".") in _NOT_NAMES:
                continue
            if needs_capital and not first_real[:1].isupper():
                continue
            if classify(name) != "person":
                continue
            # A place or a nationality is not a name ("I'm Kenyan", "this is Nairobi").
            try:
                from app.core.countries import iso_from_text
                if iso_from_text(first_real) and len(name.split()) == 1:
                    continue
            except Exception:
                pass
            # Title case a shouted or lower-cased name; keep a mixed one as written.
            if name.isupper() or name.islower():
                name = " ".join(w[:1].upper() + w[1:].lower() for w in name.split())
            return name[:100]
    return None


# ── Readings → the decision ──────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reading(value: str, *, by: str, at: str | None = None) -> dict:
    v = _fold(value)[:200]
    lvl = SOURCE_LEVEL.get(by, "inferred")
    return {"value": v, "by": by, "level": lvl, "kind": classify(v), "at": at or _now()}


def _score(r: dict) -> tuple:
    lvl = LEVELS.get(r.get("level") or "inferred", 1)
    personal = r.get("kind") == "person"
    # What staff typed always stands (even "Grace Ministries" for a church
    # account). Otherwise every personal name outranks every non-personal one;
    # then the level; then the latest.
    return (1 if r.get("by") == "operator" else 0, 1 if personal else 0, lvl, r.get("at") or "")


def _fuller(best: dict, readings: dict) -> dict:
    """A fuller personal name for the same person wins over a partial one
    ("Peter" said, "Peter Kamau" on WhatsApp), unless staff confirmed it."""
    if best.get("level") == "confirmed" or best.get("kind") != "person":
        return best
    b = best["value"].lower()
    for r in readings.values():
        v = (r.get("value") or "")
        if (r.get("kind") == "person" and len(v) > len(best["value"])
                and re.match(rf"^(?:\w+\.?\s+)?{re.escape(b)}\b", v.lower())):
            return {**best, "value": v, "fuller_from": r.get("by")}
    return best


def decide(state: dict | None) -> dict | None:
    """The canonical reading from a person's state, or None when none recorded."""
    rec = (state or {}).get("name") or {}
    readings = rec.get("readings") or {}
    if not readings:
        return None
    best = max(readings.values(), key=_score)
    return _fuller(best, readings)


def observe(state: dict | None, value: str | None, *, by: str, at: str | None = None) -> tuple[dict, bool]:
    """(new_state, changed). Records `value` from `by`; recomputes the decision;
    appends the previous decision to the history when it moves. A staff
    confirmation is replaced only by another staff confirmation."""
    st = dict(state or {})
    v = _fold(value or "")
    if not v or classify(v) in ("empty",):
        return st, False
    rec = dict(st.get("name") or {})
    readings = dict(rec.get("readings") or {})
    cur = readings.get(by)
    if cur and cur.get("value") == v[:200]:
        return st, False
    readings[by] = reading(v, by=by, at=at)
    before = decide(st)
    rec["readings"] = readings
    after = decide({"name": rec})
    if before and after and (before.get("value") != after.get("value")):
        hist = list(rec.get("history") or [])
        hist.append({"previous": {k: before.get(k) for k in ("value", "by", "level", "kind")},
                     "value": after["value"], "by": after["by"], "at": after.get("at") or _now()})
        rec["history"] = hist[-HISTORY_CAP:]
    rec["current"] = after
    st["name"] = rec
    return st, True


def seed_from_legacy(state: dict | None, *, user_name: str | None, user_confirmed: bool,
                     person_name: str | None, identities: list | None = None,
                     user_wa_id: str | None = None) -> tuple[dict, bool]:
    """Bring a person recorded before this module under the rule, once: a
    confirmed user name as 'legacy_confirmed', the WhatsApp profile name on
    the user row as 'whatsapp', each channel identity's display name as its
    channel's profile name. Nothing is invented."""
    st = dict(state or {})
    if (st.get("name") or {}).get("readings"):
        return st, False
    changed = False
    old = "2000-01-01T00:00:00+00:00"           # older than anything observed live
    for ident in identities or []:
        dn = getattr(ident, "display_name", None)
        if dn:
            st, c = observe(st, dn, by=channel_source(getattr(ident, "channel", None)), at=old)
            changed = changed or c
    if person_name and not any(
            (r.get("value") == _fold(person_name)) for r in ((st.get("name") or {}).get("readings") or {}).values()):
        st, c = observe(st, person_name, by="platform", at=old)
        changed = changed or c
    if user_name:
        if user_confirmed:
            by = "legacy_confirmed"
        else:
            from app.core.phone import is_plausible_phone
            by = "whatsapp" if is_plausible_phone(user_wa_id) else "platform"
        st, c = observe(st, user_name, by=by, at=old)
        changed = changed or c
    return st, changed


# ── Writing it, and mirroring it where every screen reads ────────────────────

def mirror(person, users: list, decision: dict | None) -> None:
    """The decision onto persons.display_name and users.name / name_confirmed."""
    if decision is None:
        return
    v = decision["value"]
    if person is not None and person.display_name != v[:200]:
        person.display_name = v[:200]
    for u in users or []:
        if u is None:
            continue
        if (u.name or "") != v[:100]:
            u.name = v[:100]
        # "Don't let a profile name overwrite this" — what the legacy guards read.
        u.name_confirmed = LEVELS.get(decision.get("level") or "", 0) >= LEVELS["stated"] \
            and decision.get("kind") == "person"


async def record(db, person, value: str | None, *, by: str, users: list | None = None,
                 identities: list | None = None) -> dict | None:
    """Record a name from `by` on `person` under the row lock, mirror the
    decision on the legacy columns and return {before, after} when the
    decision moved (None otherwise). Caller owns the commit. Never raises: a
    name must never cost a reply."""
    if person is None or not _fold(value or ""):
        return None
    # Cheap path first (this runs on every inbound message): the same name
    # from the same source is already recorded — nothing to lock or write.
    known = (((person.state or {}).get("name") or {}).get("readings") or {}).get(by) or {}
    if known.get("value") == _fold(value)[:200]:
        return None
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.services.state_lock import lock_for_write
        from app.services.market import users_for_person
        if users is None:
            users = await users_for_person(db, person.id)
        if identities is None:
            from sqlalchemy import select
            from app.models.person import Identity
            identities = (await db.execute(select(Identity).where(
                Identity.person_id == person.id))).scalars().all()
        u0 = users[0] if users else None
        locked = await lock_for_write(db, person)
        if locked is None:
            return None
        st, seeded = seed_from_legacy(locked.state, user_name=getattr(u0, "name", None),
                                      user_confirmed=bool(getattr(u0, "name_confirmed", False)),
                                      person_name=locked.display_name, identities=identities,
                                      user_wa_id=getattr(u0, "wa_id", None))
        before = decide(st)
        st, changed = observe(st, value, by=by)
        if not (changed or seeded):
            return None
        locked.state = st
        flag_modified(locked, "state")
        after = decide(st)
        mirror(locked, users, after)
        if before is None or after is None or before.get("value") != after.get("value"):
            return {"before": before, "after": after}
        return None
    except Exception:
        _log.warning("name write failed", exc_info=True)
        return None


def summary(state: dict | None, *, user_name: str | None = None, user_confirmed: bool = False,
            person_name: str | None = None, identities: list | None = None,
            user_wa_id: str | None = None) -> dict:
    """What the profile shows: the name, where it came from, whether Neema
    may greet them by it, and every channel's own name."""
    st, _ = seed_from_legacy(state, user_name=user_name, user_confirmed=user_confirmed,
                             person_name=person_name, identities=identities, user_wa_id=user_wa_id)
    d = decide(st)
    readings = ((st.get("name") or {}).get("readings") or {})
    profiles = [{"source": k, "label": SOURCE_LABELS.get(k, k), "name": r.get("value"),
                 "kind": r.get("kind"), "level": r.get("level")}
                for k, r in sorted(readings.items(), key=lambda kv: _score(kv[1]), reverse=True)]
    if d is None:
        return {"name": None, "source": None, "label": None, "level": None, "kind": "empty",
                "addressable": False, "profiles": [], "history": []}
    return {"name": d["value"], "source": d["by"], "label": SOURCE_LABELS.get(d["by"], d["by"]),
            "level": d["level"], "kind": d["kind"], "addressable": d["kind"] == "person",
            "profiles": profiles, "history": ((st.get("name") or {}).get("history") or [])[-5:]}


KIND_WORDS = {"scripture": "a scripture reference", "organization": "a church or business name",
              "handle": "a username or symbols", "placeholder": "a placeholder"}


def for_agent(name: str | None) -> tuple[str, str]:
    """(name to greet by, or "", and a note for the writer when the only name
    known is not a person's). Neema never greets anyone by a verse."""
    n = _fold(name or "")
    if not n:
        return "", ""
    kind = classify(n)
    if kind == "person":
        return n, ""
    what = KIND_WORDS.get(kind, "not a personal name")
    return "", (f"- Their profile shows \"{n}\" — {what}, not their name. Don't call them by it; "
                f"if they tell you their name, use that.")
