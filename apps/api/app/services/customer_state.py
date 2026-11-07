"""Customer state — what the customer's own words mean for what we do next
(Stage 3, audit 2026-11-05).

Until now Neema's REPLIES understood intent (the model reads the whole
conversation) but her DECISIONS to speak unprompted did not: a scheduler saw
"quiet for 4 h" and "cart with items", never "he said he will compare prices
in Arusha". This module makes the understanding visible to the schedulers:

  · a DETERMINISTIC FLOOR for the phrases that must never be missed — asking
    for time, comparing prices, consulting a bishop / spouse / committee, a
    payment claim, a polite close, an opt-out — in English, Swahili and French;
  · a light-model NOTE after each real turn (no tools, a few hundred tokens)
    that reads the same conversation and answers five questions: who are we
    waiting on, what did the customer say, until when, in which language, is
    an item under confirmation;
  · one `apply()` that stores the result where the schedulers and the next
    turn read it: a HOLD on the deal (`deal.next_action["hold"]`, with the
    date), the customer's language and latest state on the person
    (`persons.state`), a payment claim as `deal.blocking` text.

What it never does: mark an order paid (the hub does that), overwrite a
colleague's team check, or speak. Speculative model readings only ever set
state the dispatcher treats as "wait" or "ask a person" — never "send".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.core.config import settings

_log = logging.getLogger("neema.state")

HOLD_STATES = ("needs_time", "comparing", "consulting")
STATES = ("exploring", "quoting", "comparing", "consulting", "needs_time", "ready",
          "paid_claim", "complaint", "closing", "stop", "none")
# Languages an automated message may be composed in; anything else goes to a
# person (the live turn still answers in the customer's language).
AUTOMATED_LANGUAGES = frozenset({"en", "sw", "fr"})
_HOLD_LABEL = {"needs_time": "Asked for time", "comparing": "Comparing prices",
               "consulting": "Consulting someone"}

# ── the floor ────────────────────────────────────────────────────────────────
_NEEDS_TIME_RE = re.compile(
    r"\b(?:get back to you|come back to you|let you know|let me think|think about it|"
    r"not (?:yet )?ready|not now|later on|give me (?:some )?time|"
    r"i(?:'ll| will) (?:revert|decide|come back|be back|get back|sort it|arrange)|we(?:'ll| will) (?:revert|come back|get back)|"
    r"let me (?:revert|pray(?: about| over)?|sleep on it|think(?: about| it over)?|arrange the (?:money|funds|cash)|"
    r"organi[sz]e the (?:money|funds|cash)|sort out the (?:money|funds|cash))\b|"
    r"(?:contact|call|message|text|ping|reach|get back to|check with) (?:me|us)\b[^.?!\n]{0,24}?"
    r"\b(?:tomorrow|tonight|next (?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"after (?:the |our )?(?:service|meeting|church|committee|easter|christmas|lent|\d{1,2} ?(?:am|pm)|lunch|work)|"
    r"later (?:today|this week|in the (?:week|month|day))|in (?:a|an|\d+|two|three|four) (?:day|week|month|hour)s?|"
    r"on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|the \d{1,2}(?:st|nd|rd|th)?)|"
    r"by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|the \d{1,2}(?:st|nd|rd|th)?|end of)|"
    r"when (?:we|i|the|it)|once (?:we|i|the|it))\b|"
    r"(?:wait|hold on|hold)\b[^.?!\n]{0,20}?\b(?:till|until|after|for now)|on second thoughts?|"
    r"(?:away|out|travell?ing|abroad) (?:till|until)|(?:later|next) (?:in the year|month|year|term|quarter)|"
    r"nitakujulisha|nitarudi|nitakuambia|nitawasiliana|nipe muda|si sasa|baadaye|mwakani|"
    r"je reviens vers vous|je vous tiens au courant|je vous recontacte|laissez[- ]moi r[ée]fl[ée]chir|pas (?:encore|maintenant)|"
    r"on va voir|vamos ver|depois (?:eu )?aviso|mais tarde|"
    r"(?:^|\b)will (?:revert|come back|get back|confirm|update you|let you know)|"
    r"'ll (?:confirm|update you) (?:later|tomorrow|tonight|by|on|next|after|once|when|in)\b|"
    r"je (?:vous )?(?:reviens|reviendrai|r[ée]fl[ée]chis|vous [ée]cris demain)|volto a falar|vou pensar|"
    r"soch ke|sochta hoon|soch kar|don'?t send (?:it|them|anything) yet|not yet,? (?:i|we) need to|"
    r"(?:fundrais|raising (?:the )?(?:money|funds)|collecting (?:the )?money)|"
    r"(?:budget|funds|money) (?:is |are )?not (?:yet )?(?:approved|ready|available|in|released))\b",
    re.IGNORECASE)
_COMPARING_RE = re.compile(
    r"\b(?:compar\w*|other (?:supplier|shop|price|quot\w+)s?|check (?:other )?prices|shop around|"
    r"look around|see (?:elsewhere|other options)|kulinganisha|bei (?:nyingine|za wengine)|"
    r"wanaouza|maduka mengine|comparer|d'autres (?:prix|fournisseurs))\b",
    re.IGNORECASE)
_CONSULT_BODY = (
    r"(?:bishop|pastor|reverend|priest|father|husband|wife|spouse|committee|board|council|parish|"
    r"boss|director|treasurer|elders?|deacons?|vestry|pcc|synod|diocese|chairman|chairperson|"
    r"chair|choir(?: master| leader)?|leadership|leaders|management|archdeacon|dean|secretary|congregation|finance|"
    r"askofu|mchungaji|padri|mume|mke|kamati|familia|bodi|wazee|viongozi|uongozi|mwenyekiti|kwaya|"
    r"[ée]v[êe]que|pasteur|abb[ée]|cur[ée]|monseigneur|mari|femme|comit[ée]|paroisse|conseil(?: paroissial)?|"
    r"bispo|padre|comiss[ãa]o|conselho|igreja|his lordship|his grace|the reverend|mkutano|wakubwa)"
)
_CONSULTING_RE = re.compile(
    r"\b(?:consult|ask|discuss(?: it| this)? with|talk (?:to|with)|check with|confirm with|present (?:it |this |to )?to|"
    r"take (?:it|this) to (?:the |our |my )?|pass (?:it|this) on to|run (?:it|this) by|share (?:it|this) with|"
    r"needs? (?:the )?(?:approval|sign[- ]?off|blessing) (?:of|from)|see what|hear from|"
    r"nimuulize|nitamuuliza|niulize|nimwambie|niwaambie|nipeleke|nitamshow|nimshow|tuzungumze na|niongee na|baada ya|"
    r"demander [àa]|en parler [àa]|je vais en parler|consulter|je transmets [àa]|je dois consulter|vou falar com|falar com|perguntar ao)\b"
    r"[^.?!\n]{0,40}?\b" + _CONSULT_BODY + r"\b"
    # "check with him / discuss it with them / ask my wife": a person, by pronoun or kin
    r"|\b(?:consult|ask|discuss(?: it| this)? with|talk (?:to|with)|check with|confirm with|run (?:it|this) by)\s+"
    r"(?:him|her|them|my (?:wife|husband|family|team|boss|people)|the (?:team|family|church|others))\b"
    # the body first: "the committee will decide", "bishop anasema tungoje"
    r"|\b(?:the |our |my )?" + _CONSULT_BODY + r"\b[^.?!\n]{0,30}?\b(?:will|must|has to|have to|needs? to|is yet to|are yet to|"
    r"wata|ata|ana|anasema|wanasema|itabidi|doit|doivent|vai|vão) (?:decide|approve|confirm|meet|discuss|sign|see|review|"
    r"amua|kubali|tungoje|décider|approuver|decidir|aprovar)\b"
    r"|\b(?:committee|board|council|elders|kamati|bodi|wazee) (?:meets?|sits?|inakaa|itakaa|will meet|will sit)\b"
    # a bare "let me consult." with nobody named (slice 11): still a consultation
    r"|\b(?:let me|i (?:need|have) to|i must|i'll|i will) consult(?: first)?\s*(?:[.!…]+\s*|$)",
    re.IGNORECASE)
_PAID_RE = re.compile(
    r"\b(?:i(?:'ve| have)? (?:already |just )?paid|(?:just )?paid (?:by|via|with|through|using) \w+|"
    r"payment (?:is )?(?:done|made|sent|complete[d]?|went through)|(?:i )?sent the money|money sent|"
    r"(?:m-?pesa|airtel(?: money)?|mobile money) (?:deducted|went through|is done|has gone)|"
    r"(?:here(?:'s| is)|see|attached) (?:the |my )?(?:m-?pesa|payment|transfer|transaction) (?:screenshot|receipt|confirmation|message|sms)|"
    r"(?:screenshot|receipt) of (?:the |my )?(?:payment|m-?pesa|transfer|transaction)|"
    r"nimelipa|nimeshalipa|nimetuma pesa|tumelipa|j'ai (?:d[ée]j[àa] )?pay[ée]|paiement effectu[ée]|"
    r"j[áa] paguei|paguei|(?:has|have) paid|(?:i(?:'ve| have) )?sent (?:the |my )?(?:half|deposit|balance|full amount|money|cash|payment|\d[\d,]*)\b|"
    r"sent (?:it |the money |\d[\d,]* )?(?:via|through|by) (?:m-?pesa|mukuru|western ?union|moneygram|airtel|bank|card|paybill|till)|"
    r"nimetuma (?:pesa|hela|malipo|m-?pesa)|tumetuma (?:pesa|hela|malipo)|nimeshatuma (?:pesa|hela)|"
    r"(?:received|got|seen) my (?:payment|money|m-?pesa|transfer))\b"
    # a message that IS the claim: "Paid", "Done, paid", "Paid. Mpesa ref …", "Sent 2500", "nimetuma"
    r"|^(?:ok(?:ay)?[,.!]? |done[,.!]? |yes[,.!]? )?paid\b"
    r"|^(?:ok(?:ay)?[,.!]? |done[,.!]? )?sent (?:\d|the money|the payment|the deposit|the half|via|by|through)"
    r"|^(?:ok(?:ay)?[,.!]? |done[,.!]? |yes[,.!]? )?(?:sent|nimetuma|nimelipa|pay[ée]|paguei|enviado|envoy[ée])[.!,]*(?:\s*(?:cheki|check))?[.!]*$",
    re.IGNORECASE)
# "I will pay tomorrow", "I have not paid yet", "sijalipa": not a claim.
_PAID_NEG_RE = re.compile(
    r"\b(?:not paid|haven'?t paid|have not paid|didn'?t pay|yet to pay|will pay|i'll pay|gonna pay|"
    r"going to pay|about to pay|can i pay|how (?:do|can|to) (?:i |we )?pay|pay on delivery|"
    r"sija(?:lipa|tuma)|bado sija|nitalipa|tutalipa|pas encore pay|ainda n[ãa]o pag|vou pagar)\b",
    re.IGNORECASE)
_READY_RE = re.compile(
    r"\b(?:go ahead|proceed|place the order|i(?:'ll| will) take (?:it|them|one|two|three|\d+|the|that|this|both)|"
    r"let's do it|confirm(?:ed)? the order|go for it|invoice me|send (?:me )?(?:the |an |a )?(?:invoice|pro ?forma)|"
    r"^(?:ok(?:ay)?[,.!]? |yes[,.!]? )?approved\b|(?:it(?:'s| is)|has been|budget(?: is)?|order(?: is)?|they(?:'ve| have)|he has|she has) approved|"
    r"i(?:'ll| will) pay (?:now|today|via|by|through|with)|paying now|sending (?:the money |it )?now|"
    r"sort me out|i(?:'ll| will) order|we(?:'ll| will) (?:take|order|go with)|book (?:it|them|one)|"
    r"endelea|nachukua|tuendelee|weka oda|nitume (?:m-?pesa|pesa)|natuma|tuma (?:details|namba|maelezo)|"
    r"(?:send|tuma) (?:me )?(?:the |your )?(?:till|paybill|pay ?bill|account|m-?pesa) ?(?:number|no\.?|details)?|nilipe|"
    r"allons-y|je (?:le |la |les )?prends|je confirme|c'est bon pour moi|pode (?:mandar|enviar|fazer)|vamos fechar|fechado)\b",
    re.IGNORECASE)
# readiness that stands even beside a question ("Approved. How do we pay?")
# or a courtesy ("No rush, go ahead and make it")
_READY_STRONG_RE = re.compile(
    r"^(?:ok(?:ay)?[,.!]? |yes[,.!]? )?approved\b|\b(?:go ahead|place the order|i(?:'ll| will) take (?:it|them|one|\d+)|proceed|confirm(?:ed)? the order)\b",
    re.IGNORECASE)
# "not approved yet", "once the bishop approves", "send the invoice when approved": not readiness
_READY_NEG_RE = re.compile(
    r"\b(?:not|hasn'?t|haven'?t|isn'?t|yet to be|once|when|if|after|until|unless|before)\b[^.?!\n]{0,24}\bapprov",
    re.IGNORECASE)
_COMPLAINT_RE = re.compile(
    r"\b(?:complain\w*|disappoint\w*|refund|late|poor quality|imechelewa|kuchelewa|r[ée]clamation|rembours\w+|"
    r"en retard|atrasad\w*)\b", re.IGNORECASE)
# markers that make a complaint even when the message also asks a question
_COMPLAINT_STRONG_RE = re.compile(
    r"\b(?:wrong (?:one|item|size|colour|color|product|order)|damaged|torn|broken|cracked|crushed|bent|stained|faded|"
    r"coming off|falling apart|never (?:arrived|came)|hasn'?t arrived|not (?:yet )?(?:arrived|received|delivered)|"
    r"still waiting for (?:my|the) (?:order|parcel|delivery|reply|answer|refund|goods)|"
    r"been waiting (?:for|since) (?:a reply|an answer|my order|the order|\d+ (?:days|weeks|hours|months))|"
    r"waiting since (?:morning|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|last week)|"
    r"nobody (?:replies|answers|responds)|no ?one (?:replies|answers|responds)|"
    r"is anyone there|expected better|rude|ridiculous|unacceptable|disgrace\w*|came without|is missing|"
    r"(?:has|have) not moved|hasn'?t moved|supposed to (?:come|arrive|be here)|"
    r"i ordered \w+(?: \w+)? (?:but|and) (?:you sent|got|received|they sent|it (?:came|arrived|is))|"
    r"still (?:isn'?t|is not|hasn'?t|has not) (?:here|arrived|come)|(?:n'?t|not) fair|useless|hopeless|pathetic|"
    r"you sent (?:a|an|the|me) \w+[^.!?\n]{0,40}\bi ordered\b|instead of (?:the|what) \w+[^.!?\n]{0,30}\b(?:ordered|asked|paid)|"
    r"box (?:has|had|contains) only \d+|only \d+ (?:arrived|came|were delivered|in the box)|short by \d+|\d+ (?:are|is) missing|"
    r"ordered \d+ [^.!?\n]{0,40}\b(?:box|carton|parcel|package) (?:has|had|contains|came with) (?:only )?\d+|"
    r"(?:are|is|came|arrived|got|received) [^.!?\n]{0,40}, (?:but )?i ordered\b|"
    r"you said you(?:'d| would) [^.!?\n]{0,40}\b(?:by|before) (?:yesterday|today|now|\w+day)|"
    r"(?:third|3rd|second|2nd|fourth|4th|fifth) time (?:i(?:'m| am) |i have |we have |of )?(?:asking|writing|messaging|complaining|following up|calling)|"
    r"haijafika|hajafika|sijapokea|imevunjika|mbovu|imeharibika|d[ée]çu|cass[ée]|pas reçu|toujours pas|"
    r"n'ai rien reçu|inadmissible|inacceptable|quebrad\w*|n[ãa]o recebi|ainda n[ãa]o chegou)\b", re.IGNORECASE)


def floor(text: str | None, *, now: datetime | None = None) -> dict | None:
    """The deterministic reading of one customer message, or None when the
    words say nothing the schedulers must act on. Precedence: stop > paid
    claim > complaint > consulting > comparing > needs time > ready > closing."""
    t = " ".join((text or "").split())
    if not t:
        return None
    from app.services.intent import is_opt_out
    if is_opt_out(t):
        return {"customer_said": "stop", "matched": "opt-out"}
    paid = _PAID_RE.search(t) if not _PAID_NEG_RE.search(t) else None
    strong = _COMPLAINT_STRONG_RE.search(t)
    if strong and not (paid and "?" in t):        # "Have you not received my payment?" is a claim
        return {"customer_said": "complaint", "matched": strong.group(0)}
    if paid:
        return {"customer_said": "paid_claim", "matched": paid.group(0)}
    if _READY_STRONG_RE.search(t) and not _READY_NEG_RE.search(t) and not _CONSULTING_RE.search(t):
        # "No rush, go ahead and make it": the courtesy does not undo the go-ahead
        return {"customer_said": "ready", "matched": _READY_STRONG_RE.search(t).group(0)}
    if _COMPLAINT_RE.search(t) and "?" not in t:
        return {"customer_said": "complaint", "matched": _COMPLAINT_RE.search(t).group(0)}
    until = None
    try:
        from app.services.deals import detect_customer_promise
        cp = detect_customer_promise(t, now=now)
        if cp:
            until = cp[0]
    except Exception:
        until = None
    for state, rx in (("consulting", _CONSULTING_RE), ("comparing", _COMPARING_RE),
                      ("needs_time", _NEEDS_TIME_RE)):
        m = rx.search(t)
        # "if I compare two sizes?" / "can you call me tomorrow?" / "what do I
        # tell the bishop?" ask us something
        if m and not ("?" in t and until is None):
            return {"customer_said": state, "matched": m.group(0),
                    "hold_until": until.isoformat() if until else None}
    ready = _READY_RE.search(t)
    if ready and _READY_NEG_RE.search(t):
        ready = None
    if ready and ("?" not in t or _READY_STRONG_RE.search(t)):
        return {"customer_said": "ready", "matched": ready.group(0),
                "hold_until": until.isoformat() if until else None}
    if until is not None:
        return {"customer_said": "needs_time", "matched": "named a time", "hold_until": until.isoformat()}
    try:
        from app.agent.runtime import is_closer
        if is_closer(t):
            return {"customer_said": "closing", "matched": "closer"}
    except Exception:
        pass
    return None


_SW_VERB_RE = re.compile(r"^(?:ni|u|a|tu|m|wa|si|ha)(?:ta|me|na|li|ki|ka|ja|sha)[a-z]{3,}$")
_SW_EXTRA = frozenset("""
    jumatatu jumanne jumatano alhamisi ijumaa jumamosi jumapili wiki mwezi baadaye kwanza
    bado tena ujumbe asante sawa habari karibu pole ndugu mchungaji askofu kanisa bei
    nitakujulisha nitarudi nitawasiliana nimelipa nimeshalipa
    mungu akubariki akubarikie mko wapi niko tuko kesho leo sasa jioni asubuhi ngapi shilingi
    nimesikia nitalipa tutalipa ngoja subiri sitaki nataka nahitaji tunahitaji kiasi gani
    naweza nalipa natafuta naomba nauliza napenda natuma nakuja nasubiri nangoja nafikiri
    naona nasikia najua nashukuru nachukua naagiza nahitajika nipo mna una kuna hakuna ina zina
    unipunguzie punguza mambo niaje poa haya hapana ndiyo ndio sana rangi nyeupe nyeusi
    kitambaa nakshi kushonwa imeshonwa mwakani mzee baba mama bwana bibi mkuu kwaya
