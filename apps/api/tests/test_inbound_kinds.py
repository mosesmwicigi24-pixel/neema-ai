"""Cycle 2 (calls & audio programme, 2026-10-05): every WhatsApp message type
Meta can send becomes something a person — and the agent — understands, and
anything we can't show keeps Meta's own type + reason for the team.

Before: an interactive call-permission reply or a WhatsApp Flow submission
became an EMPTY row ("Message can't be displayed (unsupported type)" on the
dashboard), and every unknown type the same fixed sentence with the payload
thrown away. These scenarios pin each documented shape.
"""
import json

from app.services.inbound_kinds import describe, public_meta, redact
from app.services.wa_native import parse_events


def _one(msg: dict) -> dict:
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": "254700000009", "profile": {"name": "Grace"}}],
        "messages": [{"from": "254700000009", "id": "wamid.K1",
                      "timestamp": "1759600000", **msg}]}}]}]}
    evts = parse_events(payload)
    assert len(evts) == 1
    return evts[0]


# 1 ── the near-call empty row: a call-permission reply ──────────────────────
def test_call_permission_reply_is_never_an_empty_row():
    e = _one({"type": "interactive", "interactive": {
        "type": "call_permission_reply",
        "call_permission_reply": {"response": "accept", "is_permanent": False,
                                  "expiration_timestamp": 1760000000,
                                  "response_source": "user_action"}}})
    assert e["text"] == "✅ Allowed WhatsApp calls"
    assert e["meta"]["kind"] == "call_permission"
    assert e["meta"]["response"] == "accept" and e["meta"]["expires_at"] == 1760000000
    assert e["wake"] is False            # plumbing — the call tap handles it


def test_call_permission_declined_and_permanent_read_correctly():
    rej = _one({"type": "interactive", "interactive": {
        "type": "call_permission_reply", "call_permission_reply": {"response": "reject"}}})
    perm = _one({"type": "interactive", "interactive": {
        "type": "call_permission_reply",
        "call_permission_reply": {"response": "accept", "is_permanent": True}}})
    assert rej["text"] == "🚫 Declined WhatsApp calls"
    assert perm["text"] == "✅ Allowed WhatsApp calls — permanently"


# 2 ── reactions: emoji, removal, the message they reacted to ────────────────
def test_reaction_keeps_the_target_and_never_wakes_the_agent():
    e = _one({"type": "reaction", "reaction": {"emoji": "❤️", "message_id": "wamid.OURS"}})
    assert e["text"] == "❤️ (reacted to your message)"
    assert e["meta"] == {"v": 1, "type": "reaction", "kind": "reaction",
                         "emoji": "❤️", "to_wamid": "wamid.OURS"}
    assert e["wake"] is False


def test_reaction_removed_is_said_in_words():
    e = _one({"type": "reaction", "reaction": {"message_id": "wamid.OURS"}})
    assert e["text"] == "Removed their reaction"
    assert e["wake"] is False


# 3 ── sticker ───────────────────────────────────────────────────────────────
def test_sticker_is_a_sticker_not_a_product_photo():
    e = _one({"type": "sticker", "sticker": {"id": "M9", "mime_type": "image/webp", "animated": True}})
    assert e["text"] == "🙂 Sent a sticker"
    assert e["meta"]["kind"] == "sticker" and e["meta"]["animated"] is True
    assert e["media"]["kind"] == "image"     # still rehosted + shown
    assert e["wake"] is False                # never priced from


# 4 ── location ──────────────────────────────────────────────────────────────
def test_location_carries_coordinates_for_a_map_link():
    e = _one({"type": "location", "location": {
        "latitude": -1.2864, "longitude": 36.8172, "name": "Bethany House", "address": "Moi Ave"}})
    assert e["text"] == "📍 Location: Bethany House, Moi Ave (-1.2864,36.8172)"
    assert e["meta"]["lat"] == -1.2864 and e["meta"]["lng"] == 36.8172
    assert e["wake"] is True


def test_bare_pin_location_still_reads():
    e = _one({"type": "location", "location": {"latitude": 0.5, "longitude": 35.2}})
    assert e["text"] == "📍 Location: 0.5,35.2"


