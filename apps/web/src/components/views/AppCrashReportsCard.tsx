"use client";

// Settings → App crash reports (admins). The Android app saves a report when
// it closes unexpectedly and sends it on the next sign-in (GET
// /admin/client-crashes). Each one can be expanded and copied, so "the app
// closed" can be handed over with the exact stack trace.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface CrashRow {
    id: string;
    kind: string;
    at: string | null;
    received_at: string;
    agent_name: string | null;
    summary: string;
    trace: string;
    thread: string | null;
    app_version: string;
    build: string;
    device: string;
    sdk: number;
}

const KIND: Record<string, string> = {
    crash: "App closed",
    native: "App closed (native)",
    anr: "App froze",
    nonfatal: "Background error",
};

function when(iso: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function asText(r: CrashRow): string {
    return [
        `${KIND[r.kind] ?? r.kind} · ${when(r.at ?? r.received_at)}`,
        `Build ${r.build || "?"} (${r.app_version}) · ${r.device} · Android API ${r.sdk}${r.agent_name ? ` · ${r.agent_name}` : ""}`,
        r.thread ? `Thread: ${r.thread}` : "",
        "",
        r.trace || r.summary,
    ].filter((l, i) => l !== "" || i === 3).join("\n");
}

export function AppCrashReportsCard({ onToast }: { onToast?: (msg: string, type?: "success" | "error" | "info") => void }) {
    const [rows, setRows] = useState<CrashRow[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [open, setOpen] = useState<string | null>(null);

    const load = useCallback(() => {
        setError(null);
        api.get<CrashRow[]>("/admin/client-crashes", { params: { limit: 20 } })
            .then((r) => setRows(Array.isArray(r.data) ? r.data : []))
            .catch(() => setError("Couldn't load crash reports."));
    }, []);
    useEffect(() => { load(); }, [load]);

    const copy = async (r: CrashRow) => {
        try {
            await navigator.clipboard.writeText(asText(r));
            onToast?.("Crash report copied", "success");
        } catch {
            onToast?.("Couldn't copy — select the text instead", "error");
        }
    };

    return (
        <section aria-labelledby="crash-title" className="bg-white rounded-2xl border border-[#e6f3d8] p-5">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h4 id="crash-title" className="text-sm font-semibold text-[#16270c]">App crash reports</h4>
                    <p className="text-xs text-stone-500 mt-0.5">
                        When the Android app closes unexpectedly it sends what happened here. Copy a report to share it.
                    </p>
                </div>
                <button type="button" onClick={load} className="text-xs font-semibold text-[#3d7a1f] underline" style={{ minHeight: 44 }}>
                    Refresh
                </button>
            </div>
            {error && <p className="text-sm text-red-700 mt-3" role="alert">{error}</p>}
            {!error && rows === null && <p className="text-sm text-stone-500 mt-3">Loading…</p>}
            {rows?.length === 0 && <p className="text-sm text-stone-500 mt-3">No crashes reported. 🎉</p>}
            {rows && rows.length > 0 && (
                <ul className="mt-3 divide-y divide-[#eef5e6]">
                    {rows.map((r) => (
                        <li key={r.id} className="py-2">
                            <div className="flex items-center justify-between gap-3">
                                <button type="button" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}
                                    className="text-left min-w-0 flex-1" style={{ minHeight: 44 }}>
                                    <div className="text-sm font-medium text-[#16270c]">
                                        {KIND[r.kind] ?? r.kind} · <span className="text-stone-500 font-normal">{when(r.at ?? r.received_at)}</span>
                                    </div>
                                    <div className="text-xs text-stone-500 truncate">
                                        {r.summary || "No details"} · build {r.build || "?"} · {r.device}
                                        {r.agent_name ? ` · ${r.agent_name}` : ""}
                                    </div>
                                </button>
                                <button type="button" onClick={() => copy(r)}
                                    className="rounded-lg px-3 text-xs font-semibold border border-stone-300 text-stone-700 shrink-0" style={{ minHeight: 44 }}>
                                    Copy
                                </button>
                            </div>
                            {open === r.id && (
                                <pre className="mt-2 text-[11px] leading-snug bg-stone-50 border border-stone-200 rounded-lg p-3 overflow-auto max-h-80 whitespace-pre-wrap break-all">
                                    {asText(r)}
                                </pre>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}
