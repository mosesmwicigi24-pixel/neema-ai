// A flag's note, read as a summary (owner, 2026-11-09: "Flagged should be a
// summary and not a prose write-up"). Neema writes flags as a headline then
// "• Label: text" sections; this keeps the headline, one short line per
// section, and leaves the full note for whoever opens it.

export type FlagSummary = {
    tag: string | null;          // "COMPLAINT (HIGH)", "HELD BACK BY THE REVIEWER" …
    headline: string;            // what has to happen, one sentence
    points: { label: string; text: string }[];
};

const MAX_POINT = 140;
const MAX_POINTS = 4;

/** The first sentence, cut to `max` characters on a word. */
export function firstSentence(text: string, max = MAX_POINT): string {
    const t = text.replace(/\s+/g, " ").trim();
    const m = t.match(/^(.+?[.!?])(\s|$)/);
    let s = (m ? m[1] : t);
    if (s.length > max) s = s.slice(0, max).replace(/\s+\S*$/, "") + "…";
    return s;
}

export function summarizeFlag(note: string | null | undefined): FlagSummary | null {
    const raw = (note || "").trim();
    if (!raw) return null;
    const [head, ...rest] = raw.split(/\s*•\s*/);
    // "COMPLAINT (HIGH) — a colleague must follow up" → tag + headline.
    const dash = head.match(/^([A-Z][A-Z0-9 ()/&'-]{2,60}?)\s+[—–-]\s+([\s\S]*)$/);
    const tag = dash ? dash[1].trim() : null;
    const h = firstSentence(dash ? dash[2] : head, 180);
    const headline = h.charAt(0).toUpperCase() + h.slice(1);
    const points = rest
        .map((part) => {
            const kv = part.match(/^([^:]{2,60}):\s*([\s\S]*)$/);
            return kv ? { label: kv[1].trim(), text: firstSentence(kv[2]) } : { label: "", text: firstSentence(part) };
        })
        .filter((p) => p.text)
        .slice(0, MAX_POINTS);
    return { tag, headline, points };
}
