"""WE SELL CHURCH GOODS ONLY (owner, 2026-09-25).

Live, Messenger: "Kasoki 2 na saples" — the writer did not know "saples" (a
surplice), guessed "vikombe, divai, au maharagwe?" at the customer, took the
"Maharagwe" that came back as an order line and asked which packet. "Put
guardrails against selling things that are not church based — vestments,
communion accessories or church related. When that happens, decline politely
and stop for 12 hours."

The guard reads every real customer message before the writer does:

- an ask for goods we do not sell (beans, rice, phones, loans, land, jobs,
  livestock…) with nothing church-related in it is DECLINED in one warm
  line that says what we do sell, and the thread is PAUSED for twelve
  hours — every later message is silence (logged, the team flagged), until
  they ask for church goods, which lifts the pause: a person asking for a
  cassock is a customer again;
- when church business is already in play on the thread (a cassock being
  ordered) the FIRST such ask is declined by the writer inside the reply
  and the sale carries on — a second one pauses the thread;
- a message that mixes both ("kasoki 2 na maharagwe") is answered: the
  writer declines the beans and takes the cassocks;
- the verifier (review.domain_issues) holds any reply that treats such
  goods as ours — asks a quantity or a packet, prices them, or lists them in
  an order — so the writer's own guesses never sell them either.

Words that are also church goods never trigger it: bread (communion bread),
wine (altar wine), oil (anointing oil), water (a bottle we sell), candles,
cloth (kitambaa), a bag, a belt, a ring, a bell, a dress, a shirt, a book.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.core.config import settings

_log = logging.getLogger("neema.domain")

# ── the goods we do not sell: everyday, unambiguous categories ───────────────
# English and Swahili, whole words or phrases (longer phrases first). Never a
# word that also names a church good.
OFF_DOMAIN: dict[str, tuple[str, ...]] = {
    "food": ("cooking oil", "mafuta ya kupikia", "tea leaves", "majani ya chai", "sukuma wiki",
             "beans", "maharagwe", "maharage", "rice", "mchele", "wali", "maize", "mahindi",
             "ugali", "sugar", "sukari", "flour", "unga", "milk", "maziwa", "meat", "nyama",
             "fish", "samaki", "eggs", "mayai", "vegetables", "mboga", "sukuma", "tomatoes",
             "nyanya", "onions", "vitunguu", "potatoes", "viazi", "bananas", "ndizi", "kahawa",
             "groceries", "cereals", "nafaka", "lentils", "dengu", "githeri", "chapati",
             "chapatis", "mandazi", "cake", "cakes", "keki", "biscuits", "sweets", "pizza",
             "burgers"),
    "drink": ("soda", "sodas", "beer", "beers", "bia", "pombe", "whisky", "whiskey", "vodka",
              "spirits", "cigarettes", "sigara", "miraa", "khat", "bhang"),
    "electronics": ("mobile phone", "mobile phones", "data bundles", "sim card", "sim cards",
                    "power bank", "powerbank", "phone", "phones", "simu", "smartphone",
                    "smartphones", "iphone", "iphones", "samsung", "tecno", "infinix", "laptop",
                    "laptops", "computer", "computers", "television", "tv", "tvs", "charger",
                    "chargers", "chaja", "earphones", "headphones", "fridge", "fridges", "friji",
                    "cooker", "cookers", "microwave", "airtime", "bundles"),
    "vehicle": ("boda boda", "spare parts", "car", "cars", "gari", "magari", "motorbike",
                "motorbikes", "pikipiki", "bodaboda", "bicycle", "bicycles", "baiskeli", "tyres",
                "tires", "petrol", "diesel"),
    "money": ("mpesa float", "m-pesa float", "loan", "loans", "mkopo", "mikopo", "betting",
              "sportpesa", "betika", "1xbet", "aviator", "forex", "bitcoin", "crypto",
              "insurance", "bima", "sacco"),
    "property": ("real estate", "shamba", "ploti", "apartment", "apartments", "hostel",
                 "bedsitter"),
    "jobs": ("job vacancy", "job vacancies", "job opportunity", "job opportunities", "any job",
             "a job", "jobs", "nafasi ya kazi", "nafasi za kazi", "natafuta kazi", "nipe kazi",
             "kuomba kazi", "kazi yoyote", "kazi ipo", "employ me", "hire me", "vacancies",
             "vacancy", "employment", "hiring",
             "recruitment", "internship", "ajira", "kibarua"),
    "farm": ("animal feed", "fertilizer", "fertiliser", "mbolea", "seedlings", "miche", "cow",
             "cows", "ng'ombe", "ngombe", "goat", "goats", "mbuzi", "chicken", "chickens",
             "kuku", "chicks", "vifaranga", "pig", "pigs", "nguruwe", "pesticide", "pesticides"),
    "personal": ("cosmetics", "vipodozi", "makeup", "lipstick", "wig", "wigs", "weave", "weaves",
                 "jeans", "sneakers", "sandals", "shoes", "viatu", "socks", "underwear", "boxers",
                 "bras"),
    "medical": ("medicine", "medicines", "dawa", "tablets", "pills", "condoms", "viagra"),
    "other": ("sugar mummy", "sugar daddy", "gun", "guns", "bunduki", "porn", "sex", "girlfriend",
              "boyfriend", "dating", "hookup"),
}

# ── church words: anything here in a message makes it church business ────────
CHURCH_WORDS: tuple[str, ...] = (
    # the place and the people
    "church", "churches", "chapel", "cathedral", "parish", "diocese", "congregation", "ministry",
    "ministries", "choir", "choirs", "clergy", "priest", "priests", "pastor", "pastors", "bishop",
    "bishops", "archbishop", "reverend", "rev", "father", "fr", "deacon", "deacons", "evangelist",
    "apostle", "apostles", "prophet", "prophetess", "usher", "ushers", "altar", "sanctuary",
    "pulpit", "lectern", "pew", "pews", "vestry",
    "kanisa", "makanisa", "kwaya", "padre", "padri", "mchungaji", "wachungaji", "askofu",
    "maaskofu", "mtumishi", "watumishi", "mtume", "mitume", "nabii", "mwinjilisti", "shemasi",
    "mhudumu", "wahudumu", "madhabahu", "altare", "mimbari", "parokia", "jimbo",
    # the rites
    "mass", "service", "services", "worship", "prayer", "prayers", "sermon", "sacrament",
    "communion", "eucharist", "baptism", "ordination", "consecration", "confirmation",
    "wedding", "funeral", "easter", "christmas", "advent", "lent", "sunday",
    "ibada", "misa", "sala", "maombi", "hubiri", "mahubiri", "ushirika", "ekaristi", "ubatizo",
    "kipaimara", "harusi", "mazishi", "pasaka", "krismasi", "jumapili",
    # what we make and sell
    "vestment", "vestments", "cassock", "cassocks", "kasoki", "surplice", "surplices", "sapulisi",
    "saples", "saplis", "saplice", "alb", "albs", "stole", "stoles", "stola", "chasuble",
    "chasubles", "cope", "copes", "mitre", "miter", "dalmatic", "cincture", "cinctures", "sash",
    "collar", "collars", "kola", "shirt", "shirts", "shati", "gown", "gowns", "joho", "majoho",
    "gauni", "robe", "robes", "tunic", "skull cap", "skullcap", "zucchetto", "biretta", "kofia",
    "tallit", "prayer shawl", "shawl", "kippah", "uniform", "uniforms", "graduation", "academic",
    "doctorate", "vazi", "mavazi", "nguo",
    "chalice", "chalices", "paten", "patens", "ciborium", "pyx", "monstrance", "tabernacle",
    "host", "hosts", "wafer", "wafers", "bread", "mkate", "mikate", "tray", "trays", "sinia",
    "cup", "cups", "kikombe", "vikombe", "wine", "divai", "devai", "candle", "candles",
    "mshumaa", "mishumaa", "candlestick", "incense", "ubani", "thurible", "censer", "chetezo",
    "boat", "spoon", "bell", "bells", "kengele", "sprinkler", "aspergillum", "crozier", "crosier",
    "staff", "rod", "fimbo", "anointing", "upako", "oil", "mafuta", "horn", "pembe", "refiller",
    "bottle", "chupa", "offering", "sadaka", "basket", "baskets", "kikapu", "vikapu", "bible",
    "bibles", "biblia", "hymn", "hymnal", "devotional", "book", "books", "kitabu", "vitabu",
    "scripture", "rosary", "rozari", "crucifix", "cross", "crosses", "msalaba", "misalaba",
    "pendant", "ring", "rings", "pete", "banner", "banners", "cloth", "linen", "linens",
    "kitambaa", "vitambaa", "purificator", "corporal", "veil", "frontal", "kneeler", "bag",
    "belt", "mkanda", "dress", "dresses", "gift", "gifts", "zawadi",
)

_INTENT = (
    r"(?:do|does|did|can|could|would|will)\s+(?:you|u|we|they)\s+(?:also\s+)?(?:sell|have|stock|supply|deliver|make|get|provide|offer|do)",
    r"(?:i|we)\s*(?:'?m|'?re|am|are)?\s*(?:also\s+)?(?:want|need|wanted|needed|would\s+like|wanna|require|looking\s+for|in\s+need\s+of|interested\s+in)",
    r"(?:looking\s+for|in\s+need\s+of|price\s+of|prices\s+of|how\s+much\s+(?:is|are|for)|cost\s+of|any|selling|sell\s+me|send\s+me|bring\s+me|order|buy|purchase)",
    r"(?:nataka|natafuta|nahitaji|naomba|tunataka|tunahitaji|tunaomba|niletee|nitumie|tuletee|unauza|mnauza|wanauza|una|mna|kuna|je\s+mna|je\s+una|niuzie|tuuzie|nunua|kununua|bei\s+ya|bei\s+gani|ninataka|ninahitaji|nipe|tupe|ninunue)",
)
_INTENT_RE = re.compile(r"(?<![a-z'])(?:" + "|".join(_INTENT) + r")(?![a-z'])", re.IGNORECASE)

# Phrases in which an off-domain word is not goods at all: a phone NUMBER,
# a phone CALL, "on the phone".
_NOT_GOODS_RE = re.compile(
    r"(?:(?:phone|simu|mobile|cell|whatsapp|wasap|wasapp)\s*(?:number|numbers|no\.?|namba|nambari|yako|yangu|yetu|yenu|yake)"
    r"|(?:namba|nambari|number|no\.?)\s*(?:ya|of|yangu|yako|yetu|yenu)?\s*(?:simu|phone|whatsapp|wasap|wasapp)"
    r"|(?:on|by|over|via|through)\s+(?:the\s+|my\s+|your\s+|our\s+)?(?:phone|simu)"
    r"|kwa\s+simu|phone\s+call|(?:call|calls|called|calling)\s+(?:me|you|us|them)?\s*(?:on|by|via|at)?\s*(?:my|your|the|this|our)?\s*(?:phone|simu|number|namba)"
    r"|simu\s+ya\s+(?:mkononi|ofisi|kazi)\b"
    r"|(?:my|your|our|his|her|the)\s+(?:phone|simu|mobile|cell|whatsapp|wasap)\s+(?:is|ni|:)"
    r"|(?:phone|simu|mobile|cell|whatsapp|wasap)\s*[:\-]?\s*\+?\d[\d\s\-]{6,})",
    re.IGNORECASE)
_PHONE_NUMBER_RE = re.compile(r"\+?\d[\d\s\-]{7,}\d")
_PHONE_WORDS_RE = re.compile(r"(?<![a-z'])(?:phone|phones|simu|mobile|cell|whatsapp|wasap|wasapp)(?![a-z'])",
                             re.IGNORECASE)


def _wordish(term: str) -> str:
    return re.escape(term).replace(r"\ ", r"\s+")


def _lexicon(words) -> re.Pattern:
    terms = sorted(set(words), key=len, reverse=True)
    return re.compile(r"(?<![a-z'])(?:" + "|".join(_wordish(w) for w in terms) + r")(?![a-z'])",
                      re.IGNORECASE)


_OFF_RE = _lexicon(w for words in OFF_DOMAIN.values() for w in words)
_CHURCH_RE = _lexicon(CHURCH_WORDS)


def _clean(text: str) -> str:
    t = " ".join(str(text or "").split()).lower()
    t = _NOT_GOODS_RE.sub(" ", t)
    if _PHONE_NUMBER_RE.search(t):
        # a message that carries a number is giving one, not shopping for a phone
        t = _PHONE_WORDS_RE.sub(" ", t)
    return t


# ── a campaign's GIFT (owner, 2026-09-26) ────────────────────────────────────
# "Stop saying we do not make shoes, hatuuzi viatu. That shoe is a gift."
# Under a post that gifts an item we do not sell — a pair of shoes to one
# selected pastor — the gift's words are never goods to decline: gift_terms
# names them from the caption (with their translations and plurals), and every
# reader here takes `allow` to set them aside.
_GIFT_KIN: tuple[tuple[str, ...], ...] = (
    ("shoes", "viatu", "sneakers", "sandals"),
    ("phone", "phones", "simu", "smartphone", "smartphones", "mobile phone", "mobile phones"),
    ("laptop", "laptops", "computer", "computers"),
    ("bicycle", "bicycles", "baiskeli"),
    ("cow", "cows", "ng'ombe", "ngombe"), ("goat", "goats", "mbuzi"),
    ("chicken", "chickens", "kuku"), ("pig", "pigs", "nguruwe"),
    ("rice", "mchele", "wali"), ("maize", "mahindi"), ("sugar", "sukari"), ("flour", "unga"),
    ("milk", "maziwa"), ("beans", "maharagwe", "maharage"),
    ("cooking oil", "mafuta ya kupikia"), ("groceries", "cereals", "nafaka"),
)


def _stem(w: str) -> str:
    """shoes → shoe, sandals → sandal, dresses → dress, viatu → viatu."""
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def gift_terms(caption: str | None) -> tuple[str, ...]:
    """The goods on our do-not-sell list that a campaign's caption gives away,
    with their kin (shoe → shoes, viatu, sneakers, sandals): the words the
    guard and the reviewer must never read as goods to decline under it."""
    cap = " ".join(str(caption or "").split()).lower()
    if not cap:
        return ()
    stems = {_stem(w) for w in re.findall(r"[a-z']+", cap)}
    out: list[str] = []
    for words in OFF_DOMAIN.values():
        for t in words:
            if t not in out and all(_stem(p) in stems for p in t.split()):
                out.append(t)
    for kin in _GIFT_KIN:
        if any(k in out for k in kin):
            out.extend(k for k in kin if k not in out)
    return tuple(out)


def off_domain_in(text: str, allow=()) -> list[str]:
    """The goods we do not sell that `text` names, in their own words, in
    order, once each — a campaign's gift (`allow`) set aside."""
    skip = {" ".join(str(a or "").split()).lower() for a in (allow or ())}
    out: list[str] = []
    for m in _OFF_RE.finditer(_clean(text)):
        w = " ".join(m.group(0).split())
        if w not in out and w.lower() not in skip:
            out.append(w)
    return out


