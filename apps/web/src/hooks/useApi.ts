/**
 * apps/web/src/hooks/useApi.ts
 * Generic data fetching hook with loading, error, and refetch support.
 */

"use client";
import { useState, useEffect, useCallback, useRef } from "react";

export interface UseApiResult<T> {
    data: T | null;
    loading: boolean;
    error: string | null;
    refetch: () => void;
}

// Stale-while-revalidate snapshot store: the last good payload per cacheKey,
// so a refresh paints the dashboard instantly from local data while the real
// fetch happens in the background. Arrays are trimmed so a huge inbox can't
// blow the localStorage quota.
const SNAP_PREFIX = "neema:snap:";
const SNAP_MAX_ROWS = 600;

function readSnapshot<T>(cacheKey?: string): T | null {
    if (!cacheKey || typeof window === "undefined") return null;
    try {
        const raw = localStorage.getItem(SNAP_PREFIX + cacheKey);
        return raw ? (JSON.parse(raw) as T) : null;
    } catch {
        return null;
    }
}

function writeSnapshot(cacheKey: string, value: unknown): void {
    try {
        const v = Array.isArray(value) && value.length > SNAP_MAX_ROWS
            ? value.slice(0, SNAP_MAX_ROWS)
            : value;
        localStorage.setItem(SNAP_PREFIX + cacheKey, JSON.stringify(v));
    } catch {
        /* quota / private mode — snapshotting is best-effort */
    }
}

export function useApi<T>(
    fetcher: () => Promise<T>,
    deps: unknown[] = [],
    cacheKey?: string,
): UseApiResult<T> {
    const [data, setData] = useState<T | null>(() => readSnapshot<T>(cacheKey));
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const mountedRef = useRef(true);
    // Fingerprint of the last stored payload: background refetches that return
    // identical data must cause ZERO re-renders — flipping `loading` and always
    // storing a fresh array identity re-rendered the entire dashboard (and the
    // conversation list with it) on every poll tick, even with nothing new.
    const fingerprintRef = useRef<string | null>(null);
    const hasDataRef = useRef(false);

    const fetch = useCallback(async () => {
        if (!hasDataRef.current) setLoading(true);   // spinner only on first load
        try {
            const result = await fetcher();
            if (mountedRef.current) {
                // A null result means "not ready yet" (e.g. no auth token) —
                // never let it clobber a hydrated snapshot.
                if (result === null) return;
                let fp: string | null = null;
                try { fp = JSON.stringify(result); } catch { /* non-serializable */ }
                if (fp === null || fp !== fingerprintRef.current) {
                    fingerprintRef.current = fp;
                    setData(result);
                    if (cacheKey) writeSnapshot(cacheKey, result);
                }
                hasDataRef.current = true;
                setError(null);
            }
        } catch (e: any) {
            if (mountedRef.current) setError(e.message ?? "Unknown error");
        } finally {
            if (mountedRef.current) setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, deps);

    useEffect(() => {
        mountedRef.current = true;
        fetch();
        return () => {
            mountedRef.current = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fetch]);

    return { data, loading, error, refetch: fetch };
}

export function usePolling<T>(
    fetcher: () => Promise<T>,
    intervalMs = 8000,
    deps: unknown[] = [],
    cacheKey?: string,
): UseApiResult<T> {
    const result = useApi<T>(fetcher, deps, cacheKey);

    useEffect(() => {
        // Polls are the WebSocket's *fallback*, not the primary transport — so
        // skip ticks while the tab is hidden (an idle background dashboard was
        // hammering the API for nobody) and refetch once on return.
        const tick = () => {
            if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
            result.refetch();
        };
        const timer = setInterval(tick, intervalMs);
        const onVisible = () => {
            if (document.visibilityState === "visible") result.refetch();
        };
        document.addEventListener("visibilitychange", onVisible);
        return () => {
            clearInterval(timer);
            document.removeEventListener("visibilitychange", onVisible);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [intervalMs, result.refetch]);

    return result;
}
