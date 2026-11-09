// The open thread's list of messages: merging server pages into what is on
// screen, and retiring the "optimistic" bubble a send draws before the server
// answers.
//
// The bug this file exists for (owner, 2026-11-09): a human reply showed as
// TWO bubbles until the page was refreshed, although the customer got one.
// The send drew an optimistic bubble (id "optimistic-…"), then the real row
// arrived — by the live event and by the refetch — under its database id.
// Merging by id kept both, and nothing ever removed the optimistic one.

export interface ThreadRow {
    id: string;
    text?: string | null;
    direction?: string | null;
    created_at?: string | null;
}

export const isOptimistic = (m: { id?: unknown }): boolean =>
    String(m?.id ?? "").startsWith("optimistic-");

const words = (m: ThreadRow): string => String(m.text ?? "").trim();

/** `existing` without the optimistic bubbles that `arrived` — real rows not
 *  yet on screen — are the saved form of. One real row retires at most one
 *  optimistic bubble with the same words (so two quick identical replies stay
 *  two), oldest first. Inbound rows retire nothing. No clocks are compared:
 *  the browser's and the server's may disagree. */
export function retireOptimistic<T extends ThreadRow>(existing: T[], arrived: ThreadRow[]): T[] {
    if (!existing.some(isOptimistic)) return existing;
    const known = new Set(existing.map((m) => String(m.id)));
    const retire = new Set<string>();
    for (const real of arrived) {
        if (isOptimistic(real) || known.has(String(real.id))) continue;
        if (real.direction === "inbound") continue;
        const w = words(real);
        if (!w) continue;
        const hit = existing.find(
            (m) => isOptimistic(m) && !retire.has(String(m.id)) && words(m) === w);
        if (hit) retire.add(String(hit.id));
    }
    return retire.size ? existing.filter((m) => !retire.has(String(m.id))) : existing;
}

/** Union two thread slices by id, newest state winning, ordered by time — so
 *  a poll refresh (newest page) never throws away older pages already loaded,
 *  an older page slots in without duplicating anything, and a real row
 *  replaces the optimistic bubble drawn for it. */
export function mergeThread<T extends ThreadRow>(existing: T[], incoming: T[]): T[] {
    const byId = new Map<string, T>();
    for (const m of retireOptimistic(existing, incoming)) byId.set(String(m.id), m);
    for (const m of incoming)
        byId.set(String(m.id), { ...(byId.get(String(m.id)) ?? {}), ...m } as T);
    return [...byId.values()].sort((a, b) =>
        (a.created_at || "").localeCompare(b.created_at || ""));
}
