"""Order reconstruction against a real Postgres (2026-11-15): photos keep
their numbers in the stored record, a removal's quote is checked against the
stored messages, and the read-only access key opens the record and nothing
else. Skips without a database."""
import asyncio
import base64
import io
from datetime import datetime, timedelta, timezone

from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

KEY = "k" * 40
WA = "16125550142"          # each test uses its own contact: the database is shared by the module


def _png(seed: int) -> dict:
    """A small picture whose look depends on `seed` (so two seeds hash apart)."""
    from PIL import Image
    im = Image.new("L", (64, 64))
    im.putdata([(x * (seed + 1) * 7 + (y * y if seed % 2 else y * 3)) % 256
                for y in range(64) for x in range(64)])
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="PNG")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def _thread(env, WA=WA):
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person
    t0 = datetime.now(timezone.utc) - timedelta(minutes=30)

    async def go():
        async with env.maker() as db:
            ident = await resolve_or_create_person(db, "whatsapp", WA, display_name="Bishop M")
            conv = await get_or_create_conversation(db, "whatsapp", WA,
                                                    person_id=ident.person_id, wa_id=WA)

            def row(n, **kw):
                kw.setdefault("direction", MsgDirection.inbound)
                kw.setdefault("sender", MsgSender.user)
                db.add(Message(channel="whatsapp", wa_id=WA, external_id=WA,
                               person_id=ident.person_id, conversation_id=conv.id,
                               created_at=t0 + timedelta(minutes=n), **kw))
            row(1, media_type="image", media_url="/m/one.png")
            row(2, media_type="image", media_url="/m/two.png")
            row(3, text="Make these two for me")
            row(4, media_type="image", media_url="/m/one-again.png")       # photo 1, re-sent
            row(5, text="Please remove the cross, I already have one")
            row(6, text="internal", media_type="note", direction=MsgDirection.outbound,
                sender=MsgSender.human_agent)
            await db.commit()
            return str(conv.id)
    return asyncio.run(go())


def test_photos_keep_their_numbers_in_the_record(env, monkeypatch):
    from app.agent import media, runtime
    from app.services import photo_memory
    _thread(env)
    blocks = {"/m/one.png": _png(1), "/m/two.png": _png(2), "/m/one-again.png": _png(1)}
    monkeypatch.setattr(media, "load_image_block", lambda url: blocks.get(url))

    async def go():
        async with env.maker() as db:
            report = {}
            first = await photo_memory.index(db, None, channel="whatsapp", key=WA, report=report)
            again = await photo_memory.index(db, None, channel="whatsapp", key=WA)
            hist = await runtime._history(db, WA, limit=40)
            return first, again, report, hist
    first, again, report, hist = asyncio.run(go())
    assert [p["n"] for p in first] == [1, 2, 1]            # the re-sent picture is photo 1 again
    assert report == {"changed": True}
    assert [p["n"] for p in again] == [1, 2, 1]            # and the numbers are stored, not recomputed
    text = "\n".join(m["content"] for m in hist if m["role"] == "user")
    assert "[the customer sent photo 1]" in text and "[the customer sent photo 2]" in text
    assert "[the customer sent a photo]" not in text
    got = photo_memory.to_attach(first, "Make these two for me")
    assert [p["n"] for p in got] == [1, 2] and got[0]["url"] == "/m/one-again.png"


def test_a_removals_quote_is_checked_against_the_stored_messages(env):
    from app.agent import tools
    from app.agent.tools import ToolContext
    WA = "16125558142"
    _thread(env, WA)

    async def go():
        async with env.maker() as db:
            ctx = ToolContext(db=db, redis=None, wa_id=WA, channel="whatsapp")
            said = await tools._said_in_record(ctx)
            return said
    said = asyncio.run(go())
    from app.agent import order_sheet
    assert order_sheet.quote_found("remove the cross", said)
    assert not order_sheet.quote_found("remove the stole", said)
    assert "internal" not in said                           # a note is nobody's words


def test_the_read_key_opens_the_record_and_nothing_else(env, monkeypatch):
    from app.core.config import settings
    from app.routers import ops_read
    WA = "16125559142"
    conv = _thread(env, WA)
    ops_read._bad.clear()
    # the test app carries the admin router only: mount this one as main.py does
    env.client.app.include_router(ops_read.router, prefix="/api/ops/read")
    import inspect
    import app.main as main
    assert 'include_router(ops_read.router, prefix="/api/ops/read"' in inspect.getsource(main)
    # off by default: the routes do not exist
    monkeypatch.setattr(settings, "ops_read_key", "")
    assert env.client.get("/api/ops/read/conversations", headers={"X-Ops-Key": KEY}).status_code == 404
    # a short key is not a key
    monkeypatch.setattr(settings, "ops_read_key", "short")
    assert env.client.get("/api/ops/read/conversations", headers={"X-Ops-Key": "short"}).status_code == 404
    monkeypatch.setattr(settings, "ops_read_key", KEY)
    assert env.client.get("/api/ops/read/conversations").status_code == 401
    assert env.client.get("/api/ops/read/conversations", headers={"X-Ops-Key": "x" * 40}).status_code == 401
    h = {"X-Ops-Key": KEY}
    got = env.client.get("/api/ops/read/conversations?ends_with=9142", headers=h)
    assert got.status_code == 200
    rows = got.json()["conversations"]
    assert [r["id"] for r in rows] == [conv]
    assert rows[0]["contact"].endswith("9142") and WA not in got.text      # masked
    assert env.client.get("/api/ops/read/conversations?ends_with=42", headers=h).status_code == 422
    msgs = env.client.get(f"/api/ops/read/conversations/{conv}/messages", headers=h).json()["messages"]
    assert [m["text"] for m in msgs if m["text"]][:1] == ["Make these two for me"]
    assert sum(1 for m in msgs if m["media_type"] == "image" and m["has_media"]) == 3
    order = env.client.get(f"/api/ops/read/conversations/{conv}/order", headers=h).json()
    assert order["items"] == [] and order["awaiting_price"] == []
    assert env.client.get("/api/ops/read/conversations/not-a-uuid/messages", headers=h).status_code == 404
    # read-only: nothing but GET exists under the prefix
    for route in ops_read.router.routes:
        assert route.methods <= {"GET", "HEAD"}, route.path
    assert env.client.post("/api/ops/read/conversations", headers=h).status_code == 405
    # the door closes after too many wrong keys
    for _ in range(ops_read._MAX_BAD):
        env.client.get("/api/ops/read/conversations", headers={"X-Ops-Key": "wrong"})
    assert env.client.get("/api/ops/read/conversations", headers=h).status_code == 429
    ops_read._bad.clear()