""".split())
_PT_WORDS = frozenset("""
    obrigado obrigada preço preços quanto custa custam você vocês senhor senhora bom dia boa tarde
    noite por favor quero gostaria queria encomenda pagamento entrega não sim temos tem é está fazer
    enviar mandar pode podem posso bispo padre igreja batina casula estola cálice vamos ver depois
    aviso tenho preciso precisamos aqui também ainda já muito olá vendem vende aceitam aceita cartão
    ou só unção velas altar bom boa fique deus abençoe quero queria volto falar está bem
""".split())
_HI_ROMAN = frozenset("""
    kya hai hain mein main ka ki ke hoon hun batata soch nahi nahin haan ji kitna kitne chahiye bhej
    karo kijiye dhanyavad namaste aap aapka hum humko mujhe kripya theek thik bata dena kar
""".split())
_FR_STRONG = frozenset("""
    merci bonjour bonsoir d'accord monseigneur arrête arrêtez arrete arretez m'écrire transmets
    beaucoup infiniment remercie reviendrai j'attends dites-moi s'il plaît voudrais aimerais coûte
    livraison paiement combien étoles évêque paroisse abbé
""".split())
_PT_STRONG = frozenset("""
    obrigado obrigada olá vendem vende aceitam aceita cartão unção velas preço preços você vocês
    senhor senhora encomenda pagamento entrega batina casula estola bispo igreja abençoe