def church_in(text: str, names=()) -> list[str]:
    """The church words (and hub product names) `text` carries — read after
    the goods we do not sell are taken out, so "cooking oil" leaves no "oil"
    (the anointing oil) behind."""
    t = _OFF_RE.sub(" ", _clean(text))
    out = [" ".join(m.group(0).split()) for m in _CHURCH_RE.finditer(t)]
    for n in names or ():
        n = " ".join(str(n or "").split()).lower()
        if len(n) >= 3 and re.search(r"(?<![a-z'])" + _wordish(n) + r"(?![a-z'])", t):
            out.append(n)
    seen: list[str] = []
    for w in out:
        if w not in seen:
            seen.append(w)
    return seen


def asks(text: str) -> bool:
    """Does the message ASK for something — an intent frame ("do you sell",
    "nataka", "how much is"), or a message so short (four words) it is the
    ask itself ("Maharagwe", "beans please", "mchele kilo 5")?"""
    t = _clean(text)
    return bool(_INTENT_RE.search(t)) or len(t.split()) <= 4


def assess(text: str, names=(), allow=()) -> dict:
    """ONE message read: the goods we do not sell it names, the church words
    it carries, and whether it asks. `off_only` is the whole verdict: it asks
    for goods we do not sell and nothing church-related. A campaign's gift
    (`allow`) is never among the goods."""
    off = off_domain_in(text, allow)
    church = church_in(text, names)
    a = asks(text)
    return {"off": off, "church": church, "asks": a,
            "off_only": bool(off) and not church and a,
            "mixed": bool(off) and bool(church)}


