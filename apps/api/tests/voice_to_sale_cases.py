"""The voice-note → sale evaluation set (2026-10-05).

Each case is a REAL voice note or typed ask from production, PARAPHRASED and
anonymised (no names, numbers or places that identify anyone), in the
language it was spoken: English, Swahili, Sheng, French, Spanish /
Portuguese, mixed — single and multi-item, with quantities, colours and
sizes, and the transcription slips the engine really produced ("a train for
the sacrament", "that tree carries forty cups", "thoughts" for tots).

For every item the customer named there are up to three ways the catalogue
can be searched:

  said   — the customer's own words for the item
  en     — the English the translator would give
  query  — what the agent plausibly passes to search_catalog

and `expect` — a regular expression over hub product NAMES; the item is
found when at least one returned row's name matches it. Cases under
NOT_STOCKED name things Bethany House does not sell: the search must never
offer a confident (non-partial) row for them.

The catalogue is the live snapshot of 2026-10-05
(tests/fixtures/catalog_snapshot_2026_10_05.json).
"""

TRAYS = r"^(Wooden tray|Small Wooden tray|Aluminium Tray|Silver Communion Tray|Golden Communion Tray|Aluminium 4-Stack|Double Stacked Silver Tray Set)"
BREAD_TRAYS = r"(Bread Tray|bread tray|Bread container)"
SMALL_CUPS = r"^(Plastic Communion Cups|Pre-Packed Communion Cups|Silver Communion Cups|Glass Cups)$"
CHALICES = r"Chalice"
CASSOCKS = r"Cassock"
GOWNS = r"(Preaching Gown|Ordination Gown|Canon Gown)"
SHIRTS = r"(Shirt)"
COLLAR_SHIRTS = r"(Collar Shirt|Collar Clergy Shirt)"
STOLES = r"(Stole)"
CROSS = r"(Pectoral Cross|Episcopal Cross)"
TALLIT = r"(Tallit|Prayer Shawl)"
WINE = r"(Altar Wine|Devai|COMMUNION WINE)"
BREAD = r"(Wafer|Communion Hosts|Holy Communion Bread|^Host$)"
RINGS = r"(Ring)"