""".split())
_FR_WORDS = frozenset("""
    bonjour bonsoir merci je vous votre vos est combien prix avec pour voulez souhaitez commande oui
    nous les des une sur c'est j'ai s'il plaît voudrais aimerais coûte le la et du paiement comment
    depuis quand livraison dites-moi j'attends possible payer carte étoles couleurs chasuble évêque
    abbé paroisse bien d'accord reviens parler aussi encore très beaucoup infiniment remercie reviendrai
    monseigneur transmets arrête arrêtez m'écrire blanc noir rouge vert violet total garde dieu
""".split())
_NEUTRAL_WORDS = frozenset("ok okay k kk yes no hi hello hey noted amen sawa poa".split())
_SHOP_NOUNS = frozenset("""
    size colour color white black purple red green blue gold silver delivery pickup collect pay paid payment
    price order invoice till paybill mpesa thika nairobi mombasa kisumu nakuru eldoret
""".split())
_EN_WORDS = frozenset("""
    the is how much price do you have want need please order can i my for and what when will thanks
    thank ok okay noted call me we be blessed bless god too expensive yes no not send let know after
    still waiting shall see cheers hi hello good morning afternoon evening dear sir madam kindly same
    it that this with are am was in on at to of if but so now later tomorrow today sorry fine great
    size colour color white black purple red green blue delivery pickup collect pay paid payment
