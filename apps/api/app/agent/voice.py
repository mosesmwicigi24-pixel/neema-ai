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
_KES_TAIL = re.compile(r"(KES\s?\d[\d,]*(?:\.\d+)?)\s*(?:KES|Kenyan?\s+shillings?|shillings?|shilingi)\b", re.I)

# The butler's openers — never how the owner would start a reply. "Of course"
# and "Thank you" are a person's words and stay.
_BUTLER = re.compile(
    r"^\s*(?:very\s+well|certainly|absolutely|definitely|sure(?:\s+thing)?|"
    r"great\s+question|good\s+question|excellent\s+question|"
    r"vema|hakika|bila\s+shaka)\s*[.!,;:—–-]*\s*",           # and the Swahili butler
    re.I,
)


# Does the customer's own message read as Swahili? Whole words only, and a
# short list of everyday shop words — the point is to pick the Swahili canned
# line for "Bei gani?" or "Nataka hii", never to guess from a name or a flag.
# Weak connectives ("na", "ya", "ni") are left out: they are too short to mean
# anything on their own — and "je", the question particle, is also the French
# "I": two of them made "je vais en parler… je reviens" read as Swahili.
_SW_WORDS = frozenset("""
    bei gani ngapi pesa shilingi nataka ninataka nahitaji ninahitaji naomba ninaomba
    nipe nitumie tuma tuambie niambie tafadhali habari asante karibu sana
    unauza mnauza unayo mnayo mnaweza unaweza kuagiza agiza oda hii hiyo hizi hizo
    ile kiasi ndiyo ndio hapana sawa leo kesho wapi niko nipo nataka bado
    divai mkate vifaa meza bwana kanisa mchungaji askofu kasisi kasoki joho stola
    kikombe vikombe sinia msalaba rangi vipimo ukubwa saizi bidhaa nunua kununua
    inauzwa zinauzwa hapa huko kwako yako zako wangu yangu mimi wewe nyinyi sisi
""".split())
_EN_WORDS = frozenset("""
    the is are how much price want need this one please have you do it for me
    my your what which where can i would like get buy order send us cost
""".split())
_SW_ASK_RE = re.compile(r"\b(?:bei(?:\s+gani)?|(?:pesa\s+|shilingi\s+|ni\s+)?ngapi)\b", re.I)


def swahili_price_ask(text: str | None) -> bool:
    """A Swahili price ask inside any sentence — "na ni pesa ngapi?", "bei
    gani?" — whatever the English around it (owner, 2026-10-02: "Are they
    consecrated? na ni pesa ngapi?" is a Kenyan asking the price)."""
    return bool(_SW_ASK_RE.search(text or ""))


def looks_swahili(text: str | None) -> bool:
    """True when THEIR words are Swahili — "Bei gani?", "Nataka hii cassock",
    "Divai na mkate" — and False for English, a lone "Karibu Zambia", or a
    message you cannot place. A bare Swahili price ask counts on its own."""
    toks = re.findall(r"[a-z']+", (text or "").lower())
    if not toks:
        return False
    sw = sum(1 for t in toks if t in _SW_WORDS)
    en = sum(1 for t in toks if t in _EN_WORDS)
    if _SW_ASK_RE.search(text or "") and sw > en:
        return True
    return sw >= 2 and sw > en


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


# A reply that is only a note to self — "_(No further reply is needed.)_",
# "(no response)", "[silence]" — is the model describing its silence instead of
# keeping it. Sent as written it would reach the customer as a message (the
# first real-model pass of the intent cases, 2026-11-14, produced exactly
# that after a second appeal). It is nothing: the turn sends nothing.
_STAGE_BRACKET_RE = re.compile(r"^[\(\[][^\)\]\n]{0,200}[\)\]][.!]?$")
_STAGE_WORDS_RE = re.compile(
    r"^(?:no\s+(?:further\s+|more\s+)?(?:reply|response|message|answer)\s*(?:is\s+|was\s+)?"
    r"(?:needed|necessary|required|sent)?|silence|nothing\s+(?:more\s+)?to\s+(?:send|add|say)|"
    r"(?:left\s+)?unanswered|empty\s+(?:reply|message))[.!]?$",
    re.IGNORECASE)


