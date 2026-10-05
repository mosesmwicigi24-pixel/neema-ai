"""What an inbound WhatsApp message IS — for the team, for the AI, and for the
record — whatever type Meta sends.

Why this module exists (calls & audio programme, cycle 2, 2026-10-05). The
dashboard showed "Message can't be displayed (unsupported type)" 39 times in
30 days and nobody could say what those messages were: the parser turned every
type it didn't know into one fixed sentence (or, for some interactive replies,
into an EMPTY row) and threw Meta's payload away. Three things follow here:

  1. Every type Meta documents gets a meaningful line of text — the text the
     inbox preview, the thread and the AI's history all read.
  2. Messages that are not plain text/media carry a small structured record
     (`Message.raw_meta`, JSONB) so the dashboard can draw a designed card
     (a map link, a contact, "Reacted ❤️ to …") instead of a sentence.
  3. For anything we do NOT handle, the record also keeps Meta's own `type`,
     its `errors` (code / title / details) and a trimmed, PII-redacted copy of
     the payload — so the next unknown is identifiable from the database, not
     guessed at. That copy never leaves the API (the thread endpoint strips it).

Nothing here talks to the network or the database: `describe()` is a pure
function of one webhook message dict, which is what makes it testable against
every documented shape.
"""
from __future__ import annotations

import json
from typing import Any

META_VERSION = 1

# Plain types: text, and media whose words are its caption. They need no
# record — the row's own columns already say everything.
PLAIN_TYPES = ("text", "image", "audio", "video", "document")

# Types the AI should NOT be woken for: presence and plumbing, not a question.
# (A 👍 must not earn the customer a sales reply; a number change or a call
# permission tap is bookkeeping.)
_NO_WAKE_KINDS = {"reaction", "system", "call_permission", "call_notice", "sticker", "deleted", "edited"}

# ── Unsupported sub-types ────────────────────────────────────────────────────
# Meta delivers several WhatsApp features to businesses as `type: "unsupported"`
# (error 131051 "Message type unknown"). Newer webhook versions name the feature
# in `unsupported.type`; older ones only in the error details. Each known one
# gets words a person understands. Keys are lower-cased and matched loosely.
_UNSUPPORTED_LABELS: dict[str, tuple[str, str, bool]] = {
    # key: (label used in "a <label>", what the team can do, wake the AI?)
    "view_once": ("view-once photo or video",
                  "WhatsApp never delivers view-once media to businesses. You can ask them "
                  "to send it again as a normal photo or video.", True),
    "poll": ("poll", "Polls don't reach business accounts. You can ask them to type the choices.", True),
    "poll_creation": ("poll", "Polls don't reach business accounts. You can ask them to type the choices.", True),
    "poll_update": ("poll vote", "Poll votes don't reach business accounts.", False),
    "edit": ("edit to an earlier message",
             "WhatsApp doesn't share the new wording with businesses — the original is what we have.", False),
    "edited": ("edit to an earlier message",
               "WhatsApp doesn't share the new wording with businesses — the original is what we have.", False),
    "message_edit": ("edit to an earlier message",
                     "WhatsApp doesn't share the new wording with businesses — the original is what we have.", False),
    "revoke": ("deleted message", "They deleted a message they had sent.", False),
    "revoked": ("deleted message", "They deleted a message they had sent.", False),
    "deleted": ("deleted message", "They deleted a message they had sent.", False),
    "video_note": ("video note (a round video message)",
                   "Video notes don't reach business accounts. You can ask them to send it as a normal video.", True),
    "event": ("event invitation", "Event invitations don't reach business accounts.", True),
    "event_creation": ("event invitation", "Event invitations don't reach business accounts.", True),
    "ephemeral": ("disappearing message",
                  "Disappearing messages don't reach business accounts. You can ask them to send it as text.", True),
    "pin": ("pinned message", "Pins don't reach business accounts.", False),
    "keep_in_chat": ("kept message", "WhatsApp doesn't share this with businesses.", False),
    "group_invite": ("group invite link", "Group invites don't reach business accounts.", True),
    "unknown": ("message", "", True),
}

_GENERIC_ADVICE = "You can ask them to send it as a photo or text."

# The kinds a deleted / edited unsupported message maps to (no AI wake).
_UNSUPPORTED_KIND = {"revoke": "deleted", "revoked": "deleted", "deleted": "deleted",
                     "edit": "edited", "edited": "edited", "message_edit": "edited"}