""".split())


def guess_language(text: str | None) -> str | None:
    """The customer's language from their own words, when it can be placed:
    script first (Devanagari → hi, Arabic → ar, Amharic → am), then Swahili,
    then French; English for an English message; None when unsure."""
    t = (text or "").strip()
    if not t:
        return None
    if re.search(r"[ऀ-ॿ]", t):
        return "hi"
    if re.search(r"[؀-ۿ]", t):
        return "ar"
    if re.search(r"[ሀ-፿]", t):
        return "am"
    from app.agent.voice import looks_swahili
    if looks_swahili(t):
        return "sw"
    toks = set(re.findall(r"[a-zàâçéèêëîïôûùüÿœãõáíóúâêôç'-]+", t.lower()))
    # a bare "ok" / "yes" / "hi" / "sawa" belongs to every language: never let
    # it overwrite the language a customer has already shown (slice 7: this
    # ran after the shape rule, so a lone "Sawa" / "poa" read as Swahili)
    if toks and toks <= _NEUTRAL_WORDS:
        return None
    en = toks & _EN_WORDS
    # Swahili by its verb shape (ni-ta-kujulisha, tu-me-pata) and its calendar
    # words — the short word list in voice.py misses a sentence with no price in it.
    # Product nouns a Swahili speaker borrows ("Sawa size 42", "Nitachukua 2,
    # black", "Asante, delivery Thika") are not evidence of English.
    sw_shape = sum(1 for w in toks if _SW_VERB_RE.match(w) or w in _SW_EXTRA)
    if sw_shape >= 1 and (sw_shape >= 2 or not (en - _SHOP_NOUNS)):
        return "sw"
    fr, pt, hi = toks & _FR_WORDS, toks & _PT_WORDS, toks & _HI_ROMAN
    # romanised Hindi/Hinglish: "chasuble ka price kya hai"
    if len(hi) >= 2 and len(hi) >= len(en - _NEUTRAL_WORDS):
        return "hi"
    # "por favor"/"não"/"obrigado" are not French; "vous"/"merci" are not Portuguese
    if len(pt) >= 2 and len(pt) > len(fr):
        return "pt"
    if len(fr) >= 2 and len(fr) >= len(pt):
        return "fr"
    if (toks & _PT_STRONG) and not fr:
        return "pt"
    if (toks & _FR_STRONG) and not pt:
        return "fr"
    if len(pt) >= 1 and not en and not fr:
        return "pt"
    if en - _NEUTRAL_WORDS:
        return "en"
    # plain ASCII with nothing of the other languages reads as English
    if t.isascii() and len(toks) >= 2 and not sw_shape:
        return "en"
    return None


# ── the model's note ─────────────────────────────────────────────────────────

_NOTE_SYSTEM = (
    "You read a WhatsApp sales chat for Bethany House (church vestments and clothing) and "
    "state the customer's situation in JSON — nothing else. Fields:\n"
    '"waiting_on": "customer" | "us" | "team" | "none" — who owes the next move;\n'
    '"customer_said": one of exploring, quoting, comparing, consulting, needs_time, ready, '
    "paid_claim, complaint, closing, stop, none — what the customer's LAST message means "
    "(comparing = checking other prices; consulting = must ask a bishop/spouse/committee; "
    "needs_time = asked us to wait; ready = agreed to buy, not merely interested; "
    "paid_claim = says they paid; stop = asked for no more messages);\n"
    '"hold_until": "YYYY-MM-DD" when they named a day to come back, else null;\n'
    '"language": the ISO 639-1 code of the customer\'s last message (en, sw, fr, hi, …);\n'
    '"open_item_check": the item we told them we are confirming with the team, else null.\n'
    "Interest is not agreement. When unsure, choose none / null. Reply with the JSON object only."
)


def parse_note(raw: str | None) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    said = str(data.get("customer_said") or "none").strip().lower()
    out = {"waiting_on": str(data.get("waiting_on") or "none").strip().lower(),
           "customer_said": said if said in STATES else "none",
           "hold_until": None, "language": None,
           "open_item_check": (str(data.get("open_item_check")).strip()[:120]
                               if data.get("open_item_check") else None)}
    hu = str(data.get("hold_until") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", hu):
        out["hold_until"] = hu
    lang = str(data.get("language") or "").strip().lower()
    if re.match(r"^[a-z]{2}$", lang):
        out["language"] = lang
    return out


async def note(llm, transcript: list[tuple[str, str]], inbound_text: str, reply: str) -> dict | None:
    """One light completion, no tools. None when it cannot be read."""
    lines = [f"{'Customer' if r == 'customer' else ('Colleague' if r == 'team' else 'Neema')}: "
             f"{' '.join(t.split())[:300]}" for r, t in transcript[-12:]]
    if inbound_text:
        lines.append(f"Customer: {' '.join(inbound_text.split())[:400]}")
    if reply:
        lines.append(f"Neema: {' '.join(reply.split())[:300]}")
    today = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%A %Y-%m-%d")
    user = f"Today is {today} (Nairobi).\n\n" + "\n".join(lines)
    res = await llm.complete(system=_NOTE_SYSTEM, messages=[{"role": "user", "content": user}], tools=[])
    return parse_note(getattr(res, "text", None))


# ── storing and reading ──────────────────────────────────────────────────────

def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def hold_open(deal, *, now: datetime | None = None) -> tuple[datetime, str] | None:
    """(until, what they said) while the customer's own request for time
    stands — read by the dispatcher and the live turn."""
    nxt = getattr(deal, "next_action", None) or {}
    hold = nxt.get("hold") if isinstance(nxt, dict) else None
    if not isinstance(hold, dict) or not hold.get("until"):
        return None
    try:
        until = _aware(datetime.fromisoformat(hold["until"]))
    except (TypeError, ValueError):
        return None
    if until <= (now or datetime.now(timezone.utc)):
        return None
    return until, str(hold.get("said") or "needs_time")


def _default_until(now: datetime) -> datetime:
    days = int(getattr(settings, "customer_hold_days", 7) or 7)
    nbo = now + timedelta(hours=3)
    return (nbo + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(hours=3)


async def apply(db, conv, deal, reading: dict, *, source: str, inbound_text: str = "",
                now: datetime | None = None) -> dict:
    """Persist one reading (floor or model note). Returns what changed, for
    logs and tests. Commits. Never marks anything paid, never overwrites an
    open team check, never clears a hold on a reading that merely failed."""
    from sqlalchemy.orm.attributes import flag_modified
    now = now or datetime.now(timezone.utc)
    said = reading.get("customer_said") or "none"
    changed: dict = {"said": said, "source": source}

    # ── the person: language and the latest state ────────────────────────
    person = None
    if getattr(conv, "person_id", None) is not None:
        from app.models.person import Person
        person = await db.get(Person, conv.person_id)
    if person is not None:
        try:
            from app.services.state_lock import lock_for_write
            person = await lock_for_write(db, person)
        except Exception:
            pass
        state = dict(person.state or {})
        prefs = dict(state.get("contact_preferences") or {})
        lang = reading.get("language") or guess_language(inbound_text)
        if lang and prefs.get("language") != lang:
            prefs["language"] = lang
            changed["language"] = lang
        state["contact_preferences"] = prefs
        state["customer_state"] = {"said": said, "waiting_on": reading.get("waiting_on"),
                                   "at": now.isoformat(timespec="seconds"), "source": source,
                                   "hold_until": reading.get("hold_until")}
        person.state = state
        try:
            flag_modified(person, "state")
        except Exception:
            pass

    # ── the deal: holds and claims ───────────────────────────────────────
    if deal is not None:
        nxt = dict(deal.next_action or {}) if isinstance(deal.next_action, dict) else {}
        if said in HOLD_STATES:
            until = None
            if reading.get("hold_until"):
                try:
                    until = _aware(datetime.fromisoformat(reading["hold_until"]))
                    if until.hour == 0 and until.minute == 0:
                        until = until.replace(hour=7)         # 10:00 Nairobi on their day
                except (TypeError, ValueError):
                    until = None
            until = until or _default_until(now)
            nxt["hold"] = {"until": until.isoformat(timespec="seconds"), "said": said,
                           "since": now.isoformat(timespec="seconds"), "source": source}
            deal.next_action = nxt
            if not (nxt.get("kind") == "team_check"):
                deal.blocking = f"{_HOLD_LABEL[said]} — until {(until + timedelta(hours=3)).strftime('%d %b')}"
            changed["hold_until"] = nxt["hold"]["until"]
        elif nxt.get("hold") and (inbound_text or "").strip() and (
                said in ("exploring", "quoting", "ready") or _buying_message(inbound_text)):
            # They came back with a real message: the time they asked for is over.
            nxt.pop("hold", None)
            deal.next_action = nxt or None
            if deal.blocking and deal.blocking.split(" — ")[0] in _HOLD_LABEL.values():
                deal.blocking = None
            changed["hold_cleared"] = True
        if said == "paid_claim":
            deal.blocking = "Says they have paid — awaiting the hub's confirmation (never mark paid by hand)"
            changed["paid_claim"] = True
        if reading.get("open_item_check") and nxt.get("kind") != "team_check":
            # The model noticed an item under confirmation the tool did not record.
            changed["open_item_check"] = reading["open_item_check"]
        try:
            flag_modified(deal, "next_action")
        except Exception:
            pass
    await db.commit()
    return changed


def _buying_message(text: str) -> bool:
    """A question or a buying signal from a customer on hold: the time they
    asked for is over, whatever the floor read (W2, 2026-11-06). The floor
    never returns exploring/quoting, so before this a hold outlived the
    customer's return whenever the model note was off."""
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    try:
        from app.agent.cooling import buying_signal
        return bool(buying_signal(t))
    except Exception:
        return False


