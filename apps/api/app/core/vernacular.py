"""The words our customers really use for the things we stock — Swahili,
Sheng, French, Spanish, Portuguese — read as the catalogue's English.

Why (voice note → sale, 2026-10-05). The catalogue search matches the hub's
English names and aliases. Customers — typing and, now, speaking — say
"kasoki", "stola", "shati ya kola", "mishumaa", "plateau de communion",
"bandeja dorada", "étole", "calice", "vasitos"… and every one of those came
back EMPTY from search_catalog (measured on the live catalogue snapshot), so
a customer who said exactly what they wanted was told "let me confirm" or
nothing at all. The agent itself passed such words straight to the search in
production ("stola", "toge", "aube", "bandeja comunhão", "vasitos plástico
comunión", "cálice comunhão" are all real zero-result searches from the
activity log).

Every entry below is DATA-DERIVED: it appears in real customer messages or
voice-note transcripts (counts from the production export, 2026-10-05, noted
beside the less obvious ones) and it maps only to a KIND we stock. Words
that name things we do NOT stock (suit, rosary, monstrance, altar linen,
tunic…) are deliberately absent — a customer asking for one must be told the
truth, never force-matched onto a neighbour.

`to_hub(text)` folds accents, lowercases, and rewrites phrases first (so
"plateau de pain" is a bread tray before "plateau" alone is read as a tray),
then single words. The search tokenises the result as it always has. The
owner's own one-item table (core/synonyms.canonical) runs before this.
"""
from __future__ import annotations

import re
import unicodedata


def fold(text: str | None) -> str:
    """Lowercase, accents stripped ("étole" → "etole", "comunhão" → "comunhao")."""
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


# Swahili connectors that join a thing to what it is for.
_OF = r"(?:ya|za|la|cha|vya|wa|kwa)"
_FOR = r"(?:ku(?:bebea|beba|wekea|weka|hifadhia|tilia))"
_CUPS = r"(?:vikombe|bikombe|vikomb|vikombo)"
_BREAD = r"(?:mkate|mikate|mkat|mikat)"
_TRAY_SW = r"(?:sinia|siniya|kisinia|lisinia|trei|trey|treyi|bakuli|chombo|kifaa|kile|icho|hicho|kibebeo)"