# 5 ── contacts ──────────────────────────────────────────────────────────────
def test_shared_contact_gives_the_agent_the_number():
    e = _one({"type": "contacts", "contacts": [{
        "name": {"formatted_name": "Fr. Peter Kamau"},
        "phones": [{"phone": "+254 722 000 111", "wa_id": "254722000111", "type": "CELL"}]}]})
    assert e["text"] == "👤 Shared contact: Fr. Peter Kamau (+254 722 000 111)"
    assert e["meta"]["contacts"][0]["phones"] == ["+254 722 000 111"]


# 6 ── interactive replies + WhatsApp Flows ──────────────────────────────────
def test_list_reply_and_template_button_keep_their_title():
    lst = _one({"type": "interactive", "interactive": {
        "type": "list_reply", "list_reply": {"id": "r1", "title": "Red chasuble", "description": "KES 18,000"}}})
    btn = _one({"type": "button", "button": {"payload": "YES", "text": "Yes please"}})
    assert lst["text"] == "Red chasuble" and lst["meta"]["kind"] == "reply"
    assert btn["text"] == "Yes please" and btn["meta"]["source"] == "template_button"


def test_flow_submission_was_empty_and_now_carries_the_answers():
    e = _one({"type": "interactive", "interactive": {
        "type": "nfm_reply", "nfm_reply": {
            "name": "flow", "body": "Sent",
            "response_json": json.dumps({"flow_token": "SECRET", "size": "XL", "colour": "white"})}}})
    assert e["text"] == "📝 Submitted a form — size: XL; colour: white"
    assert "flow_token" not in e["meta"]["fields"]
    assert e["wake"] is True


def test_unknown_interactive_type_is_never_blank():
    e = _one({"type": "interactive", "interactive": {"type": "something_new", "something_new": {"x": 1}}})
    assert e["text"].strip()
    assert e["meta"]["kind"] == "unsupported" and e["meta"]["subtype"] == "something_new"
    assert "payload" in e["meta"]


# 7 ── catalog order ─────────────────────────────────────────────────────────
def test_order_lists_skus_total_and_note():
    e = _one({"type": "order", "order": {"catalog_id": "C1", "text": "for Sunday", "product_items": [
        {"product_retailer_id": "ALB-01", "quantity": "2", "item_price": 4500, "currency": "KES"},
        {"product_retailer_id": "STO-RED", "quantity": 1, "item_price": 3000, "currency": "KES"}]}})
    assert e["text"] == ('🛒 Sent a cart from the catalog: 3 items — ALB-01 ×2, STO-RED ×1 '
                         '(KES 12,000). Note: "for Sunday"')
    assert e["meta"]["count"] == 3 and e["meta"]["total"] == "KES 12,000"


# 8 ── system notices ────────────────────────────────────────────────────────
def test_number_change_is_team_info_not_a_turn():
    e = _one({"type": "system", "system": {
        "body": "User A changed from 254700000009 to 254711000222",
        "type": "user_changed_number", "new_wa_id": "254711000222"}})
    assert e["text"] == "📱 Changed their WhatsApp number to +254711000222"
    assert e["wake"] is False and e["meta"]["kind"] == "system"


# 9 ── request_welcome ───────────────────────────────────────────────────────
def test_request_welcome_greets_instead_of_asking_to_resend():
    e = _one({"type": "request_welcome"})
    assert e["text"] == "👋 Opened a chat with us for the first time"
    assert e["wake"] is True
    assert "Greet them" in e["agent_text"] and "resend" not in e["agent_text"]


# 10 ── unsupported: 131051 with and without the feature named ───────────────
def test_unsupported_view_once_names_the_feature_and_keeps_metas_error():
    e = _one({"type": "unsupported", "unsupported": {"type": "view_once"},
              "errors": [{"code": 131051, "title": "Message type unknown",
                          "message": "Message type unknown",
                          "error_data": {"details": "Message type is currently not supported."}}]})
    assert e["text"].startswith("Sent something WhatsApp doesn't let us show here — a view-once photo or video.")
    m = e["meta"]
    assert m["kind"] == "unsupported" and m["subtype"] == "view_once"
    assert m["errors"] == [{"code": 131051, "title": "Message type unknown",
                            "details": "Message type is currently not supported."}]
    assert m["payload"]["type"] == "unsupported"
    assert e["wake"] is True and "resend" not in e["agent_text"]