def in_play(transcript: list | None, names=()) -> bool:
    """Is church business already on this thread — a cassock being ordered,
    a tray priced? Read from the last turns, theirs and ours."""
    from app.agent.review import transcript_text
    texts = " ".join(t for _r, t in transcript_text(transcript, limit=40))
    return bool(church_in(texts, names))


# ── what we say ──────────────────────────────────────────────────────────────

def _list(goods: list[str]) -> str:
    g = [x for x in goods if x][:3]
    if not g:
        return "that"
    return ", ".join(g[:-1]) + (" and " if len(g) > 1 else "") + g[-1]


_CATEGORY = {w: cat for cat, words in OFF_DOMAIN.items() for w in words}


def _category(term: str) -> str:
    t = " ".join(str(term or "").lower().split())
    if t in _CATEGORY:
        return _CATEGORY[t]
    for w in sorted(_CATEGORY, key=len, reverse=True):
        if re.search(r"(?<![a-z'])" + _wordish(w) + r"(?![a-z'])", t):
            return _CATEGORY[w]
    return ""


def category_of(goods: list[str]) -> str:
    cats = [_category(g) for g in goods or ()]
    for c in ("other", "jobs", "money"):
        if c in cats:
            return c
    return next((c for c in cats if c), "")


def _refusal(goods: list[str], swahili: bool) -> str:
    """The clause that fits: goods are not sold, loans not offered, jobs not
    open, the rest not something we can help with."""
    what = _list(goods)
    cat = category_of(goods)
    if cat == "jobs":
        return ("hatuna nafasi za kazi kwa sasa" if swahili
                else "we have no vacancies at the moment")
    if cat == "money":
        return (f"{what} hatutoi" if swahili else f"we don't offer {what}")
    if cat == "other":
        return ("hatuwezi kusaidia na hilo" if swahili else "we can't help with that")
    return (f"{what} hatuuzi" if swahili else f"we don't sell {what}")


