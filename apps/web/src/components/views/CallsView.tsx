"use client";

// Calls — the "Calls · History" panel from the Figma "WhatsApp Softphone" board.
// A dark, premium call-console: header with a live missed badge, and phone-style
// rows — colour-coded outcome (answered / missed / callback), duration, the agent
// who took it, timestamp, and a green call-back shortcut. Polls the call log and
// live-refreshes on WebSocket call events.
import React, { useCallback, useEffect, useState } from "react";
import { timeAgo } from "@/lib/utils";
import { callsApi, type ApiCall } from "@/lib/api";
import { useWs } from "@/lib/websocket";
import type { SharedViewProps } from "@/types";

const fmtDur = (s: number | null) => (!s ? "" : `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`);

const OUTCOME: Record<string, { label: string; color: string; dir: "in" | "out" | "back" }> = {
    answered: { label: "Answered", color: "#2ad17f", dir: "in" },
    ended:    { label: "Answered", color: "#2ad17f", dir: "in" },
    missed:   { label: "Missed",   color: "#f2555a", dir: "in" },
    declined: { label: "Declined", color: "#f5a623", dir: "in" },
    callback: { label: "Callback", color: "#f5a623", dir: "back" },
    ringing:  { label: "Ringing…", color: "#2ad17f", dir: "in" },
};

const AV = ["#3b6ea5", "#a5417d", "#b5892f", "#3c8c5a", "#8a4fc4", "#b24a4a"];
const avatarColor = (s: string) => AV[[...(s || "?")].reduce((a, c) => a + c.charCodeAt(0), 0) % AV.length];

function DirIcon({ dir, color }: { dir: "in" | "out" | "back"; color: string }) {
    const d = dir === "back"
        ? "M9 14l-4-4 4-4M5 10h10a4 4 0 014 4v2"
        : "M17 7L7 17M7 17h7M7 17V10";   // incoming arrow
    return (
        <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
            <path d={d} />
        </svg>
    );
}

export function CallsView({ isMobile }: SharedViewProps): React.ReactElement {
    const ws = useWs();
    const [calls, setCalls] = useState<ApiCall[] | null>(null);

    const load = useCallback(() => { callsApi.list().then(setCalls).catch(() => setCalls([])); }, []);
    useEffect(() => {
        load();
        const t = setInterval(() => {
            if (typeof document === "undefined" || document.visibilityState === "visible") load();
        }, 20000);
        return () => clearInterval(t);
    }, [load]);
    useEffect(() => {
        if (!ws) return;
        const on = (e: any) => { if (e?.type === "incoming_call" || e?.type === "call_ended") setTimeout(load, 500); };
        ws.on("event", on);
        return () => ws.off("event", on);
    }, [ws, load]);

    const missed = (calls ?? []).filter((c) => c.status === "missed").length;

    return (
        <div className="h-full overflow-y-auto w-full" style={{ backgroundColor: "#f6f7f2" }}>
            <div className="mx-auto px-4 sm:px-6 py-6" style={{ maxWidth: 560 }}>
                <div className="rounded-2xl overflow-hidden"
                    style={{ background: "radial-gradient(120% 60% at 50% 0%, #123626 0%, #0b1410 60%)", border: "1px solid rgba(37,211,102,0.14)", boxShadow: "0 20px 50px rgba(0,0,0,0.25)" }}>

                    <div className="px-6 pt-6 pb-4 flex items-start justify-between">
                        <div>
                            <div className="text-white" style={{ fontSize: 22, fontWeight: 500 }}>Calls</div>
                            <div style={{ fontSize: 13, color: "#7f9b8b", marginTop: 2 }}>
                                WhatsApp voice calls · {calls?.length ?? 0} total
                            </div>
                        </div>
                        {missed > 0 && (
                            <span style={{ fontSize: 12, fontWeight: 500, color: "#ff8a8d", backgroundColor: "rgba(242,85,90,0.16)", padding: "5px 11px", borderRadius: 999 }}>
                                {missed} missed
                            </span>
                        )}
                    </div>

                    <div>
                        {calls === null ? (
                            <div style={{ color: "#7f9b8b", fontSize: 14 }} className="px-6 py-10 text-center">Loading…</div>
                        ) : calls.length === 0 ? (
                            <div className="px-6 py-14 text-center">
                                <div style={{ color: "#cfe9d9", fontSize: 15, fontWeight: 500 }}>No calls yet</div>
                                <div style={{ color: "#7f9b8b", fontSize: 13, marginTop: 6 }}>
                                    Incoming WhatsApp voice calls appear here. Keep the dashboard open — a call
                                    takes over the screen when it rings.
                                </div>
                            </div>
                        ) : (
                            calls.map((c) => {
                                const o = OUTCOME[c.status] ?? OUTCOME.ended;
                                const who = c.name || (c.wa_id ? `+${c.wa_id}` : "Unknown");
                                const initials = who.replace("+", "").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
                                return (
                                    <div key={c.id} className="flex items-center gap-3 px-6 py-3.5"
                                        style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
                                        <div className="flex items-center justify-center rounded-full flex-shrink-0"
                                            style={{ width: 40, height: 40, backgroundColor: avatarColor(who), color: "#fff", fontSize: 13, fontWeight: 500 }}>
                                            {initials || "?"}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="truncate" style={{ fontSize: 14, fontWeight: 500, color: "#e9edef" }}>{who}</div>
                                            <div className="flex items-center gap-1.5" style={{ fontSize: 12, color: o.color, marginTop: 1 }}>
                                                <DirIcon dir={o.dir} color={o.color} />
                                                <span>{o.label}</span>
                                                {c.duration ? <span style={{ color: "#7f9b8b" }}>· {fmtDur(c.duration)}</span> : null}
                                                {c.agent_name ? <span style={{ color: "#7f9b8b" }}>· {c.agent_name.split(" ")[0]}</span> : null}
                                            </div>
                                        </div>
                                        <div style={{ fontSize: 11, color: "#6b8577" }} className="flex-shrink-0">
                                            {c.started_at ? timeAgo(c.started_at) : ""}
                                        </div>
                                        {c.wa_id && (
                                            <a href={`https://wa.me/${c.wa_id}`} target="_blank" rel="noopener noreferrer"
                                                title="Message on WhatsApp (opens WhatsApp)"
                                                className="flex-shrink-0 flex items-center justify-center rounded-full transition-transform hover:scale-105"
                                                style={{ width: 34, height: 34, backgroundColor: "rgba(37,211,102,0.16)", color: "#2ad17f", border: "1px solid rgba(37,211,102,0.3)" }}>
                                                <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                                                    <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" />
                                                </svg>
                                            </a>
                                        )}
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
