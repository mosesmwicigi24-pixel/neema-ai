// One word + one colour per call status, shared by the Calls view, the
// customer panel and the thread's call pills — so a call reads the same
// everywhere (docs/CALLING_UX.md §7: coloured AND worded, never colour alone).
import type { ApiCall, CallPermission } from "@/lib/api";

export type CallIconKind = "in" | "out" | "missed" | "live" | "rejected";

export interface CallStatusMeta {
    word: string;
    /** On the dark call console. */
    dark: string;
    /** On the light panels (customer sidebar, thread). */
    light: string;
    icon: CallIconKind;
    /** The call is still happening. */
    live: boolean;
}

const GREEN = { dark: "#2ad17f", light: "#128C4B" };
const RED = { dark: "#ff6b70", light: "#C62828" };
const AMBER = { dark: "#f5b642", light: "#A15C00" };
const GREY = { dark: "#9fb3a8", light: "#57534e" };

export function callStatus(c: Pick<ApiCall, "status" | "direction">): CallStatusMeta {
    const out = c.direction === "outbound";
    const dir: CallIconKind = out ? "out" : "in";
    switch (c.status) {
        case "ringing": return { word: out ? "Calling…" : "Ringing…", ...GREEN, icon: "live", live: true };
        case "answered": return { word: "On a call", ...GREEN, icon: "live", live: true };
        case "completed":
        case "ended": return { word: out ? "Outgoing" : "Incoming", ...GREEN, icon: dir, live: false };
        case "missed": return { word: "Missed", ...RED, icon: "missed", live: false };
        case "declined": return { word: "Declined", ...AMBER, icon: "in", live: false };
        case "callback": return { word: "Call back", ...AMBER, icon: "missed", live: false };
        case "no_answer": return { word: "No answer", ...RED, icon: "out", live: false };
        // The customer declined OUR call (Meta's REJECTED) — not a follow-up.
        case "rejected": return { word: "Declined by customer", ...RED, icon: "rejected", live: false };
        case "cancelled": return { word: "Cancelled", ...GREY, icon: "out", live: false };
        case "failed": return { word: "Failed", ...RED, icon: "out", live: false };
        default: return { word: "Call", ...GREY, icon: dir, live: false };
    }
}

export const fmtCallDuration = (s: number | null | undefined) =>
    !s ? "" : `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;

/** The arrow / missed glyph path for a call row (24×24, stroke). */
export const CALL_ICON_PATH: Record<CallIconKind, string> = {
    in: "M17 7L7 17M7 17h7M7 17v-7",
    out: "M7 17L17 7M17 7h-7M17 7v7",
    missed: "M3 7l6 6 4-4 8 8M21 11v6h-6",
    // Outgoing arrow + a small cross: they turned our call down.
    rejected: "M5 19L15 9M15 9H9M15 9v6M16 3l5 5M21 3l-5 5",
    live: "M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z",
};

/** Put a changed row in place (newest first), for live `call_update`s. */
export function upsertCall(list: ApiCall[], row: ApiCall): ApiCall[] {
    const i = list.findIndex((c) => c.call_id === row.call_id);
    if (i >= 0) {
        const next = list.slice();
        next[i] = { ...list[i], ...row };
        return next;
    }
    return [row, ...list].sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
}

// ── Call permission, in words (docs/CALLING_UX.md §2.1) ──────────────────────

/** "in 3 h" / "in 20 min" / "tomorrow at 09:00" / "on Tue 4 Oct at 09:00". */
export function relTime(iso: string | null | undefined, now = Date.now()): string {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (!Number.isFinite(t)) return "";
    const mins = Math.round((t - now) / 60_000);
    if (mins <= 1) return "now";
    if (mins < 60) return `in ${mins} min`;
    if (mins < 6 * 60) return `in ${Math.round(mins / 60)} h`;
    const d = new Date(t);
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const today = new Date(now);
    const tomorrow = new Date(now + 86_400_000);
    if (d.toDateString() === today.toDateString()) return `today at ${hm}`;
    if (d.toDateString() === tomorrow.toDateString()) return `tomorrow at ${hm}`;
    return `on ${d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} at ${hm}`;
}

/** "3 Oct" / "3 Oct 2027" — a day, for "Allowed until …". */
export function dayDate(iso: string | null | undefined): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return "";
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString([], { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

/** A past moment, briefly: "14:05" today, else "3 Oct 14:05". */
function whenPast(iso: string | null | undefined): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return "";
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === new Date().toDateString() ? hm : `${dayDate(iso)} ${hm}`;
}

export type PermTone = "ok" | "wait" | "bad" | "info";
export interface PermLine { text: string; tone: PermTone; }

/** The permission state as the agent should read it, one line each — only
 *  what the server actually said (never a guess). `first` = their first name. */
export function permissionLines(p: CallPermission | null | undefined, first: string): PermLine[] {
    if (!p) return [];
    const out: PermLine[] = [];
    if (p.status === "granted") {
        if (p.permanent || p.meta_status === "permanent") out.push({ text: "Allowed permanently", tone: "ok" });
        else if (p.expires_at) out.push({ text: `Allowed until ${dayDate(p.expires_at)}`, tone: "ok" });
        else out.push({ text: "Allowed calls", tone: "ok" });
    } else if (p.status === "requested") {
        const at = whenPast(p.requested_at);
        out.push({ text: `Request sent${at ? ` ${at}` : ""} — waiting for ${first}`, tone: "wait" });
    } else if (p.status === "denied") {
        out.push(p.revoked
            ? { text: "Permission revoked after unanswered calls", tone: "bad" }
            : { text: `${first} declined calls`, tone: "bad" });
    } else if (p.meta_status === "no_permission") {
        out.push({ text: `${first} hasn't allowed calls yet`, tone: "info" });
    }
    if (p.can_request === false && p.status !== "granted" && p.request_available_at) {
        out.push({ text: `You can ask again ${relTime(p.request_available_at)}`, tone: "wait" });
    }
    if (typeof p.calls_left_today === "number") {
        out.push({ text: `Calls left today: ${p.calls_left_today}`, tone: "info" });
    }
    return out;
}

/** Transcript text "Agent: …\nCustomer: …" → speaker turns (null when unlabelled). */
export function speakerTurns(text: string | null | undefined): { who: "Agent" | "Customer"; text: string }[] | null {
    if (!text) return null;
    const turns: { who: "Agent" | "Customer"; text: string }[] = [];
    for (const raw of text.split(/\n+/)) {
        const line = raw.trim();
        if (!line) continue;
        const m = line.match(/^(Agent|Customer)\s*:\s*(.*)$/i);
        if (m) turns.push({ who: m[1].toLowerCase() === "agent" ? "Agent" : "Customer", text: m[2] });
        else if (turns.length) turns[turns.length - 1].text += ` ${line}`;
        else return null;
    }
    return turns.length ? turns : null;
}