def decline_line(goods: list[str], swahili: bool = False, public: bool = False) -> str:
    """The one polite line: what we do not sell (or offer), what we do."""
    no = _refusal(goods, swahili)
    if public:
        return (f"Samahani, {no} — sisi ni mavazi ya kanisa na vifaa vya ushirika tu 🙏"
                if swahili else
                f"Sorry, {no} — we make church vestments and communion ware only 🙏")
    if swahili:
        return (f"Asante kwa kutufikia 🙏 Samahani, {no} — Bethany House inatengeneza na "
                "kuuza mavazi ya kanisa (kasoki, sapulisi, majoho, kola) na vifaa vya ushirika "
                "(vikombe, sinia, kikombe cha Bwana, divai ya ushirika) tu. Ukihitaji chochote "
                "kati ya hivyo, tuko hapa kukuhudumia.")
    return (f"Thank you for reaching out 🙏 Sorry, {no} — Bethany House makes and "
            "supplies church vestments (cassocks, surplices, gowns, collars) and communion ware "
            "(chalices, trays, cups, altar wine) only. If you ever need any of those, we're "
            "here for you.")


def guard_note(goods: list[str]) -> str:
    """The writer's instruction when a message asks for such goods beside
    church business: decline in one line, sell on."""
    return (f"\n\n[NOT OUR GOODS — this message asks for {_list(goods)}, which we do NOT sell: "
            "we sell church vestments, communion ware and church supplies only. Decline it in "
            "ONE short warm line that says what we do sell; ask NOTHING about it (no quantity, "
            "no packet, no price); never add it to the order or a summary; then carry on with "
            "the church items they want.]")


