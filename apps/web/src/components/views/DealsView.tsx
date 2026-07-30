"use client";

// Deals — the shared board (plan B1/B3): what Neema currently owns, what's
// blocking each deal, whose move is next, and when she plans to act. The
// planned-actions strip on top is her initiative queue: approve or veto
// anything before (or instead of) it firing.
import React, { useCallback, useEffect, useState } from "react";
import { timeAgo } from "@/lib/utils";
import { dealsApi, actionsApi, type ApiDeal, type ApiAction } from "@/lib/api";
import type { SharedViewProps } from "@/types";

interface DealsViewProps extends SharedViewProps {
    onOpenConversation?: (key: string) => void;
}

const STAGES: { id: string; label: string; color: string }[] = [
    { id: "new",       label: "New",        color: "#94a3b8" },
    { id: "qualified", label: "Qualified",  color: "#589b31" },
    { id: "proposal",  label: "Proposal",   color: "#f59e0b" },
];

const fmtDue = (iso: string | null) => {
    if (!iso) return "";
    const d = new Date(iso).getTime() - Date.now();
    if (d <= 0) return "due now";
    const h = Math.floor(d / 3600000);
    if (h < 1) return `in ${Math.max(1, Math.floor(d / 60000))}m`;
    if (h < 48) return `in ${h}h`;
    return `in ${Math.floor(h / 24)}d`;
};