def test_unsupported_with_nothing_named_reads_calmly():
    e = _one({"type": "unsupported", "errors": [{"code": 131051, "title": "Message type unknown"}]})
    assert e["text"] == ("Sent something WhatsApp doesn't let us show here. "
                         "You can ask them to send it as a photo or text.")
    assert "⚠️" not in e["text"]


def test_edited_and_deleted_are_said_and_stay_silent():
    ed = _one({"type": "unsupported", "unsupported": {"type": "edit"}, "errors": [{"code": 131051}]})
    de = _one({"type": "revoked"})
    assert ed["meta"]["kind"] == "edited" and ed["wake"] is False
    assert de["text"] == "🗑️ Deleted a message" and de["wake"] is False


def test_future_type_is_named_from_metas_type():
    e = _one({"type": "poll", "poll": {"question": "Which colour?"}})
    assert "a poll" in e["text"] and e["meta"]["type"] == "poll"
    # The poll question is the customer's words — never kept in the copy.
    assert e["meta"]["payload"]["poll"]["question"] == "<str:13>"


# 11 ── PII: the payload copy is structure only, and bounded ─────────────────
def test_payload_copy_redacts_people_and_is_bounded():
    msg = {"type": "unsupported", "from": "254700000009", "id": "wamid.K1",
           "text": {"body": "my secret"}, "location": {"latitude": -1.2, "longitude": 36.8},
           "contacts": [{"name": {"formatted_name": "X"}}] * 20,
           "huge": "y" * 50_000, "errors": [{"code": 131051, "title": "Message type unknown"}]}
    m = describe(msg)["meta"]
    raw = json.dumps(m["payload"])
    assert "254700000009" not in raw and "my secret" not in raw
    assert "-1.2" not in raw and "36.8" not in raw
    assert len(raw.encode()) <= 2048
    assert m["payload"]["errors"][0]["title"] == "Message type unknown"   # structure kept


def test_public_meta_never_exposes_the_payload_copy():
    m = describe({"type": "unsupported", "errors": [{"code": 131051}]})["meta"]
    assert "payload" in m and "payload" not in public_meta(m)
    assert public_meta(None) is None


def test_hostile_depth_and_width_are_cut():
    deep: dict = {}
    cur = deep
    for _ in range(50):
        cur["x"] = {}
        cur = cur["x"]
    wide = {f"k{i}": i for i in range(500)}
    assert "<…>" in json.dumps(redact(deep), ensure_ascii=False)
    assert len(redact(wide)) == 31


# 12 ── plain types stay plain (no record, same words as before) ─────────────
def test_plain_text_and_media_carry_no_record():
    t = _one({"type": "text", "text": {"body": " habari "}})
    a = _one({"type": "audio", "audio": {"id": "A1", "mime_type": "audio/ogg"}})
    assert t["text"] == "habari" and t["meta"] is None and t["wake"] is True
    assert a["text"] == "" and a["meta"] is None


def test_media_with_metas_errors_keeps_the_error():
    e = _one({"type": "image", "image": {"id": "I1"},
              "errors": [{"code": 131052, "title": "Media download error"}]})
    assert e["meta"] == {"v": 1, "type": "image", "kind": "plain",
                         "errors": [{"code": 131052, "title": "Media download error"}]}


# 13 ── voicemail is marked for its call card ────────────────────────────────
def test_voicemail_audio_is_linked_to_its_call():
    payload = {"entry": [{"changes": [{"field": "messages", "value": {"messages": [
        {"from": "254700000009", "id": "wacid.ABC", "type": "audio",
         "audio": {"id": "VM1", "mime_type": "audio/ogg"}}]}}]}]}
    e = parse_events(payload)[0]
    assert e["meta"] == {"v": 1, "type": "audio", "kind": "voicemail", "call_id": "wacid.ABC"}