def stage_direction(text: str | None) -> bool:
    """True when the whole reply is a bracketed aside or a bare statement that
    no reply is being sent — never a real sentence to the customer. A reply
    that merely contains brackets ("the set (cassock and stole) is $210") is
    not one."""
    t = re.sub(r"[_*`~]", "", str(text or "")).strip()
    if not t:
        return False
    if _STAGE_BRACKET_RE.match(t):
        inner = t.strip("()[].! ").strip()
        return bool(_STAGE_WORDS_RE.match(inner)) or bool(
            re.search(r"(?i)\b(no|without)\b.{0,30}\b(reply|response|message|answer)\b|\bsilen", inner))
    return bool(_STAGE_WORDS_RE.match(t))


def plain_public_voice(text: str | None) -> str:
    """Everything above, in order, for Neema's own public text. Idempotent."""
    return drop_butler_opener(plain_money(strip_markdown(text))).strip()


# ── A NAME IS NOT A PREFIX (owner, 2026-11-20) ───────────────────────────────
# "Neema was repeating the name of a person after every message sent, e.g.
# Moses, … then Moses, …". The instruction ("use their name the way a person
# does … not in every line") was only an instruction. This is the check: a
# reply that OPENS by addressing the customer by name, when one of our last
# replies in the same chat already used the name, loses that opening. The
# name in a greeting ("Hello Moses"), at a thank-you or at the close is left
# alone, and so is the first use.
_NAME_TITLES = ("pastor", "pst", "ps", "bishop", "archbishop", "rev", "reverend", "apostle",
                "prophet", "prophetess", "elder", "deacon", "deaconess", "dr", "fr", "father",
                "sister", "brother", "mama", "mum", "mr", "mrs", "ms", "madam", "sir", "evangelist")


def _name_words(name: str | None) -> list[str]:
    out = []
    for w in re.findall(r"[^\W\d_]+", name or "", flags=re.UNICODE):
        if len(w) >= 3 and w.lower() not in _NAME_TITLES and w.lower() not in out:
            out.append(w.lower())
    return out


def drop_repeated_name(reply: str | None, name: str | None, earlier: list[str] | None,
                       window: int = 2) -> str:
    """`reply` without its opening "Moses, " when one of our last `window`
    replies in this chat already used the customer's name. Unchanged
    otherwise — and always unchanged when nothing would be left."""
    text = reply or ""
    words = _name_words(name)
    if not text.strip() or not words:
        return text
    alt = "|".join(re.escape(w) for w in words)
    titles = "|".join(_NAME_TITLES)
    opening = re.compile(
        rf"^\s*(?:(?:{titles})\.?\s+)?(?:{alt})(?:\s+(?:{alt}))?\s*(?:[,:;!]|\s[—–-])\s*",
        re.IGNORECASE)
    m = opening.match(text)
    if not m:
        return text
    used = re.compile(rf"\b(?:{alt})\b", re.IGNORECASE)
    recent = [e for e in (earlier or []) if isinstance(e, str) and e.strip()][-window:]
    if not any(used.search(e) for e in recent):
        return text
    rest = text[m.end():]
    if len(rest.strip()) < 3:
        return text
    return rest[0].upper() + rest[1:]


# ── THE OFFICIAL NUMBERS, WRITTEN BY CODE (audit C6, 2026-11-20) ─────────────
_NUMBERS_LINE_RE = re.compile(
    r"[^.!?\n]*(?:official numbers?|namba (?:zetu )?rasmi)[^.!?\n]*[.!?]?[ \t]*"
    r"(?:[^.!?\n]*(?:any other number|namba nyingine)[^.!?\n]*[.!?]?)?",
    re.IGNORECASE)


def official_numbers_line(*, swahili: bool = False) -> str:
    """The first-greeting line, built from the configured lines. "" when none
    is configured."""
    nums = [n for n, _tail in _official()]
    if not nums:
        return ""
    if swahili:
        return f"Namba zetu rasmi ni {' na '.join(nums)}. Namba nyingine yoyote si ya Bethany House."
    return f"Our official numbers are {' and '.join(nums)}. Any other number is not from Bethany House."


