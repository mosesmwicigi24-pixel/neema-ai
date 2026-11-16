// The thread note (owner, 2026-11-15): internal notes were "too many and too
// long" — a yellow card in the chat for every briefing, auto-return and staff
// note. They now live in ONE floating panel above the reply box:
//
//   * the team note — one per thread, edited in place (server: team_note);
//   * Neema's brief — only the newest handoff briefing, as labelled rows;
//   * history — every other note as one short line, full text a tap away.
//
// This module reads note rows into that shape. Pure (no React, no "@/"
// imports) so node --test runs it directly.

export type NoteKind = "brief" | "return" | "unclaimed" | "staff" | "system";

export interface NoteLike {
    id?: string;
    text?: string | null;
    sender?: string;
    agent_name?: string | null;
    created_at?: string | null;
}

export interface BriefRow {
    /** "Status" | "Next" | "Avoid" | "Say", or the writer's own label; "" when unlabelled. */
    label: string;
    text: string;
}

const BRIEF_RE = /^\s*(?:🤝\s*)?handoff briefing\b/i;
const RETURN_RE = /^\s*↩️?\s*(?:returned to neema|back to neema)/i;
const UNCLAIMED_RE = /^\s*⏳\s*unclaimed/i;

export function noteKind(n: NoteLike): NoteKind {
    const t = n.text ?? "";
    if (BRIEF_RE.test(t)) return "brief";
    if (RETURN_RE.test(t)) return "return";
    if (UNCLAIMED_RE.test(t)) return "unclaimed";
    if (n.sender === "human_agent" && n.agent_name) return "staff";
    return "system";
}

export const KIND_ICON: Record<NoteKind, string> = {
    brief: "🤝",
    return: "↩",
    unclaimed: "⏳",
    staff: "📝",
    system: "ℹ️",
};

const ts = (n: NoteLike) => (n.created_at ? new Date(n.created_at).getTime() : 0) || 0;

/** The newest briefing, and every non-briefing note newest first. Older
 *  briefings are dropped: a briefing is a snapshot of where the sale stands,
 *  and a stale one beside a fresh one only makes the reader work out which
 *  is current (copilot.py supersedes them the same way). */
export function splitNotes<T extends NoteLike>(notes: readonly T[]): { brief: T | null; history: T[] } {
    const sorted = [...notes].sort((a, b) => ts(b) - ts(a));
    const brief = sorted.find((n) => noteKind(n) === "brief") ?? null;
    return { brief, history: sorted.filter((n) => noteKind(n) !== "brief") };
}

const KNOWN = ["Status", "Next", "Avoid", "Say"];

/** A briefing as rows. The heading goes; bullets and markdown go; a
 *  "Label: text" line keeps its label (the four standard ones in any case). */
export function parseBrief(text: string | null | undefined): BriefRow[] {
    const rows: BriefRow[] = [];
    for (const raw of (text ?? "").split(/\r?\n/)) {
        const line = raw.replace(/[*_#`>]+/g, "").replace(/^[\s\-•·]+/, "").trim();
        if (!line || BRIEF_RE.test(line)) continue;
        const kv = line.match(/^([A-Za-z][A-Za-z /&']{1,24}):\s*(.+)$/);
        if (kv) {
            const label = kv[1].trim();
            const known = KNOWN.find((k) => k.toLowerCase() === label.toLowerCase());
            rows.push({ label: known ?? label, text: kv[2].trim() });
        } else {
            rows.push({ label: "", text: line });
        }
    }
    return rows;
}

const squash = (t: string) => t.replace(/\s+/g, " ").trim();

/** Cut to `max` characters on a word boundary. */
export function clip(text: string, max: number): string {
    const t = squash(text);
    if (t.length <= max) return t;
    return t.slice(0, max).replace(/\s+\S*$/, "") + "…";
}

/** One short line for the history list. Long system texts are shortened to
 *  the facts; a colleague's own words are kept as written (just clipped). */
export function oneLine(n: NoteLike, max = 110): string {
    const t = squash(n.text ?? "");
    switch (noteKind(n)) {
        case "return": {
            const mins = t.match(/(\d+)\s*min/i)?.[1];
            // New: "↩ Back to Neema — no colleague reply in 45 min; <why>."
            // Old: "… for 45 minutes, and <why>, so nobody is left waiting. …"
            const why = (t.match(/,\s*and\s+(.+?),\s*so nobody/i)?.[1] ?? t.match(/min;\s*([^.]+)\./i)?.[1] ?? "").trim();
            const head = mins ? `Back to Neema after ${mins} min quiet` : "Back to Neema";
            return clip(why ? `${head} — ${why}` : head, max);
        }
        case "unclaimed": {
            const mins = t.match(/(\d+)\s*min/i)?.[1];
            return clip(`Unclaimed${mins ? ` ${mins} min` : ""} — needs a person`, max);
        }
        case "brief": {
            const s = parseBrief(n.text).find((r) => r.label === "Status") ?? parseBrief(n.text)[0];
            return clip(s ? s.text : "Handoff briefing", max);
        }
        default:
            return clip(t.replace(/^(?:📝|ℹ️|📌)\s*/u, ""), max);
    }
}

/** The one line the folded bar shows: the team note first (people's words
 *  win), else the brief's Status, else nothing. */
export function barSummary(teamText: string | null | undefined, brief: NoteLike | null): { icon: string; text: string } | null {
    const team = squash(teamText ?? "");
    if (team) return { icon: "📌", text: team };
    if (brief) {
        const rows = parseBrief(brief.text);
        const status = rows.find((r) => r.label === "Status") ?? rows[0];
        const next = rows.find((r) => r.label === "Next");
        if (status) return { icon: "🤝", text: next && next !== status ? `${status.text} · Next: ${next.text}` : status.text };
    }
    return null;
}

/** Notes newer than `seenIso` (the last time this thread's note was opened).
 *  No mark yet means nothing is new: a first visit must not light every thread. */
export function unseenCount(notes: readonly NoteLike[], seenIso: string | null): number {
    if (!seenIso) return 0;
    const seen = new Date(seenIso).getTime();
    if (!Number.isFinite(seen)) return 0;
    return notes.filter((n) => ts(n) > seen).length;
}