# (said, hub words). Phrases — longest, most specific first.
PHRASES: tuple[tuple[str, str], ...] = (
    # ── Swahili / Sheng ──────────────────────────────────────────────────
    # "hicho kisinia cha kubebea vikombe" / "siniya ya kubebea mikate" /
    # "cha kuwekea mikate yake" (typed + voice, 2026-09-29)
    (rf"{_TRAY_SW}\s+{_OF}\s+(?:{_FOR}\s+)?(?:hivyo\s+|hivo\s+)?{_CUPS}", "communion tray"),
    (rf"{_TRAY_SW}\s+{_OF}\s+(?:{_FOR}\s+)?{_BREAD}", "bread tray"),
    (rf"{_OF}\s+{_FOR}\s+(?:hivyo\s+|hivo\s+)?{_CUPS}", "communion tray"),
    (rf"{_OF}\s+{_FOR}\s+{_BREAD}", "bread tray"),
    (r"(?:sinia|siniya|trei|trey)\s+(?:ya|za)\s+(?:meza\s+ya\s+bwana|ushirika)", "communion tray"),
    (r"vyombo\s+vya\s+(?:ushirika|sakramenti|sakalamenti|sakalament)", "communion set"),
    # "kikombe kubwa ya mchungaji", "kikombe ya Rev" — the pastor's cup is a chalice
    (r"kikombe\s+(?:kikubwa|kubwa)(?:\s+(?:cha|ya)\s+(?:mchungaji|padri|rev\w*|askofu|onyesho))?"
     r"|kikombe\s+(?:cha|ya)\s+(?:mchungaji|padri|rev\w*|askofu|onyesho)", "chalice"),
    # "shati ya kola", "shati za kora" (typed 17 + voice 2026-09-30)
    (r"(?:ma)?shati\s+(?:ya|za|la|yenye)\s+(?:kola|kora|collar)", "collar shirt"),
    # "cheni ya msalaba", "msalaba wa kifua", "cheni na msalaba"
    (r"cheni\s+(?:ya|na|yenye)\s+msalaba|msalaba\s+(?:wa|na)\s+(?:kifua|cheni|kuvaa)", "pectoral cross"),
    (r"kofia\s+(?:ya|za)\s+(?:ki)?askofu", "mitre"),
    (r"pete\s+ya\s+(?:kidole|ki)?askofu|pete\s+ya\s+kidole", "ring"),
    (r"kitambaa\s+cha\s+(?:kiyahudi|maombi)", "prayer shawl"),
    (r"mafuta\s+ya\s+(?:upako|kupaka|kupakwa|kupakia)", "anointing oil"),
    # ── French ───────────────────────────────────────────────────────────
    # "plateau de pain", "plateaux pour le vin", "plateau de communion" (plateau 235)
    (r"plateaux?\s+(?:a|de|du|pour)\s+(?:le\s+|la\s+)?pain", "bread tray"),
    (r"plateaux?\s+(?:de|du|pour)\s+(?:le\s+)?vin", "communion tray"),
    (r"plateaux?\s+(?:de\s+|pour\s+)?(?:la\s+)?(?:sainte\s+)?(?:communion|cene)", "communion tray"),
    (r"gobelets?\s+(?:de\s+|pour\s+)?(?:la\s+)?(?:sainte\s+)?(?:communion|cene)", "communion cups"),
    # "chemise pastorale", "chemise col pastorale", "chemise clergyman" (chemise 48)
    (r"chemises?\s+(?:a\s+|avec\s+)?(?:col\s+)?(?:pastorale?s?|clerg\w*|pasteur|romain)", "clergy shirt"),
    (r"croix\s+pectorales?|cruz\s+(?:peitoral|pectoral)", "pectoral cross"),
    (r"col\s+romain", "collar"),
    (r"huile\s+(?:d\s*'?\s*onction|sainte)", "anointing oil"),
    (r"chale\s+de\s+priere", "prayer shawl"),
    (r"vin\s+de\s+messe", "altar wine"),
    # ── Spanish / Portuguese ─────────────────────────────────────────────
    # "bandeja de las copas", "bandeja para colocar los vasitos", "porta copas
    # y pan", "la del pan" (bandeja 164, copas 112, vasitos 25)
    (r"bandejas?\s+(?:de|para|del)\s+(?:colocar\s+)?(?:el\s+)?pan", "bread tray"),
    (r"bandejas?\s+(?:de|para)\s+(?:colocar\s+)?(?:las\s+|los\s+|os\s+|as\s+)?(?:copas|vasitos|copos)",
     "communion tray"),
    (r"porta\s*-?\s*copas", "communion tray"),
    (r"bandejas?\s+(?:de\s+|para\s+)?(?:la\s+|a\s+)?(?:santa\s+)?(?:comunion|comunhao|cena|ceia)",
     "communion tray"),
    (r"copa\s+grande", "chalice"),
    (r"(?:copas|vasitos|copos)\s+(?:de\s+|para\s+)?(?:la\s+|a\s+)?(?:santa\s+)?(?:comunion|comunhao)",
     "communion cups"),
    (r"capa\s+(?:episcopal|pluvial|para\s+(?:o\s+)?bispo|de\s+bispo|de\s+obispo)", "cope"),
    (r"santa\s+(?:cena|ceia)", "communion"),
    # ── transcription slips (voice notes, 2026-09-21 / 10-04) ────────────
    # "a train for a sacrament for the church", "that tree is just carrying
    # forty cups": tray, misheard. Only beside the sacrament / communion /
    # cups — a train or a tree alone is never a tray.
    (r"(?:trains?|trees?|treys?)\s+(?:for|of)\s+(?:a\s+|the\s+)?(?:holy\s+)?(?:sacrament|communion)",
     "communion tray"),
    (r"(?:trains?|trees?)\s+(?:that\s+|which\s+|is\s+)?(?:just\s+)?(?:carry|carries|carrying|holds?|holding)"
     r"\s+(?:\w+\s+)?cups", "communion tray"),
)