_DECLINE_RE = re.compile(
    r"(?:\b(?:we|i)\s+(?:do\s+not|don'?t|do\s+not\s+currently|cannot|can'?t)\s+(?:sell|stock|carry|supply|offer|make|deal\s+in|provide|do)\b"
    r"|\bnot\s+(?:something|an?\s+item|a\s+product|goods|things?)\s+we\s+(?:sell|stock|carry|offer|make)\b"
    r"|\b(?:we\s+)?(?:only\s+)?(?:sell|make|supply|stock|deal\s+in)\s+(?:only\s+)?(?:church|clergy|christian|communion|vestments?)\b"
    r"|\b(?:church|clergy)\s+(?:goods|items|vestments|supplies|wear|products)\s+only\b"
    r"|\b(?:isn'?t|is\s+not|aren'?t|are\s+not|not)\s+(?:in\s+)?(?:our|the)\s+(?:line|business|range|catalogue|catalog)\b"
    r"|\bwe\s+(?:are|'re)\s+(?:a\s+)?(?:church|clergy|vestment)"
    r"|\bwe\s+(?:do\s+not|don'?t)\s+offer\b|\bno\s+vacanc(?:y|ies)\b|\bnot\s+hiring\b|\bcan'?t\s+help\s+with\s+that\b"
    r"|\bhatutoi\b|\bhatuna\s+nafasi\b|\bhatuwezi\s+kusaidia\b"
    r"|\bhatuuzi\b|\bhatuna\b|\bhatushughuliki\b|\bhaiuzwi\b|\bhazuzwi\b|\bhaipatikani\b"
    r"|\b(?:si|sio|siyo)\s+bidhaa\s+(?:zetu|tunazouza)\b|\btunauza\s+(?:tu\s+)?(?:mavazi|vifaa|bidhaa\s+za\s+kanisa)\b"
    r"|\bmavazi\s+ya\s+kanisa\b.{0,60}\btu\b|\bvifaa\s+vya\s+(?:ushirika|kanisa)\b.{0,40}\btu\b)",
    re.IGNORECASE | re.DOTALL)