# ── PII-safe payload copy ────────────────────────────────────────────────────
# Strings are kept ONLY under these structural keys (they describe the shape,
# never the person). Every other string becomes "<str:N>" (its length), numbers
# under location keys are dropped, lists are cut to 5 items, depth to 5 and the
# whole copy to ~2 KB. Enough to learn what an unknown type looks like.
_KEEP_STRING_KEYS = {
    "type", "code", "title", "message", "details", "mime_type", "status", "event",
    "response", "response_source", "source_type", "media_type", "emoji", "animated",
    "sub_type", "subtype", "kind", "messaging_product", "voice",
}
_DROP_NUMBER_KEYS = {"latitude", "longitude"}
_MAX_COPY_BYTES = 2048


def redact(obj: Any, depth: int = 0, key: str | None = None) -> Any:
    """A structure-preserving, PII-free copy of one webhook object."""
    if depth > 5:
        return "<…>"
    if isinstance(obj, dict):
        out = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= 30:
                out["<…>"] = f"{len(obj) - 30} more keys"
                break
            out[str(k)[:40]] = redact(v, depth + 1, str(k))
        return out
    if isinstance(obj, list):
        items = [redact(v, depth + 1, key) for v in obj[:5]]
        if len(obj) > 5:
            items.append(f"<{len(obj) - 5} more>")
        return items
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        return "<num>" if (key or "").lower() in _DROP_NUMBER_KEYS else obj
    s = str(obj)
    if (key or "").lower() in _KEEP_STRING_KEYS:
        return s[:120]
    return f"<str:{len(s)}>"


def _bounded(copy: Any) -> Any:
    """Cap the redacted copy's serialized size (a hostile or huge payload must
    never bloat a messages row)."""
    try:
        raw = json.dumps(copy, ensure_ascii=False)
    except Exception:
        return {"<unserializable>": True}
    if len(raw.encode("utf-8")) <= _MAX_COPY_BYTES:
        return copy
    if isinstance(copy, dict):
        return {"<truncated>": True, "keys": sorted(copy.keys())[:30]}
    return {"<truncated>": True}


def errors_of(msg: dict) -> list[dict]:
    """Meta's `errors` block, normalised to code / title / details (≤ 3)."""
    out = []
    for e in (msg.get("errors") or [])[:3]:
        if not isinstance(e, dict):
            continue
        details = ((e.get("error_data") or {}).get("details") if isinstance(e.get("error_data"), dict)
                   else None) or e.get("details") or e.get("message")
        out.append({k: v for k, v in {
            "code": e.get("code"),
            "title": (str(e["title"])[:120] if e.get("title") else None),
            "details": (str(details)[:200] if details else None),
        }.items() if v is not None})
    return out


def _unsupported_key(msg: dict) -> str:
    """The feature behind an `unsupported` message, when Meta names it."""
    t = str(msg.get("type") or "").lower()
    sub = msg.get("unsupported") if isinstance(msg.get("unsupported"), dict) else {}
    for cand in (sub.get("type"), sub.get("message_type"), t if t != "unsupported" else None):
        c = str(cand or "").strip().lower()
        if c:
            return c
    # Older shapes name it only in the error details ("… view once …").
    blob = " ".join(str(e.get("details") or e.get("title") or "") for e in errors_of(msg)).lower()
    for k, needle in (("view_once", "view once"), ("poll", "poll"), ("edit", "edit"),
                      ("video_note", "video note"), ("revoked", "delet")):
        if needle in blob:
            return k
    return "unknown"


def _money(amount: Any, currency: Any) -> str:
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return ""
    cur = str(currency or "").upper()
    s = f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"
    return f"{cur} {s}".strip()


def _a(label: str) -> str:
    return "an" if label[:1].lower() in "aeiou" else "a"


class Described(dict):
    """{text, agent_text, wake, meta} — a dict so it rides events as-is."""


