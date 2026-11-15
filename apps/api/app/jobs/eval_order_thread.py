"""THE THREE-GARMENT ORDER, with the model in the loop (owner, 2026-11-15 —
the Melchizkek thread, kept as a permanent test).

A customer chose three garments for two people by sending photos: two for
himself (black with red, white with red), one for his spiritual father
(purple, with the stole and the cross, "all as in the picture"). The real
conversation ended as two standard sets: one garment dropped, the style
swapped. This job plays the same shape of conversation through the real turn
(`run_turn`: prompt, model, catalogue, cart, gate) and checks the ORDER
RECORD after every turn — not the wording.

What the customer says here is a reconstruction of the shape of that thread,
not his words, and the pictures are drawn by this job (three plain garment
drawings), not his photos: nothing of a real customer is stored in the
repository.

Nothing reaches a customer or the hub: the contact is a throwaway number on a
local throwaway database, product cards and the measurement guide are
recorders, and an order that would be created is recorded instead (the
order's own refusals — a piece awaiting a price, a piece unconfirmed — are
the real ones).

    python -m app.jobs.eval_order_thread --out order-thread-eval.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone

CONTACT = "15550009771"          # a throwaway US number (the 555 exchange)

BLACK, WHITE, PURPLE = "black-red", "white-red", "purple-set"

TURNS = [
    {"id": "t1", "photos": [BLACK, WHITE],
     "text": "Hello. I want these two made for me. How much are they?",
     "about": "two photos together: two garments for himself"},
    {"id": "t2", "photos": [PURPLE],
     "text": "And this one is for my spiritual father, with the stole and the cross, all as in the picture.",
     "about": "a third photo: a third garment, for someone else, as pictured"},
    {"id": "t3", "photos": [],
     "text": "So how much for everything, the two for me and the one for him?",
     "about": "the total for all three", "pieces": 3, "for_other": True},
    {"id": "t4", "photos": [],
     "text": "For the purple one, let the cross be silver, not gold.",
     "about": "a correction to ONE piece: nothing else may move", "pieces": 3, "for_other": True,
     "no_loss": True},
    {"id": "t5", "photos": [],
     "text": "Good. Send me the total and how I pay.",
     "about": "closing: the whole order, nothing left out", "pieces": 3, "for_other": True,
     "no_loss": True, "closing": True},
]

# What must never be said in this conversation.
REASK = r"(?:what|which) would you like to order|which (?:item|product)s? (?:would you like|are you interested)|" \
        r"what are you looking for|how can i (?:help|assist) you"
BLIND = r"(?:can(?:'|’)?t|cannot|unable to|could ?n(?:'|’)?t) (?:see|view|open) (?:the|your|this|that|those|these) " \
        r"(?:photo|picture|image)|does not deliver|did(?: not|n(?:'|’)?t) (?:come through|arrive)"
OTHER = r"father|spiritual|him\b|his\b"
GARMENT = r"cassock|robe|\bset\b|vestment|gown|\balb\b|chasuble|apostolic"
OFFER = r"shall i (?:start|place|create|proceed|go ahead)|(?:start|place) (?:your|the) order now"


def words(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text or "", re.UNICODE))


def draw(kind: str) -> bytes:
    """A plain drawing of one garment, as a PNG: enough for a reader to tell
    the three apart by colour and by what is worn with it."""
    import io
    from PIL import Image, ImageDraw
    body, trim, stole, cross = {
        BLACK: ((20, 20, 24), (190, 20, 30), None, None),
        WHITE: ((245, 245, 240), (190, 20, 30), None, None),
        PURPLE: ((96, 40, 140), (212, 175, 55), (212, 175, 55), (212, 175, 55)),
    }[kind]
    im = Image.new("RGB", (600, 800), (206, 210, 214))
    d = ImageDraw.Draw(im)
    d.ellipse((255, 40, 345, 140), fill=(196, 150, 120))                       # head
    d.polygon([(200, 160), (400, 160), (470, 760), (130, 760)], fill=body)      # robe
    d.polygon([(200, 160), (110, 470), (160, 490), (235, 240)], fill=body)      # sleeves
    d.polygon([(400, 160), (490, 470), (440, 490), (365, 240)], fill=body)
    d.rectangle((270, 150, 330, 172), fill=(250, 250, 250))                     # collar
    d.line([(300, 172), (300, 760)], fill=trim, width=8)                        # front piping
    for y in range(200, 740, 40):
        d.ellipse((292, y, 308, y + 16), fill=trim)                             # buttons
    d.line([(110, 470), (160, 490)], fill=trim, width=12)                       # cuffs
    d.line([(490, 470), (440, 490)], fill=trim, width=12)
    d.line([(130, 756), (470, 756)], fill=trim, width=10)                       # hem
    d.rectangle((215, 400, 385, 440), fill=trim)                                # sash
    if stole:
        d.polygon([(232, 165), (268, 165), (250, 640), (205, 640)], fill=stole)
        d.polygon([(332, 165), (368, 165), (395, 640), (350, 640)], fill=stole)
        for x in (228, 372):
            d.line([(x, 560), (x, 610)], fill=(96, 40, 140), width=6)
            d.line([(x - 16, 578), (x + 16, 578)], fill=(96, 40, 140), width=6)
    if cross:
        d.line([(262, 172), (300, 300), (338, 172)], fill=cross, width=4)       # chain
        d.line([(300, 300), (300, 372)], fill=cross, width=12)
        d.line([(276, 322), (324, 322)], fill=cross, width=12)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def order_state(cart: dict) -> dict:
    """The order record in the terms the checks use."""
    from app.agent import order_sheet
    items = cart.get("items") or []
    pending = order_sheet.pending_of(cart)
    garments = [i for i in items if re.search(GARMENT, str(i.get("name") or ""), re.IGNORECASE)]
    units = [u for i in items for u in (i.get("units") or []) if isinstance(u, dict)]
    whom = " ".join(str(x.get("for") or "") for x in units + pending) + " " \
        + " ".join(str(p.get("description") or "") + " " + str(p.get("note") or "") for p in pending)
    return {
        "lines": [{"name": i.get("name"), "qty": int(i.get("qty") or 0),
                   "units": i.get("units") or []} for i in items],
        "awaiting_price": pending,
        # a held stole or cross is not a garment; a held robe is
        "garment_pieces": sum(int(i.get("qty") or 0) for i in garments)
        + sum(1 for p in pending if re.search(GARMENT, p.get("description") or "", re.IGNORECASE)),
        "for_someone_else": bool(re.search(OTHER, whom, re.IGNORECASE)),
    }


def check_turn(turn: dict, reply: str, state: dict, before: dict | None, tools: list[dict]) -> list[str]:
    """What is wrong after this turn — [] when nothing is. Objective only:
    the record's piece count, who a piece is for, what was said that must
    never be, and an order placed that should not have been."""
    out: list[str] = []
    r = (reply or "").strip()
    if not r:
        out.append("no reply")
    for name, pat in (("asked what they want again", REASK), ("said the photo was not seen", BLIND)):
        m = re.search(pat, r, re.IGNORECASE)
        if m:
            out.append(f"{name}: “{m.group(0)}”")
    need = turn.get("pieces")
    if need and state["garment_pieces"] < need:
        out.append(f"the order holds {state['garment_pieces']} garment(s), the customer asked for {need}")
    if turn.get("for_other") and not state["for_someone_else"]:
        out.append("no piece is recorded as for his spiritual father")
    if turn.get("no_loss") and before and state["garment_pieces"] < before["garment_pieces"]:
        out.append(f"a garment was lost: {before['garment_pieces']} → {state['garment_pieces']}")
    placed = [t for t in tools if t.get("tool") == "create_order" and (t.get("out") or {}).get("sandbox")]
    if placed and (state["awaiting_price"] or state["garment_pieces"] < 3):
        out.append("an order was placed without all three garments priced")
    if state["awaiting_price"] and re.search(OFFER, r, re.IGNORECASE):
        out.append("offered to place the order while a piece awaits its price")
    if not state["lines"] and re.search(OFFER, r, re.IGNORECASE) and turn.get("pieces"):
        out.append("offered to start the order with nothing on the record")
    if turn.get("closing") and state["awaiting_price"] \
            and not re.search(r"colleague|team|confirm|price", r, re.IGNORECASE):
        out.append("gave a closing total without saying a piece still awaits its price")
    return out


def summarise(turns: list[dict]) -> dict:
    kinds: dict[str, int] = {}
    for t in turns:
        for f in t["failures"]:
            k = f.split(":")[0]
            kinds[k] = kinds.get(k, 0) + 1
    last = turns[-1]["order"] if turns else {}
    return {"turns": len(turns), "passed": sum(1 for t in turns if not t["failures"]),
            "words": sum(t["words"] for t in turns),
            "garment_pieces_at_end": last.get("garment_pieces"),
            "awaiting_price_at_end": len(last.get("awaiting_price") or []),
            "usage": {k: sum(int((t.get("usage") or {}).get(k) or 0) for t in turns) for k in
                      ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
            "failure_kinds": kinds}


def _local_db_only() -> None:
    from app.core.config import settings
    url = str(getattr(settings, "database_url", "") or "")
    if not re.search(r"@(?:127\.0\.0\.1|localhost)[:/]", url):
        raise SystemExit("eval_order_thread runs against a local throwaway database only "
                         "(DATABASE_URL must point at 127.0.0.1 or localhost).")


async def run(out_path: str | None = None) -> dict:
    _local_db_only()
    import redis.asyncio as aioredis
    import app.main  # noqa: F401 — registers the models
    from app.agent import cart as cartmod, media, tools as _t
    from app.agent.runtime import build_llm, run_turn
    from app.core.config import settings
    from app.database import AsyncSessionLocal
    from app.jobs.agent_eval import _cleanup_contacts
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.messaging import provision_user

    redis = aioredis.from_url(settings.redis_url)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    os.makedirs(media.MEDIA_DIR, exist_ok=True)
    files: dict[str, str] = {}
    for kind in (BLACK, WHITE, PURPLE):
        name = f"evalorder-{stamp}-{kind}.png"
        with open(os.path.join(media.MEDIA_DIR, name), "wb") as fh:
            fh.write(draw(kind))
        files[kind] = f"/api/admin/media/{name}"

    # Recorders for what would reach a customer or the hub.
    real_create = _t._HANDLERS["create_order"]
    saved = {n: _t._HANDLERS[n] for n in ("create_order", "send_product_cards", "send_measurement_guide")
             if n in _t._HANDLERS}

    async def create_order(args: dict, ctx) -> dict:
        from app.agent import order_sheet
        cart = await cartmod.get_cart(ctx.db, ctx.wa_id, ctx.channel)
        unsure = any(u.get("status") == "tentative" for i in cart.get("items") or []
                     for u in (i.get("units") or []) if isinstance(u, dict))
        if not cart.get("items") or order_sheet.pending_of(cart) or unsure:
            return await real_create(args, ctx)          # the order's own refusal, before any hub call
        return {"ok": True, "sandbox": True, "order_ref": "EVAL-0000",
                "note": "eval sandbox — no order was created on the hub"}

    async def recorder(args: dict, ctx) -> dict:
        return {"ok": True, "sandbox": True, "sent": 0, "note": "eval sandbox — nothing sent"}

    _t._HANDLERS["create_order"] = create_order
    for n in ("send_product_cards", "send_measurement_guide"):
        if n in _t._HANDLERS:
            _t._HANDLERS[n] = recorder

    record: dict = {"started": datetime.now(timezone.utc).isoformat(),
                    "thread": "three garments for two people, chosen by photo",
                    "models": {"producer": settings.tier2_model, "light": settings.tier2_model_light},
                    "turns": []}
    await _cleanup_contacts(redis, [CONTACT])
    before: dict | None = None
    try:
        async with AsyncSessionLocal() as db:
            await provision_user(db, CONTACT)
            await db.commit()
        for turn in TURNS:
            ids: list[str] = []
            async with AsyncSessionLocal() as db:
                rows = [Message(wa_id=CONTACT, channel="whatsapp", direction=MsgDirection.inbound,
                                sender=MsgSender.user, media_type="image", media_url=files[k])
                        for k in turn["photos"]]
                rows.append(Message(wa_id=CONTACT, channel="whatsapp", direction=MsgDirection.inbound,
                                    sender=MsgSender.user, text=turn["text"]))
                for row in rows:
                    db.add(row)
                await db.commit()
                ids = [str(row.id) for row in rows]
            imgs = [{"type": "image", "url": files[k]} for k in turn["photos"]]
            media_arg = dict(imgs[0], more=imgs[1:]) if imgs else None
            facts: dict = {}
            t0 = time.monotonic()
            error, reply = None, ""
            try:
                async with AsyncSessionLocal() as db:
                    reply = await run_turn(db, redis, CONTACT, turn["text"], build_llm(purpose="job:eval"),
                                           media=media_arg, inbound_ids=ids, turn_facts=facts) or ""
            except Exception as exc:                     # a crash is a result, not a stop
                error = f"{type(exc).__name__}: {exc}"[:300]
            async with AsyncSessionLocal() as db:
                if reply:
                    db.add(Message(wa_id=CONTACT, channel="whatsapp", direction=MsgDirection.outbound,
                                   sender=MsgSender.ai, text=reply))
                    await db.commit()
                state = order_state(await cartmod.get_cart(db, CONTACT, "whatsapp"))
            tools = [{"tool": e.get("tool"), "input": e.get("input"),
                      "out": {k: v for k, v in (e.get("out") or {}).items()
                              if k in ("ok", "error", "unchanged", "held", "team_asked", "sandbox",
                                       "total", "awaiting_price", "team_check_open")}
                      if isinstance(e.get("out"), dict) else None}
                     for e in (facts.get("tools") or [])]
            failures = check_turn(turn, reply, state, before, tools) + ([f"crashed: {error}"] if error else [])
            usage = facts.get("usage") or {}
            record["turns"].append({
                "id": turn["id"], "about": turn["about"], "photos": len(turn["photos"]),
                "customer": turn["text"], "reply": reply, "words": words(reply),
                "order": state, "tools": tools, "review": facts.get("review"),
                "usage": {k: int(usage.get(k) or 0) for k in
                          ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
                "latency_s": round(time.monotonic() - t0, 2), "failures": failures})
            mark = "ok " if not failures else "FAIL"
            print(f"[{mark}] {turn['id']} — {turn['about']}"
                  + (f"  ← {'; '.join(failures)}" if failures else ""))
            print(f"       THEM: {'[' + str(len(turn['photos'])) + ' photo(s)] ' if turn['photos'] else ''}{turn['text']}")
            print(f"       US:   {reply or '(nothing)'}")
            print(f"       ORDER: {state['garment_pieces']} garment(s); lines "
                  + json.dumps([(ln['name'], ln['qty']) for ln in state['lines']], ensure_ascii=False)
                  + f"; awaiting price {len(state['awaiting_price'])}; tools "
                  + ", ".join(str(t['tool']) for t in tools))
            before = state
    finally:
        for n, fn in saved.items():
            _t._HANDLERS[n] = fn
        try:
            await _cleanup_contacts(redis, [CONTACT])
        except Exception:
            pass
        for url in files.values():
            try:
                os.remove(os.path.join(media.MEDIA_DIR, os.path.basename(url)))
            except OSError:
                pass
        try:
            await redis.aclose()
        except Exception:
            pass
    record["finished"] = datetime.now(timezone.utc).isoformat()
    record["summary"] = summarise(record["turns"])
    s = record["summary"]
    print(f"\nSUMMARY  turns {s['passed']}/{s['turns']} · garments on the order at the end "
          f"{s['garment_pieces_at_end']} (asked for 3) · awaiting a price {s['awaiting_price_at_end']} · "
          f"failure kinds: {json.dumps(s['failure_kinds'], ensure_ascii=False)}")
    print(f"TOKENS   {json.dumps(s['usage'])}")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1)
        print(f"written {out_path}")
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description="The three-garment order with the model in the loop")
    ap.add_argument("--out", help="write the run record (JSON) here")
    args = ap.parse_args()
    asyncio.run(run(args.out))


if __name__ == "__main__":
    main()
