// LeadsView.tsx
// Kanban-style leads pipeline with drag-friendly stage columns.

import React, { useState, useEffect, useCallback } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import { fmtCurrency, timeAgo } from "@/lib/utils";
import type { SharedViewProps } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

type LeadStage =
    | "new"
    | "contacted"
    | "qualified"
    | "proposal"
    | "negotiation"
    | "won"
    | "lost";

interface Lead {
    id: string;
    wa_id: string;
    name: string | null;
    phone: string | null;
    email: string | null;
    location: string | null;
    lead_stage: LeadStage;
    lead_score: number;
    tags: string[];
    channels: string[];
    total_orders: number;
    total_spent: number;
    last_seen_at: string | null;
    notes: string | null;
}

// ── Stage config ──────────────────────────────────────────────────────────────

const STAGES: {
    id: LeadStage;
    label: string;
    color: string;
    bg: string;
    border: string;
    dot: string;
}[] = [
    { id: "new",         label: "New",         color: "text-stone-600",   bg: "bg-stone-50",    border: "border-stone-200",  dot: "bg-stone-400"   },
    { id: "contacted",   label: "Contacted",   color: "text-blue-700",    bg: "bg-blue-50",     border: "border-blue-200",   dot: "bg-blue-500"    },
    { id: "qualified",   label: "Qualified",   color: "text-violet-700",  bg: "bg-violet-50",   border: "border-violet-200", dot: "bg-violet-500"  },
    { id: "proposal",    label: "Proposal",    color: "text-amber-700",   bg: "bg-amber-50",    border: "border-amber-200",  dot: "bg-amber-500"   },
    { id: "negotiation", label: "Negotiating", color: "text-orange-700",  bg: "bg-orange-50",   border: "border-orange-200", dot: "bg-orange-500"  },
    { id: "won",         label: "Won",         color: "text-emerald-700", bg: "bg-emerald-50",  border: "border-emerald-200",dot: "bg-emerald-500" },
    { id: "lost",        label: "Lost",        color: "text-red-600",     bg: "bg-red-50",      border: "border-red-200",    dot: "bg-red-400"     },
];

const CHANNEL_ICONS: Record<string, string> = {
    whatsapp:  "📱", messenger: "💙", instagram: "📸", email: "📧", sms: "💬",
};

// ── Lead card ─────────────────────────────────────────────────────────────────