def describe(msg: dict) -> Described:
    """Describe one Cloud API webhook message.

    text        → stored on the row: the preview, the thread and the AI history.
    agent_text  → what THIS turn hands the agent (defaults to `text`).
    wake        → whether the agent should answer this message at all.
    meta        → the structured record for `Message.raw_meta`, or None for a
                  plain text / media message.
    """
    t = str(msg.get("type") or "")
    errs = errors_of(msg)

    def done(text: str, kind: str | None, data: dict | None = None, *,
             agent_text: str | None = None, wake: bool | None = None,
             keep_payload: bool = False) -> Described:
        meta = None
        if kind is not None:
            meta = {"v": META_VERSION, "type": t or "unknown", "kind": kind}
            if data:
                meta.update({k: v for k, v in data.items() if v not in (None, "", [], {})})
            if errs:
                meta["errors"] = errs
            if keep_payload:
                meta["payload"] = _bounded(redact(msg))
        elif errs:
            # A plain type that still carried errors (e.g. media Meta couldn't
            # fetch): keep the errors so the failure is visible to the team.
            meta = {"v": META_VERSION, "type": t, "kind": "plain", "errors": errs}
        return Described(text=text, agent_text=agent_text or text,
                         wake=(kind not in _NO_WAKE_KINDS) if wake is None else wake,
                         meta=meta)

    if t == "text":
        return done(((msg.get("text") or {}).get("body") or "").strip(), None)

    if t in ("image", "audio", "video", "document"):
        return done(((msg.get(t) or {}).get("caption") or "").strip(), None)

    if t == "sticker":
        st = msg.get("sticker") or {}
        return done("🙂 Sent a sticker", "sticker", {"animated": bool(st.get("animated"))},
                    agent_text="(The customer sent a sticker — an emoji-style reaction, not a product photo.)")

    if t == "reaction":
        r = msg.get("reaction") or {}
        emoji = (r.get("emoji") or "").strip()
        data = {"emoji": emoji, "to_wamid": r.get("message_id")}
        if not emoji:
            return done("Removed their reaction", "reaction", data)
        return done(f"{emoji} (reacted to your message)", "reaction", data)

    if t == "location":
        loc = msg.get("location") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        parts = [p for p in (loc.get("name"), loc.get("address")) if p]
        coords = f"{lat},{lng}" if lat is not None and lng is not None else ""
        if parts:
            text = "📍 Location: " + ", ".join(parts) + (f" ({coords})" if coords else "")
        else:
            text = "📍 Location: " + (coords or "shared a location")
        return done(text, "location", {"lat": lat, "lng": lng, "name": loc.get("name"),
                                       "address": loc.get("address"), "url": loc.get("url")})

    if t == "contacts":
        cards = []
        for c in (msg.get("contacts") or [])[:5]:
            name = ((c.get("name") or {}).get("formatted_name") or "").strip()
            phones = [str(p.get("phone") or p.get("wa_id") or "").strip()
                      for p in (c.get("phones") or [])[:3]]
            phones = [p for p in phones if p]
            org = ((c.get("org") or {}).get("company") or "").strip()
            cards.append({"name": name, "phones": phones, "org": org or None})
        bits = []
        for c in cards:
            label = c["name"] or (c["phones"][0] if c["phones"] else "")
            if c["name"] and c["phones"]:
                label = f"{c['name']} ({', '.join(c['phones'])})"
            if label:
                bits.append(label)
        text = "👤 Shared contact: " + (", ".join(bits) if bits else "a contact card")
        return done(text, "contacts", {"contacts": cards})

    if t == "button":
        b = msg.get("button") or {}
        title = (b.get("text") or "").strip()
        return done(title or "Tapped a button", "reply",
                    {"title": title, "source": "template_button"})

    if t == "interactive":
        i = msg.get("interactive") or {}
        itype = str(i.get("type") or "")
        for k in ("button_reply", "list_reply"):
            if i.get(k):
                r = i[k] or {}
                title = (r.get("title") or "").strip()
                desc = (r.get("description") or "").strip()
                return done(title or "Tapped a button", "reply",
                            {"title": title, "description": desc, "source": k})
        if itype == "call_permission_reply" or i.get("call_permission_reply"):
            cp = i.get("call_permission_reply") or {}
            resp = str(cp.get("response") or "").lower()
            permanent = bool(cp.get("is_permanent"))
            if resp == "accept":
                text = "✅ Allowed WhatsApp calls" + (" — permanently" if permanent else "")
            elif resp == "reject":
                text = "🚫 Declined WhatsApp calls"
            else:
                text = "Answered the call request"
            return done(text, "call_permission", {
                "response": resp or None, "permanent": permanent,
                "expires_at": cp.get("expiration_timestamp"),
                "source": cp.get("response_source")})
        if itype == "nfm_reply" or i.get("nfm_reply"):
            nfm = i.get("nfm_reply") or {}
            fields: dict = {}
            try:
                fields = json.loads(nfm.get("response_json") or "{}") or {}
            except Exception:
                fields = {}
            shown = {str(k)[:40]: str(v)[:120] for k, v in list(fields.items())[:12]
                     if k != "flow_token" and v not in (None, "")}
            name = (nfm.get("name") or "").strip()
            summary = "; ".join(f"{k}: {v}" for k, v in shown.items())
            text = "📝 Submitted a form" + (f" ({name})" if name and name != "flow" else "")
            if summary:
                text += f" — {summary}"
            return done(text, "form", {"name": name, "fields": shown})
        # An interactive reply we don't know yet: never an empty row.
        return done("Replied with a WhatsApp button we can't show here", "unsupported",
                    {"label": "button reply", "advice": _GENERIC_ADVICE, "subtype": itype or None},
                    keep_payload=True)

    if t == "order":
        o = msg.get("order") or {}
        items = o.get("product_items") or []
        n = 0
        total = 0.0
        cur = ""
        lines, parsed = [], []
        for it in items[:20]:
            try:
                q = int(it.get("quantity") or 1)
            except (TypeError, ValueError):
                q = 1
            n += q
            sku = str(it.get("product_retailer_id") or "item")[:60]
            try:
                total += float(it.get("item_price") or 0) * q
            except (TypeError, ValueError):
                pass
            cur = cur or str(it.get("currency") or "")
            lines.append(f"{sku} ×{q}")
            parsed.append({"sku": sku, "qty": q, "price": it.get("item_price"),
                           "currency": it.get("currency")})
        text = f"🛒 Sent a cart from the catalog: {n} item{'s' if n != 1 else ''}"
        if lines:
            text += " — " + ", ".join(lines[:8]) + ("…" if len(lines) > 8 else "")
        tot = _money(total, cur) if total else ""
        if tot:
            text += f" ({tot})"
        note = (o.get("text") or "").strip()
        if note:
            text += f'. Note: "{note[:200]}"'
        return done(text, "order", {"items": parsed, "count": n, "total": tot or None,
                                    "note": note or None})

    if t == "system":
        s = msg.get("system") or {}
        stype = str(s.get("type") or "")
        if stype in ("user_changed_number", "customer_changed_number"):
            new = str(s.get("new_wa_id") or s.get("wa_id") or "")
            text = "📱 Changed their WhatsApp number" + (f" to +{new.lstrip('+')}" if new else "")
            return done(text, "system", {"subtype": stype, "new_wa_id": new or None})
        if stype in ("customer_identity_changed", "user_identity_changed"):
            return done("🔐 Their WhatsApp security code changed", "system", {"subtype": stype})
        return done("WhatsApp sent a notice about this chat", "system",
                    {"subtype": stype or None}, keep_payload=True)

    if t == "request_welcome":
        return done("👋 Opened a chat with us for the first time", "welcome", None,
                    agent_text="(The customer just opened a chat with us for the first time and "
                               "hasn't written anything yet. Greet them warmly and ask how we can help.)")

    # ── Unsupported / unknown: the residual ──────────────────────────────────
    key = _unsupported_key(msg)
    # A call-related notice (Meta names a call / missed-call feature): part of
    # that call, not a message — the dashboard folds it into the call's card.
    if "call" in key:
        return done("📞 WhatsApp sent a notice about a call", "call_notice",
                    {"label": key.replace("_", " "), "subtype": key},
                    wake=False, keep_payload=True)
    label, advice, wake = _UNSUPPORTED_LABELS.get(key, (key.replace("_", " ") or "message",
                                                        _GENERIC_ADVICE, True))
    kind = _UNSUPPORTED_KIND.get(key, "unsupported")
    if kind == "deleted":
        text = "🗑️ Deleted a message"
    elif kind == "edited":
        text = "✏️ Edited an earlier message (WhatsApp doesn't share the new wording)"
    elif key == "unknown":
        text = f"Sent something WhatsApp doesn't let us show here. {_GENERIC_ADVICE}"
    else:
        text = (f"Sent something WhatsApp doesn't let us show here — {_a(label)} {label}. "
                f"{advice or _GENERIC_ADVICE}").strip()
    agent_text = (f"(The customer sent {_a(label)} {label} "
                  "that WhatsApp does not deliver to businesses, so we cannot see what it says. "
                  "If it seems to matter, kindly ask them to send it as a photo or a text.)")
    return done(text, kind, {"label": label, "advice": advice or _GENERIC_ADVICE,
                             "subtype": None if key == "unknown" else key},
                agent_text=agent_text, wake=wake, keep_payload=True)


