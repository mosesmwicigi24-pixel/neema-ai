// What a non-plain message IS, in words a person reads — the dashboard half of
// services/inbound_kinds.py (calls & audio programme, cycle 2, 2026-10-05).
//
// The server stores, for every inbound message that is not plain text/media,
// a small record (`meta`): Meta's own type, our `kind` (location, contact,
// reaction, call-permission reply, unsupported + Meta's error …) and the
// fields a card is drawn from. This module turns that record into a view —
// pure data, no React — so every kind reads the same everywhere and is
// testable on its own (tests/messageKinds.test.mjs). Rows written before the
// record existed are recognised from their old wording (legacyMeta), so the
// thread never again shows a bare "can't be displayed" warning.
//
// No imports on purpose: node runs the tests on this file directly.

export interface MessageMetaError { code?: number; title?: string; details?: string }

export interface MessageMeta {
    v?: number;
    /** Meta's / TikTok's own message type ("unsupported", "reaction", …). */
    type?: string;
    kind?: string;
    // location
    lat?: number; lng?: number; name?: string; address?: string;
    // contacts
    contacts?: { name?: string; phones?: string[]; org?: string | null }[];
    // reaction
    emoji?: string; to_text?: string; to_sender?: string;
    // reply / form
    title?: string; description?: string; source?: string;
    fields?: Record<string, string>;
    // order
    items?: { sku?: string; qty?: number; price?: number | string; currency?: string }[];
    count?: number; total?: string; note?: string;
    // call permission
    response?: string; permanent?: boolean; expires_at?: number | string;
    // system
    subtype?: string; new_wa_id?: string;
    // unsupported
    label?: string; advice?: string; app?: string;
    errors?: MessageMetaError[];
    // comment media / voicemail
    photo?: string; video?: string; call_id?: string;
    /** Set by legacyMeta for rows stored before the record existed. */
    legacy?: boolean;
}

export type KindTone = "neutral" | "info" | "good" | "warn" | "muted";

export interface KindLink { href: string; label: string }

export interface KindView {
    /** One glyph, decorative (the words carry the meaning). */
    icon: string;
    title: string;
    /** Secondary lines, each already in words. */
    lines: string[];
    link?: KindLink;
    tone: KindTone;
    /** Render as a centred event pill (not something the customer "said"). */
    centred: boolean;
    /** Small print for the team — Meta's type / error, never the payload. */
    details?: string;
}

const APP_DEFAULT = "WhatsApp";
const GENERIC_ADVICE = "You can ask them to send it as a photo or text.";

