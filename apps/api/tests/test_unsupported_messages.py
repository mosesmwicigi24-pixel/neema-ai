"""No inbound WhatsApp message may become an empty row.

An empty bubble reads as a bug and hides that the customer said something.
Reactions, catalog carts and Meta's "unsupported" type all get visible text;
reactions additionally never wake the agent (a 👍 must not earn a sales reply).
"""
from app.services.wa_native import parse_events


def _payload(msg: dict) -> dict:
    return {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": "254700000009", "profile": {"name": "Test"}}],
        "messages": [{"from": "254700000009", "id": "wamid.X",
                      "timestamp": "1755300000", **msg}]}}]}]}


def test_a_reaction_gets_visible_text():
    evts = parse_events(_payload({"type": "reaction",
                                  "reaction": {"emoji": "👍", "message_id": "wamid.Y"}}))
    assert evts and evts[0]["text"] == "👍 (reacted to your message)"
    assert evts[0]["type"] == "reaction"    # the ingest gate keys off this


def test_a_catalog_cart_is_summarised():
    evts = parse_events(_payload({"type": "order", "order": {
        "catalog_id": "1", "product_items": [
            {"product_retailer_id": "tray", "quantity": 2},
            {"product_retailer_id": "cups", "quantity": 1}]}}))
    # The count still leads; the SKUs follow so the agent can see WHAT is in
    # the cart (cycle 2, 2026-10-05) — it used to be told only "3 items".
    assert evts[0]["text"].startswith("🛒 Sent a cart from the catalog: 3 items")
    assert "tray ×2" in evts[0]["text"] and "cups ×1" in evts[0]["text"]


def test_an_unknown_type_is_never_blank_and_keeps_metas_reason():
    # Cycle 2 (2026-10-05): the old line ("… (unsupported type) — ask them to
    # resend as text") named OUR parser's blind spot, not the message. Now the
    # words are calm and the record keeps Meta's type + error for the team.
    evts = parse_events(_payload({"type": "unsupported",
                                  "errors": [{"code": 131051}]}))
    assert evts[0]["text"].strip()
    assert "WhatsApp doesn't let us show" in evts[0]["text"]
    assert evts[0]["meta"]["type"] == "unsupported"
    assert evts[0]["meta"]["errors"] == [{"code": 131051}]


def test_plain_text_and_captions_are_untouched():
    evts = parse_events(_payload({"type": "text", "text": {"body": " habari "}}))
    assert evts[0]["text"] == "habari"
    evts = parse_events(_payload({"type": "image", "image": {
        "id": "m1", "mime_type": "image/jpeg", "caption": "how much?"}}))
    assert evts[0]["text"] == "how much?"
    assert evts[0]["media"]["kind"] == "image"
