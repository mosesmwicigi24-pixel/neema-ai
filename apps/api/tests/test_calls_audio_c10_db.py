"""Cycle 10 — the final independent re-break of the calls & audio programme.

What cycles 2-9 tested piece by piece is replayed here as whole journeys, with
only the outside world faked (Meta's Graph API over HTTP, the speech provider,
the Claude client, the WhatsApp send):

  · a WhatsApp voice note from Meta's webhook payload through the REAL media
    download (Graph metadata → CDN bytes → a served file with its extension)
    to the REAL agent turn (schedule_reply → run_turn) and the reply row;
  · a WhatsApp call from Meta's `calls` webhook through the softphone's
    recording upload (HTTP), the transcript, the brief, the call card the
    dashboard receives, the CRM note — and the web's own card code reading
    that exact JSON;
  · every inbound kind in production's mix, nulls included, from webhook to
    row to the thread payload to the web's renderer;
  · the deploy: the alembic upgrade FROM origin/main's schema with old rows in
    it, and main.py's startup statements on top of it.
"""
import asyncio
import json
import os
import shutil
import subprocess
import time
import types
import uuid

import pytest
import sqlalchemy as sa

import app.agent.runtime as _runtime_at_import
from tests.test_security_db import _as, _reachable, _sync_url, fresh_db  # noqa: F401
from tests import test_voice_notes_db as vn

rig, clips = vn.rig, vn.clips                    # the cycle-5 voice rig (fixtures)
drain_tasks, run, wa_payload = vn.drain_tasks, vn.run, vn.wa_payload

# The real trigger, captured before any fixture swaps it for a recorder.
_REAL_SCHEDULE_REPLY = _runtime_at_import.schedule_reply

pytestmark = [
    pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                       reason="needs a reachable Postgres (CI migrations job / Docker harness)"),
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg"),
]

WEB = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))


def _node_can_strip_types() -> bool:
    """The web's libs are .ts; Node ≥ 22.18 runs them without a build."""
    node = shutil.which("node")
    if not node or not os.path.isdir(os.path.join(WEB, "src", "lib")):
        return False
    try:
        v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout
        major, minor = (int(x) for x in v.strip().lstrip("v").split(".")[:2])
        return (major, minor) >= (22, 18)
    except Exception:
        return False


def _web(script: str, data) -> dict:
    """Run `script` (an ES module body) under Node with `DATA` bound to `data`;
    it prints one JSON value, returned here."""
    src = f"const DATA = {json.dumps(data)};\n{script}"
    r = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True,
                       cwd=os.path.join(WEB, "tests"), timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class _GraphAndCdn:
    """Meta's Graph API (media metadata) and its CDN (the bytes), over httpx."""

    def __init__(self, files: dict):
        self.files = files            # media_id → (mime_type, bytes)
        self.requests: list = []

    def handler(self, request):
        import httpx
        self.requests.append((request.method, str(request.url), request.headers.get("authorization")))
        url = str(request.url)
        for mid, (mime, blob) in self.files.items():
            if url == f"https://lookaside.fbsbx.com/cdn/{mid}":
                return httpx.Response(200, content=blob, headers={"content-type": mime})
            if url.startswith("https://graph.facebook.com/") and url.endswith(f"/{mid}"):
                return httpx.Response(200, json={"url": f"https://lookaside.fbsbx.com/cdn/{mid}",
                                                 "mime_type": mime, "id": mid})
        return httpx.Response(404, json={"error": "not faked"})