def public_meta(meta: dict | None) -> dict | None:
    """The record as the dashboard may see it: everything except the redacted
    payload copy (that stays in the database for whoever investigates)."""
    if not isinstance(meta, dict):
        return None
    return {k: v for k, v in meta.items() if k != "payload"} or None


# ── Messenger / Instagram / TikTok ───────────────────────────────────────────
# Their webhooks are different shapes, but the residual is the same problem:
# a message with no text and no usable attachment used to land as a bracket
# placeholder ("[story_mention]", "[unsupported message]") or a warning
# sentence. Same rule as WhatsApp: words a person understands, a record for
# the team, Meta's/TikTok's own type kept.

_APP_NAME = {"messenger": "Messenger", "facebook": "Facebook", "instagram": "Instagram",
             "tiktok": "TikTok", "whatsapp": "WhatsApp"}

_SOCIAL_ATTACHMENT_WORDS = {
    "story_mention": ("📸 Mentioned us in their story", "story_mention"),
    "story": ("📸 Replied to our story", "story"),
    "share": ("🔗 Shared a post", "share"),
    "ig_reel": ("🎬 Shared a reel", "share"),
    "reel": ("🎬 Shared a reel", "share"),
    "ig_post": ("🔗 Shared a post", "share"),
    "template": ("🔗 Shared a card", "share"),
    "fallback": ("🔗 Shared a link", "share"),
    "sticker": ("🙂 Sent a sticker", "sticker"),
}


