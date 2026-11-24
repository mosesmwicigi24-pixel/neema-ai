"use client";

// Settings → Call audio reports (admins). When a call rings and is answered
// but the audio never connects ("The call audio couldn't connect"), the
// device sends what it saw: how far the connection got, which kinds of
// network path it found, whether our own relay was offered. They were stored
// (GET /admin/calls-diagnostics) with no screen to read them on, so "calls
// don't connect" could only be guessed at. No customer number, no audio.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface DiagRow {
    at?: string;
    call?: string;
    agent?: string;
    stage?: string;
    direction?: string;
    connection?: string;
    ice?: string;
    gathering?: string;
    local?: Record<string, number>;
    remote?: Record<string, number>;
    pair?: string;
    relay_offered?: boolean;
    relay_errors?: number;
    seconds?: number;
    client?: string;
    platform?: string;
    network?: string;
    reading?: string;
}
interface DiagResp {
    count: number;
    by_reading: Record<string, number>;
    items: DiagRow[];
    relay: boolean;
}

const STAGE: Record<string, string> = {
    connect_guard: "Answered, no audio after 20 seconds",
    ice_failed: "No network path could be opened",
    ice_lost: "Connected, then the path was lost",
    no_answer_sdp: "WhatsApp's answer never arrived",
    mic: "Microphone could not be opened",
    signalling: "Call setup failed",
    other: "Other",
};
const KIND: Record<string, string> = { host: "direct", srflx: "via STUN", prflx: "peer", relay: "via relay" };

function when(iso?: string): string {
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function paths(c?: Record<string, number>): string {
    const parts = Object.entries(c ?? {}).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${KIND[k] ?? k}`);
    return parts.length ? parts.join(", ") : "none";
}

export function callAudioReportText(r: DiagRow): string {
    return [
        `${STAGE[r.stage ?? ""] ?? r.stage ?? "?"} · ${when(r.at)}`,
        r.reading ?? "",
        `${r.direction ?? "?"} call · ${r.client ?? "?"} · ${r.platform || "device unknown"} · network ${r.network || "unknown"}${r.agent ? ` · ${r.agent}` : ""}`,
        `Paths this device found: ${paths(r.local)}`,
        `Paths WhatsApp offered: ${paths(r.remote)}`,
        `Path chosen: ${r.pair && r.pair !== "none" ? (KIND[r.pair] ?? r.pair) : "none"}`,
        `Our relay offered: ${r.relay_offered ? "yes" : "no"} · relay errors: ${r.relay_errors ?? 0}`,
        `States: connection ${r.connection || "?"}, ice ${r.ice || "?"}, gathering ${r.gathering || "?"} · ${r.seconds ?? 0}s`,
    ].filter(Boolean).join("\n");
}

export function CallAudioReportsCard({ onToast }: { onToast?: (msg: string, type?: "success" | "error" | "info") => void }) {
    const [data, setData] = useState<DiagResp | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [open, setOpen] = useState<number | null>(null);

    const fetchReports = useCallback(() =>
        api.get<DiagResp>("/admin/calls-diagnostics", { params: { limit: 30 } })
            .then((r) => { setData(r.data); setError(null); })
            .catch(() => setError("Couldn't load the call audio reports.")), []);
    useEffect(() => { void fetchReports(); }, [fetchReports]);
    const load = () => { void fetchReports(); };

    const copyAll = async () => {
        if (!data) return;
        const text = [
            `Our own relay: ${data.relay ? "ON" : "OFF"}`,
            `Reports: ${data.count}`,
            ...Object.entries(data.by_reading).map(([k, n]) => `${n} × ${k}`),
            "",
            ...data.items.map(callAudioReportText).flatMap((t) => [t, ""]),
        ].join("\n");
        try {
            await navigator.clipboard.writeText(text);
            onToast?.("Call audio reports copied", "success");
        } catch {
            onToast?.("Couldn't copy — select the text instead", "error");
        }
    };

    const rows = data?.items ?? [];

    return (
        <section aria-labelledby="callaudio-title" className="bg-white rounded-2xl border border-[#e6f3d8] p-5">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h4 id="callaudio-title" className="text-sm font-semibold text-[#16270c]">Call audio reports</h4>
                    <p className="text-xs text-stone-500 mt-0.5">
                        When a call is answered but the audio never connects, the device sends why. No numbers, no audio.
                    </p>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                    {rows.length > 0 && (
                        <button type="button" onClick={copyAll}
                            className="rounded-lg px-3 text-xs font-semibold border border-stone-300 text-stone-700" style={{ minHeight: 44 }}>
                            Copy all
                        </button>
                    )}
                    <button type="button" onClick={load} className="text-xs font-semibold text-[#3d7a1f] underline" style={{ minHeight: 44 }}>
                        Refresh
                    </button>
                </div>
            </div>

            {error && <p className="text-sm text-red-700 mt-3" role="alert">{error}</p>}
            {!error && data === null && <p className="text-sm text-stone-500 mt-3">Loading…</p>}

            {data && (
                <div className="mt-3 rounded-xl px-3 py-2.5 text-sm"
                    style={{ background: data.relay ? "#eef8e4" : "#fff4e5", color: data.relay ? "#1f4d0c" : "#7a4b00" }}>
                    <span className="font-semibold">Our own call relay is {data.relay ? "on" : "off"}.</span>{" "}
                    {data.relay
                        ? "Devices are offered it first."
                        : "Devices only have a free public relay to fall back on, so calls on mobile data and many Wi‑Fi networks may not connect."}
                </div>
            )}

            {data && rows.length === 0 && <p className="text-sm text-stone-500 mt-3">No failed-audio reports.</p>}

            {data && rows.length > 0 && (
                <>
                    <ul className="mt-3 space-y-1">
                        {Object.entries(data.by_reading).sort((a, b) => b[1] - a[1]).map(([reading, n]) => (
                            <li key={reading} className="flex gap-2 text-sm text-[#16270c]">
                                <span className="font-semibold tabular-nums shrink-0">{n}×</span>
                                <span>{reading}</span>
                            </li>
                        ))}
                    </ul>
                    <ul className="mt-3 divide-y divide-[#eef5e6]">
                        {rows.map((r, i) => (
                            <li key={`${r.at}-${r.call}-${i}`} className="py-2">
                                <button type="button" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}
                                    className="text-left w-full" style={{ minHeight: 44 }}>
                                    <div className="text-sm font-medium text-[#16270c]">
                                        {STAGE[r.stage ?? ""] ?? r.stage} · <span className="text-stone-500 font-normal">{when(r.at)}</span>
                                    </div>
                                    <div className="text-xs text-stone-500">
                                        {r.direction === "outbound" ? "Outgoing" : "Incoming"} · {r.client ?? "?"} · {r.platform || "device unknown"} · {r.network || "network unknown"}
                                        {r.agent ? ` · ${r.agent}` : ""}
                                    </div>
                                </button>
                                {open === i && (
                                    <pre className="mt-2 text-[11px] leading-snug bg-stone-50 border border-stone-200 rounded-lg p-3 overflow-auto max-h-80 whitespace-pre-wrap break-words">
                                        {callAudioReportText(r)}
                                    </pre>
                                )}
                            </li>
                        ))}
                    </ul>
                </>
            )}
        </section>
    );
}