def _patch_httpx(monkeypatch, fake):
    import httpx
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(fake.handler)
        return real(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", client)


# ═════════════════════════════════════════════════════════════════════════════
# 1 · A WhatsApp voice note, webhook → real download → words → agent → reply
# ═════════════════════════════════════════════════════════════════════════════

def test_voice_note_end_to_end_real_download_real_agent_turn(rig, clips, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.agent.runtime as runtime
    from app.agent.llm import FakeLLM
    from app.models.message import Message, MsgDirection
    from app.routers import media as media_router
    from app.services import n8n_bridge, wa_native

    wa, wamid = "254711100001", "wamid.C10VOICE1"
    with open(clips[3], "rb") as f:
        ogg = f.read()
    graph = _GraphAndCdn({f"media-{wamid}": ("audio/ogg; codecs=opus", ogg)})
    _patch_httpx(monkeypatch, graph)
    monkeypatch.setattr(rig.settings, "waba_token", "test-waba-token")
    monkeypatch.setattr(rig.settings, "media_public_url", "https://neema.test")
    rig.provider.answers = [("Habari, nataka kasoki mbili za size 42, ni bei gani?", None)]
    rig.llm.answers["translate-voice"] = json.dumps(
        {"lang": "Swahili", "en": "Hello, I want two cassocks size 42, how much?"})

    # The REAL trigger: schedule_reply → _run_and_send → run_turn, with the
    # Claude client faked and the WhatsApp send captured.
    monkeypatch.setattr(runtime, "schedule_reply", _REAL_SCHEDULE_REPLY)
    seen: list = []

    class Agent(FakeLLM):
        async def complete(self, *, system, messages, tools, tool_choice=None):
            seen.append(messages)
            return await super().complete(system=system, messages=messages, tools=tools)

    agent = Agent([{"text": "Karibu! Kasoki za size 42 tunazo. Ungependa rangi gani?"}] * 4)
    built: list = []

    def build_llm(model=None, purpose="other", cache=None):
        built.append(purpose)
        return agent if purpose == "whatsapp" else rig.llm(model=model, purpose=purpose)
    monkeypatch.setattr(runtime, "build_llm", build_llm)
    sent: list = []

    async def send_waba(to, text, *a, **k):
        sent.append((to, text))
        return "wamid.OUT1"
    monkeypatch.setattr(n8n_bridge, "_send_waba", send_waba)

    async def go():
        n, failed = await wa_native.handle_webhook(wa_payload(wa, wamid), rig.redis)
        assert (n, failed) == (1, 0)
        await drain_tasks()
        for _ in range(200):                          # the reply task (runtime._bg_tasks)
            if sent:
                break
            await asyncio.sleep(0.05)
        async with rig.maker() as db:
            return (await db.execute(sa.select(Message).where(Message.wa_id == wa)
                                     .order_by(Message.created_at))).scalars().all()
    rows = run(go())

    # Hand-off 1: the Graph was asked with the WABA token, then the CDN.
    assert [r[1] for r in graph.requests][:2] == [
        f"https://graph.facebook.com/{rig.settings.waba_api_version}/media-{wamid}",
        f"https://lookaside.fbsbx.com/cdn/media-{wamid}"]
    assert all(r[2] == "Bearer test-waba-token" for r in graph.requests[:2])
    # Hand-off 2: the file is ours, with an extension, and the media route serves it.
    note = next(r for r in rows if r.media_type == "audio")
    assert note.media_url == f"https://neema.test/api/admin/media/wa_media-{wamid}.ogg"
    on_disk = os.path.join(rig.media_dir, f"wa_media-{wamid}.ogg")
    assert open(on_disk, "rb").read() == ogg
    app = FastAPI()
    app.include_router(media_router.router, prefix="/api")
    with TestClient(app) as cl:
        got = cl.get(f"/api/admin/media/wa_media-{wamid}.ogg")
    assert got.status_code == 200 and got.content == ogg
    # Hand-off 3: transcribed once, from the saved file, words on the row.
    assert len(rig.provider.calls) == 1
    assert (note.transcript_status, note.transcript_lang) == ("done", "sw")
    assert note.text == "Habari, nataka kasoki mbili za size 42, ni bei gani?"
    assert note.translated_text == "Hello, I want two cassocks size 42, how much?"
    # Hand-off 4: the agent's CURRENT turn is the customer's words — no token,
    # no "[audio]", no "(the customer sent a audio)".
    assert "whatsapp" in built and seen, built
    last_user = [m for m in seen[0] if m["role"] == "user"][-1]
    content = last_user["content"] if isinstance(last_user["content"], str) else json.dumps(
        last_user["content"], ensure_ascii=False)
    assert "🎤 (voice note): Habari, nataka kasoki mbili za size 42, ni bei gani?" in content
    assert "⟦voice:" not in content and "sent a audio" not in content
    # Hand-off 5: the reply went to the customer and was stored as theirs.
    assert sent == [(wa, "Karibu! Kasoki za size 42 tunazo. Ungependa rangi gani?")]
    out = [r for r in rows if r.direction == MsgDirection.outbound]
    assert [o.text for o in out] == ["Karibu! Kasoki za size 42 tunazo. Ungependa rangi gani?"]
    # The live events the open thread patches itself with, in order.
    new = [e for e in rig.redis.events("new_message") if e.get("id") == str(note.id)]
    assert new and new[0]["transcriptStatus"] == "queued" and new[0]["direction"] == "inbound"
    done = [e for e in rig.redis.events("voice_transcript") if e["transcriptStatus"] == "done"]
    assert done and done[-1]["text"] == note.text and done[-1]["translatedFrom"] == "Swahili"


# ═════════════════════════════════════════════════════════════════════════════
# 2 · A WhatsApp call: webhook → answer → hangup → recording upload →
#     transcript → brief → call card JSON (read by the web's code) → CRM note
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def callrig(rig, monkeypatch):
    """The voice rig + the admin router over HTTP, Meta's calling API faked."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers import admin
    from app.services import call_log, wa_calling

    monkeypatch.setattr(call_log, "AsyncSessionLocal", rig.maker)
    monkeypatch.setattr(rig.settings, "call_recording_enabled", True)
    monkeypatch.setattr(rig.settings, "media_public_url", "https://neema.test")
    meta: list = []

    async def accept(cid, sdp, **kw):
        meta.append(("accept", cid))

    async def terminate(cid):
        meta.append(("terminate", cid))
    monkeypatch.setattr(wa_calling, "accept", accept)
    monkeypatch.setattr(wa_calling, "terminate", terminate)
    ann = str(uuid.uuid4())
    eng = sa.create_engine(rig.maker.kw["bind"].url.render_as_string(hide_password=False)
                           .replace("+asyncpg", "+psycopg2"))
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO agents (id, name, email, password_hash, role, is_available, is_superuser, "
            "active_convs, created_at) VALUES (:id, 'Ann Wanjiru', 'ann@x.ke', 'x', 'agent', TRUE, FALSE, 0, NOW())"),
            {"id": ann})
    eng.dispose()

    async def _db():
        async with rig.maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = _db
    app.state.redis = rig.redis
    with TestClient(app) as cl:
        yield types.SimpleNamespace(rig=rig, client=cl, ann=ann, meta=meta, app=app)


def _calls_webhook(rig, *events, contacts=None):
    from app.routers import whatsapp_webhook as ww
    value = {"metadata": {"phone_number_id": "PNID"}, "contacts": contacts or [], "calls": list(events)}
    payload = {"object": "whatsapp_business_account",
               "entry": [{"changes": [{"field": "calls", "value": value}]}]}
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=rig.redis)))
    run(ww._handle_calls(req, payload))


def _wait_bg(timeout=30.0):
    from app.services import call_transcribe
    end = time.time() + timeout
    while time.time() < end:
        if not [t for t in call_transcribe._bg_tasks if not t.done()]:
            return
        time.sleep(0.05)
    raise AssertionError("call transcription never finished")


BRIEF = {
    "summary": "Fr. Peter Mwangi of St. Mark's Nyeri wants 2 black clergy shirts, collar 16, at KES 4,500 each; "
               "he will pay by M-Pesa once Ann sends the Paybill details.",
    "intent": "buy two clergy shirts",
    "products": ["2 × black clergy shirt, collar 16"],
    "prices": ["KES 4,500 per shirt", "KES 9,999 delivery"],
    "objections": [],
    "commitments": ["Ann to send Paybill details today"],
    "action_items": ["Ann — send M-Pesa Paybill details — today"],
    "next_action": "Send the Paybill details",
    "follow_up_message": "Habari Fr. Peter! Hizi ndizo details za Paybill...",
    "sentiment": "positive",
    "language": "Swahili",
}


def test_call_end_to_end_webhook_to_card_to_crm_note(callrig, clips):
    from app.models.call import Call
    from app.models.user import User
    from app.services import wa_native
    cr, rig = callrig, callrig.rig
    wa, cid = "254722300001", "wacid.C10CALL1"
    # The customer has a WhatsApp thread (a text first) …
    run(wa_native.handle_webhook(wa_payload(wa, "wamid.C10T1", kind="text", text="Habari"), rig.redis))
    run(drain_tasks())
    # … then calls; Ann answers; Meta hangs up after 3:05.
    _calls_webhook(rig, {"id": cid, "event": "connect", "from": wa, "to": "254785",
                         "session": {"sdp_type": "offer", "sdp": "v=0 offer"}},
                   contacts=[{"wa_id": wa, "profile": {"name": "Fr. Peter Mwangi"}}])
    r = cr.client.post(f"/api/admin/calls/{cid}/answer", json={"sdp": "v=0 a"}, headers=_as(cr.ann))
    assert r.status_code == 200, r.text
    _calls_webhook(rig, {"id": cid, "event": "terminate", "status": "COMPLETED", "duration": 185})

    # The softphone uploads the mixed recording on hangup.
    rig.provider.answers = [("Habari Father Peter. Nataka clergy shirt mbili nyeusi collar 16. "
                             "Ni 4,500 kila moja. Nitatuma Paybill leo.", None)]
    rig.llm.answers["calls"] = json.dumps(BRIEF)
    with open(clips["call"], "rb") as f:
        up = cr.client.post(f"/api/admin/calls/{cid}/recording", headers=_as(cr.ann),
                            files={"file": (f"{cid}.webm", f.read(), "audio/webm")})
    assert up.status_code == 200 and up.json()["will_transcribe"] is True, up.text
    _wait_bg()

    # Hand-off 1: the call row carries transcript, brief, insights — the
    # invented delivery price was dropped (the call never said 9,999).
    async def row():
        async with rig.maker() as db:
            return (await db.execute(sa.select(Call).where(Call.call_id == cid))).scalar_one()
    c = run(row())
    assert c.transcript_status == "done" and "clergy shirt mbili" in c.transcript
    assert c.summary == BRIEF["summary"] and c.transcript_lang == "sw"
    assert c.insights["prices"] == ["KES 4,500 per shirt"]
    assert c.recording_url.startswith("https://neema.test/api/admin/media/call_") and c.recording_url.endswith(".webm")
    assert len(rig.provider.calls) == 1

    # Hand-off 2: the thread payload's call card — what the dashboard receives.
    conv_id = run(_conv_id(rig, wa))
    t = cr.client.get(f"/api/admin/conversations/{conv_id}/messages", headers=_as(cr.ann))
    assert t.status_code == 200, t.text
    cards = [i for i in t.json() if i.get("event_kind") == "call"]
    assert len(cards) == 1, [i.get("event_kind") for i in t.json()]
    card = cards[0]["call"]
    assert card["call_id"] == cid and card["status"] == "completed" and card["duration"] == 185
    assert card["agent_name"] == "Ann Wanjiru" and card["direction"] == "inbound"
    assert (card["transcript_state"], card["transcript_failure"], card["has_transcript"],
            card["has_recording"]) == ("done", None, True, True)
    assert card["summary"] == BRIEF["summary"] and card["insights"]["next_action"] == "Send the Paybill details"
    assert "recording_url" not in json.dumps(cards[0]) or card.get("recording_url") in (None, "")
    tr = cr.client.get(f"/api/admin/calls/{cid}/transcript", headers=_as(cr.ann)).json()
    assert tr["state"] == "done" and tr["failure"] is None and "Paybill" in tr["transcript"]

    # Hand-off 3: the CRM note (sidebar Notes) — once, with the prices said.
    async def user():
        async with rig.maker() as db:
            return (await db.execute(sa.select(User).where(User.wa_id == wa))).scalar_one()
    u = run(user())
    notes = u.state.get("crm_notes") or ""
    assert notes.count("📞 Call (") == 1 and BRIEF["summary"] in notes
    assert "incoming WhatsApp · 3:05 · Ann" in notes and "Next: Send the Paybill details" in notes
    assert "9,999" not in notes
    assert cid in (u.state.get("call_note_ids") or [])

    # Hand-off 4: the web's own card code, fed the exact JSON the API sent.
    if not _node_can_strip_types():
        pytest.skip("node ≥ 22.18 needed to run the web's .ts card code")
    view = _web("""
import { callCardView, transcriptSlot, transcriptFailure, actionItems, callFacts, lastCallBrief, callLanguage }
    from "../src/lib/callCard.ts";
const c = DATA;
const v = callCardView(c);
console.log(JSON.stringify({ title: v.title, outcome: v.outcome, who: v.who, duration: v.duration,
    slot: transcriptSlot(c.transcript_status, c.transcript_state), failure: transcriptFailure(c),
    items: actionItems(c.insights), facts: callFacts(c.insights), brief: lastCallBrief(c),
    lang: callLanguage(c.insights?.language, c.transcript_lang) }));
""", card)
    assert (view["title"], view["outcome"], view["who"], view["duration"]) == \
        ("Incoming call", "Answered", "Answered by Ann", "3:05")
    assert (view["slot"], view["failure"], view["lang"]) == ("ready", None, "Swahili")
    assert view["items"] == ["Ann — send M-Pesa Paybill details — today"]
    assert view["facts"] == [["Products", ["2 × black clergy shirt, collar 16"]], ["Prices", ["KES 4,500 per shirt"]]]
    assert view["brief"] == {"summary": BRIEF["summary"], "prices": ["KES 4,500 per shirt"],
                             "next": "Send the Paybill details"}


async def _conv_id(rig, wa):
    from app.models.conversation import Conversation
    async with rig.maker() as db:
        return str((await db.execute(sa.select(Conversation.id).where(Conversation.wa_id == wa))).scalar_one())


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Production's inbound mix — nulls included — webhook → row → thread → web
# ═════════════════════════════════════════════════════════════════════════════

_MIX = [
    # (label, message body without from/id/timestamp)
    ("call_permission_empty", {"type": "interactive", "interactive": {
        "type": "call_permission_reply", "call_permission_reply": {"response": "accept",
                                                                   "is_permanent": False,
                                                                   "expiration_timestamp": 1760000000}}}),
    ("call_permission_bare", {"type": "interactive", "interactive": {"type": "call_permission_reply"}}),
    ("template_button", {"type": "button", "button": {"payload": "YES", "text": "Yes please"}}),
    ("button_null", {"type": "button", "button": None}),
    ("button_reply", {"type": "interactive", "interactive": {
        "type": "button_reply", "button_reply": {"id": "b1", "title": "See prices"}}}),
    ("button_reply_null", {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": None}}),
    ("list_reply", {"type": "interactive", "interactive": {
        "type": "list_reply", "list_reply": {"id": "l1", "title": "Cassocks", "description": None}}}),
    ("interactive_null", {"type": "interactive", "interactive": None}),
    ("reaction", {"type": "reaction", "reaction": {"message_id": "wamid.UNKNOWN", "emoji": "🙏"}}),
    ("reaction_null", {"type": "reaction", "reaction": None}),
    ("edit_type", {"type": "edit", "edit": {"message_id": "wamid.X"}}),
    ("unsupported_edit", {"type": "unsupported", "unsupported": {"type": "edit"},
                          "errors": [{"code": 131051, "title": "Message type unknown",
                                      "message": "Message type unknown",
                                      "error_data": {"details": "Message type is currently not supported."}}]}),
    ("unsupported_errors_odd", {"type": "unsupported", "errors": [None, {"code": 131051, "error_data": None}]}),
    ("unsupported_bare", {"type": "unsupported"}),
    ("system_number", {"type": "system", "system": {"type": "user_changed_number", "new_wa_id": "254799000111",
                                                    "body": "User A changed from ... to ..."}}),
    ("system_null", {"type": "system", "system": None}),
    ("location", {"type": "location", "location": {"latitude": -1.28, "longitude": 36.82,
                                                   "name": "St. Mark's", "address": None}}),
    ("location_null", {"type": "location", "location": None}),
    ("contacts", {"type": "contacts", "contacts": [{"name": {"formatted_name": "Fr. John"},
                                                    "phones": [{"phone": "+254 700 000 001", "wa_id": None}]}]}),
    ("contacts_nulls", {"type": "contacts", "contacts": [{"name": None, "phones": None, "org": None}]}),
    ("contacts_null_item", {"type": "contacts", "contacts": [None]}),
    ("sticker", {"type": "sticker", "sticker": {"id": "stk1", "mime_type": "image/webp", "animated": None}}),
    ("video", {"type": "video", "video": {"id": "vid1", "mime_type": "video/mp4", "caption": None}}),
    ("video_null", {"type": "video", "video": None}),
    ("document", {"type": "document", "document": {"id": "doc1", "mime_type": "application/pdf",
                                                   "filename": None}}),
    ("order_nulls", {"type": "order", "order": {"product_items": None, "text": None}}),
    ("text_null", {"type": "text", "text": None}),
    ("type_null", {"type": None}),
    ("request_welcome", {"type": "request_welcome"}),
]

_OLD_WORDS = ("can't display", "cant display", "unsupported type", "resend as text", "(unknown type)")


def test_production_inbound_mix_with_nulls_lands_and_renders(callrig):
    from app.models.message import Message
    from app.services import wa_native
    cr, rig = callrig, callrig.rig
    wa = "254733400001"
    msgs = [{"from": wa, "id": f"wamid.C10MIX{i:02d}", "timestamp": str(int(time.time()) + i), **body}
            for i, (_label, body) in enumerate(_MIX)]
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "messages": msgs, "contacts": [{"wa_id": wa, "profile": {"name": "Sr. Agnes"}}]}}]}]}
    n, failed = run(wa_native.handle_webhook(payload, rig.redis))
    run(drain_tasks())
    assert (n, failed) == (len(_MIX), 0)

    async def rows():
        async with rig.maker() as db:
            return (await db.execute(sa.select(Message).where(Message.wa_id == wa)
                                     .order_by(Message.created_at, Message.ts_ms))).scalars().all()
    stored = run(rows())
    assert len(stored) == len(_MIX), [r.text for r in stored]
    # One row per message, in the order Meta sent them (created_at follows ts).
    by_label = {label: r for (label, _b), r in zip(_MIX, stored)}
    for label, r in by_label.items():
        text = (r.text or "").strip()
        # (A text message with a null body is not a shape Meta sends; it only
        # has to land without failing the delivery.)
        assert text or r.media_type or label == "text_null", f"{label}: an empty row"
        assert not any(w in text.lower() for w in _OLD_WORDS), f"{label}: {text!r}"
        if r.raw_meta and r.raw_meta.get("kind") == "unsupported":
            assert r.raw_meta.get("payload") is not None or r.raw_meta.get("parse_error"), label
    # Known kinds are named, not "unsupported".
    kinds = {k: (v.raw_meta or {}).get("kind") for k, v in by_label.items()}
    for label in ("call_permission_empty", "call_permission_bare"):
        assert kinds[label] == "call_permission", (label, kinds[label])
    assert kinds["edit_type"] == kinds["unsupported_edit"] == "edited"
    assert (kinds["system_number"], kinds["location"], kinds["contacts"], kinds["sticker"],
            kinds["reaction"], kinds["request_welcome"]) == (
        "system", "location", "contacts", "sticker", "reaction", "welcome")
    assert by_label["unsupported_edit"].raw_meta["errors"][0]["code"] == 131051
    assert by_label["video"].media_type == "video" and by_label["document"].media_type == "document"

    # The thread payload: the record without its redacted copy.
    conv_id = run(_conv_id(rig, wa))
    t = cr.client.get(f"/api/admin/conversations/{conv_id}/messages?limit=100", headers=_as(cr.ann))
    assert t.status_code == 200, t.text
    thread = [m for m in t.json() if m.get("type", "message") == "message" and m.get("direction") == "inbound"]
    assert len(thread) == len(_MIX), len(thread)
    assert '"payload"' not in t.text
    if not _node_can_strip_types():
        pytest.skip("node ≥ 22.18 needed to run the web's .ts renderer")
    views = _web("""
import { viewForRow } from "../src/lib/messageKinds.ts";
console.log(JSON.stringify(DATA.map((m) => {
    const v = viewForRow({ text: m.text, media_type: m.media_type, meta: m.meta, direction: m.direction });
    return { text: m.text, kind: m.meta?.kind ?? null, title: v ? v.title : null, lines: v ? v.lines : null };
})));
""", thread)
    for v in views:
        if v["text"] == "" and v["kind"] is None:
            continue                                   # the text_null shape (see above)
        shown = " ".join(str(x) for x in (v["title"], *(v["lines"] or []), v["text"] if v["title"] is None else "")
                         if x)
        assert shown.strip(), v
        assert not any(w in shown.lower() for w in _OLD_WORDS), v
        assert "before we recorded message types" not in shown, v


# ═════════════════════════════════════════════════════════════════════════════
# 4 · The deploy's schema step: upgrade FROM origin/main's head with old rows
# ═════════════════════════════════════════════════════════════════════════════

MAIN_HEAD = "d1f3a5c7e9b2"        # origin/main's alembic head when this branch was cut


def _alembic(url, *args):
    import sys
    env = {**os.environ, "DATABASE_URL_SYNC": url}
    r = subprocess.run([sys.executable, "-m", "alembic", *args], capture_output=True, text=True, env=env,
                       cwd=os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
    assert r.returncode == 0, f"alembic {' '.join(args)} failed:\n{r.stderr[-3000:]}"
    return r.stdout + r.stderr


def test_upgrade_from_mains_schema_keeps_old_rows_readable_and_startup_is_a_no_op():
    import app.main  # noqa: F401 — every model registered
    from app.main import MIGRATION_STATEMENTS
    from app.models.call import Call
    from app.models.message import Message
    from app.routers.admin import _shape_messages_into
    from app.services import call_log, voice_notes

    base = _sync_url()
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    name = f"c10up_{uuid.uuid4().hex[:10]}"
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.rsplit("/", 1)[0] + f"/{name}"
    try:
        _alembic(url, "upgrade", MAIN_HEAD)
        eng = sa.create_engine(url)
        insp = sa.inspect(eng)
        assert "raw_meta" not in {c["name"] for c in insp.get_columns("messages")}
        assert {c["name"]: c for c in insp.get_columns("calls")}["transcript_status"]["type"].length == 20
        conv, mids = str(uuid.uuid4()), [str(uuid.uuid4()) for _ in range(4)]
        with eng.begin() as c:
            # Production's rows as they are today: voice notes nobody heard, a
            # caption, plain text; calls with the narrow statuses of the old code.
            c.execute(sa.text(
                "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, "
                "created_at, updated_at) VALUES (:id, '254744500001', 'whatsapp', '254744500001', 'ai', "
                "'open', NOW(), NOW())"), {"id": conv})
            for mid, (direction, sender, text, media, url_) in zip(mids, (
                    ("inbound", "user", "[audio received]", "audio", "https://neema.test/api/admin/media/wa_1"),
                    ("inbound", "user", "Nataka alb", "audio", "https://neema.test/api/admin/media/wa_2"),
                    ("inbound", "user", "Habari", None, None),
                    ("outbound", "ai", "Karibu!", None, None))):
                c.execute(sa.text(
                    "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, "
                    "text, media_type, media_url, created_at) VALUES (:id, '254744500001', 'whatsapp', "
                    "'254744500001', :c, :d, :s, :t, :m, :u, NOW() - interval '2 days')"),
                    {"id": mid, "c": conv, "d": direction, "s": sender, "t": text, "m": media, "u": url_})
            for cid, st in (("wacid.OLD1", "recorded"), ("wacid.OLD2", "pending"), ("wacid.OLD3", "failed"),
                            ("wacid.OLD4", "none"), ("wacid.OLD5", "processing"), ("wacid.OLD6", "x" * 20)):
                c.execute(sa.text(
                    "INSERT INTO calls (id, call_id, wa_id, channel, direction, status, started_at, "
                    "recording_url, transcript_status) VALUES (:id, :cid, '254744500001', 'whatsapp', "
                    "'inbound', 'completed', NOW() - interval '2 days', :rec, :st)"),
                    {"id": str(uuid.uuid4()), "cid": cid, "st": st,
                     "rec": None if st == "none" else f"https://neema.test/api/admin/media/call_{cid}.webm"})
        eng.dispose()

        out = _alembic(url, "upgrade", "head")
        assert "e2a4c6d8f0b1" in out and "36ed77bde344" in out
        # The image runs alembic, then uvicorn runs main.py's statements: on a
        # migrated schema every one of them is a no-op — twice (2 workers).
        eng = sa.create_engine(url)
        for _ in range(2):
            with eng.begin() as c:
                for stmt in MIGRATION_STATEMENTS:
                    c.execute(sa.text(stmt))
        insp = sa.inspect(eng)
        cols = {c["name"]: c for c in insp.get_columns("messages")}
        assert {"raw_meta", "transcript_status", "transcript_lang"} <= set(cols)
        assert cols["transcript_status"]["type"].length == 40 and cols["transcript_lang"]["type"].length == 12
        assert {c["name"]: c for c in insp.get_columns("calls")}["transcript_status"]["type"].length == 40
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "36ed77bde344"
            calls = dict(c.execute(sa.text("SELECT call_id, transcript_status FROM calls")).all())
            msgs = c.execute(sa.text("SELECT count(*) FROM messages WHERE raw_meta IS NULL AND "
                                     "transcript_status IS NULL AND transcript_lang IS NULL")).scalar()
        assert calls == {"wacid.OLD1": "recorded", "wacid.OLD2": "pending", "wacid.OLD3": "failed",
                         "wacid.OLD4": "none", "wacid.OLD5": "processing", "wacid.OLD6": "x" * 20}
        assert msgs == 4                                       # old rows: NULLs, untouched
        # The startup statement that widens calls must not take its lock again
        # once alembic has run (it is guarded by the current length).
        assert any("character_maximum_length" in s for s in MIGRATION_STATEMENTS)
        # A second `alembic upgrade head` (every restart) is a no-op.
        out2 = _alembic(url, "upgrade", "head")
        assert "Running upgrade" not in out2

        # The app reads the old rows: thread shaping, the agent's history line,
        # the call card's folded state.
        from sqlalchemy.orm import Session
        with Session(eng) as s:
            rows = s.execute(sa.select(Message).where(Message.conversation_id == uuid.UUID(conv))
                             .order_by(Message.id)).scalars().all()
            shaped: list = []
            _shape_messages_into(shaped, rows, {})
            by_text = {m["text"]: m for m in shaped}
            assert by_text["[audio received]"]["transcript_status"] is None
            assert by_text["[audio received]"]["meta"] is None and by_text["Habari"]["meta"] is None
            hist = {r.text: voice_notes.history_text(r) for r in rows}
            assert hist["[audio received]"] == "🎤 (voice note — it was not transcribed)"
            assert hist["Nataka alb"] == "🎤 (voice note): Nataka alb"   # a pre-programme transcript
            assert hist["Habari"] is None and hist["Karibu!"] is None
            cards = {c.call_id: call_log.serialize(c) for c in s.execute(sa.select(Call)).scalars()}
        assert {k: v["transcript_state"] for k, v in cards.items()} == {
            "wacid.OLD1": "recorded", "wacid.OLD2": "queued", "wacid.OLD3": "failed", "wacid.OLD4": "none",
            "wacid.OLD5": "processing", "wacid.OLD6": "x" * 20}
        assert cards["wacid.OLD3"]["transcript_failure"] == "failed"
        eng.dispose()

        # Rollback path: two steps down returns main's schema, and up again.
        _alembic(url, "downgrade", MAIN_HEAD)
        eng = sa.create_engine(url)
        insp = sa.inspect(eng)
        assert "raw_meta" not in {c["name"] for c in insp.get_columns("messages")}
        assert {c["name"]: c for c in insp.get_columns("calls")}["transcript_status"]["type"].length == 20
        eng.dispose()
        _alembic(url, "upgrade", "head")
    finally:
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Deploy config: what production's container will actually run with
# ═════════════════════════════════════════════════════════════════════════════

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _compose_api_env() -> dict:
    """The `api` service's `environment:` block of docker-compose.vps.yml
    (parsed by hand — PyYAML is not a dependency)."""
    import re
    env, in_api, in_env = {}, False, False
    for line in open(os.path.join(ROOT, "docker-compose.vps.yml"), encoding="utf-8"):
        if re.match(r"^    \w", line):
            in_api, in_env = line.strip() == "api:", False
            continue
        if in_api and re.match(r"^        environment:\s*$", line):
            in_env = True
            continue
        if in_env:
            m = re.match(r'^            ([A-Z0-9_]+):\s*"?([^"#]*)"?\s*(#.*)?$', line)
            if m:
                env[m.group(1)] = m.group(2).strip()
            elif re.match(r"^        \w", line):
                in_env = False
    return env


def test_production_env_parses_and_needs_no_new_secret(monkeypatch):
    env = _compose_api_env()
    assert env["CALL_META_TRANSCRIPTION"] == "false" and env["CALL_META_RECORDING"] == "false"
    assert (env["WHISPER_ENABLED"], env["WHISPER_AUTO"], env["WHISPER_PROVIDER"]) == ("true", "true", "openai")
    # Only the vars production already has (no .env read here — the three
    # below are what pydantic requires of every deployment) + the compose block.
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("WHISPER_", "TRANSCRIBE_", "CALL_META_", "OPENAI_", "GROQ_"))}
    clean.update(env)
    clean.update(DATABASE_URL="postgresql+asyncpg://u@h/db", DATABASE_URL_SYNC="postgresql+psycopg2://u@h/db",
                 SECRET_KEY="not-a-secret")
    code = (
        "import json; from app.core.config import Settings; s = Settings(_env_file=None); "
        "print(json.dumps({k: getattr(s, k) for k in ('whisper_enabled', 'whisper_auto', 'whisper_provider', "
        "'transcribe_model', 'transcribe_daily_cap_usd', 'transcribe_concurrency', 'transcribe_voice_max_seconds', "
        "'transcribe_call_max_seconds', 'transcribe_timeout_seconds', 'transcribe_translate', "
        "'call_meta_transcription', 'call_meta_recording', 'call_recording_enabled', 'media_dir')}))")
    import sys
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=clean,
                       cwd=os.path.join(ROOT, "apps", "api"))
    assert r.returncode == 0, r.stderr[-2000:]
    s = json.loads(r.stdout.strip().splitlines()[-1])
    assert (s["whisper_enabled"], s["whisper_auto"], s["whisper_provider"]) == (True, True, "openai")
    assert (s["transcribe_model"], s["transcribe_daily_cap_usd"]) == ("gpt-4o-transcribe", 3.0)
    assert (s["call_meta_transcription"], s["call_meta_recording"]) == (False, False)
    assert s["transcribe_concurrency"] >= 2           # notes-never-behind-calls needs ≥ 2 slots
    assert s["call_recording_enabled"] is True and s["media_dir"] == "/var/neema/media"
    # With the key missing, the engine names the gap instead of failing hidden.
    from app.core.config import settings
    from app.services import transcribe as stt
    monkeypatch.setattr(settings, "whisper_enabled", True)
    monkeypatch.setattr(settings, "whisper_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert stt.configured() == "no_provider"


def test_the_runtime_image_has_ffmpeg_and_the_engine_needs_no_mime_table():
    """Cycle 5's root cause was the slim image: no /etc/mime.types (so
    audio/ogg had no extension) — the engine must not depend on one, and the
    runtime stage must install ffmpeg."""
    import mimetypes
    from app.services.wa_native import media_ext
    docker = open(os.path.join(ROOT, "apps", "api", "Dockerfile"), encoding="utf-8").read()
    runner = docker.split("AS runner", 1)[1]
    assert "ffmpeg" in runner.split("COPY", 1)[0]
    bare = mimetypes.MimeTypes()                         # the slim image's view: no system table
    assert bare.guess_extension("audio/ogg") is None
    real = mimetypes.guess_extension
    try:
        mimetypes.guess_extension = bare.guess_extension
        assert media_ext("audio/ogg; codecs=opus") == ".ogg"
        assert media_ext("audio/mp4") == ".m4a" and media_ext("audio/amr") == ".amr"
    finally:
        mimetypes.guess_extension = real

