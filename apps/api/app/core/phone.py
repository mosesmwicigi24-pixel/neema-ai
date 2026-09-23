"""Canonical, country-aware phone handling — the shared identity key between
WhatsApp and the Bethany House hub.

We match customers on the **full E.164 number, country code included** — never on
the trailing national digits. Trailing-digit matching collides across countries:
a Kenyan `+254 712 345 678` and a Ugandan `+256 712 345 678` share the same last 9
digits and would be wrongly merged. Bethany House takes international orders
(KE +254, UG +256, TZ +255, RW +250…), so the country code is the disambiguator.

`to_e164` takes a default region (the country to assume for a *local* number with
no country code — the shop's home country, Kenya). A number that already carries a
country code (`+256…`, `256…`) keeps it, so an international customer never collapses
onto a Kenyan one.

WhatsApp ids (wa_id) are not always numbers the library's metadata calls valid
(owner export, 2026-09-21: 116 customers who had written to us were rejected):
  - Mexico keeps the retired mobile "1" (52 1 + 10 digits) and Brazil drops the
    mobile 9 (55 + area + 8 digits). Those are repaired to the real number.
  - Côte d'Ivoire / Cameroon accounts from before renumbering keep their old
    8-digit form, Benin's 2024 numbers are newer than the metadata, and a few
    KE/CD/ZM/TZ ranges are unknown to it. There is no honest conversion for
    these, so they are accepted exactly as WhatsApp sent them — but only when the
    caller holds proof of life (`proven=True`: WhatsApp delivered inbound
    messages from that very handle). A string with no such proof stays rejected.
"""
from __future__ import annotations

import phonenumbers

DEFAULT_REGION = "KE"