def language_of(person) -> str | None:
    from app.services.intent import preferences
    return (preferences(person) or {}).get("language") if person is not None else None


def turn_note(deal, person, *, now: datetime | None = None) -> str | None:
    """What the next LIVE turn must know, in one note: an open hold (do not
    re-ask for a date, do not re-pitch), a pending team check, a payment
    claim. None when nothing stands."""
    bits = []
    hold = hold_open(deal, now=now) if deal is not None else None
    if hold:
        until, said = hold
        bits.append(f"they asked for time ({_HOLD_LABEL.get(said, said).lower()}) until "
                    f"{(until + timedelta(hours=3)).strftime('%A %d %b')} — do NOT ask again when "
                    "they will decide, do NOT re-pitch or re-list; answer what they ask and wait")
    if deal is not None:
        try:
            from app.services.deals import team_check_open
            item = team_check_open(deal, now=now)
        except Exception:
            item = None
        if item:
            bits.append(f"the team is still confirming '{item}' — never ask them to start, confirm "
                        "or pay for that item until the answer is in this chat")
        if (deal.blocking or "").startswith("Says they have paid"):
            bits.append("they say they have paid and the hub has not confirmed it — thank them, "
                        "say the confirmation reaches them here automatically, never announce it as received")
    if not bits:
        return None
    return "(CUSTOMER STATE: " + "; ".join(bits) + ".)"


