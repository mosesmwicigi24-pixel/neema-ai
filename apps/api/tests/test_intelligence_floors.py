"""Workstream 2 (intelligence programme, 2026-11-06): the deterministic floor
reads what customers actually write. Every phrasing here came from the
independent case set's misses on the development half; the negatives are the
developer file that guards against overreach. The held-out numbers live in
docs/intelligence/BENCHMARK_RESULTS.md, not here."""
from __future__ import annotations

import pytest

from app.agent.runtime import is_closer
from app.agent.voice import looks_swahili
from app.services.customer_state import floor, guess_language
from app.services.deals import detect_customer_promise
from app.services.intent import is_opt_out


def said(text):
    return (floor(text) or {}).get("customer_said")


@pytest.mark.parametrize("text", [
    "Paid", "paid", "Done, paid", "Paid by card", "Paid. 46 white, Kisumu", "Paid. Mpesa ref RKJ7H2X9PL",
    "Mpesa deducted 4500 but you have not confirmed anything", "Sent 2500", "Ok I've sent the half",
    "Sent via Mukuru, reference shared", "nimetuma", "Nimetuma, cheki.",
    "Our treasurer has paid for the 12 choir robes, check your account and start the work",
    "[image] here is the mpesa screenshot, paid",
])
def test_a_bare_payment_claim_is_read(text):
    assert said(text) == "paid_claim", text


@pytest.mark.parametrize("text", [
    "I will pay tomorrow morning", "I have not paid yet, waiting for the invoice", "How do I pay? Paybill?",
    "Can I pay on delivery?", "Sijalipa bado", "I have sent the photo of the old cassock",
    "I received an incense burner instead of the communion tray I paid for",
])
def test_a_future_or_negated_payment_is_not_a_claim(text):
    assert said(text) != "paid_claim", text


@pytest.mark.parametrize("text", [
    "I'll take one. Delivery to Thika town", "Ok go for it", "Size 42 is right, continue",
    "Please invoice me for the cassock", "Approved! send invoice", "Approved. How do we pay from Nigeria?",
    "ok sort me out, I'll pay via Mpesa", "sawa, nitume mpesa", "sawa, tuma till number", "Yes that one. Send the till.",
    "Je confirme, je paie par Western Union demain.",
])
def test_readiness_is_read_in_the_words_customers_use(text):
    assert said(text) == "ready", text


@pytest.mark.parametrize("text", [
    "Do you have ready-made cassocks or is it custom?", "I will take about 50 cups, how much would that be?",
])
def test_readiness_is_not_read_into_a_question(text):
    assert said(text) != "ready", text


@pytest.mark.parametrize("text", [
    "Please contact me on Thursday.", "Call me after 4pm.", "Let's talk next week", "Let me revert",
    "Let me pray about it", "Let me arrange the money and come back", "Hmm on second thought let me wait till after Easter",
    "our treasurer is away till the 20th", "Will revert", "Je vous reviens la semaine prochaine.", "Merci, je réfléchis.",
    "Está bem, volto a falar.", "Nitalipa kesho asubuhi", "ok we are fundraising, will come back in 2 months",
    "Don't send it yet, I need to confirm the address first",
])
def test_a_request_for_time_is_read(text):
    assert said(text) == "needs_time", text


@pytest.mark.parametrize("text", [
    "Deliver it on Thursday please, to the church office", "Let me know, do you have size 46?",
])
def test_a_delivery_date_or_a_question_is_not_a_request_for_time(text):
    assert said(text) != "needs_time", text


@pytest.mark.parametrize("text", [
    "Let me check with the diocese", "ok the elders will decide", "ok let me present to the committee",
    "Let me take this to the finance committee", "ok let me ask the chairman", "ok will confirm with him",
    "I will present it to His Lordship and revert.", "Je dois consulter le conseil paroissial.", "Je transmets à Monseigneur.",
    "Ngoja kwanza, bishop anasema tungoje", "Tutarudi baada ya mkutano wa wazee wa kanisa.", "Nitamshow bishop.",
])
def test_consulting_someone_is_read(text):
    assert said(text) == "consulting", text


def test_a_consultation_at_our_shop_is_not_consulting_someone():
    assert said("Can I come to the shop for a consultation on sizes?") is None