export function DealsView({ isMobile, onToast, onOpenConversation }: DealsViewProps): React.ReactElement {
    const [deals, setDeals] = useState<ApiDeal[] | null>(null);
    const [actions, setActions] = useState<ApiAction[] | null>(null);
    const [editing, setEditing] = useState<string | null>(null);
    const [guidanceDraft, setGuidanceDraft] = useState("");

    const load = useCallback(() => {
        dealsApi.list().then((r) => setDeals(r.deals)).catch(() => setDeals([]));
        actionsApi.list().then((r) => setActions(r.actions)).catch(() => setActions([]));
    }, []);
    useEffect(() => {
        load();
        const t = setInterval(() => {
            if (typeof document === "undefined" || document.visibilityState === "visible") load();
        }, 60000);
        return () => clearInterval(t);
    }, [load]);

    const patchDeal = async (id: string, body: Record<string, unknown>, msg: string) => {
        try {
            await dealsApi.patch(id, body);
            onToast(msg);
            load();
        } catch {
            onToast("Update failed", "error");
        }
    };

    const act = async (id: string, verb: "approve" | "veto") => {
        try {
            if (verb === "approve") await actionsApi.approve(id);
            else await actionsApi.veto(id);
            onToast(verb === "approve" ? "Sent ✓" : "Vetoed");
            load();
        } catch {
            onToast(`${verb} failed`, "error");
        }
    };

    const open = (deals ?? []).filter((d) => d.status === "open");
    const wonCount = (deals ?? []).filter((d) => d.status === "won").length;
    const pending = actions ?? [];

    return (
        <div className="h-full overflow-y-auto w-full px-4 sm:px-6 py-6" style={{ backgroundColor: "#f6f7f2" }}>
            <div className="mx-auto" style={{ maxWidth: 1100 }}>
                <div className="flex items-end justify-between mb-4">
                    <div>
                        <h1 className="text-xl font-semibold text-[#1c2917]">Deals</h1>
                        <p className="text-xs text-[#8a9e80] mt-0.5">
                            What Neema owns right now · {open.length} open · {wonCount} won
                        </p>
                    </div>
                </div>

                {/* ── Initiative queue ─────────────────────────────────────── */}
                <div className="rounded-2xl bg-white border border-stone-200 p-4 mb-5">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-[#8a9e80] mb-2">
                        Planned actions — Neema&apos;s next moves
                    </div>
                    {actions === null ? (
                        <p className="text-xs text-stone-400">Loading…</p>
                    ) : pending.length === 0 ? (
                        <p className="text-xs text-stone-400">
                            Nothing queued. Promises made in chat (hers or the customer&apos;s) land here automatically.
                        </p>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {pending.map((a) => (
                                <div key={a.id}
                                     className="flex items-start gap-3 rounded-xl px-3 py-2.5"
                                     style={{ backgroundColor: a.status === "needs_approval" ? "#fdf6e9" : "#f8faf6",
                                              border: a.status === "needs_approval" ? "1px solid #f0ddb0" : "1px solid #e8ede4" }}>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs font-medium text-[#1c2917]">
                                            {a.status === "needs_approval" ? "⏳ Needs your approval" : `🕐 ${fmtDue(a.due_at)}`}
                                            <span className="font-normal text-[#64748b]"> · {a.kind === "customer_promise" ? "their timeline" : "her promise"}</span>
                                        </div>
                                        <div className="text-xs text-[#475569] mt-0.5 line-clamp-2">{a.reason}</div>
                                        {a.draft && (
                                            <div className="text-[11px] text-[#1c2917] mt-1 px-2 py-1.5 rounded-lg bg-white border border-stone-100 line-clamp-3">
                                                “{a.draft}”
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex gap-1.5 flex-shrink-0">
                                        <button onClick={() => act(a.id, "approve")}
                                                className="text-[11px] font-semibold px-3 py-1.5 rounded-lg text-white"
                                                style={{ backgroundColor: "#589b31" }}>
                                            Send
                                        </button>
                                        <button onClick={() => act(a.id, "veto")}
                                                className="text-[11px] font-semibold px-3 py-1.5 rounded-lg text-[#64748b] bg-stone-100 hover:bg-stone-200">
                                            Veto
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* ── The board ────────────────────────────────────────────── */}
                <div className={isMobile ? "flex flex-col gap-4" : "grid grid-cols-3 gap-4"}>
                    {STAGES.map((stage) => {
                        const col = open.filter((d) => (d.stage === stage.id)
                            || (stage.id === "new" && !STAGES.some((s) => s.id === d.stage)));
                        return (
                            <div key={stage.id} className="rounded-2xl bg-white border border-stone-200 p-3 min-h-[120px]">
                                <div className="flex items-center gap-2 px-1 mb-2">
                                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: stage.color }} />
                                    <span className="text-xs font-semibold text-[#1c2917]">{stage.label}</span>
                                    <span className="text-[10px] text-[#8a9e80]">{col.length}</span>
                                </div>
                                <div className="flex flex-col gap-2">
                                    {col.map((d) => (
                                        <div key={d.id} className="rounded-xl border border-stone-100 p-3 hover:border-stone-200 transition-colors">
                                            <div className="flex items-start justify-between gap-2">
                                                <button className="text-xs font-semibold text-[#1c2917] text-left truncate hover:underline"
                                                        onClick={() => d.wa_id && onOpenConversation?.(d.wa_id)}>
                                                    {d.customer}
                                                </button>
                                                <span className="text-[10px] text-[#b5c9a8] flex-shrink-0">{timeAgo(d.updated_at)}</span>
                                            </div>
                                            {d.title && <div className="text-[11px] text-[#475569] mt-1 line-clamp-2">{d.title}</div>}
                                            {d.blocking && (
                                                <div className="text-[10px] text-[#b45309] mt-1.5 line-clamp-2">⛔ {d.blocking}</div>
                                            )}
                                            {d.next_action?.due_at && (
                                                <div className="text-[10px] text-[#589b31] mt-1">
                                                    → {d.next_action.owner === "ai" ? "Neema" : "You"} · {fmtDue(d.next_action.due_at)}
                                                </div>
                                            )}
                                            {editing === d.id ? (
                                                <div className="mt-2">
                                                    <textarea value={guidanceDraft} rows={2}
                                                              onChange={(e) => setGuidanceDraft(e.target.value.slice(0, 400))}
                                                              placeholder='e.g. "No discount on this one"'
                                                              className="w-full text-[11px] rounded-lg px-2 py-1.5 border border-stone-200 focus:outline-none" />
                                                    <div className="flex gap-1.5 mt-1">
                                                        <button onClick={() => { patchDeal(d.id, { guidance: guidanceDraft }, "Guidance saved — Neema obeys it now"); setEditing(null); }}
                                                                className="text-[10px] font-semibold px-2.5 py-1 rounded-lg text-white" style={{ backgroundColor: "#1e293b" }}>Save</button>
                                                        <button onClick={() => setEditing(null)}
                                                                className="text-[10px] px-2 py-1 text-[#64748b]">Cancel</button>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="flex items-center gap-2 mt-2">
                                                    <button onClick={() => { setEditing(d.id); setGuidanceDraft(d.guidance || ""); }}
                                                            title={d.guidance || "Set guidance Neema must obey for this deal"}
                                                            className="text-[10px] px-2 py-1 rounded-lg bg-stone-50 hover:bg-stone-100 text-[#64748b]">
                                                        {d.guidance ? "📌 Guidance" : "＋ Guidance"}
                                                    </button>
                                                    <button onClick={() => patchDeal(d.id, { status: "won", stage: "won" }, "Marked won 🎉")}
                                                            className="text-[10px] px-2 py-1 rounded-lg bg-[#e9f6df] hover:bg-[#def0d0] text-[#427425]">Won</button>
                                                    <button onClick={() => patchDeal(d.id, { status: "lost", stage: "lost" }, "Marked lost")}
                                                            className="text-[10px] px-2 py-1 rounded-lg bg-stone-50 hover:bg-stone-100 text-[#94a3b8]">Lost</button>
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                    {col.length === 0 && (
                                        <div className="text-[11px] text-stone-300 text-center py-4">—</div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
