// One word + one colour per call status, shared by the Calls view, the
// customer panel and the thread's call pills — so a call reads the same
// everywhere (docs/CALLING_UX.md §7: coloured AND worded, never colour alone).
import type { ApiCall } from "@/lib/api";

export type CallIconKind = "in" | "out" | "missed" | "live";

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