function LeadCard({
    lead,
    onStageChange,
    onSelect,
}: {
    lead: Lead;
    onStageChange: (id: string, stage: LeadStage) => void;
    onSelect: (lead: Lead) => void;
}) {
    const stageIdx = STAGES.findIndex((s) => s.id === lead.lead_stage);

    return (
        <div
            onClick={() => onSelect(lead)}
            className="bg-white rounded-xl border border-stone-100 shadow-sm p-3 mb-2 cursor-pointer hover:border-stone-300 hover:shadow-md transition-all group"
        >
            <div className="flex items-start gap-2 mb-2">
                <Avatar name={lead.name ?? lead.wa_id} size={32} />
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-stone-800 truncate">
                        {lead.name || <span className="text-stone-400 italic font-normal text-xs">Unknown</span>}
                    </div>
                    <div className="text-[10px] text-stone-400 font-mono truncate">+{lead.wa_id}</div>
                </div>
                <div className="text-[10px] font-bold text-stone-500 flex-shrink-0">
                    {lead.lead_score}/100
                </div>
            </div>

            {/* Score bar */}
            <div className="h-1 bg-stone-100 rounded-full overflow-hidden mb-2">
                <div
                    className={`h-full rounded-full ${lead.lead_score >= 70 ? "bg-emerald-500" : lead.lead_score >= 40 ? "bg-amber-500" : "bg-stone-300"}`}
                    style={{ width: `${lead.lead_score}%` }}
                />
            </div>

            <div className="flex items-center justify-between">
                <div className="flex gap-1">
                    {lead.channels.slice(0, 3).map((ch) => (
                        <span key={ch} className="text-xs" title={ch}>{CHANNEL_ICONS[ch] || "🔗"}</span>
                    ))}
                </div>
                {lead.total_spent > 0 && (
                    <span className="text-[10px] font-semibold text-green-700">
                        {fmtCurrency(lead.total_spent)}
                    </span>
                )}
            </div>

            {lead.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                    {lead.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="text-[9px] bg-stone-100 text-stone-600 rounded px-1 py-0.5">{tag}</span>
                    ))}
                </div>
            )}

            {lead.last_seen_at && (
                <div className="text-[10px] text-stone-400 mt-1.5">{timeAgo(lead.last_seen_at)}</div>
            )}

            {/* Stage advance buttons — visible on hover */}
            <div className="hidden group-hover:flex gap-1 mt-2 pt-2 border-t border-stone-100">
                {stageIdx > 0 && (
                    <button
                        onClick={(e) => { e.stopPropagation(); onStageChange(lead.id, STAGES[stageIdx - 1].id); }}
                        className="flex-1 text-[9px] text-stone-500 bg-stone-50 border border-stone-200 rounded py-1 hover:bg-stone-100 transition-colors"
                    >
                        ← {STAGES[stageIdx - 1].label}
                    </button>
                )}
                {stageIdx < STAGES.length - 1 && STAGES[stageIdx + 1].id !== "lost" && (
                    <button
                        onClick={(e) => { e.stopPropagation(); onStageChange(lead.id, STAGES[stageIdx + 1].id); }}
                        className="flex-1 text-[9px] text-green-700 bg-green-50 border border-green-200 rounded py-1 hover:bg-green-100 transition-colors"
                    >
                        {STAGES[stageIdx + 1].label} →
                    </button>
                )}
            </div>
        </div>
    );
}

// ── Lead detail modal ─────────────────────────────────────────────────────────

