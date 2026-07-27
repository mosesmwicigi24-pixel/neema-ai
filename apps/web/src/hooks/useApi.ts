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

export function useApi<T>(
    fetcher: () => Promise<T>,
    deps: unknown[] = [],
): UseApiResult<T> {
    const [data, setData] = useState<T | null>(null);
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
                let fp: string | null = null;
                try { fp = JSON.stringify(result); } catch { /* non-serializable */ }
                if (fp === null || fp !== fingerprintRef.current) {
                    fingerprintRef.current = fp;
                    setData(result);
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
): UseApiResult<T> {
    const result = useApi<T>(fetcher, deps);

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