@pytest.mark.parametrize("text", [
    "You sent a red stole, I ordered GREEN!", "The cope arrived with the box crushed and the gold trim bent",
    "The lady at your shop was very rude to my wife today", "The clerical shirts are all size 42, I ordered 40",
    "The bishop's set came without the mitre", "The tracking hasn't moved for 5 days",
    "Where is my order? It was supposed to come yesterday", "I have been waiting for a reply since morning, is anyone there??",
    "We ordered 30 communion cups, the box has 24", "Kanzu niliyoagiza bado haijafika na nililipa wiki iliyopita",
    "Ma commande devait arriver avant la Pentecôte et je n'ai rien reçu. C'est inadmissible.",
])
def test_a_complaint_is_read_with_or_without_a_question_mark(text):
    assert said(text) == "complaint", text


@pytest.mark.parametrize("text", [
    "Is it normal for delivery to be late by a day?", "What is your refund policy if the size is wrong?",
])
def test_a_question_about_lateness_or_refunds_is_not_a_complaint(text):
    assert said(text) != "complaint", text


@pytest.mark.parametrize("text", [
    "Thank you very much.", "Thanks so much", "Thanks for the invoice", "Thanks for understanding", "cheers",
    "Great, thanks", "Ok thank you", "Hmm ok", "Noted with thanks.", "Sawa, asante sana.", "Merci, que Dieu vous bénisse.",
    "Obrigado, fique com Deus.", "Mungu akubariki, mwanangu.", "Ok now I understand, thank you",
])
def test_long_thank_yous_are_closers(text):
    assert is_closer(text), text
    assert said(text) == "closing", text


@pytest.mark.parametrize("text", [
    "Thanks, but how much is the stole?", "Thank you very much, please send me the payment details",
])
def test_a_thank_you_with_an_ask_is_not_a_closer(text):
    assert not is_closer(text), text


@pytest.mark.parametrize("text", [
    "STOP", "Usinitumie tena, sitaki", "Wrong number, I never contacted you. Stop.",
    "I told you on Facebook to stop messaging me. Why are you now on my WhatsApp?", "Please stop messaging me.",
])
def test_an_opt_out_is_recognised(text):
    assert is_opt_out(text), text
    assert said(text) == "stop"


@pytest.mark.parametrize("text", [
    "Stop sending the trays, I only need the cups now", "Stop, wait — I meant the purple one",
    "Don't stop the order, go ahead", "Sitaki hii, nataka ile nyingine ya rangi ya zambarau", "Stop by the shop tomorrow?",
])
def test_stop_inside_an_instruction_is_not_an_opt_out(text):
    assert not is_opt_out(text), text


@pytest.mark.parametrize("text,lang", [
    ("Aceitam cartão? Ou só Western Union?", "pt"), ("Olá, óleo de unção e velas de altar, vendem?", "pt"),
    ("Le paiement se fait comment depuis le Rwanda ?", "fr"), ("Merci.", "fr"), ("Et en blanc ?", "fr"),
    ("D'accord, je vais en parler à l'abbé et je reviens vers vous.", "fr"), ("Arrête de m'écrire.", "fr"),
    ("Hello, chasuble ka price kya hai? Purple colour mein.", "hi"), ("Mungu akubariki.", "sw"), ("Mko wapi?", "sw"),
    ("God bless.", "en"), ("Too expensive.", "en"), ("Call me after 4pm.", "en"), ("Noted with thanks.", "en"),
])
def test_the_language_guess_covers_the_languages_customers_write(text, lang):
    assert guess_language(text) == lang, text


@pytest.mark.parametrize("text", ["ok", "Okay", "yes", "hi", "👍"])
def test_a_bare_acknowledgement_never_overwrites_a_stored_language(text):
    assert guess_language(text) is None


def test_french_with_two_je_is_not_swahili():
    assert not looks_swahili("Je confirme, je paie par Western Union demain.")
    assert looks_swahili("Je, bei gani ya stola?")


@pytest.mark.parametrize("text", [
    "Please contact me on Thursday.", "Call me tomorrow", "Let's talk next week", "Nitalipa kesho asubuhi",
    "Je vous recontacte lundi", "Volto a falar amanhã",
])
def test_the_customers_timeline_is_read_in_the_imperative_and_in_three_languages(text):
    assert detect_customer_promise(text) is not None, text


def test_the_developer_negatives_file_has_no_misses():
    from app.jobs import eval_cases, eval_floors
    res = eval_floors.score(eval_cases.load("developer_negatives.jsonl"))
    assert res["misses"] == [], res["misses"]