function LeadModal({ lead, onClose, onSave }: {
    lead: Lead;
    onClose: () => void;
    onSave: (updates: Partial<Lead>) => void;
}) {
    const [stage, setStage]   = useState<LeadStage>(lead.lead_stage);
    const [notes, setNotes]   = useState(lead.notes || "");
    const [tags, setTags]     = useState(lead.tags.join(", "));

    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <div
                className="bg-white rounded-2xl shadow-xl w-full max-w-md p-5 max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <Avatar name={lead.name ?? lead.wa_id} size={44} />
                        <div>
                            <div className="text-sm font-bold text-stone-800">
                                {lead.name || "Unknown customer"}
                            </div>
                            <div className="text-xs text-stone-400 font-mono">+{lead.wa_id}</div>
                        </div>
                    </div>
                    <button onClick={onClose} className="text-stone-400 hover:text-stone-600 text-lg">✕</button>
                </div>

                <div className="space-y-4">
                    <div>
                        <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider mb-1.5 block">
                            Lead Stage
                        </label>
                        <div className="flex flex-wrap gap-1.5">
                            {STAGES.map((s) => (
                                <button
                                    key={s.id}
                                    onClick={() => setStage(s.id)}
                                    className={`text-xs font-semibold px-2.5 py-1.5 rounded-lg border transition-all ${
                                        stage === s.id
                                            ? `${s.bg} ${s.color} ${s.border}`
                                            : "bg-white text-stone-400 border-stone-200 hover:border-stone-400"
                                    }`}
                                >
                                    {s.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div>
                        <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider mb-1.5 block">
                            Tags (comma separated)
                        </label>
                        <input
                            value={tags}
                            onChange={(e) => setTags(e.target.value)}
                            className="w-full text-sm bg-stone-50 border border-stone-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-green-600 text-stone-700"
                            placeholder="church, wholesale, repeat-buyer"
                        />
                    </div>

                    <div>
                        <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider mb-1.5 block">
                            Notes
                        </label>
                        <textarea
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            rows={3}
                            className="w-full text-sm bg-stone-50 border border-stone-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-green-600 text-stone-700"
                            placeholder="Internal notes about this lead…"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-3 py-3 bg-stone-50 rounded-xl px-3">
                        {[
                            { label: "Orders",      value: lead.total_orders },
                            { label: "Total spent", value: fmtCurrency(lead.total_spent) },
                            { label: "Lead score",  value: `${lead.lead_score}/100` },
                            { label: "Channels",    value: lead.channels.length },
                        ].map((row) => (
                            <div key={row.label}>
                                <div className="text-[10px] text-stone-400">{row.label}</div>
                                <div className="text-sm font-bold text-stone-800">{row.value}</div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="flex gap-2 mt-4">
                    <Btn
                        variant="primary"
                        onClick={() => {
                            onSave({
                                lead_stage: stage,
                                notes,
                                tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
                            });
                            onClose();
                        }}
                        full
                    >
                        Save Changes
                    </Btn>
                    <Btn variant="outline" onClick={onClose}>Cancel</Btn>
                </div>
            </div>
        </div>
    );
}

// ── Main LeadsView ────────────────────────────────────────────────────────────

interface LeadsViewProps extends SharedViewProps {
    // Reuses SharedViewProps: onToast, isMobile
}

export function LeadsView({ onToast, isMobile }: LeadsViewProps): React.ReactElement {
    const [leads, setLeads]           = useState<Lead[]>([]);
    const [loading, setLoading]       = useState(true);
    const [selected, setSelected]     = useState<Lead | null>(null);
    const [filterStage, setFilterStage] = useState<"all" | LeadStage>("all");
    const [search, setSearch]         = useState("");

    const loadLeads = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch("/api/admin/leads", {
                headers: { Authorization: `Bearer ${(window as any).__neema_token}` },
            });
            if (res.ok) {
                const data = await res.json();
                setLeads(data);
            } else {
                setLeads([]);
            }
        } catch {
            setLeads([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadLeads(); }, [loadLeads]);

    const updateLead = async (id: string, updates: Partial<Lead>) => {
        setLeads((prev) => prev.map((l) => l.id === id ? { ...l, ...updates } : l));
        try {
            await fetch(`/api/admin/leads/${id}`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${(window as any).__neema_token}`,
                },
                body: JSON.stringify(updates),
            });
            onToast("Lead updated");
        } catch {
            onToast("Failed to update lead", "error");
            loadLeads(); // rollback by reloading
        }
    };

    const filteredLeads = leads.filter((l) => {
        if (filterStage !== "all" && l.lead_stage !== filterStage) return false;
        if (search) {
            const q = search.toLowerCase();
            return (
                (l.name || "").toLowerCase().includes(q) ||
                l.wa_id.includes(q) ||
                (l.email || "").toLowerCase().includes(q) ||
                (l.location || "").toLowerCase().includes(q)
            );
        }
        return true;
    });

    // Pipeline totals
    const pipelineValue = leads
        .filter((l) => !["lost", "won"].includes(l.lead_stage))
        .reduce((s, l) => s + l.total_spent, 0);
    const wonValue = leads
        .filter((l) => l.lead_stage === "won")
        .reduce((s, l) => s + l.total_spent, 0);

    return (
        <div className={`flex-1 overflow-hidden flex flex-col bg-stone-50 ${isMobile ? "pb-20" : ""}`}>
            {/* Header */}
            <div className={`flex items-center justify-between border-b border-stone-100 bg-white ${isMobile ? "px-4 py-3" : "px-6 py-4"}`}>
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">Leads Pipeline</h1>
                    <p className="text-sm text-stone-400 mt-0.5">
                        {leads.length} leads · Pipeline {fmtCurrency(pipelineValue)} · Won {fmtCurrency(wonValue)}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <div className="relative">
                        <svg className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                        </svg>
                        <input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search leads…"
                            className="h-8 pl-8 pr-3 text-xs bg-stone-50 border border-stone-200 rounded-lg text-stone-700 placeholder-stone-300 focus:outline-none focus:ring-1 focus:ring-green-600"
                            style={{ fontSize: 14 }}
                        />
                    </div>
                </div>
            </div>

            {/* Stage filter pills */}
            <div className="flex gap-2 px-6 py-3 border-b border-stone-100 bg-white overflow-x-auto scrollbar-none">
                <button
                    onClick={() => setFilterStage("all")}
                    className={`flex-shrink-0 h-7 px-3 rounded-lg text-xs font-medium border transition-all ${
                        filterStage === "all" ? "bg-stone-800 text-white border-stone-800" : "bg-white text-stone-500 border-stone-200 hover:border-stone-400"
                    }`}
                >
                    All ({leads.length})
                </button>
                {STAGES.map((s) => {
                    const count = leads.filter((l) => l.lead_stage === s.id).length;
                    return (
                        <button
                            key={s.id}
                            onClick={() => setFilterStage(s.id)}
                            className={`flex-shrink-0 h-7 px-3 rounded-lg text-xs font-medium border transition-all flex items-center gap-1.5 ${
                                filterStage === s.id
                                    ? `${s.bg} ${s.color} ${s.border}`
                                    : "bg-white text-stone-500 border-stone-200 hover:border-stone-400"
                            }`}
                        >
                            <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                            {s.label} ({count})
                        </button>
                    );
                })}
            </div>

            {/* Kanban board */}
            {loading ? (
                <div className="flex-1 flex items-center justify-center">
                    <div className="w-6 h-6 border-2 border-green-700 border-t-transparent rounded-full animate-spin" />
                </div>
            ) : (
                <div className="flex-1 overflow-x-auto">
                    <div className="flex h-full gap-3 p-4" style={{ minWidth: STAGES.length * 220 + "px" }}>
                        {STAGES.map((stage) => {
                            const stageLeads = filteredLeads.filter((l) => l.lead_stage === stage.id);
                            const stageValue = stageLeads.reduce((s, l) => s + l.total_spent, 0);
                            return (
                                <div key={stage.id} className="flex flex-col" style={{ width: 210, flexShrink: 0 }}>
                                    {/* Column header */}
                                    <div className={`flex items-center justify-between px-3 py-2 rounded-xl mb-2 ${stage.bg} border ${stage.border}`}>
                                        <div className="flex items-center gap-1.5">
                                            <span className={`w-2 h-2 rounded-full ${stage.dot}`} />
                                            <span className={`text-xs font-bold ${stage.color}`}>{stage.label}</span>
                                        </div>
                                        <div className="text-right">
                                            <div className={`text-xs font-bold ${stage.color}`}>{stageLeads.length}</div>
                                            {stageValue > 0 && (
                                                <div className={`text-[10px] ${stage.color} opacity-70`}>{fmtCurrency(stageValue)}</div>
                                            )}
                                        </div>
                                    </div>

                                    {/* Cards */}
                                    <div className="flex-1 overflow-y-auto pr-0.5">
                                        {stageLeads.length === 0 ? (
                                            <div className="text-center py-8 text-stone-300 text-xs">No leads</div>
                                        ) : (
                                            stageLeads.map((lead) => (
                                                <LeadCard
                                                    key={lead.id}
                                                    lead={lead}
                                                    onStageChange={(id, s) => updateLead(id, { lead_stage: s })}
                                                    onSelect={setSelected}
                                                />
                                            ))
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Lead detail modal */}
            {selected && (
                <LeadModal
                    lead={selected}
                    onClose={() => setSelected(null)}
                    onSave={(updates) => {
                        updateLead(selected.id, updates);
                        setSelected(null);
                    }}
                />
            )}
        </div>
    );
}