# ITU-T E.164: country code + national number is 15 digits at most. Anything
# longer is a platform id (a 16-17 digit Messenger/Facebook PSID), even when the
# library's variable-length metadata for a country (Germany) would take it.
E164_MAX_DIGITS = 15


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _valid_e164(num: str, region: str | None) -> str | None:
    try:
        p = phonenumbers.parse(num, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(p):
        return None
    e = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    return e if len(e) - 1 <= E164_MAX_DIGITS else None


def _whatsapp_legacy_repair(digs: str) -> str | None:
    """The real number (digits, country code first) behind a WhatsApp wa_id kept
    in a retired national form, or None when `digs` is not one of those forms.
    The caller validates the result, so a repair that isn't a real number is
    discarded rather than invented."""
    # Mexico dropped the mobile "1" in 2019; WhatsApp kept it: 52 1 + 10 digits.
    if len(digs) == 13 and digs.startswith("521"):
        return "52" + digs[3:]
    # Brazil put a 9 before every mobile by 2016; WhatsApp dropped it for older
    # accounts: 55 + 2-digit area code + 8 digits. The 9 goes after the area code.
    if len(digs) == 12 and digs.startswith("55"):
        return digs[:4] + "9" + digs[4:]
    return None


def _proven_handle(s: str) -> str | None:
    """A digits-only WhatsApp handle taken as-is — the `proven=True` path. It must
    still look like an international number: WhatsApp's own shape (digits, an
    optional '+', nothing else), E.164 length, no trunk '0', and a country
    calling code that exists. Proof of life vouches for the handle, not for
    free text."""
    body = s[1:] if s.startswith("+") else s
    if not body.isdigit() or body.startswith("0") or not 7 <= len(body) <= E164_MAX_DIGITS:
        return None
    try:
        p = phonenumbers.parse("+" + body, None)
    except phonenumbers.NumberParseException:
        return None
    if phonenumbers.region_code_for_country_code(p.country_code) == phonenumbers.UNKNOWN_REGION:
        return None
    return "+" + body


def to_e164(raw: str | None, region: str = DEFAULT_REGION, *,
            proven: bool = False) -> str | None:
    """Canonical E.164 (`+254712345678`) or None if not a valid number.

    Resolves the mixed formats the hub stores and the WhatsApp id shape:
      0712345678        + region KE   -> +254712345678   (local)
      254712345678      (wa_id)       -> +254712345678   (intl, no plus)
      +254 712 345 678                -> +254712345678
      256712345678 / +256712345678    -> +256712345678   (stays Ugandan)
      5215512345678     (MX wa_id)    -> +525512345678   (retired mobile 1 removed)
      551187654321      (BR wa_id)    -> +5511987654321  (mobile 9 re-inserted)

    `proven=True` is the caller's statement that WhatsApp has delivered inbound
    messages from exactly this handle. Then a digits-only handle the library
    cannot validate (CI/CM pre-renumbering, BJ 2024, unknown KE ranges) is taken
    as-is instead of being rejected. It never overrides a valid reading or a
    repair, and it is never a license to guess: without it they stay None.

    Nothing longer than 15 digits is returned (E.164 cap): a bare 16-17 digit
    string is a Meta PSID, not a phone.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    digs = _digits(s)
    if not digs:
        return None
    if len(digs) > E164_MAX_DIGITS and s.lstrip("+").isdigit():
        return None           # the platform-id shape; free text ("… ext 12") may still hold a number

    candidates: list[tuple[str, str | None]] = []
    if s.startswith("+"):
        candidates.append((s, None))
    else:
        # Prefer an international read (a leading country code wins), then fall
        # back to interpreting it as a local number for the default region.
        candidates.append(("+" + digs, None))
        candidates.append((s, region))

    for num, reg in candidates:
        e = _valid_e164(num, reg)
        if e:
            return e

    repaired = _whatsapp_legacy_repair(digs)
    if repaired:
        e = _valid_e164("+" + repaired, None)
        if e:
            return e

    if proven:
        return _proven_handle(s)
    return None


def same_number(
    a: str | None, b: str | None,
    region_a: str = DEFAULT_REGION, region_b: str = DEFAULT_REGION,
    *, proven: bool = False,
) -> bool:
    """True when two raw numbers canonicalize to the same E.164 (country-safe).

    `proven` is proof of life for `a` (see `to_e164`). It carries over to `b`
    only when `b` is digit-for-digit that same handle — the hub storing the very
    wa_id Neema pushed — so the full country code is still part of the match."""
    ea = to_e164(a, region_a, proven=proven)
    eb = to_e164(b, region_b)
    if eb is None and proven and ea and _digits(str(b or "")) == ea[1:]:
        eb = ea
    return bool(ea and eb and ea == eb)


def national_digits(raw: str | None, region: str = DEFAULT_REGION, *,
                    proven: bool = False) -> str | None:
    """The national number as a plain digit string (for a hub ILIKE search that
    should hit every stored format). Confirm any hit with `same_number`."""
    e = to_e164(raw, region, proven=proven)
    if not e:
        return None
    try:
        p = phonenumbers.parse(e, None)
    except phonenumbers.NumberParseException:
        return None
    return str(p.national_number)


def region_of(raw: str | None, *, proven: bool = False) -> str | None:
    """ISO region of a full international number (a wa_id: '27821…' → 'ZA'), for
    reading a customer's LOCAL number ('0821…') against their own country. None
    when it is not a number or its country code is non-geographic."""
    e = to_e164(raw, proven=proven)
    if not e:
        return None
    try:
        p = phonenumbers.parse(e, None)
    except phonenumbers.NumberParseException:
        return None
    reg = (phonenumbers.region_code_for_number(p)
           or phonenumbers.region_code_for_country_code(p.country_code))
    return reg if reg and reg not in (phonenumbers.UNKNOWN_REGION, "001") else None


def whatsapp_ids(e164: str | None) -> list[str]:
    """The wa_id(s) WhatsApp may key this number under, for finding a WhatsApp
    identity or conversation from a canonical number: its E.164 digits, then the
    legacy form WhatsApp keeps for older Mexican and Brazilian accounts (the
    inverse of the repair in `to_e164` — `+525512345678` is wa_id `5215512345678`)."""
    d = _digits(str(e164 or ""))
    if not d:
        return []
    ids = [d]
    if len(d) == 12 and d.startswith("52"):
        ids.append("521" + d[2:])
    elif len(d) == 13 and d.startswith("55") and d[4] == "9":
        ids.append(d[:4] + d[5:])
    return ids


def carries_country_code(raw: str | None, e164: str | None) -> bool:
    """Did the customer GIVE the country — "+254712…" or "254712…" — or was
    it a bare local number ("0712…") whose region we assumed? The difference
    is evidence versus a parsing default (owner, 2026-09-05: no evidence, no
    KES)."""
    s = str(raw or "").strip()
    if not s or not e164:
        return False
    if s.startswith("+"):
        return True
    digs = "".join(ch for ch in s if ch.isdigit())
    e = str(e164).lstrip("+")
    # WhatsApp's legacy Mexican/Brazilian form ("52 1…") carries the code too.
    return digs == e or digs == "00" + e or digs in whatsapp_ids(e164)


def is_plausible_phone(raw: str | None) -> bool:
    """Cheap guard: could this string be a phone number at all?

    E.164 caps a full international number at 15 digits; Meta scoped ids (Messenger
    PSIDs, Facebook comment-author ids, IGSIDs) are 16-17 digits. So anything longer
    than 15 digits is NOT a phone — it's a platform id that must never be stored as
    a wa_id-as-phone or minted as a (whatsapp, …) identity. Deliberately does NOT
    require full to_e164 validity (WhatsApp wa_ids are trusted), just plausibility.
    """
    s = str(raw or "").strip()
    # Strip common phone FORMATTING only ('+', spaces, dashes, dots, parens). Any
    # OTHER character (letters, underscores…) means this is NOT a phone at all —
    # a web session key like "web_3fa4…" carries 7-15 digits inside its hash and
    # was passing the old digits-only extraction, minting phantom identities.
    cleaned = s.lstrip("+")
    for ch in " -.()":
        cleaned = cleaned.replace(ch, "")
    if not cleaned.isdigit():
        return False
    return 7 <= len(cleaned) <= 15