def declines(text: str) -> bool:
    """Does the reply say plainly that we do not sell it?"""
    return bool(_DECLINE_RE.search(text or ""))


def treats_as_ours(text: str, allow=()) -> list[str]:
    """The goods we do not sell that a reply treats as ours — named without a
    plain decline beside them (asked about, priced, listed in an order). A
    campaign's gift (`allow`) is never among them."""
    goods = off_domain_in(text, allow)
    if not goods or declines(text):
        return []
    return goods


# ── the pause: twelve hours of silence, lifted by church business ────────────

def _pause_key(channel: str, key: str) -> str:
    return f"guard:pause:{channel}:{key}"


def _count_key(channel: str, key: str) -> str:
    return f"guard:asks:{channel}:{key}"


def pause_seconds() -> int:
    return int(getattr(settings, "offdomain_pause_hours", 12) or 12) * 3600


async def is_paused(redis, channel: str, key: str) -> str:
    """The reason the thread is paused, or ''."""
    if redis is None:
        return ""
    try:
        v = await redis.get(_pause_key(channel, key))
        return (v.decode() if isinstance(v, bytes) else str(v)) if v else ""
    except Exception:
        return ""


async def pause(redis, channel: str, key: str, goods: list[str]) -> None:
    if redis is None:
        return
    try:
        await redis.set(_pause_key(channel, key), _list(goods), ex=pause_seconds())
    except Exception:
        pass