# (said, hub word). Whole words only, on folded text.
WORDS: tuple[tuple[str, str], ...] = (
    # ── Swahili / Sheng ──────────────────────────────────────────────────
    (r"kasoki|kasoke|kassoki|kasok|kasoku", "cassock"),          # kasoki 5 typed + the hint itself
    (r"kasula", "chasuble"),
    (r"stola|stolas|sitola|stoli|stoler", "stole"),               # stola 10
    (r"kola|kora", "collar"),                                     # kola 17, kora 5
    (r"shati|mashati|sati", "shirt"),                             # shati 34
    (r"mshipi|mishipi|mkanda|mikanda", "belt"),                   # mshipi 7
    (r"kofia", "cap"),                                            # kofia 23 (after the mitre phrase)
    (r"mshumaa|mishumaa", "candles"),
    (r"sinia|siniya|kisinia|lisinia|visinia", "tray"),
    (r"trei|trey|treyi", "tray"),                                 # trey 23, trei 7
    (r"vikombe|bikombe|vikomb|vikombo", "communion cups"),        # vikombe 67
    # the owner's own word for the small cups ("tot glasses"); a lone "tots"
    # (typed, and the agent's own word in replies) found nothing
    (r"tots?", "communion cups"),
    (r"kikombe|kikomb", "cup"),
    (r"mkate|mikate|mkat|mikat", "bread"),
    (r"ushirika", "communion"),
    (r"sacraments?", "communion"),                                # "a tray for the sacrament"
    (r"sakramenti|sakalamenti|sakalament", "communion"),
    (r"divai|mvinyo", "wine"),
    (r"mafuta", "anointing oil"),
    (r"pete", "ring"),
    (r"fimbo", "staff"),
    (r"gauni|magauni", "gown"),
    (r"majoho", "joho"),
    (r"misalaba", "msalaba"),
    (r"biblia|bibilia", "bible"),
    # ── French ───────────────────────────────────────────────────────────
    (r"chemises?", "shirt"),
    (r"toges?|thoges?|togas?", "gown"),                           # toge 62, toga 2
    (r"aubes?", "alb"),                                           # aube 18
    (r"etoles?", "stole"),                                        # étole 25
    (r"calices?", "chalice"),                                     # calice 19 (also pt cálice)
    (r"plateaux?", "tray"),
    (r"gobelets?", "cups"),                                       # gobelets 50
    (r"verres", "cups"),                                          # "les verres pour le vin de messe"
    (r"hosties?", "host"),
    (r"croix", "cross"),
    (r"vin", "wine"),
    (r"ceintures?", "belt"),
    (r"cordons?", "cincture"),
    (r"bagues?|anneaux?", "ring"),
    (r"paniers?", "basket"),
    (r"encensoirs?", "thurible"),
    (r"encens", "incense"),
    (r"cierges?|bougies?", "candles"),
    (r"cloches?|clochettes?", "bell"),
    (r"ciboires?", "ciborium"),
    (r"patenes?", "paten"),
    (r"col", "collar"),
    (r"dores?|doree?s?", "gold"),
    (r"argentes?|argentee?s?", "silver"),
    # ── Spanish / Portuguese ─────────────────────────────────────────────
    (r"bandejas?", "tray"),
    (r"caliz|calis", "chalice"),
    (r"copas?|copos?|vasitos?", "cups"),
    (r"vinos?|vinhos?", "wine"),
    (r"estolas?", "stole"),
    (r"sotanas?|batinas?", "cassock"),
    (r"alvas?", "alb"),
    (r"hostias?", "host"),
    (r"cruz", "cross"),
    (r"camisas?", "shirt"),
    (r"clergyman", "clergy shirt"),
    (r"casullas?|casulas?", "chasuble"),
    (r"capas?", "cope"),
    (r"anillos?|aneis|anel", "ring"),
    (r"mitras?", "mitre"),
    (r"baculos?", "staff"),
    (r"incienso|incenso", "incense"),
    (r"incensarios?|turibulos?", "thurible"),
    (r"velas?", "candles"),
    (r"campanas?", "bell"),
    (r"cestas?|canastas?", "basket"),
    (r"comunion|comunhao", "communion"),
    (r"dorad[oa]s?|dourad[oa]s?|ouro|oro", "gold"),
    (r"platead[oa]s?|pratead[oa]s?|prata|plata", "silver"),
    (r"aluminio", "aluminium"),
    (r"plasticos?", "plastic"),
    (r"vidrio|vidro", "glass"),
)

_PHRASES = tuple((re.compile(rf"\b(?:{p})\b"), hub) for p, hub in PHRASES)
_WORDS = tuple((re.compile(rf"\b(?:{p})\b"), hub) for p, hub in WORDS)


def to_hub(text: str | None) -> str:
    """The text folded and rewritten into the catalogue's words.

    "nataka kasoki na stola"        -> "nataka cassock na stole"
    "siniya ya kubebea mikate"      -> "bread tray"
    "plateau de communion"          -> "communion tray"
    "bandeja dorada"                -> "tray gold"
    "suti ya kanisa"                -> "suti ya kanisa" (we sell no suits: untouched)
    """
    out = fold(text)
    for pat, hub in _PHRASES:
        out = pat.sub(hub, out)
    for pat, hub in _WORDS:
        out = pat.sub(hub, out)
    return out


# The Swahili/Sheng words worth teaching the transcriber (services/
# stt_vocabulary): how customers SAY our goods, spelled the way they write
# them. Every one maps to a stocked kind above (tested).
SPOKEN_SWAHILI: tuple[str, ...] = (
    "kasoki", "kanzu", "joho", "stola", "shati ya kola", "mshipi", "kofia",
    "msalaba", "mishumaa", "sinia", "trei", "kikombe", "vikombe vya ushirika",
    "mkate wa ushirika", "meza ya Bwana", "divai", "mafuta ya upako", "pete",
    "fimbo", "ubani", "chetezo", "kengele",
)
SPOKEN_FRENCH: tuple[str, ...] = (
    "soutane", "chemise pastorale", "toge", "aube", "étole", "calice",
    "plateau de communion", "gobelets", "hosties",
)
