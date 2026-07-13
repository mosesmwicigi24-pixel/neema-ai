"use client";

// Calls — a phone-style "recents" list of WhatsApp voice calls: who called,
// when, missed/answered, duration, who picked up. Polls the /admin/calls log and
// refreshes live when the softphone fires call events over the WebSocket.
import React, { useCallback, useEffect, useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { timeAgo } from "@/lib/utils";
import { callsApi, type ApiCall } from "@/lib/api";
import { useWs } from "@/lib/websocket";
import type { SharedViewProps } from "@/types";

function fmtDur(s: number | null): string {
    if (!s) return "";
    const m = Math.floor(s / 60);
    return `${m}:${(s % 60).toString().padStart(2, "0")}`;
}

const STATUS_META: Record<string, { label: string; color: string; icon: string }> = {
    answered: { label: "Answered",  color: "#16a34a", icon: "↙" },
    ended:    { label: "Answered",  color: "#16a34a", icon: "↙" },
    missed:   { label: "Missed",    color: "#ef4444", icon: "↙" },
    declined: { label: "Declined",  color: "#f59e0b", icon: "↙" },
    callback: { label: "Callback ↩", color: "#f59e0b", icon: "↩" },
    ringing:  { label: "Ringing…",  color: "#25D366", icon: "●" },
};

export function CallsView({ isMobile }: SharedViewProps): React.ReactElement {
    const ws = useWs();
    const [calls, setCalls] = useState<ApiCall[] | null>(null);

    const load = useCallback(() => {
        callsApi.list().then(setCalls).catch(() => setCalls([]));
    }, []);

    useEffect(() => {
        load();
        const t = setInterval(() => {
            if (typeof document === "undefined" || document.visibilityState === "visible") load();
        }, 20000);
        return () => clearInterval(t);
    }, [load]);

    // Live refresh when a call starts/ends.
    useEffect(() => {
        if (!ws) return;
        const onEvent = (e: any) => {
            if (e?.type === "incoming_call" || e?.type === "call_ended") setTimeout(load, 500);
        };
        ws.on("event", onEvent);
        return () => ws.off("event", onEvent);
    }, [ws, load]);

    const missedCount = (calls ?? []).filter((c) => c.status === "missed").length;

    return (
        <div className="h-full overflow-y-auto bg-[#fafcf7]">
            <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6">
                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h1 className="text-xl font-bold text-[#16270c]">Calls</h1>
                        <p className="text-xs text-[#8a9e80] mt-0.5">
                            WhatsApp voice calls · {calls?.length ?? 0} total
                            {missedCount > 0 && (
                                <span className="text-red-500 font-semibold"> · {missedCount} missed</span>
                            )}
                        </p>
                    </div>
                </div>

                {calls === null ? (
                    <div className="text-sm text-[#8a9e80] py-10 text-center">Loading…</div>
                ) : calls.length === 0 ? (
                    <div className="bg-white rounded-xl border border-[#cee6b2] p-10 text-center">
                        <div className="text-3xl mb-2">📞</div>
                        <div className="text-sm font-semibold text-[#1c2917]">No calls yet</div>
                        <div className="text-xs text-[#8a9e80] mt-1">
                            Incoming WhatsApp voice calls will appear here. Keep the dashboard open —
                            the softphone rings anywhere in Neema.
                        </div>
                    </div>
                ) : (
                    <div className="bg-white rounded-xl border border-[#cee6b2] overflow-hidden divide-y divide-[#f2f4ef]">
                        {calls.map((c) => {
                            const meta = STATUS_META[c.status] ?? STATUS_META.ended;
                            const who = c.name || (c.wa_id ? `+${c.wa_id}` : "Unknown");
                            const missed = c.status === "missed";
                            return (
                                <div key={c.id} className="flex items-center gap-3 px-4 py-3 hover:bg-[#fbfaf6]">
                                    <Avatar name={who} size={38} />
                                    <div className="flex-1 min-w-0">
                                        <div className={`text-sm font-medium truncate ${missed ? "text-red-600" : "text-[#1c2917]"}`}>
                                            {who}
                                        </div>
                                        <div className="text-[11px] flex items-center gap-1.5" style={{ color: meta.color }}>
                                            <span>{meta.icon}</span>
                                            <span>{meta.label}</span>
                                            {c.duration ? <span className="text-[#8a9e80]">· {fmtDur(c.duration)}</span> : null}
                                            {c.agent_name ? <span className="text-[#8a9e80]">· {c.agent_name}</span> : null}
                                        </div>
                                    </div>
                                    <div className="text-[10px] text-[#b5c9a8] flex-shrink-0">
                                        {c.started_at ? timeAgo(c.started_at) : ""}
                                    </div>
                                    {c.wa_id && (
                                        <a
                                            href={`https://wa.me/${c.wa_id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            title="Open WhatsApp chat"
                                            className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white text-sm hover:brightness-95"
                                            style={{ backgroundColor: "#25D366" }}
                                        >💬</a>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
