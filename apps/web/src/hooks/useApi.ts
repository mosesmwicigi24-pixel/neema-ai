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

    const fetch = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await fetcher();
            if (mountedRef.current) setData(result);
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