# ── BOTH NUMBERS ARE OURS (owner, 2026-11-28) ────────────────────────────────
# "Our official numbers are 2 … +254727891989 and +254785490805. Do not say
# when you give one number that we do not have another number. This should
# not be ignored." A customer asked about one of our lines and was told the
# other was the only one. The prompt says both; this is the check.
_ONLY_ONE_RE = re.compile(
    r"\b(?:only|sole|single)\s+(?:official\s+|whatsapp\s+|phone\s+|contact\s+)?(?:number|line|contact)\b"
    r"|\bonly\s+(?:have\s+|use\s+)?(?:one|1)\s+(?:official\s+|whatsapp\s+|phone\s+)?(?:number|line)\b"
    r"|\b(?:no|not\s+have|don'?t\s+have|do\s+not\s+have|haven'?t|without)\s+(?:any\s+|an\s+)?"
    r"(?:other|another|second)\s+(?:official\s+|whatsapp\s+|phone\s+)?(?:number|line)\b"
    r"|\b(?:one|1)\s+(?:official\s+)?(?:number|line)\s+only\b"
    r"|\bhatuna\s+namba\s+nyingine\b|\bnamba\s+(?:yetu\s+)?(?:rasmi\s+)?pekee\b|\bnamba\s+moja\s+tu\b"
    r"|\b(?:un\s+)?seul\s+num[ée]ro\b|\bpas\s+d'autre\s+num[ée]ro\b",
    re.IGNORECASE)
_NOT_OURS_RE = re.compile(
    r"\b(?:not|isn'?t|is\s+not|never|si|sio|siyo|n'est\s+pas)\b[^.!?\n]{0,50}"
    r"\b(?:ours|our\s+(?:number|line)|from\s+bethany|bethany\s+house'?s?|yetu|ya\s+bethany|le\s+n[oô]tre)\b",
    re.IGNORECASE)
_ANY_OTHER_RE = re.compile(r"\bany\s+other\s+number\b|\bnamba\s+nyingine\s+yoyote\b", re.IGNORECASE)
_PAYING_RE = re.compile(
    r"\b(?:pay(?:ment|ing|s)?|paid|m-?pesa|airtel\s+money|till|paybill|lipa|send\s+(?:the\s+)?money|"
    r"deposit|transfer|malipo|tuma\s+pesa)\b", re.IGNORECASE)


def _official() -> list[tuple[str, str]]:
    """Our official numbers as (written form, last nine digits), each once.
    From `official_numbers`; the hand-off settings only stand in when that is
    blank. The same line written two ways, or set twice, is one number."""
    from app.core.config import settings
    listed = [p for p in str(getattr(settings, "official_numbers", "") or "").split(",") if p.strip()]
    if not listed:
        listed = [getattr(settings, "whatsapp_handoff_number", ""), getattr(settings, "whatsapp_handoff_alt", "")]
    out = []
    for n in listed:
        n = (n or "").strip()
        tail = re.sub(r"\D", "", n)[-9:]
        if n and len(tail) == 9 and all(tail != t for _n, t in out):
            out.append((n, tail))
    return out


def both_official_numbers(reply: str | None, *, swahili: bool = False) -> str:
    """`reply` made true about our numbers: we have TWO, and both are ours.

      * a sentence that says we have only one number, or no other number, is
        removed — and so is one that says one of OUR numbers is not ours;
      * "any other number is not from Bethany House" is only ever said beside
        BOTH numbers;
      * when one of our numbers is given as how to reach us, the other is
        given with it. (A payment instruction names the one line that takes
        that payment — it is left as written.)

    Unchanged when only one line is configured, or the reply says nothing
    about our numbers."""
    text = reply or ""
    nums = _official()
    if len(nums) < 2 or not text.strip():
        return text

    def has(t: str) -> set:
        d = re.sub(r"\D", "", t)
        return {tail for _n, tail in nums if tail in d}

    kept, fixed = [], False
    for block in re.split(r"(\n+)", text):
        if not block.strip():
            kept.append(block)
            continue
        parts = []
        for part in re.split(r"(?<=[.!?…])\s+", block):
            wrong = bool(_ONLY_ONE_RE.search(part)) or (bool(has(part)) and bool(_NOT_OURS_RE.search(part))
                                                         and not _ANY_OTHER_RE.search(part))
            if wrong:
                fixed = True
                continue
            parts.append(part)
        kept.append(" ".join(parts))
    out = "".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    present = has(out)
    line = official_numbers_line(swahili=swahili)
    if _ANY_OTHER_RE.search(out) and len(present) < 2:
        # "any other number is not ours" beside one number disowns our second line
        out = _NUMBERS_LINE_RE.sub("", out)
        out = "\n".join(p for p in (re.sub(r"[^.!?\n]*" + _ANY_OTHER_RE.pattern + r"[^.!?\n]*[.!?]?", "",
                                           ln, flags=re.IGNORECASE).strip() for ln in out.split("\n")))
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return (out + "\n\n" + line).strip() if line else out
    if fixed and len(present) < 2:
        return (out + ("\n\n" if out else "") + line).strip() if line else out
    if len(present) == 1 and not _PAYING_RE.search(out):
        other = next(n for n, tail in nums if tail not in present)
        tail_line = (f"Namba yetu nyingine rasmi ni {other}." if swahili
                     else f"Our other official number is {other}.")
        return out.rstrip() + " " + tail_line
    return out