# (case id, language, transcript, [(said, en, query, expect), …])
CASES: list[tuple] = [
    # ── English ──────────────────────────────────────────────────────────
    ("en-tray-cups-chalice", "en",
     "Hi there, I need to buy a communion tray, several cups and a chalice cup.",
     [("communion tray", "communion tray", "communion tray", TRAYS),
      ("several cups", "cups", "communion cups", SMALL_CUPS),
      ("a chalice cup", "chalice cup", "chalice", CHALICES)]),
    ("en-prayer-shawl", "en", "Good morning, I'm looking for a prayer shawl.",
     [("prayer shawl", "prayer shawl", "prayer shawl", TALLIT)]),
    ("en-slip-train", "en", "Sir, madam, I'm looking for a train for a sacrament for the church.",
     [("train for a sacrament", "tray for the sacrament", "communion tray", TRAYS)]),
    ("en-slip-tree", "en", "So that tree is just carrying forty cups and nothing else?",
     [("tree is just carrying forty cups", "tray carrying forty cups", "communion tray", TRAYS)]),
    ("en-tots-golden-bowl", "en",
     "Not the big cup. I'm looking for the tots, and I think it was a big golden round tray, "
     "and also a bowl where I can put the communion wafers.",
     [("tots", "tots", "communion cups", SMALL_CUPS),
      ("golden big tray", "golden tray", "golden communion tray", r"Golden Communion Tray"),
      ("bowl for the communion wafers", "bowl for wafers", "bread tray", BREAD_TRAYS + r"|Ciborium")]),
    ("en-plates-holder", "en", "Can I get communion plates and a holder for the cups?",
     [("communion plates", "communion plates", "communion bread plate", BREAD_TRAYS),
      ("holder for the cups", "cup holder", "communion tray", TRAYS)]),
    ("en-cap-only", "en",
     "I don't need the collar, I have the white collar and the mitre. Only the garment and the cap.",
     [("the cap", "cap", "skull cap", r"Skull Cap")]),
    ("en-black-cassock-gold", "en",
     "It must be black with gold, three stripes at each shoulder and a star on top.",
     [("black cassock", "black cassock", "cassock", CASSOCKS)]),
    ("en-gown-for-church", "en", "I need a very nice gown for the church. How do I send money?",
     [("gown", "gown", "gown", GOWNS)]),
    ("en-oil-horn", "en", "How much are the anointing oil and the horn?",
     [("anointing oil", "anointing oil", "anointing oil", r"Anointing [Oo]il"),
      ("the horn", "horn", "anointing horn", r"[Hh]orn")]),
    ("en-two-shirts-stole", "en", "I want two clergy shirts with the round collar and one stole.",
     [("clergy shirts with the round collar", "round collar clergy shirt", "round collar shirt", COLLAR_SHIRTS),
      ("one stole", "stole", "stole", STOLES)]),
    ("en-incense-thurible", "en", "Do you have incense and a thurible for the mass?",
     [("incense", "incense", "incense", r"^Incense$"),
      ("thurible", "thurible", "thurible", r"Thurible")]),
    ("en-wine-wafers", "en", "We need altar wine and communion wafers, a thousand pieces.",
     [("altar wine", "altar wine", "altar wine", WINE),
      ("communion wafers a thousand pieces", "communion wafers 1000", "communion wafers 1000", BREAD)]),
    ("en-ring-cross", "en", "I need a bishop's ring and a pectoral cross.",
     [("bishop's ring", "bishop ring", "bishopric ring", RINGS),
      ("pectoral cross", "pectoral cross", "pectoral cross", CROSS)]),
    ("en-mitre-crozier", "en", "Price for a mitre and a crozier please.",
     [("mitre", "mitre", "mitre", r"^Mitre$"),
      ("crozier", "crozier", "crozier", r"Crozier")]),
    ("en-alb-cincture", "en", "I need an alb and a cincture for the deacon.",
     [("alb", "alb", "alb", r"^Alb$"),
      ("cincture", "cincture", "cincture", r"(?i)cincture")]),
    ("en-surplice-choir", "en", "Looking for surplices for our choir, five of them.",
     [("surplices", "surplices", "surplice", r"^Surplice$")]),
    ("en-chasuble-green", "en", "Do you have a chasuble in green?",
     [("chasuble", "chasuble", "chasuble", r"Chasuble")]),
    ("en-offering-basket", "en", "How much is the offering basket?",
     [("offering basket", "offering basket", "offering basket", r"[Oo]ffering basket")]),
    ("en-candles", "en", "I want candles for the altar.",
     [("candles", "candles", "candles", r"^Candles$")]),
    ("en-sprinkler", "en", "I want the holy water sprinkler.",
     [("holy water sprinkler", "holy water sprinkler", "aspergillum", r"Sprinkler")]),
    ("en-ordination-gown", "en", "An ordination gown for my husband, size large.",
     [("ordination gown", "ordination gown", "ordination gown", r"Ordination Gown")]),
    ("en-garbled-sholl", "en", "I'm looking for prayer sholl.",
     [("prayer sholl", "prayer shawl", "prayer shawl", TALLIT)]),
    ("en-skull-cap", "en", "A purple skull cap for the bishop.",
     [("skull cap", "skull cap", "skull cap", r"Skull Cap")]),
    # ── Swahili / Sheng ─────────────────────────────────────────────────
    ("sw-kasoki-52", "sw", "Habari, nataka kasoki nyeusi size hamsini na mbili.",
     [("kasoki", "cassock", "cassock", CASSOCKS)]),
    ("sw-carrier-not-cups", "sw",
     "Kanisani kwetu vikombe vipo. Ninachotaka ni kisinia cha kubebea vikombe, pamoja na "
     "sinia ya kubebea mikate. Sitaki vikombe. Bei gani?",
     [("kisinia cha kubebea vikombe", "tray for carrying cups", "communion tray", TRAYS),
      ("sinia ya kubebea mikate", "tray for carrying bread", "bread tray", BREAD_TRAYS)]),
    ("sw-collar-shirts-kanzu-chain", "sw",
     "Nataka shati za kola mbili, kanzu moja, na cheni ya msalaba moja. Niko nje ya Kenya.",
     [("shati za kola", "collar shirts", "clergy shirt", COLLAR_SHIRTS),
      ("kanzu", "cassock", "cassock", CASSOCKS),
      ("cheni ya msalaba", "cross pendant", "pectoral cross", CROSS)]),
    ("sw-outfit-list", "sw", "Kasoki, shati, kola, stola na mkanda.",
     [("kasoki", "cassock", "cassock", CASSOCKS),
      ("shati", "shirt", "clergy shirt", SHIRTS),
      ("kola", "collar", "collar", r"Collar"),
      ("stola", "stole", "stole", STOLES),
      ("mkanda", "belt", "cincture belt", r"(?i)belt")]),
    ("sw-meza-ya-bwana", "sw", "Nahitaji vyombo vya meza ya Bwana.",
     [("vyombo vya meza ya Bwana", "communion ware", "communion set", TRAYS)]),
    ("sw-joho-kofia", "sw", "Bei ya joho na kofia ya askofu ni ngapi?",
     [("joho", "gown", "gown", GOWNS),
      ("kofia ya askofu", "bishop's hat", "mitre", r"^Mitre$")]),
    ("sw-mishumaa-ubani", "sw", "Nataka mishumaa ya altare na ubani.",
     [("mishumaa", "candles", "candles", r"^Candles$"),
      ("ubani", "incense", "incense", r"^Incense$")]),
    ("sw-pastors-cup", "sw", "Kikombe kubwa ya mchungaji ni pesa ngapi?",
     [("kikombe kubwa ya mchungaji", "the pastor's big cup", "chalice", CHALICES)]),
    ("sw-divai-mikate", "sw", "Divai na mikate ya ushirika.",
     [("divai", "wine", "communion wine", WINE),
      ("mikate ya ushirika", "communion bread", "communion bread", BREAD)]),
    ("sw-pete-msalaba", "sw", "Pete mbili za askofu na msalaba mmoja.",
     [("pete za askofu", "bishop's rings", "bishopric ring", RINGS),
      ("msalaba", "cross", "pectoral cross", CROSS)]),
    ("sw-mafuta", "sw", "Mafuta ya upako bei gani?",
     [("mafuta ya upako", "anointing oil", "anointing oil", r"Anointing [Oo]il")]),
    ("sw-trei-40", "sw", "Nataka trei ya vikombe arobaini.",
     [("trei ya vikombe", "tray of cups", "communion tray", TRAYS)]),
    ("sw-stola-red", "sw", "Nataka stola nyekundu peke yake.",
     [("stola", "stole", "stole", STOLES)]),
    ("sw-fimbo", "sw", "Fimbo ya askofu iko?",
     [("fimbo ya askofu", "bishop's staff", "crozier", r"Crozier")]),
    ("sheng-kasoki-kora", "sw", "Niaje, nataka ile kasoki black na shati ya kora.",
     [("kasoki", "cassock", "cassock", CASSOCKS),
      ("shati ya kora", "collar shirt", "clergy shirt", COLLAR_SHIRTS)]),
    ("sw-kitambaa-kiyahudi", "sw", "Kitambaa cha kiyahudi ni shingapi?",
     [("kitambaa cha kiyahudi", "Jewish cloth", "prayer shawl", TALLIT)]),
    ("sw-chetezo-kengele", "sw", "Chetezo na kengele.",
     [("chetezo", "censer", "thurible", r"Thurible"),
      ("kengele", "bell", "altar bell", r"(?i)bell")]),
    ("sw-mshipi-kasoki", "sw", "Mshipi wa kasoki.",
     [("mshipi wa kasoki", "cassock belt", "cincture belt", r"(?i)cincture belt")]),
    # ── French ───────────────────────────────────────────────────────────
    ("fr-shirts-toges", "fr",
     "Personnellement, j'ai besoin de chemises pastorales et aussi de toges pastorales.",
     [("chemises pastorales", "pastoral shirts", "clergy shirt", SHIRTS),
      ("toges pastorales", "pastoral robes", "preaching gown", GOWNS)]),
    ("fr-chemise", "fr", "Je cherche une chemise. C'est combien les chemises?",
     [("chemise", "shirt", "clergy shirt", SHIRTS)]),
    ("fr-plateaux", "fr", "Le plateau de communion et le plateau de pain, c'est combien?",
     [("plateau de communion", "communion tray", "communion tray", TRAYS),
      ("plateau de pain", "bread tray", "bread tray", BREAD_TRAYS)]),
    ("fr-aube", "fr", "Une aube pour les enfants de chœur.",
     [("aube", "alb", "alb", r"^Alb$")]),
    ("fr-etole-soutane", "fr", "Le prix de l'étole et de la soutane.",
     [("étole", "stole", "stole", STOLES),
      ("soutane", "cassock", "cassock", CASSOCKS)]),
    ("fr-calice-hosties", "fr", "Je veux un calice et des hosties.",
     [("calice", "chalice", "chalice", CHALICES),
      ("hosties", "hosts", "communion hosts", BREAD)]),
    ("fr-croix", "fr", "Combien coûte la croix pectorale?",
     [("croix pectorale", "pectoral cross", "pectoral cross", CROSS)]),
    ("fr-gobelets", "fr", "Je voudrais deux cents gobelets.",
     [("gobelets", "cups", "communion cups", SMALL_CUPS)]),
    # ── Spanish / Portuguese ─────────────────────────────────────────────
    ("es-bandejas", "es", "¿Qué precio tiene la bandeja de las copas y la del pan?",
     [("bandeja de las copas", "tray for the cups", "communion tray", TRAYS),
      ("bandeja del pan", "bread tray", "bread tray", BREAD_TRAYS)]),
    ("es-aluminio-40", "es", "Necesito bandeja de aluminio de cuarenta copas con su tapa.",
     [("bandeja de aluminio", "aluminium tray", "aluminium tray", r"^Aluminium Tray$")]),
    ("pt-casula-capa-cruz", "pt", "Preciso de uma casula, uma capa e uma cruz peitoral.",
     [("casula", "chasuble", "chasuble", r"Chasuble"),
      ("capa", "cope", "cope", r"Cope"),
      ("cruz peitoral", "pectoral cross", "pectoral cross", CROSS)]),
    ("es-copa-grande", "es", "¿Cuánto la copa grande?",
     [("copa grande", "big cup", "chalice", CHALICES)]),
    ("es-vasitos", "es", "Doscientos vasitos de plástico.",
     [("vasitos de plástico", "plastic cups", "plastic communion cups", r"Plastic Communion Cups")]),
    ("es-bandeja-dorada", "es", "Bandeja dorada para la comunión.",
     [("bandeja dorada", "golden tray", "golden communion tray", r"Golden Communion Tray")]),
    ("pt-vinho", "pt", "Vinho para a santa ceia.",
     [("vinho", "wine", "communion wine", WINE)]),
    # ── garbled / misspelt ───────────────────────────────────────────────
    ("slip-chausable", "en", "How much is the chausable?",
     [("chausable", "chasuble", "chasuble", r"Chasuble")]),
    ("slip-tallith", "en", "Tallith for the intercessors.",
     [("tallith", "tallit", "tallit", TALLIT)]),
    ("slip-sprinkle", "en", "The sprinkle for holy water.",
     [("sprinkle", "sprinkler", "sprinkler", r"Sprinkler")]),
]

# Things Bethany House does NOT sell: never force-matched. (said, why)
NOT_STOCKED: list[tuple[str, str]] = [
    ("suti ya kanisa", "a church suit — not a hub product"),
    ("rosary", "not stocked"),
    ("monstrance", "not stocked"),
    ("blanket", "not stocked"),
    ("shoes", "not stocked"),
    ("purificator", "altar linen — not stocked"),
    ("linge d'autel", "altar linen — not stocked"),
    ("hudhuria ibada ya jumapili", "a sentence, not a product (a transcription hallucination)"),
    ("biretta", "not stocked"),
    ("menorah", "not stocked"),
]


def items():
    """Every (case id, item index, form, words, expect) — the measured units."""
    for cid, _lang, _text, its in CASES:
        for i, (said, en, query, expect) in enumerate(its):
            yield cid, i, "said", said, expect
            yield cid, i, "en", en, expect
            yield cid, i, "query", query, expect
