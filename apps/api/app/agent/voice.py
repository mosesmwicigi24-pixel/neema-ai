"""The public voice, made plain and human at the seam.

Owner, 2026-09-15: "make your language human and not AI or bot or
auto-generic language." Three things a person typing on a phone never does
kept turning up in Facebook replies: markdown that Facebook shows raw
(`**$450 USD**`), a currency word after a currency sign ("$450 USD"), and a
butler's opener ("Very well. The Round Collar Shirt…"). The prompt now forbids
all three; this strips whatever slips through, at the seams where Neema's own
text leaves for a public comment, a comment DM, or a Messenger/Instagram/
TikTok thread — never WhatsApp, where a single *bold* is the house style, and
never a human colleague's words (the inbox goes through its own sender).
"""
from __future__ import annotations

import re

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_UNDER = re.compile(r"__(.+?)__", re.S)
_MD_ITALIC = re.compile(r"(?<!\w)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\w)")
_MD_CODE = re.compile(r"`([^`\n]*)`")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)

# "$450 USD", "USD $450", "$450 US dollars", "KES 12,000 Kenyan Shillings"
_USD_TAIL = re.compile(r"(\$\s?\d[\d,]*(?:\.\d+)?)\s*(?:USD|US\s*dollars?|dollars?)\b", re.I)
_USD_HEAD = re.compile(r"\bUSD\s*\$", re.I)
_KES_TAIL = re.compile(r"(KES\s?\d[\d,]*(?:\.\d+)?)\s*(?:KES|Kenyan?\s+shillings?|shillings?)\b", re.I)

# The butler's openers — never how the owner would start a reply. "Of course"
# and "Thank you" are a person's words and stay.
_BUTLER = re.compile(
    r"^\s*(?:very\s+well|certainly|absolutely|definitely|sure(?:\s+thing)?|"
    r"great\s+question|good\s+question|excellent\s+question)\s*[.!,;:—–-]*\s*",
    re.I,
)


def strip_markdown(text: str | None) -> str:
    """Markdown marks removed, the words kept — for channels that show the
    asterisks raw (Facebook comments, Messenger, Instagram, TikTok)."""
    t = text or ""
    t = _MD_BOLD.sub(r"\1", t)
    t = _MD_UNDER.sub(r"\1", t)
    t = _MD_ITALIC.sub(r"\1", t)
    t = _MD_CODE.sub(r"\1", t)
    t = _MD_HEADING.sub("", t)
    return t


def plain_money(text: str | None) -> str:
    """'$450 USD' → '$450'; 'USD $450' → '$450'; 'KES 500 shillings' → 'KES 500'."""
    t = text or ""
    t = _USD_HEAD.sub("$", t)
    t = _USD_TAIL.sub(r"\1", t)
    t = _KES_TAIL.sub(r"\1", t)
    return t


def drop_butler_opener(text: str | None) -> str:
    """'Very well. The Round Collar Shirt is ZMW 900.' → 'The Round Collar Shirt
    is ZMW 900.' Only the opener goes; the first letter that remains is
    capitalised so the sentence still starts like one."""
    t = text or ""
    stripped = _BUTLER.sub("", t, count=1)
    if stripped == t or not stripped.strip():
        return t if not stripped.strip() and stripped != t else stripped
    lead = stripped.lstrip()
    return lead[0].upper() + lead[1:]


def plain_public_voice(text: str | None) -> str:
    """Everything above, in order, for Neema's own public text. Idempotent."""
    return drop_butler_opener(plain_money(strip_markdown(text))).strip()
