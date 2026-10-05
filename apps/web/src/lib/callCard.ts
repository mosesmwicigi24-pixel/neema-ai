// The words on a call card in the conversation (calls & audio programme,
// cycle 3, 2026-10-05): direction, outcome, who took it, when, how long, what
// to do next. Pure data — CallCard draws it; tests/callCard.test.mjs proves it.
//
// One rule per line, so the card reads the same for every call the log can
// hold: inbound / outbound × answered / missed / declined / callback /
// no answer / declined by customer / cancelled / failed / live, on WhatsApp
// or Messenger. No imports with runtime effect: node runs the tests directly.
import type { ApiCall, CallInsights } from "./api";

export type CallTone = "good" | "bad" | "warn" | "muted" | "live";

export interface CallCardView {
    /** "Incoming call" / "Outgoing call" / "Missed call" … */
    title: string;
    /** One word or two: "Answered", "Missed", "Callback requested" … */
    outcome: string;
    tone: CallTone;
    /** "Answered by Ann" / "Called by Ben" / "Declined by Ann" — null when nobody took it. */
    who: string | null;
    /** "1:16" — only for a call that connected. */
    duration: string | null;
    live: boolean;
    /** A missed / callback call nobody has returned yet. */
    owed: boolean;
    /** It was owed, and someone called back (or marked it done). */
    returned: boolean;
    app: "WhatsApp" | "Messenger";
}

const OWED = new Set(["missed", "callback"]);
const CONNECTED = new Set(["completed", "ended", "answered"]);

export function fmtDuration(s: number | null | undefined): string | null {
    if (!s || s <= 0 || !Number.isFinite(s)) return null;
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = Math.floor(s % 60);
    return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
        : `${m}:${String(sec).padStart(2, "0")}`;
}

/** The first word that isn't a title — "Ann Wanjiru" → "Ann". */
const first = (name: string | null | undefined) => (name || "").trim().split(/\s+/)[0] || null;

export function callCardView(c: Pick<ApiCall, "status" | "direction" | "agent_name" | "duration" | "channel"
    | "follow_up_open" | "follow_up_done_at">): CallCardView {
    const out = c.direction === "outbound";
    const agent = first(c.agent_name);
    const app = String(c.channel || "").toLowerCase() === "messenger" ? "Messenger" : "WhatsApp";
    const status = c.status === "ended" ? "completed" : c.status;
    const base = { app, live: false, owed: false, returned: false, duration: null as string | null } as const;
    const dir = out ? "Outgoing call" : "Incoming call";
    switch (status) {
        case "ringing":
            return { ...base, title: out ? "Calling…" : "Incoming call", outcome: out ? "Ringing" : "Ringing now",
                tone: "live", who: out && agent ? `Called by ${agent}` : null, live: true };
        case "answered":
            return { ...base, title: dir, outcome: "On the call now", tone: "live",
                who: agent ? (out ? `Called by ${agent}` : `Answered by ${agent}`) : null, live: true };
        case "completed":
            return { ...base, title: dir, outcome: "Answered", tone: "good",
                who: agent ? (out ? `Called by ${agent}` : `Answered by ${agent}`) : null,
                duration: fmtDuration(c.duration) };
        case "missed":
        case "callback": {
            const owed = OWED.has(status) && c.follow_up_open !== false && !c.follow_up_done_at;
            return { ...base, title: "Missed call", outcome: status === "callback" ? "Callback requested" : "Missed",
                tone: "bad", who: status === "callback" && agent ? `${agent} chose to call back` : null,
                owed, returned: !owed };
        }
        case "declined":
            return { ...base, title: "Incoming call", outcome: "Declined", tone: "warn",
                who: agent ? `Declined by ${agent}` : null };
        case "no_answer":
            return { ...base, title: "Outgoing call", outcome: "No answer", tone: "bad",
                who: agent ? `Called by ${agent}` : null };
        case "rejected":
            return { ...base, title: "Outgoing call", outcome: "Declined by customer", tone: "bad",
                who: agent ? `Called by ${agent}` : null };
        case "cancelled":
            return { ...base, title: "Outgoing call", outcome: "Cancelled", tone: "muted",
                who: agent ? `Called by ${agent}` : null };
        case "failed":
            return { ...base, title: "Outgoing call", outcome: "Didn't go through", tone: "bad",
                who: agent ? `Called by ${agent}` : null };
        default:
            return { ...base, title: dir, outcome: "Call", tone: "muted", who: null,
                duration: CONNECTED.has(status) ? fmtDuration(c.duration) : null };
    }
}