const article = (s: string) => (/^[aeiou]/i.test(s) ? "an" : "a");

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A map link built ONLY from the coordinates (never a URL the sender chose). */
export function mapsHref(lat: unknown, lng: unknown): string | null {
    if (!isNum(lat) || !isNum(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
    return `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
}

/** "Meta: unsupported · 131051 Message type unknown" — the team's small print. */
export function detailsLine(meta: MessageMeta): string | undefined {
    const bits: string[] = [];
    if (meta.type && meta.type !== "unknown") bits.push(`type “${meta.type}”`);
    for (const e of meta.errors ?? []) {
        const t = [e.code, e.title].filter((x) => x !== undefined && x !== null && x !== "").join(" ");
        if (t) bits.push(t);
    }
    return bits.length ? bits.join(" · ") : undefined;
}

// ── Old rows: recognised from the words they were stored with ─────────────────

const OLD_NATIVE = /^⚠️ Sent a message we can't display here \(([^)]*) type\) — ask them to resend as text\.?$/;
const OLD_MESSENGER = /^⚠️ Sent a message we can't display here — ask them to resend as text\.?$/;

/** A record for a row stored before records existed — or null when the row is
 *  an ordinary message. `hasMedia` = the row carries a media type. */
export function legacyMeta(text: string | null | undefined, hasMedia: boolean): MessageMeta | null {
    const t = (text ?? "").trim();
    const m = t.match(OLD_NATIVE);
    if (m) {
        const type = (m[1] || "").trim();
        return { kind: "unsupported", type: type && type !== "unknown" ? type : undefined, legacy: true };
    }
    if (OLD_MESSENGER.test(t) || t === "[unsupported message]") return { kind: "unsupported", legacy: true };
    if (!t && !hasMedia) return { kind: "unsupported", legacy: true };
    return null;
}

// ── Unsupported labels (mirror of the server's, for legacy rows) ──────────────

const UNSUPPORTED_LABEL: Record<string, string> = {
    unsupported: "",
    unknown: "",
    view_once: "view-once photo or video",
    poll: "poll",
    poll_creation: "poll",
    video_note: "video note (a round video message)",
    event: "event invitation",
    ephemeral: "disappearing message",
    request_welcome: "",
    system: "",
};

export function unsupportedTitle(meta: MessageMeta): string {
    const app = meta.app || APP_DEFAULT;
    const raw = meta.label ?? (meta.subtype ? UNSUPPORTED_LABEL[meta.subtype] ?? meta.subtype.replace(/_/g, " ")
        : meta.type ? UNSUPPORTED_LABEL[meta.type] ?? meta.type.replace(/_/g, " ") : "");
    const label = (raw || "").trim();
    return label && label !== "message"
        ? `Sent something ${app} doesn't let us show here — ${article(label)} ${label}.`
        : `Sent something ${app} doesn't let us show here.`;
}

// ── The view for each kind ────────────────────────────────────────────────────

function fmtExpiry(v: number | string | undefined): string | null {
    if (v === undefined || v === null || v === "") return null;
    const n = typeof v === "number" ? v : Number(v);
    if (!Number.isFinite(n)) return null;
    const d = new Date(n < 1e12 ? n * 1000 : n);
    if (!Number.isFinite(d.getTime())) return null;
    return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

/** The card for a record, or null when the row should render as plain text. */
export function kindView(meta: MessageMeta | null | undefined): KindView | null {
    if (!meta || !meta.kind) return null;
    switch (meta.kind) {
        case "location": {
            const href = mapsHref(meta.lat, meta.lng);
            const place = [meta.name, meta.address].filter(Boolean).join(" · ");
            return {
                icon: "📍", title: "Shared a location", tone: "info", centred: false,
                lines: place ? [place] : isNum(meta.lat) && isNum(meta.lng) ? [`${meta.lat}, ${meta.lng}`] : [],
                link: href ? { href, label: "Open map" } : undefined,
            };
        }
        case "contacts": {
            const cs = (meta.contacts ?? []).filter((c) => c && (c.name || (c.phones ?? []).length));
            const title = cs.length > 1 ? `Shared ${cs.length} contacts` : "Shared a contact";
            const lines = cs.slice(0, 5).map((c) =>
                [c.name, (c.phones ?? []).join(", "), c.org].filter(Boolean).join(" · "));
            return { icon: "👤", title, lines: lines.length ? lines : ["A contact card"], tone: "info", centred: false };
        }
        case "reaction": {
            const emoji = (meta.emoji || "").trim();
            const to = (meta.to_text || "").trim();
            const quoted = to ? `“${to.length > 80 ? `${to.slice(0, 79)}…` : to}”` : "your message";
            return emoji
                ? { icon: emoji, title: `Reacted ${emoji} to ${quoted}`, lines: [], tone: "neutral", centred: false }
                : { icon: "↩︎", title: `Removed their reaction${to ? ` to ${quoted}` : ""}`, lines: [], tone: "muted", centred: false };
        }
        case "call_permission": {
            const exp = fmtExpiry(meta.expires_at);
            if (meta.response === "accept") {
                return {
                    icon: "✅", title: meta.permanent ? "Allowed WhatsApp calls — permanently" : "Allowed WhatsApp calls",
                    lines: !meta.permanent && exp ? [`Until ${exp}`] : [], tone: "good", centred: true,
                };
            }
            if (meta.response === "reject") {
                return { icon: "🚫", title: "Declined WhatsApp calls", lines: [], tone: "warn", centred: true };
            }
            return { icon: "📞", title: "Answered the call request", lines: [], tone: "neutral", centred: true };
        }
        case "system": {
            if (meta.subtype === "user_changed_number" || meta.subtype === "customer_changed_number") {
                return {
                    icon: "📱", title: "Changed their WhatsApp number",
                    lines: meta.new_wa_id ? [`New number: +${String(meta.new_wa_id).replace(/^\+/, "")}`] : [],
                    tone: "info", centred: true,
                };
            }
            if (meta.subtype === "customer_identity_changed" || meta.subtype === "user_identity_changed") {
                return { icon: "🔐", title: "Their WhatsApp security code changed", lines: [], tone: "muted", centred: true };
            }
            return { icon: "ℹ️", title: "WhatsApp sent a notice about this chat", lines: [], tone: "muted", centred: true,
                details: detailsLine(meta) };
        }
        case "welcome":
            return { icon: "👋", title: "Opened a chat with us for the first time", lines: [], tone: "info", centred: true };
        case "form": {
            const entries = Object.entries(meta.fields ?? {}).slice(0, 8);
            return {
                icon: "📝", title: meta.name && meta.name !== "flow" ? `Submitted a form — ${meta.name}` : "Submitted a form",
                lines: entries.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`), tone: "info", centred: false,
            };
        }
        case "order": {
            const n = meta.count ?? (meta.items ?? []).reduce((s, i) => s + (Number(i.qty) || 1), 0);
            const lines = (meta.items ?? []).slice(0, 6).map((i) => `${i.sku || "item"} × ${i.qty ?? 1}`);
            if ((meta.items ?? []).length > 6) lines.push(`+${(meta.items ?? []).length - 6} more`);
            if (meta.note) lines.push(`Note: “${meta.note}”`);
            return {
                icon: "🛒", title: `Sent a cart — ${n} item${n === 1 ? "" : "s"}${meta.total ? ` · ${meta.total}` : ""}`,
                lines, tone: "info", centred: false,
            };
        }
        case "deleted":
            return { icon: "🗑️", title: "Deleted a message", lines: [], tone: "muted", centred: false };
        case "edited":
            return {
                icon: "✏️", title: "Edited an earlier message",
                lines: ["WhatsApp doesn't share the new wording with businesses — the original is what we have."],
                tone: "muted", centred: false,
            };
        case "comment_media":
            return {
                icon: meta.video ? "🎥" : "📷",
                title: meta.video ? "Commented with a video" : meta.photo ? "Commented with a photo or sticker" : "Commented without words",
                lines: [], tone: "neutral", centred: false,
                link: meta.photo && /^https:\/\//.test(meta.photo) ? { href: meta.photo, label: "View the comment's image" } : undefined,
            };
        case "call_notice":
            // Folded into the nearest call card when there is one (ConversationsView).
            return { icon: "📞", title: "WhatsApp sent a notice about a call", lines: [], tone: "neutral", centred: true,
                details: detailsLine(meta) };
        case "story_mention":
            return { icon: "📸", title: "Mentioned us in their story", lines: [], tone: "info", centred: false };
        case "unsupported": {
            const advice = meta.advice || GENERIC_ADVICE;
            return {
                icon: "💬", title: unsupportedTitle(meta), tone: "neutral", centred: false,
                lines: meta.legacy && !meta.type
                    ? ["This came in before we recorded message types.", advice]
                    : [advice],
                details: detailsLine(meta),
            };
        }
        default:
            return null;
    }
}

/** The view for one thread row: its record, else a legacy reading of its text. */
export function viewForRow(row: { text?: string | null; media_type?: string | null; meta?: MessageMeta | null }): KindView | null {
    const meta = row.meta ?? legacyMeta(row.text, !!row.media_type);
    return kindView(meta);
}
