"""Today's exchange rates for the currencies the hub does NOT price in.

Owner's rule (2026-09-05): ONE currency per market — KES for Kenya, ZMW for
Zambia, USD everywhere else — and the prompt's one exception: a customer who
asks for prices in their OWN money ("how much is that in rands?") gets the
USD figure converted. The model used to do that from memory, "with
confidence", and the gate (2026-09-25) rightly held every such figure as one
from nowhere — so a Durban customer was told "let me confirm the exact rate
with our team", a promise nobody keeps.

This module makes the conversion a FACT: one fetch a day of USD rates from a
public source, cached in Redis (a stale copy kept a week for the days the
source is down), given to the writer as "Today's rate: 1 USD = 16.43 ZAR"
and to the gate as the rate a figure may be verified against. No rate → no
conversion: the writer says the price is charged in USD and converts at the
day's rate when they pay. The house KES rate (settings.usd_kes_rate) and the
hub's own ZMW prices are never overridden here.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

_log = logging.getLogger("neema.fx")

FX_SOURCE = "https://open.er-api.com/v6/latest/USD"
# The currencies a customer of ours asks for — not KES / USD / ZMW, which the
# hub prices itself.
FX_CURRENCIES = ("ZAR", "NGN", "UGX", "TZS", "GHS", "RWF", "MWK", "BWP", "ETB",
                 "GBP", "EUR", "CAD", "AUD", "SSP", "CDF", "MZN", "NAD", "SZL", "LSL")
_NAMES: dict[str, tuple[str, ...]] = {
    "ZAR": (r"rands?", r"zar", r"south\s+african\s+rands?"),
    "NGN": (r"naira", r"ngn", r"₦"),
    "UGX": (r"ugandan?\s+shillings?", r"ugx", r"ush"),
    "TZS": (r"tanzanian?\s+shillings?", r"tzs", r"tsh"),
    "GHS": (r"cedis?", r"ghs", r"gh₵"),
    "RWF": (r"rwandan?\s+francs?", r"rwf"),
    "MWK": (r"malawian?\s+kwacha", r"mwk"),
    "BWP": (r"pula", r"bwp"),
    "ETB": (r"birr", r"etb"),
    "GBP": (r"pounds?(?:\s+sterling)?", r"sterling", r"gbp", r"£"),
    "EUR": (r"euros?", r"eur", r"€"),
    "CAD": (r"canadian\s+dollars?", r"cad"),
    "AUD": (r"australian\s+dollars?", r"aud"),
    "NAD": (r"namibian\s+dollars?", r"nad"),
    "MZN": (r"meticais?", r"mzn"),
}
_ASK_RE = {
    code: re.compile(r"(?<![A-Za-z])(?:" + "|".join(pats) + r")(?![A-Za-z])", re.IGNORECASE)
    for code, pats in _NAMES.items()
}


def currency_asked(text: str | None) -> str | None:
    """The ISO code of a currency the message names ("in rands", "how much in
    naira", "price in pounds") — None when it names none of ours."""
    t = text or ""
    if not t.strip():
        return None
    for code, rx in _ASK_RE.items():
        if rx.search(t):
            return code
    return None


_KEY = "fx:usd"
_STALE_KEY = "fx:usd:stale"
_mem: dict = {"at": 0.0, "rates": {}}


def _pick(raw: dict) -> dict[str, float]:
    rates = (raw or {}).get("rates") or {}
    out: dict[str, float] = {}
    for code in FX_CURRENCIES:
        try:
            v = float(rates.get(code) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            out[code] = round(v, 6)
    return out


async def fetch() -> dict[str, float]:
    """One fetch of today's USD rates; {} on any failure."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(FX_SOURCE, timeout=8.0)
        if not r.is_success:
            return {}
        data = r.json()
        if str(data.get("result") or "").lower() != "success":
            return {}
        return _pick(data)
    except Exception as exc:
        _log.info("fx fetch failed: %s", exc)
        return {}


async def rates(redis) -> dict[str, float]:
    """Today's USD rates, cached a day (in Redis, and in process for six
    hours); a stale copy from the last good fetch when the source is down;
    {} when nothing is known — the writer then converts nothing."""
    now = time.time()
    if _mem["rates"] and now - _mem["at"] < 6 * 3600:
        return dict(_mem["rates"])
    if redis is not None:
        try:
            raw = await redis.get(_KEY)
            if raw:
                got = json.loads(raw)
                if got:
                    _mem.update(at=now, rates=got)
                    return dict(got)
        except Exception:
            pass
    got = await fetch()
    if got:
        _mem.update(at=now, rates=got)
        if redis is not None:
            try:
                await redis.set(_KEY, json.dumps(got), ex=24 * 3600)
                await redis.set(_STALE_KEY, json.dumps(got), ex=7 * 24 * 3600)
            except Exception:
                pass
        return dict(got)
    if redis is not None:
        try:
            raw = await redis.get(_STALE_KEY)
            if raw:
                got = json.loads(raw)
                _mem.update(at=now, rates=got)
                return dict(got)
        except Exception:
            pass
    return {}


def convert_usd(usd: float, rate: float) -> float:
    """The figure the arithmetic gives, to the cent — never tidied."""
    return round(float(usd) * float(rate), 2)


def context_line(code: str, rate: float) -> str:
    """What the writer is told when the customer asked for their own money."""
    return (f"\n\n(They asked for prices in {code}. TODAY'S RATE: 1 USD = {rate:g} {code} "
            f"(fetched today from a public source). Convert from the USD price only — "
            f"the figure the arithmetic gives, e.g. $120 = {convert_usd(120, rate):,.2f} {code} "
            f"— and say it is today's rate; USD stays the currency of record. Never "
            "promise to 'confirm the rate' — this IS the rate.)")


def no_rate_line(code: str) -> str:
    return (f"\n\n(They asked for prices in {code} and no rate is available today: give the "
            "USD price and say it is charged in USD and converts at the day's rate when "
            "they pay. Never invent a rate, never promise to confirm one with the team.)")
