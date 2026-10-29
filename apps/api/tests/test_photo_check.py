"""The photo check (owner, 2026-10-29): "images that come through sent by
people are AI enhanced or generated, which comes with so much embroidery and
design … the pricing is not accurate. Anything that deviates from what we have
too much should be referred to human agent … [but] don't refer people … for
the things that are listed on our website." Then: "refer any extra
embroidery, start in shadow mode"."""
import asyncio
import base64
import io
import json
import types

import pytest

import app.main  # noqa: F401 — registers models before runtime import
import app.agent.runtime as runtime
from app.core.config import settings
from app.services import photo_check as pc
from app.services import post_catalog


def _png(colour="white", band="#b91c1c") -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 320), colour)
    ImageDraw.Draw(img).rectangle([20, 40, 220, 120], fill=band)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _block(raw: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(raw).decode()}}


CHASUBLE = {"id": 7, "name": "Ornate Chasuble", "slug": "ornate-chasuble",
            "images": [{"url": "https://hub.example/chasuble.jpg"}]}
STOLE = {"id": 8, "name": "Clergy Stole", "slug": "clergy-stole", "images": []}
CATALOG = [CHASUBLE, STOLE]


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        self.kv[k] = v
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


class _Reads:
    """The model's two reads, in order; counts the calls."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, *, system, messages, tools, **kw):
        self.calls.append(messages)
        text = self.answers.pop(0) if self.answers else "{}"
        return types.SimpleNamespace(text=text if isinstance(text, str) else json.dumps(text),
                                     tool_calls=[], assistant_content=[], usage={})


def _wire(monkeypatch, reads, prints=()):
    monkeypatch.setattr(runtime, "build_llm", lambda **kw: reads)
    monkeypatch.setattr("app.agent.media.load_image_block",
                        lambda url: _block(_png("white", "#1d4ed8")))

    async def _prints(redis, catalog):
        return list(prints)
    monkeypatch.setattr(post_catalog, "_catalog_fingerprints", _prints)


# ── the rule the owner set ──────────────────────────────────────────────────

def test_the_verdicts():
    look = {"subject": "product", "closest": "Ornate Chasuble", "conf": "high",
            "embroidery": "light", "ai_made": "unlikely"}
    assert pc.decide(look, {"match": "same"}, CHASUBLE)[0] == "ours"
    v, why = pc.decide(look, {"match": "close", "differences": ["green, not purple"]}, CHASUBLE)
    assert v == "close" and "green, not purple" in why[0]
    # Any extra embroidery is a person's to price — even on our own chasuble.
    v, why = pc.decide(look, {"match": "same", "extra_embroidery": True,
                              "extra_embroidery_detail": ["gold IHS on the back"]}, CHASUBLE)
    assert v == "refer" and "extra embroidery" in why[0] and "gold IHS" in why[0]
    v, why = pc.decide(look, {"match": "far", "differences": ["a cope, not a chasuble"]}, CHASUBLE)
    assert v == "refer" and "far from our Ornate Chasuble" in why[0]
    # Nothing like it in our range.
    assert pc.decide(dict(look, closest="NONE"), None, None)[0] == "refer"
    # A logo or a drawing to stitch is a design: a person prices it.
    assert pc.decide(dict(look, subject="design"), None, None)[0] == "refer"
    # A receipt, a person, a document: nothing to judge.
    assert pc.decide(dict(look, subject="other"), None, None) == ("not_product", [])


def test_ai_made_alone_never_refers_our_own_product():
    look = {"subject": "product", "closest": "Ornate Chasuble", "conf": "high",
            "ai_made": "likely", "ai_signs": ["garbled lettering"]}
    v, why = pc.decide(look, {"match": "same"}, CHASUBLE)
    assert v == "ours" and "looks AI-made" in why[1] and "Neema answers" in why[1]
    # …but AI-made with nothing like it in our range goes to a person.
    v, why = pc.decide(dict(look, closest="NONE"), None, None)
    assert v == "refer" and any("AI-made" in w for w in why)


def test_with_no_catalogue_photo_only_a_plain_item_stands():
    look = {"subject": "product", "closest": "Clergy Stole", "conf": "high",
            "embroidery": "none", "ai_made": "unlikely"}
    assert pc.decide(look, None, STOLE)[0] == "close"
    assert pc.decide(dict(look, embroidery="heavy"), None, STOLE)[0] == "refer"
    assert pc.decide(dict(look, ai_made="likely"), None, STOLE)[0] == "refer"


# ── the check itself ────────────────────────────────────────────────────────

def test_a_customer_photo_is_compared_with_our_own_photos(monkeypatch):
    reads = _Reads({"subject": "product", "closest": "Ornate Chasuble", "conf": "high",
                    "embroidery": "heavy", "ai_made": "likely", "ai_signs": ["impossible symmetry"]},
                   {"match": "close", "extra_embroidery": True,
                    "extra_embroidery_detail": ["dense gold vine pattern over the whole front"]})
    _wire(monkeypatch, reads)
    r = _Redis()
    block = _block(_png())
    out = asyncio.run(pc.check_photo(r, block, CATALOG, "how much is this one?"))
    assert out["verdict"] == "refer" and out["product"] == "Ornate Chasuble"
    assert out["extra_embroidery"] is True and out["ai_made"] == "likely"
    assert "dense gold vine" in pc.why(out) and "looks AI-made" in pc.why(out)
    # The look read sees the catalogue names and the caption; the compare read
    # sees the customer's photo AND our catalogue photo.
    look_text = reads.calls[0][0]["content"][1]["text"]
    assert "- Ornate Chasuble" in look_text and "how much is this one?" in look_text
    assert sum(1 for c in reads.calls[1][0]["content"] if c.get("type") == "image") == 2
    # Remembered per image: the same photo never costs twice.
    again = asyncio.run(pc.check_photo(r, block, CATALOG))
    assert again == out and len(reads.calls) == 2


def test_our_own_photo_is_recognised_with_no_model_call(monkeypatch):
    def _no_model(**kw):
        raise AssertionError("a fingerprint match needs no model")
    raw = _png()
    _wire(monkeypatch, _Reads(), prints=[(CHASUBLE, post_catalog.dhash_bytes(raw))])
    monkeypatch.setattr(runtime, "build_llm", _no_model)
    out = asyncio.run(pc.check_photo(_Redis(), _block(raw), CATALOG))
    assert out["verdict"] == "ours" and out["source"] == "fingerprint"
    assert out["product"] == "Ornate Chasuble"


def test_a_name_outside_the_list_or_a_broken_read_is_never_a_match(monkeypatch):
    _wire(monkeypatch, _Reads({"subject": "product", "closest": "Golden Cope", "conf": "high"}))
    out = asyncio.run(pc.check_photo(_Redis(), _block(_png()), CATALOG))
    assert out["verdict"] == "refer" and out["product"] is None
    _wire(monkeypatch, _Reads("I think it is a chasuble"))          # no JSON at all
    r = _Redis()
    out = asyncio.run(pc.check_photo(r, _block(_png("ivory")), CATALOG))
    assert out["verdict"] == "unknown" and not r.kv             # unknown is never cached


# ── the turn: shadow changes nothing, live refers ──────────────────────────

class _ReplyLLM:
    def __init__(self, text):
        self.text, self.seen = text, []

    async def complete(self, *, system, messages, tools, **kw):
        self.seen.append(messages)
        return types.SimpleNamespace(text=self.text, tool_calls=[], assistant_content=[], usage={})


def _turn_db():
    from tests.test_cost_circuit_breaker import _turn_db as base
    return base()


def _turn(monkeypatch, mode, check, reply="Our Ornate Chasuble is KES 13,000."):
    monkeypatch.setattr(settings, "photo_check_mode", mode, raising=False)
    monkeypatch.setattr(settings, "tier2_vision", True, raising=False)
    monkeypatch.setattr("app.agent.media.load_image_block", lambda url: _block(_png()))

    async def _cat(db, redis):
        return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", _cat)

    async def _pass(reply, **kw):
        return reply, [], "pass"
    monkeypatch.setattr(runtime, "_gate_turn_reply", _pass)
    bg, recorded, escalated = [], [], []
    monkeypatch.setattr(pc, "run_in_background", lambda *a, **kw: bg.append(kw))

    async def _check(redis, block, catalog, caption=""):
        return check

    async def _record(check, **kw):
        recorded.append(kw)

    async def _esc(channel, ext, note, draft=None, redis=None):
        escalated.append((channel, ext, note))
        return True
    monkeypatch.setattr(pc, "check_photo", _check)
    monkeypatch.setattr(pc, "record", _record)
    monkeypatch.setattr(runtime, "escalate_to_human", _esc)
    llm = _ReplyLLM(reply)
    out = asyncio.run(runtime.run_turn(_turn_db(), _Redis(), "254700000001", "", llm,
                                       media={"type": "image", "url": "/api/admin/media/x.jpg",
                                              "caption": ""}))
    return out, llm, bg, recorded, escalated


REFER = {"verdict": "refer", "reasons": ["extra embroidery beyond our Ornate Chasuble: gold IHS"],
         "product": "Ornate Chasuble", "image_sha": "abc"}


def test_shadow_mode_records_in_the_background_and_changes_nothing(monkeypatch):
    out, llm, bg, recorded, escalated = _turn(monkeypatch, "shadow", REFER)
    assert out == "Our Ornate Chasuble is KES 13,000."
    assert bg and bg[0]["channel"] == "whatsapp" and bg[0]["contact"] == "254700000001"
    assert not escalated and not recorded
    assert "PHOTO CHECK" not in json.dumps(llm.seen[-1])


def test_live_mode_refers_and_never_prices_the_photo(monkeypatch):
    out, llm, bg, recorded, escalated = _turn(monkeypatch, "live", REFER)
    assert out == pc.SAFE_LINE["en"]                     # the price never goes out
    assert "PHOTO CHECK" in json.dumps(llm.seen[0]) and "gold IHS" in json.dumps(llm.seen[0])
    assert escalated and escalated[0][0] == "whatsapp" and "gold IHS" in escalated[0][2]
    assert recorded and recorded[0]["mode"] == "live" and recorded[0]["acted"] is True
    assert not bg


def test_live_mode_keeps_a_warm_reply_with_no_price(monkeypatch):
    warm = "Thank you for the photo! A colleague will confirm this design for you."
    out, *_rest, escalated = _turn(monkeypatch, "live", REFER, reply=warm)
    assert out == warm and escalated


@pytest.mark.parametrize("verdict", ["ours", "close", "not_product", "unknown"])
def test_live_mode_leaves_our_own_products_to_neema(monkeypatch, verdict):
    out, llm, bg, recorded, escalated = _turn(monkeypatch, "live", {"verdict": verdict, "reasons": []})
    assert out == "Our Ornate Chasuble is KES 13,000." and not escalated
    assert recorded and recorded[0]["acted"] is False


def test_off_does_nothing(monkeypatch):
    out, llm, bg, recorded, escalated = _turn(monkeypatch, "off", REFER)
    assert out == "Our Ornate Chasuble is KES 13,000." and not (bg or recorded or escalated)


def test_shadow_is_the_default():
    from app.core.config import Settings
    assert Settings.model_fields["photo_check_mode"].default == "shadow"
