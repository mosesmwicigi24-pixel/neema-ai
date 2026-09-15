"use client";

/**
 * useInbox — the conversation list, one page of people at a time.
 *
 * It replaced a single fetch of EVERY conversation (14,000 rows, 13 MB) on a
 * 60-second poll that could lose to its own 30-second timeout. Three rules
 * shape it, each one a bug the old design had or pagination would have caused:
 *
 * 1. `conversations` is a CACHE of every row ever loaded — never just the
 *    visible page. The inbox looks conversations up by id in eight places (the
 *    open thread, identity switching, drafts, ownership checks…). If the open
 *    thread fell out of the array, the pane showed "Select a conversation".
 *    What the list SHOWS is `visibleIds`: the current filter's server pages.
 *
 * 2. A refresh MERGES. The old code replaced the whole list on every fetch;
 *    with pages, that would wipe everything scrolled into past page one — and
 *    the row the hub's chat deep link inserts.
 *
 * 3. The newest request wins. Poll, push events, action refetches and tab
 *    focus used to overlap, and whichever finished LAST won, even if older.
 *    Every response is checked against a sequence number and the live filter.
 *
 * Badges come from `summary`, counted by the server over ALL conversations —
 * a count over the loaded rows would be a count of one page.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    conversationsApi,
    mapConversation,
    type ApiConversation,
    type InboxQuery,
    type InboxSummary,
} from "@/lib/api";
import type { Conversation } from "@/types";

const PAGE = 50;
const POLL_MS = 60_000;
/** Per agent: the old single key showed the previous agent's inbox to the
 *  next person who signed in on the same browser. */
const SNAP_PREFIX = "neema:inbox:v2:";
const LEGACY_SNAP = "neema:snap:conversations";

const DEFAULT_FILTERS: InboxQuery = { tab: "all", channel: "all", mode: "all", tag: null, q: "" };

const filterKeyOf = (f: InboxQuery) =>
    JSON.stringify([f.tab ?? "all", f.channel ?? "all", f.mode ?? "all", f.tag ?? null, (f.q ?? "").trim()]);
const DEFAULT_KEY = filterKeyOf(DEFAULT_FILTERS);

const byRecency = (a: Conversation, b: Conversation) =>
    (b.last_message_at ?? "").localeCompare(a.last_message_at ?? "");

interface Snapshot { items: ApiConversation[]; next_cursor: string | null }

function readSnapshot(agentId: string | null): Snapshot | null {
    if (!agentId || typeof window === "undefined") return null;
    try {
        const raw = localStorage.getItem(SNAP_PREFIX + agentId);
        return raw ? (JSON.parse(raw) as Snapshot) : null;
    } catch {
        return null;
    }
}

function writeSnapshot(agentId: string | null, snap: Snapshot) {
    if (!agentId) return;
    try {
        localStorage.setItem(SNAP_PREFIX + agentId, JSON.stringify(snap));
    } catch { /* quota / private mode — best effort */ }
}

export interface Inbox {
    /** Every row ever loaded, most recent first. For LOOKUPS. */
    conversations: Conversation[];
    /** The rows the current filter's server pages returned. For the LIST. */
    visibleIds: Set<string>;
    filters: InboxQuery;
    setFilters: (patch: Partial<InboxQuery>) => void;
    summary: InboxSummary | null;
    /** The first page for the current filters is on its way. */
    loading: boolean;
    loadingMore: boolean;
    hasMore: boolean;
    /** Page one has come from the SERVER this session (not just a snapshot). */
    freshLoaded: boolean;
    refresh: () => void;
    loadMore: () => void;
    /** Optimistic local edit to cached rows; a quiet refresh follows. */
    setConversations: (updater: React.SetStateAction<Conversation[]>) => void;
    /** Add rows to the cache AND the visible list — e.g. a thread opened by a
     *  deep link that is older than anything loaded. */
    reveal: (rows: Conversation[]) => void;
    /** The open thread: kept fresh on every refresh even when it is not on
     *  page one, or taking it over would leave its row saying "AI". */
    watch: (id: string | null) => void;
}

