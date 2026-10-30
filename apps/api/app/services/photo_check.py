"""Is the customer's photo something we sell? (owner, 2026-10-29)

Customers send photos that were made or touched up with AI — heavy, ornate
embroidery and patterns that are hard to stitch — and Neema priced them as if
they were our catalogue items. The owner: refer anything AI-made or far from
what we carry to a person, refer ANY extra embroidery, and cross-examine every
photo so the things on our website and the work we do every day are still
answered by Neema.

One check per customer photo, remembered per image (the same picture never
costs twice):

  1. FINGERPRINT — the photo IS one of our catalogue photos (a screenshot of
     the website, a picture we sent): "ours", no model call.
  2. LOOK — the model reads the photo beside our catalogue's names: what it
     shows (a product of our kind / a design or logo to make / something else
     — a receipt, a person, a document), the closest item we sell, and the
     signs of an AI-made image.
  3. COMPARE — the photo beside that item's own catalogue photos: the SAME
     product, CLOSE (only colour, shade, size or lighting differ), or FAR —
     and whether it carries embroidery, motifs or lettering ours does not.

The verdict:
  ours         our product — Neema answers as always
  close        our product in another colour / size — Neema answers
  refer        a person decides: extra embroidery, a design to make, far from
               anything we carry, or AI-made with nothing like it in our range
  not_product  a receipt, a person, a document… — nothing to judge
  unknown      the check could not run — nothing changes

AI-made alone does not refer a photo that is plainly one of our products:
what matters is whether we can make it at our price (owner's call, 2026-10-29,
on the recommendation).

`settings.photo_check_mode`: "shadow" (the owner's first week) runs and
records every check but changes nothing; "live" refers; "off" skips.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re

from app.core.config import settings

_log = logging.getLogger("neema.photo_check")

CACHE_TTL = 30 * 24 * 3600
_SUBJECTS = {"product", "design", "other"}
_MATCHES = {"same", "close", "far"}
_AI = {"likely", "possible", "unlikely"}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _cache_key(sha: str) -> str:
    return f"photocheck:v1:{sha}"


def image_sha(block: dict | None) -> str:
    data = ((block or {}).get("source") or {}).get("data") or ""
    return hashlib.sha1(data.encode("ascii", "ignore")).hexdigest() if data else ""


def _parse(text: str) -> dict:
    m = _JSON_RE.search(text or "")
    if not m:
        return {}
    try:
        out = json.loads(m.group(0))
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def _word(v, allowed: set[str], default: str) -> str:
    w = str(v or "").strip().lower()
    return w if w in allowed else default


def _phrases(v, cap: int = 4) -> list[str]:
    if not isinstance(v, list):
        return []
    return [" ".join(str(x).split())[:120] for x in v if str(x).strip()][:cap]


def _pick(name: str, candidates: list[dict]) -> dict | None:
    n = (name or "").strip().strip("\"'`.").lower()
    if not n or n == "none":
        return None
    return next((p for p in candidates if (p.get("name") or "").strip().lower() == n), None)


def _catalog_photos(row: dict, cap: int = 2) -> list[str]:
    urls = [im.get("url") or im.get("image_url") or "" for im in (row.get("images") or [])]
    urls = [u for u in urls if u][:cap]
    return urls or ([row["image_url"]] if row.get("image_url") else [])


def decide(look: dict, compare: dict | None, product: dict | None) -> tuple[str, list[str]]:
    """The verdict and its reasons from the two reads — pure, so the rule the
    owner set is tested without a model."""
    subject = _word(look.get("subject"), _SUBJECTS, "product")
    ai = _word(look.get("ai_made"), _AI, "unlikely")
    signs = _phrases(look.get("ai_signs"))
    ai_note = ("looks AI-made" + (f" ({', '.join(signs[:2])})" if signs else "")) if ai == "likely" else ""
    if subject == "other":
        return "not_product", []
    if subject == "design":
        return "refer", [r for r in ("a design or logo to embroider — a colleague prices it", ai_note) if r]
    name = (product or {}).get("name") or ""
    if product is None:
        return "refer", [r for r in ("nothing like it in our catalogue", ai_note) if r]
    if compare is None:
        # No catalogue photo to compare against: only a confident name read
        # of a photo with no embroidery of its own stands.
        if _word(look.get("embroidery"), {"none", "light", "heavy"}, "none") == "heavy":
            return "refer", [f"heavy embroidery — not checked against a photo of our {name}"]
        if ai == "likely":
            return "refer", [f"{ai_note}; no photo of our {name} to compare"]
        return "close", [f"read as our {name} (no catalogue photo to compare)"]
    match = _word(compare.get("match"), _MATCHES, "far")
    diffs = _phrases(compare.get("differences"), 3)
    if bool(compare.get("extra_embroidery")):
        extra = _phrases(compare.get("extra_embroidery_detail"), 2) or diffs[:2]
        return "refer", [r for r in (
            f"extra embroidery beyond our {name}" + (f": {'; '.join(extra)}" if extra else ""),
            ai_note) if r]
    if match == "far":
        return "refer", [r for r in (
            f"far from our {name}" + (f": {'; '.join(diffs)}" if diffs else ""), ai_note) if r]
    reasons = [f"our {name}" + (f" — {'; '.join(diffs)}" if match == "close" and diffs else "")]
    if ai_note:
        reasons.append(ai_note + " — but plainly our product, so Neema answers")
    return ("ours" if match == "same" else "close"), reasons


_LOOK_SYSTEM = (
    "You check photos customers send to a church-supplies shop (clergy vestments, "
    "robes, stoles, cassocks, shirts and collars, choir wear, communion ware, church "
    "items). You answer with ONE JSON object and nothing else. You never invent a "
    "catalogue name; you say NONE when nothing listed is the same kind of item.")

_LOOK_ASK = (
    "Our catalogue (names):\n{listing}\n\n{caption}"
    "Read the customer's photo and answer with this JSON:\n"
    '{{"subject": "product" | "design" | "other",\n'
    ' "closest": "<exact name from the list, or NONE>",\n'
    ' "conf": "high" | "medium" | "low",\n'
    ' "embroidery": "none" | "light" | "heavy",\n'
    ' "ai_made": "likely" | "possible" | "unlikely",\n'
    ' "ai_signs": ["<short phrase>", ...]}}\n\n'
    "subject: product = an item of the kinds we sell, worn or shown (also a "
    "screenshot of a shop page or post); design = a logo, badge, artwork, drawing "
    "or embroidery pattern to be made or stitched on something; other = anything "
    "else (a payment receipt, a document, a person or measurements, a place, a "
    "meme).\n"
    "closest: the ONE listed item that is the same kind of item as the main thing "
    "in the photo (a chasuble is never a cope, a stole is never a scarf). NONE if "
    "none is.\n"
    "embroidery: how much decorative embroidery, appliqué or ornament the item "
    "itself carries.\n"
    "ai_made: is the photo itself generated or heavily altered by AI? Signs: "
    "embroidery too perfect or too dense to be stitched, symmetry no workshop "
    "makes, garbled or nonsense lettering, fabric or trim melting into the "
    "background or into the body, impossible folds, waxy skin, warped hands, "
    "an unreal setting, an AI watermark. A plain phone photo or a shop "
    "photograph is unlikely.")

_COMPARE_SYSTEM = (
    "You compare a customer's photo with a shop's own catalogue photos of one "
    "product. You answer with ONE JSON object and nothing else.")

_COMPARE_ASK = (
    "Is the main item in the CUSTOMER photo our '{name}' as shown in OUR photos? "
    "Answer with this JSON:\n"
    '{{"match": "same" | "close" | "far",\n'
    ' "extra_embroidery": true | false,\n'
    ' "extra_embroidery_detail": ["<short phrase>", ...],\n'
    ' "differences": ["<short phrase>", ...]}}\n\n'
    "same = the same product; lighting, angle, background and the person wearing "
    "it may differ.\n"
    "close = the same product in another colour, fabric shade or size — nothing "
    "added, nothing re-cut.\n"
    "far = a different cut, shape or construction, different motifs or "
    "decoration, or not really this item.\n"
    "extra_embroidery = true when the customer's item carries ANY embroidery, "
    "appliqué, motifs, patterns, lettering, names or logos that our photos of "
    "this product do not show (more of it, denser, or different). Name it in "
    "extra_embroidery_detail.")


async def _read(llm, system: str, content: list) -> dict:
    resp = await llm.complete(system=system, messages=[{"role": "user", "content": content}],
                              tools=[])
    return _parse(resp.text or "")


async def check_photo(redis, block: dict, catalog: list[dict], caption: str = "") -> dict:
    """The check for one customer photo (an Anthropic image block, as the
    turn already loaded it). Never raises: any failure is verdict "unknown"."""
    sha = image_sha(block)
    out = {"verdict": "unknown", "reasons": [], "product": None, "product_slug": None,
           "match": None, "ai_made": None, "extra_embroidery": None, "source": None,
           "image_sha": sha}
    if not sha:
        return out
    if redis is not None:
        try:
            cached = await redis.get(_cache_key(sha))
            if cached:
                return json.loads(cached)
        except Exception:
            pass
    try:
        out = await _check(redis, block, catalog, caption, out)
    except Exception as exc:
        _log.info("photo check failed: %s", exc)
        return out
    if redis is not None and out["verdict"] != "unknown":
        try:
            await redis.set(_cache_key(sha), json.dumps(out), ex=CACHE_TTL)
        except Exception:
            pass
    return out


async def _check(redis, block: dict, catalog: list[dict], caption: str, out: dict) -> dict:
    from app.services import post_catalog as pc
    # 1. It IS one of our own photos.
    try:
        raw = base64.standard_b64decode(block["source"]["data"])
        h = pc.dhash_bytes(raw)
    except Exception:
        h = None
    if h is not None and catalog:
        try:
            prints = await asyncio.wait_for(pc._catalog_fingerprints(redis, catalog), timeout=10)
        except Exception:
            prints = []
        scored = sorted(((pc.hamming(h, ph), p) for p, ph in prints), key=lambda x: x[0])
        if scored and scored[0][0] <= pc.HASH_MATCH_MAX:
            row = scored[0][1]
            out.update(verdict="ours", reasons=[f"our own photo of {row.get('name')}"],
                       product=row.get("name"), product_slug=row.get("slug"),
                       match="same", source="fingerprint")
            return out

    from app.agent.media import load_image_block
    from app.agent.runtime import build_llm          # lazy: runtime imports services
    llm = build_llm(model=(settings.photo_check_model or settings.tier2_model_vision
                           or settings.tier2_model), purpose="vision", cache=False)
    cands = pc.vision_candidates(catalog, caption)
    listing = "\n".join(f"- {p.get('name')}" for p in cands) or "(none)"
    cap = f"The customer wrote with it: {caption.strip()[:300]}\n\n" if caption.strip() else ""
    # 2. What it shows, and the closest thing we sell.
    look = await _read(llm, _LOOK_SYSTEM, [
        block, {"type": "text", "text": _LOOK_ASK.format(listing=listing, caption=cap)}])
    if not look:
        return out
    product = _pick(str(look.get("closest") or ""), cands)
    if product is not None and _word(look.get("conf"), {"high", "medium", "low"}, "low") == "low":
        product = None
    # 3. Beside our own photos of it.
    compare = None
    if product is not None and _word(look.get("subject"), _SUBJECTS, "product") == "product":
        ours = [b for b in [await asyncio.to_thread(load_image_block, u)
                            for u in _catalog_photos(product)] if b]
        if ours:
            content = [{"type": "text", "text": "CUSTOMER photo:"}, block,
                       {"type": "text", "text": f"OUR catalogue photo(s) of '{product.get('name')}':"},
                       *ours,
                       {"type": "text", "text": _COMPARE_ASK.format(name=product.get("name"))}]
            compare = await _read(llm, _COMPARE_SYSTEM, content) or None
    verdict, reasons = decide(look, compare, product)
    out.update(verdict=verdict, reasons=reasons,
               product=(product or {}).get("name"), product_slug=(product or {}).get("slug"),
               match=(_word((compare or {}).get("match"), _MATCHES, "far") if compare else None),
               ai_made=_word(look.get("ai_made"), _AI, "unlikely"),
               extra_embroidery=(bool(compare.get("extra_embroidery")) if compare else None),
               source="vision")
    return out


# ── what the turn does with it ───────────────────────────────────────────────

REFER_NOTE = (
    "\n\n(PHOTO CHECK — this photo needs a colleague: {why}. Do NOT quote a price "
    "for what is in it and do not promise we can make it. Thank them warmly for the "
    "photo, say a colleague will look at the design and confirm what it involves and "
    "what it would cost, and keep the conversation going meanwhile — ask what it is "
    "for, the size or quantity, and when they need it. Quote no price at all this "
    "turn.)")

SAFE_LINE = {
    "en": ("Thank you for the photo! A colleague will look at this design and confirm "
           "what it involves and what it would cost. Meanwhile, what is it for, and when "
           "would you need it?"),
    "sw": ("Asante kwa picha! Mwenzangu ataangalia muundo huu na kuthibitisha "
           "unachohusisha na gharama yake. Wakati huo huo, ni kwa ajili ya nini, na "
           "utauhitaji lini?"),
}


def why(check: dict) -> str:
    return "; ".join(check.get("reasons") or []) or "it differs from what we make"


async def record(check: dict, *, channel: str, contact: str, media_url: str | None,
                 mode: str, acted: bool) -> None:
    """One photo_checks row — the owner's review list. Finds the conversation
    and the customer's message the photo came in on, so the list shows the
    photo from its permanent copy. Best-effort; never raises."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection
    from app.models.photo_check import PhotoCheck
    try:
        async with AsyncSessionLocal() as db:
            conv = (await db.execute(select(Conversation).where(
                Conversation.channel == channel,
                or_(Conversation.external_id == contact, Conversation.wa_id == contact)))
            ).scalars().first()
            sha = check.get("image_sha") or None
            if sha:
                # The same photo in the same chat (a re-run of a missed turn)
                # is one row, not one per attempt.
                dup = (await db.execute(select(PhotoCheck.id).where(
                    PhotoCheck.image_sha == sha, PhotoCheck.channel == channel,
                    PhotoCheck.contact == contact[:128],
                    PhotoCheck.created_at >= datetime.now(timezone.utc) - timedelta(days=1))
                    .limit(1))).scalar()
                if dup is not None:
                    return
            msg_id = None
            if conv is not None:
                since = datetime.now(timezone.utc) - timedelta(hours=2)
                rows = (await db.execute(
                    select(Message.id, Message.media_url).where(
                        Message.conversation_id == conv.id,
                        Message.direction == MsgDirection.inbound,
                        Message.media_type == "image",
                        Message.created_at >= since)
                    .order_by(Message.created_at.desc()).limit(5))).all()
                hit = next((r for r in rows if media_url and r[1] == media_url), None) \
                    or (rows[0] if rows else None)
                msg_id = hit[0] if hit else None
            db.add(PhotoCheck(
                channel=channel, contact=contact[:128],
                conversation_id=conv.id if conv is not None else None, message_id=msg_id,
                media_url=media_url, image_sha=sha,
                verdict=check.get("verdict") or "unknown", product=(check.get("product") or None),
                product_slug=check.get("product_slug"), match=check.get("match"),
                ai_made=check.get("ai_made"), extra_embroidery=check.get("extra_embroidery"),
                reasons=list(check.get("reasons") or []), source=check.get("source"),
                mode=mode, acted=acted))
            await db.commit()
    except Exception:
        _log.warning("photo check record failed for %s/%s", channel, contact, exc_info=True)


_bg: set = set()


def run_in_background(redis, block: dict, catalog: list[dict], caption: str, *,
                      channel: str, contact: str, media_url: str | None) -> None:
    """Shadow mode: check and record off the reply path — the customer's
    answer is never slowed or changed."""
    async def go():
        check = await check_photo(redis, block, catalog, caption)
        await record(check, channel=channel, contact=contact, media_url=media_url,
                     mode="shadow", acted=False)
    task = asyncio.create_task(go())
    _bg.add(task)
    task.add_done_callback(_bg.discard)