async def lift(redis, channel: str, key: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(_pause_key(channel, key))
        await redis.delete(_count_key(channel, key))
    except Exception:
        pass


async def count_ask(redis, channel: str, key: str) -> int:
    """How many times this thread has asked for goods we do not sell in the
    pause window, this one included (1 without redis)."""
    if redis is None:
        return 1
    try:
        n = int(await redis.incr(_count_key(channel, key)))
        await redis.expire(_count_key(channel, key), pause_seconds())
        return n
    except Exception:
        return 1


# ── the tally: what the guard did today (health) ─────────────────────────────

def _day_key() -> str:
    return "guard:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def record(redis, outcome: str, channel: str = "") -> None:
    """declined / paused / silenced / lifted / noted, per UTC day (three days)."""
    if redis is None or outcome not in ("declined", "paused", "silenced", "lifted", "noted"):
        return
    try:
        key = _day_key()
        await redis.hincrby(key, outcome, 1)
        if channel:
            await redis.hincrby(key, f"{outcome}:{channel}", 1)
        await redis.expire(key, 3 * 24 * 3600)
    except Exception:
        pass


async def read_tally(redis) -> dict:
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(_day_key()) or {}
    except Exception:
        return {}
    out: dict = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else str(k)
        v = v.decode() if isinstance(v, bytes) else v
        try:
            out[k] = int(v)
        except (TypeError, ValueError):
            pass
    return out


# ── the turn ─────────────────────────────────────────────────────────────────

async def guard_turn(redis, *, channel: str, key: str, text: str, transcript: list | None,
                     public_comment: bool = False, swahili: bool = False,
                     names=(), allow=()) -> dict | None:
    """What the guard does with this message, before the writer sees it:

    None — nothing: an ordinary message, or the guard is off.
    {"action": "silence"} — the thread is paused; say nothing.
    {"action": "decline", "reply", "goods"} — decline in one line; the thread
        is now paused for twelve hours (the caller flags the team).
    {"action": "note", "note", "goods"} — the writer answers, told to decline
        the goods we do not sell and sell on.
    """
    if not getattr(settings, "church_goods_guard", True):
        return None
    a = assess(text, names, allow)
    paused = await is_paused(redis, channel, key)
    if paused:
        # Church goods lift the pause — and so does a campaign post's thread
        # (owner, 2026-09-26): one paused for "shoes" under the gift is a
        # guest again the moment they write about the gift.
        if (a["church"] or allow) and not a["off"]:
            await lift(redis, channel, key)
            await record(redis, "lifted", channel)
            _log.info("guard: pause lifted for %s/%s — they asked for church goods", channel, key)
            return None
        await record(redis, "silenced", channel)
        _log.info("guard: silence for %s/%s (paused: %s)", channel, key, paused)
        return {"action": "silence", "why": paused}
    if a["mixed"]:
        await record(redis, "noted", channel)
        return {"action": "note", "note": guard_note(a["off"]), "goods": a["off"]}
    if not a["off_only"]:
        return None
    n = await count_ask(redis, channel, key)
    if not public_comment and n <= 1 and in_play(transcript, names):
        await record(redis, "noted", channel)
        _log.info("guard: %s/%s asked for %s with church business in play — declined in the reply",
                  channel, key, a["off"])
        return {"action": "note", "note": guard_note(a["off"]), "goods": a["off"]}
    await pause(redis, channel, key, a["off"])
    await record(redis, "declined", channel)
    await record(redis, "paused", channel)
    _log.info("guard: %s/%s asked for %s — declined, paused %dh", channel, key, a["off"],
              pause_seconds() // 3600)
    return {"action": "decline", "goods": a["off"],
            "reply": decline_line(a["off"], swahili=swahili, public=public_comment)}


def flag_note(goods: list[str], public: bool = False) -> str:
    hours = pause_seconds() // 3600
    where = "under our post" if public else "here"
    return (f"NOT OUR GOODS — this person asked {where} for {_list(goods)}, which we do not "
            f"sell. Neema declined politely and is now silent on this thread for {hours} hours "
            "(owner's rule); she resumes the moment they ask for church goods. Step in here "
            "if you wish.")