def strip_numbers_line(reply: str | None, *, every_mention: bool = False) -> str:
    """`reply` without any official-numbers line the model wrote itself.
    `every_mention` (the first reply, where the code-written line follows)
    also drops a sentence that merely carries one of our numbers — "You can
    reach us on +254… or +254…" beside the official line said them twice
    (model run of 2026-11-23)."""
    out = _NUMBERS_LINE_RE.sub("", reply or "").strip()
    if not every_mention or not out:
        return out
    tails = [tail for _n, tail in _official()]
    if not tails:
        return out
    kept = []
    for part in re.split(r"(?<=[.!?…])\s+|\n+", out):
        if any(t in re.sub(r"\D", "", part) for t in tails):
            continue
        kept.append(part)
    return " ".join(k for k in kept if k.strip()).strip()


# ── a private message is only spoken of when one went (audit H5, X21) ────────
_INBOX_WORDS = (r"(?:inbox|dms?|pm|private message|direct message|privately|messenger|"
                r"ujumbe(?: wa faragha| binafsi)?|message priv[ée]e?|mp)")
_INBOX_CLAIM_RE = re.compile(
    r"\b(?:i|we)(?:'ve|\s+have|'ll|\s+will|\s+am|\s+are|'m|'re)?\s+(?:also\s+|just\s+|already\s+)?"
    r"(?:sent|sending|send|dropped|shared|sharing|share|inboxed|messaged|message|dm'?e?d)\b"
    r"[^.?!\n]{0,80}\b" + _INBOX_WORDS + r"\b"
    r"|\bcheck your (?:inbox|dms?|messages|messenger)\b"
    r"|\b(?:i|we)(?:'ve|\s+have)\s+(?:inboxed|dm'?e?d|messaged)\s+you\b"
    r"|\b(?:nimekutumia|tumekutumia|nitakutumia|tutakutumia)\b[^.?!\n]{0,60}\b" + _INBOX_WORDS + r"\b"
    r"|\bangalia (?:inbox|ujumbe|dm)\b"
    r"|\b(?:je vous ai|nous vous avons|je viens de vous)\s+envoy[ée]\b[^.?!\n]{0,60}\b" + _INBOX_WORDS + r"\b",
    re.IGNORECASE)
_PHOTO_WORD_RE = re.compile(r"\b(?:photos?|pictures?|pics?|images?|picha|catalogue|catalog)\b", re.IGNORECASE)
_SENT_LINE = {
    ("en", True): "I've sent you a private message with the link.",
    ("en", False): "I've sent you a private message.",
    ("sw", True): "Nimekutumia ujumbe wa faragha wenye kiungo.",
    ("sw", False): "Nimekutumia ujumbe wa faragha.",
}


def honest_inbox_claims(text: str, *, dm_sent: bool, link_sent: bool = False,
                        swahili: bool = False) -> str:
    """A public reply may speak of a private message only when one went.

    The reply is written before the private message is attempted, and it may
    not go at all (an opt-out, a campaign post, a refused send). A sentence
    that says one was sent is dropped when none was; a sentence that says
    PHOTOS were sent there — the private message carries words and at most
    one link, never photos — becomes the plain true line. Everything else is
    left exactly as written."""
    if not (text or "").strip() or not _INBOX_CLAIM_RE.search(text):
        return text
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())
    kept: list[str] = []
    for part in parts:
        if not _INBOX_CLAIM_RE.search(part):
            kept.append(part)
            continue
        if not dm_sent:
            continue
        if _PHOTO_WORD_RE.search(part):
            line = _SENT_LINE[("sw" if swahili else "en", bool(link_sent))]
            if line not in kept:
                kept.append(line)
            continue
        kept.append(part)
    return " ".join(k for k in kept if k.strip()).strip()
