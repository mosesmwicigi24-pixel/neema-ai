"""One pricing rule for every surface — WhatsApp, Messenger, Facebook, Instagram
and the website all quote a product the same way.

The business rule:
  1. Kenya → KES (our native prices).
  2. Everyone else → USD, UNLESS the hub prices the product in the customer's own
     currency (then use that exact local price — "currencies added on products").
  3. Fallback for a country outside Kenya whose currency we know a rate for:
     USD = KES / usd_kes_rate, then local = USD × (local units per 1 USD).
  4. Anything we still can't place → USD.

A real hub price ALWAYS wins over a conversion (step 2 before step 3). The
USD→local rates below are approximate and only used as a fallback; tune them live
via the FX_USD_RATES env (JSON: {"UGX": 3800, "ZMW": 27}) — no deploy, and they
never override a real hub price.
"""
from app.core.config import settings

# Local-currency units per 1 USD. Approximate fallbacks only — the hub's own
# per-currency prices take precedence whenever present. Currencies we're unsure
# of (very volatile / thin markets) are deliberately omitted so they safely quote
# USD rather than a wrong local number; add them via FX_USD_RATES when confirmed.
_DEFAULT_USD_RATES: dict[str, float] = {
    "UGX": 3800, "TZS": 2550, "ZMW": 27, "ZAR": 18, "NGN": 1600,
    "GHS": 15, "RWF": 1400, "MWK": 1750, "ETB": 125, "XAF": 600, "XOF": 600,
    "BWP": 13.5, "NAD": 18, "GBP": 0.79, "EUR": 0.92, "CAD": 1.37, "AUD": 1.52,
}


def _usd_rates() -> dict[str, float]:
    """Default rates with the FX_USD_RATES env overrides merged over the top."""
    rates = dict(_DEFAULT_USD_RATES)
    raw = (getattr(settings, "fx_usd_rates", "") or "").strip()
    if raw:
        try:
            import json
            for k, v in (json.loads(raw) or {}).items():
                fv = float(v)
                if fv > 0:
                    rates[str(k).upper()] = fv
        except Exception:
            pass
    return rates


def usd_rate_for(ccy: str | None) -> float | None:
    """USD→local rate (local units per 1 USD) for a currency, or None if unknown."""
    return _usd_rates().get((ccy or "").upper())


def _money(v):
    """Whole units for anything ≥ 1 (KES 12,000 · ZMW 1,260 · $130); cents below a
    unit so a small item never shows as 0 (a $0.30 cup, not $0)."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return round(v) if v >= 1 else max(round(v, 2), 0.01)


def resolve_price(prices: dict | None, ccy: str | None, *, kes_rate: int | None = None):
    """(amount, currency) to quote a customer whose money is `ccy`, from the hub's
    multi-currency price map. Implements the business rule above.

    `prices` is {CODE: amount} (e.g. {"KES": 12000, "USD": 95}). `kes_rate` is
    KES per 1 USD (defaults to settings.usd_kes_rate)."""
    prices = prices or {}
    ccy = (ccy or "USD").upper()
    rate = kes_rate or settings.usd_kes_rate or 100

    # 1) Kenya → KES (derive from USD only if the hub has no KES price).
    if ccy == "KES":
        kes = prices.get("KES") or (prices.get("USD") and prices["USD"] * rate)
        return _money(kes), "KES"

    # 2) Their own currency, priced by the hub → the exact local price wins.
    if prices.get(ccy):
        return _money(prices[ccy]), ccy

    # USD base: real hub USD, else KES / rate.
    usd = prices.get("USD")
    if usd is None and prices.get("KES") is not None:
        try:
            usd = prices["KES"] / rate
        except (TypeError, ValueError, ZeroDivisionError):
            usd = None

    # 3) Fallback: convert USD → their local currency when we know a rate.
    if usd is not None and ccy != "USD":
        r = usd_rate_for(ccy)
        if r:
            return _money(usd * r), ccy

    # 4) Otherwise USD.
    return _money(usd), "USD"