async def after_turn(db, conv, deal, *, inbound_text: str, reply: str, transcript=None,
                     llm=None, reading: dict | None = None, now: datetime | None = None) -> dict | None:
    """The scribe's hook: floor first, then the model's note when the floor
    found nothing and a model is given. Returns what was applied."""
    now = now or datetime.now(timezone.utc)
    if reading is None:
        reading = floor(inbound_text, now=now)
    source = "floor"
    if reading is None and llm is not None and (inbound_text or "").strip():
        try:
            if transcript is None:
                transcript = await _transcript(db, conv)
            reading = await note(llm, transcript or [], inbound_text, reply)
            source = "note"
        except Exception as exc:
            _log.info("state note skipped for %s: %s", getattr(conv, "id", "?"), exc)
            reading = None
    if reading is None:
        reading = {"customer_said": "none"}
        source = "none"
    if not reading.get("language"):
        reading["language"] = guess_language(inbound_text)
    return await apply(db, conv, deal, reading, source=source, inbound_text=inbound_text, now=now)


async def _transcript(db, conv, limit: int = 12) -> list[tuple[str, str]]:
    """The last turns as (role, text): customer / team / neema. Notes stay out."""
    from sqlalchemy import select
    from app.models.message import Message, MsgDirection, MsgSender
    rows = (await db.execute(
        select(Message.direction, Message.sender, Message.text)
        .where(Message.conversation_id == conv.id, Message.text.isnot(None),
               Message.media_type.is_(None) | (Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(limit))).all()
    out = []
    for direction, sender, text in reversed(rows):
        role = ("customer" if direction == MsgDirection.inbound
                else ("team" if sender == MsgSender.human_agent else "neema"))
        out.append((role, text or ""))
    return out


def note_llm():
    """The light model for the note — None when the note is off or no key is
    configured (tests, a box without the key): the floor alone then stands."""
    if not getattr(settings, "customer_state_note", True) or not getattr(settings, "anthropic_api_key", ""):
        return None
    try:
        from app.agent.runtime import build_llm
        return build_llm(model=getattr(settings, "tier2_model_light", None) or None, purpose="state")
    except Exception:
        return None


# ── what the dispatcher asks ─────────────────────────────────────────────────

async def hold_for(db, action, *, now: datetime | None = None) -> tuple[datetime, str] | None:
    """The open hold on the deal this row belongs to (or the conversation's
    open deal when the row names none) — (until, said) or None."""
    from app.services.deals import open_deal_for
    deal = None
    try:
        if getattr(action, "deal_id", None) is not None:
            from app.models.deal import Deal
            deal = await db.get(Deal, action.deal_id)
        if deal is None and getattr(action, "conversation_id", None) is not None:
            deal = await open_deal_for(db, conversation_id=action.conversation_id)
    except Exception:
        return None
    return hold_open(deal, now=now) if deal is not None else None


async def language_for(db, conv) -> str | None:
    """The customer's stored language, or None when nothing is known."""
    pid = getattr(conv, "person_id", None)
    if pid is None:
        return None
    try:
        from app.models.person import Person
        return language_of(await db.get(Person, pid))
    except Exception:
        return None


def automated_ok(lang: str | None) -> bool:
    return lang is None or lang in AUTOMATED_LANGUAGES


async def live_note(db, key: str, channel: str, *, now: datetime | None = None) -> str | None:
    """`turn_note` for the live turn, from the conversation key."""
    from app.services.deals import _conversation_of, open_deal_for
    conv = await _conversation_of(db, key, channel)
    if conv is None:
        return None
    deal = await open_deal_for(db, conversation_id=conv.id)
    person = None
    if getattr(conv, "person_id", None) is not None:
        from app.models.person import Person
        person = await db.get(Person, conv.person_id)
    return turn_note(deal, person, now=now)