/** "14:05" today, "Yesterday 14:05", else "3 Oct 14:05" — plus "· 2 h ago"
 *  when `relative` (a missed call: how long they've been waiting). */
export function whenText(iso: string | null | undefined, now = Date.now(), relative = false): string {
    if (!iso) return "";
    const d = new Date(iso);
    const t = d.getTime();
    if (!Number.isFinite(t)) return "";
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const today = new Date(now);
    const yest = new Date(now - 86_400_000);
    const day = d.toDateString() === today.toDateString() ? hm
        : d.toDateString() === yest.toDateString() ? `Yesterday ${hm}`
        : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${hm}`;
    if (!relative) return day;
    const mins = Math.max(0, Math.round((now - t) / 60_000));
    const ago = mins < 1 ? "just now" : mins < 60 ? `${mins} min ago`
        : mins < 48 * 60 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} days ago`;
    return `${day} · ${ago}`;
}

/** The handle a call back dials: the number on WhatsApp, the PSID on Messenger. */
export function callBackHandle(c: Pick<ApiCall, "channel" | "wa_id" | "external_id">): string {
    return String(c.channel || "").toLowerCase() === "messenger"
        ? String(c.external_id || "") : String(c.wa_id || c.external_id || "");
}

/** Whether "Call back" can be offered: a call owed to the customer, on an app
 *  that can place calls now (Messenger only while the server says it can). The
 *  calling flow itself still applies WhatsApp's permission + 24h rules. */
export function canCallBack(c: Pick<ApiCall, "status" | "channel" | "wa_id" | "external_id"
    | "follow_up_open" | "follow_up_done_at" | "direction" | "agent_name" | "duration">,
    messengerOutbound: boolean): boolean {
    if (!callCardView(c).owed) return false;
    const handle = callBackHandle(c).replace(/\D/g, "");
    if (String(c.channel || "").toLowerCase() === "messenger") return !!handle && messengerOutbound;
    return handle.length >= 7;
}

/** What the brief says to do next: Meta's / our summariser's action items when
 *  present (a later cycle may add `action_items`), else the commitments. */
export function actionItems(ins: (CallInsights & { action_items?: unknown }) | null | undefined): string[] {
    if (!ins) return [];
    const raw = Array.isArray(ins.action_items) ? ins.action_items : ins.commitments;
    return (Array.isArray(raw) ? raw : []).map((x) => String(x ?? "").trim()).filter(Boolean).slice(0, 8);
}

/** The transcript slot's state, in one word. */
export function transcriptSlot(status: string | null | undefined): "ready" | "working" | "failed" | "none" {
    if (status === "done") return "ready";
    if (status === "pending" || status === "processing") return "working";
    if (status === "failed") return "failed";
    return "none";
}

/** A recording / media URL as the browser can fetch it: absolute and rooted
 *  URLs as they are, a bare stored file name under the API's media path. */
export function mediaSrc(url: string | null | undefined, apiBase: string): string | null {
    const u = (url || "").trim();
    if (!u) return null;
    if (/^https?:\/\//i.test(u) || u.startsWith("/")) return u;
    if (!/^[\w.-]+$/.test(u)) return null;          // never a path the server didn't write
    return `${apiBase.replace(/\/$/, "")}/admin/media/${u}`;
}
