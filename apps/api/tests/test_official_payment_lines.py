"""Our own M-Pesa and Airtel Money lines are payments TO Bethany House
(owner, 2026-10-27; "+254785490805 is Airtel payment number").

Pst Samuel Kiarie paid KES 2,500 to 0727 891 989 — our official line — and
Neema answered "That payment went to a personal M-Pesa number, not Bethany
House" and later "this looks like someone impersonating us". M-Pesa shows the
name the line is registered to (a person's), and her only rule was "never ask
them to pay a personal number". Now the M-Pesa line, the Airtel Money line,
the link, bank, Western Union and MoneyGram are her official channels, and the
reviewer holds the mistake.
"""
import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import prompt, review

RECEIPT = ("UJQFRB8NSA Confirmed. Ksh2,500.00 sent to MOSES NG'ANG'A 0727891989 on 26/10/26 "
           "at 6:18 PM. New M-PESA balance")


def test_both_official_lines_and_every_route_are_in_her_rules():
    for iso, ccy in (("KE", "KES"), ("ZA", "USD"), ("", "USD")):
        rules = prompt.build_system_prompt(country_iso=iso, currency=ccy)
        assert "OUR OFFICIAL PAYMENT CHANNELS" in rules
        assert "+254727891989" in rules and "+254785490805" in rules
        assert "0727891989" in rules and "0785490805" in rules   # the local way, too
        # Each line on its own rail: 0727 is M-Pesa, 0785 is Airtel Money.
        assert "M-Pesa (Send Money) to our own line: +254727891989" in rules
        assert "Airtel Money to our own line: +254785490805" in rules
        assert "Bank transfer" in rules
        # Kenyans pay by M-Pesa (owner, 2026-08-22): the international rails
        # are named only for customers abroad.
        for route in ("Western Union", "MoneyGram"):
            assert (route in rules) is (ccy != "KES"), (iso, route)
        assert "never ask them to pay a personal number" not in rules
        assert "impersonation" in rules       # named only to forbid it


def test_a_payment_to_our_line_called_personal_or_fraud_is_held():
    for wrong in ("That payment went to a personal M-Pesa number, not Bethany House — please "
                  "note that is not our official line.",
                  "I've flagged this — this looks like someone impersonating us.",
                  "Please be careful, that could be a scam."):
        found = review.payment_line_issues(RECEIPT, wrong)
        assert found and found[0]["hard"] and "+254727891989" in found[0]["text"], wrong


def test_the_same_line_in_any_form_and_the_second_line_count():
    for said in ("sent to 254727891989", "paid +254 727 891 989", "I sent to 0785490805",
                 "sent to MOSES 0727891989", "paid 0785 490 805"):
        assert review.our_lines_named(said), said


def test_thanking_them_passes_and_a_stranger_s_number_may_be_questioned():
    good = ("Thank you, Pastor — we've noted M-Pesa code UJQFRB8NSA; the team will match it "
            "to your order.")
    assert review.payment_line_issues(RECEIPT, good) == []
    stranger = "UJQ1 Confirmed. Ksh2,500.00 sent to JOHN DOE 0711000111"
    assert review.payment_line_issues(stranger, "That isn't one of our lines — a colleague "
                                                "will look into it with you.") == []


def test_the_receipt_earlier_in_the_thread_still_counts():
    transcript = [{"role": "user", "content": RECEIPT},
                  {"role": "assistant", "content": "Noted."},
                  {"role": "user", "content": "Is it not yours?"}]
    found = review.payment_line_issues("Is it not yours?", "No — it is not our official line.",
                                       transcript)
    assert found and found[0]["kind"] == "payment_line"
    assert any(f["kind"] == "payment_line" for f in review.rule_findings(
        "Is it not yours?", "No — it is not our official line.", [], transcript=transcript))


def test_an_airtel_money_payment_to_our_airtel_line_is_ours_too():
    airtel = ("TID: MP261026.1830.A12345 Confirmed. You have sent Ksh 2,500.00 to "
              "0785490805 MOSES NGANGA. Airtel Money")
    found = review.payment_line_issues(airtel, "That number is not our official line.")
    assert found and "+254785490805" in found[0]["text"]
