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
"""
from __future__ import annotations

import phonenumbers

DEFAULT_REGION = "KE"


def to_e164(raw: str | None, region: str = DEFAULT_REGION) -> str | None:
    """Canonical E.164 (`+254712345678`) or None if not a valid number.

    Resolves the mixed formats the hub stores and the WhatsApp id shape:
      0712345678        + region KE   -> +254712345678   (local)
      254712345678      (wa_id)       -> +254712345678   (intl, no plus)
      +254 712 345 678                -> +254712345678
      256712345678 / +256712345678    -> +256712345678   (stays Ugandan)
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    candidates: list[tuple[str, str | None]] = []
    if s.startswith("+"):
        candidates.append((s, None))
    else:
        digs = "".join(ch for ch in s if ch.isdigit())
        if not digs:
            return None
        # Prefer an international read (a leading country code wins), then fall
        # back to interpreting it as a local number for the default region.
        candidates.append(("+" + digs, None))
        candidates.append((s, region))

    for num, reg in candidates:
        try:
            p = phonenumbers.parse(num, reg)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(p):
            return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    return None


def same_number(
    a: str | None, b: str | None,
    region_a: str = DEFAULT_REGION, region_b: str = DEFAULT_REGION,
) -> bool:
    """True when two raw numbers canonicalize to the same E.164 (country-safe)."""
    ea, eb = to_e164(a, region_a), to_e164(b, region_b)
    return bool(ea and eb and ea == eb)


def national_digits(raw: str | None, region: str = DEFAULT_REGION) -> str | None:
    """The national number as a plain digit string (for a hub ILIKE search that
    should hit every stored format). Confirm any hit with `same_number`."""
    e = to_e164(raw, region)
    if not e:
        return None
    try:
        p = phonenumbers.parse(e, None)
    except phonenumbers.NumberParseException:
        return None
    return str(p.national_number)