def unsupported_social(channel: str, mtype: str | None, raw: dict | None = None,
                       errs: list | None = None) -> tuple[str, dict]:
    """(text, meta) for a Messenger / Instagram / TikTok message we can't show."""
    app = _APP_NAME.get(channel, channel.title() if channel else "The app")
    t = str(mtype or "").strip()
    label = t.replace("_", " ") if t and t not in ("unsupported", "unknown") else ""
    if label:
        text = f"Sent something {app} doesn't let us show here — {_a(label)} {label}. {_GENERIC_ADVICE}"
    else:
        text = f"Sent something {app} doesn't let us show here. {_GENERIC_ADVICE}"
    meta = {"v": META_VERSION, "type": t or "unknown", "kind": "unsupported",
            "app": app, "label": label or None, "advice": _GENERIC_ADVICE}
    meta = {k: v for k, v in meta.items() if v is not None}
    if errs:
        meta["errors"] = errs
    if raw is not None:
        meta["payload"] = _bounded(redact(raw))
    return text, meta


def describe_meta_dm(message: dict, channel: str) -> tuple[str | None, dict | None]:
    """For a Messenger / Instagram DM `message` object: (replacement text, meta)
    when the message is one the plain text/attachment path can't express —
    an unsent (deleted) message, Meta's `is_unsupported`, a story mention, a
    share without a usable URL, a legacy location pin. (None, None) otherwise."""
    if message.get("is_deleted"):
        return "🗑️ Unsent a message", {"v": META_VERSION, "type": "deleted", "kind": "deleted"}
    if message.get("is_unsupported"):
        return unsupported_social(channel, "unsupported", message)
    if (message.get("text") or "").strip():
        return None, None
    for att in (message.get("attachments") or []):
        at = str(att.get("type") or "").lower()
        payload = att.get("payload") or {}
        if at == "location":
            co = payload.get("coordinates") or {}
            lat, lng = co.get("lat"), co.get("long")
            if lat is not None and lng is not None:
                title = (att.get("title") or "").strip()
                text = "📍 Location: " + (f"{title} " if title else "") + f"({lat},{lng})"
                return text, {"v": META_VERSION, "type": "location", "kind": "location",
                              "lat": lat, "lng": lng, **({"name": title} if title else {})}
        if at in _SOCIAL_ATTACHMENT_WORDS:
            words, kind = _SOCIAL_ATTACHMENT_WORDS[at]
            if (payload.get("url") or att.get("url")) and at not in ("story_mention", "story", "sticker"):
                return None, None      # the media path renders it
            return words, {"v": META_VERSION, "type": at, "kind": kind}
    if message.get("attachments"):
        at = str((message["attachments"][0] or {}).get("type") or "")
        p = message["attachments"][0] or {}
        if not ((p.get("payload") or {}).get("url") or p.get("url")):
            return unsupported_social(channel, at or "unsupported", message)
    return None, None