export function useInbox(enabled: boolean, agentId: string | null): Inbox {
    const [cache, setCache] = useState<Map<string, Conversation>>(() => new Map());
    const [order, setOrder] = useState<{ key: string; ids: string[] }>({ key: DEFAULT_KEY, ids: [] });
    const [filters, setFiltersState] = useState<InboxQuery>(DEFAULT_FILTERS);
    const [summary, setSummary] = useState<InboxSummary | null>(null);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [freshLoaded, setFreshLoaded] = useState(false);

    const filterKey = filterKeyOf(filters);
    const keyRef = useRef(filterKey);
    keyRef.current = filterKey;
    const filtersRef = useRef(filters);
    filtersRef.current = filters;
    const cursorRef = useRef<string | null>(null);
    /** Pages loaded for the current filters — a snapshot counts as one. */
    const pagesRef = useRef(0);
    const orderRef = useRef(order);
    orderRef.current = order;
    const firstSeq = useRef(0);
    const moreSeq = useRef(0);
    /** Rows revealed for the current filters (deep links) — they survive a
     *  page-one replace, or the thread you opened would lose its list row. */
    const revealedRef = useRef<string[]>([]);
    const watchedRef = useRef<string | null>(null);

    const upsertRows = useCallback((rows: Conversation[]) => {
        if (!rows.length) return;
        setCache((prev) => {
            const next = new Map(prev);
            for (const r of rows) next.set(r.id, r);
            return next;
        });
    }, []);

    // ── Seed from this agent's snapshot so the inbox paints instantly ──────────
    const seeded = useRef<string | null>(null);
    useEffect(() => {
        if (!agentId || seeded.current === agentId) return;
        seeded.current = agentId;
        try { localStorage.removeItem(LEGACY_SNAP); } catch { /* ignore */ }
        const snap = readSnapshot(agentId);
        if (!snap?.items?.length) return;
        const rows = snap.items.map(mapConversation);
        upsertRows(rows);
        setOrder((o) => (o.ids.length ? o : { key: DEFAULT_KEY, ids: rows.map((r) => r.id) }));
        cursorRef.current = snap.next_cursor;
        pagesRef.current = 1;
        setHasMore(Boolean(snap.next_cursor));
    }, [agentId, upsertRows]);

    // ── Page one + badges ────────────────────────────────────────────────────
    const refresh = useCallback(() => {
        if (!enabled) return;
        const seq = ++firstSeq.current;
        const key = keyRef.current;
        const f = filtersRef.current;
        if (orderRef.current.key !== key || !orderRef.current.ids.length) setLoading(true);

        conversationsApi.summary()
            .then((s) => { if (seq === firstSeq.current) setSummary(s); })
            .catch(() => { /* badges keep their last value */ });

        conversationsApi.page({ ...f, limit: PAGE })
            .then((res) => {
                // Superseded by a newer refresh, or the filters moved on.
                if (seq !== firstSeq.current || key !== keyRef.current) return;
                const rows = res.items.map(mapConversation);
                upsertRows(rows);
                const fresh = rows.map((r) => r.id);
                const o = orderRef.current;
                if (o.key !== key || pagesRef.current <= 1) {
                    // Only page one was loaded (or a snapshot, possibly days
                    // old): REPLACE it and take the fresh cursor. Merging onto
                    // a stale cursor would skip anything that became active
                    // since but fell outside today's top page.
                    cursorRef.current = res.next_cursor;
                    pagesRef.current = 1;
                    setHasMore(Boolean(res.next_cursor));
                    // A "load more" still in flight was paging from the OLD
                    // cursor; landing now it would append past a boundary that
                    // no longer exists and leave a gap. Cancel it — the next
                    // scroll pages from the fresh cursor.
                    moreSeq.current++;
                    setLoadingMore(false);
                    const top = new Set(fresh);
                    setOrder({ key, ids: [...fresh, ...revealedRef.current.filter((id) => !top.has(id))] });
                } else {
                    // Scrolled further this session: page one on top, the rest
                    // kept below; the cursor still points past the last page.
                    const top = new Set(fresh);
                    setOrder({ key, ids: [...fresh, ...o.ids.filter((id) => !top.has(id))] });
                }
                setFreshLoaded(true);
                setLoading(false);
                if (key === DEFAULT_KEY) writeSnapshot(agentId, res);
                const w = watchedRef.current;
                if (w && !fresh.includes(w)) {
                    conversationsApi.get(w)
                        .then((one) => { if (seq === firstSeq.current) upsertRows([mapConversation(one)]); })
                        .catch(() => { /* the thread keeps its last known row */ });
                }
            })
            .catch(() => {
                if (seq === firstSeq.current) setLoading(false);
            });
    }, [enabled, agentId, upsertRows]);

    // ── The next page of people ──────────────────────────────────────────────
    const loadMore = useCallback(() => {
        if (!enabled || loadingMore || !cursorRef.current) return;
        const seq = ++moreSeq.current;
        const key = keyRef.current;
        const cursor = cursorRef.current;
        setLoadingMore(true);
        conversationsApi.page({ ...filtersRef.current, limit: PAGE, cursor })
            .then((res) => {
                if (seq !== moreSeq.current || key !== keyRef.current) return;
                const rows = res.items.map(mapConversation);
                upsertRows(rows);
                const o = orderRef.current;
                if (o.key !== key) return;
                const have = new Set(o.ids);
                setOrder({ key, ids: [...o.ids, ...rows.map((r) => r.id).filter((id) => !have.has(id))] });
                cursorRef.current = res.next_cursor;
                pagesRef.current += 1;
                setHasMore(Boolean(res.next_cursor));
            })
            .catch(() => { /* scrolling again retries */ })
            .finally(() => { if (seq === moreSeq.current) setLoadingMore(false); });
    }, [enabled, loadingMore, upsertRows]);

    // New filters start their own list; the cache (and the open thread) stays.
    const setFilters = useCallback((patch: Partial<InboxQuery>) => {
        setFiltersState((prev) => ({ ...prev, ...patch }));
    }, []);
    useEffect(() => {
        if (!enabled) return;
        if (orderRef.current.key !== filterKey) {
            cursorRef.current = null;
            pagesRef.current = 0;
            revealedRef.current = [];
            setHasMore(false);
            setOrder({ key: filterKey, ids: [] });
        }
        refresh();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled, filterKey]);

    // ── Poll (the push events are the primary signal) and refocus ────────────
    useEffect(() => {
        if (!enabled) return;
        const tick = () => { if (document.visibilityState === "visible") refresh(); };
        const id = window.setInterval(tick, POLL_MS);
        const onVis = () => { if (document.visibilityState === "visible") refresh(); };
        document.addEventListener("visibilitychange", onVis);
        return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", onVis); };
    }, [enabled, refresh]);

    // ── Optimistic edits and reveals ─────────────────────────────────────────
    const quiet = useRef<number | undefined>(undefined);
    const setConversations = useCallback((updater: React.SetStateAction<Conversation[]>) => {
        setCache((prev) => {
            const arr = [...prev.values()];
            const next = typeof updater === "function" ? updater(arr) : updater;
            return new Map(next.map((c) => [c.id, c]));
        });
        window.clearTimeout(quiet.current);
        quiet.current = window.setTimeout(refresh, 2000);
    }, [refresh]);

    const reveal = useCallback((rows: Conversation[]) => {
        upsertRows(rows);
        revealedRef.current = [...new Set([...revealedRef.current, ...rows.map((r) => r.id)])];
        setOrder((o) => {
            const have = new Set(o.ids);
            return { ...o, ids: [...o.ids, ...rows.map((r) => r.id).filter((id) => !have.has(id))] };
        });
    }, [upsertRows]);

    const watch = useCallback((id: string | null) => { watchedRef.current = id || null; }, []);

    const conversations = useMemo(() => [...cache.values()].sort(byRecency), [cache]);
    const visibleIds = useMemo(
        () => new Set(order.key === filterKey ? order.ids : []),
        [order, filterKey],
    );

    return {
        conversations, visibleIds, filters, setFilters, summary,
        loading, loadingMore, hasMore, freshLoaded,
        refresh, loadMore, setConversations, reveal, watch,
    };
}
