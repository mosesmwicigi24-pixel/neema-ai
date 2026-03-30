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

// Flat SVG channel icons matching Settings/CustomerSidebar
const CH_SVG: Record<string, { bg: string; path: string }> = {
    whatsapp:  { bg:"#25D366", path:'<path fill="white" d="M12 2C6.48 2 2 6.48 2 12c0 1.82.48 3.54 1.32 5.04L2 22l5.08-1.3A9.94 9.94 0 0012 22c5.52 0 10-4.48 10-10S17.52 2 12 2zm0 18c-1.56 0-3.02-.44-4.26-1.2l-.3-.18-3.14.72.7-3.06-.2-.32A7.96 7.96 0 014 12c0-4.42 3.58-8 8-8s8 3.58 8 8-3.58 8-8 8zm4.24-5.78c-.24-.12-1.42-.7-1.64-.78-.22-.08-.38-.12-.54.12-.16.24-.62.78-.76.94-.14.16-.28.18-.52.06-.24-.12-1.02-.38-1.94-1.18a7.2 7.2 0 01-1.34-1.64c-.14-.24 0-.36.1-.5.1-.1.24-.28.36-.42.12-.16.16-.26.24-.44.08-.16.04-.3 0-.42-.06-.14-.54-1.32-.74-1.8-.2-.48-.4-.42-.54-.44h-.46c-.16 0-.42.06-.64.3-.22.24-.84.82-.84 2s.86 2.32.98 2.48c.12.16 1.7 2.6 4.12 3.64.58.26 1.02.4 1.38.52.58.18 1.1.16 1.52.1.46-.08 1.42-.58 1.62-1.14.2-.56.2-1.04.14-1.14-.08-.1-.22-.16-.46-.28z"/>'},
    messenger: { bg:"#0099FF", path:'<path fill="white" d="M12 2C6.477 2 2 6.145 2 11.259c0 2.906 1.395 5.502 3.58 7.215V22l3.254-1.843A10.61 10.61 0 0012 20.518c5.523 0 10-4.145 10-9.259S17.523 2 12 2zm1.067 12.508L10.9 12.26l-4.24 2.248 4.718-5.009 2.249 2.25 4.148-2.25-4.708 5.009z"/>'},
    instagram: { bg:"url(#igGrad)", path:'<defs><linearGradient id="igGrad" x1="0" y1="1" x2="1" y2="0"><stop offset="0%" stop-color="#f09433"/><stop offset="25%" stop-color="#e6683c"/><stop offset="50%" stop-color="#dc2743"/><stop offset="75%" stop-color="#cc2366"/><stop offset="100%" stop-color="#bc1888"/></linearGradient></defs><path fill="white" d="M12 7.5A4.5 4.5 0 1012 16.5 4.5 4.5 0 0012 7.5zm0 7.5a3 3 0 110-6 3 3 0 010 6zm5.92-7.69a1.05 1.05 0 11-2.1 0 1.05 1.05 0 012.1 0zM21.94 9c-.07-1.47-.4-2.77-1.48-3.85S17.47 3.13 16 3.06C14.48 3 9.52 3 8 3.06 6.53 3.13 5.23 3.46 4.15 4.54S2.13 7.53 2.06 9C2 10.52 2 15.48 2.06 17c.07 1.47.4 2.77 1.48 3.85S6.53 22.87 8 22.94c1.52.06 6.48.06 8 0 1.47-.07 2.77-.4 3.85-1.48S22.87 18.47 22.94 17C23 15.48 23 10.52 22.94 9zM21.2 18.62a3.26 3.26 0 01-1.84 1.84c-1.27.5-4.29.39-5.7.39s-4.43.1-5.7-.39a3.26 3.26 0 01-1.84-1.84C5.63 17.35 5.74 14.33 5.74 12s-.1-5.35.39-5.62A3.26 3.26 0 017.97 4.54c1.27-.5 4.29-.39 5.7-.39s4.43-.1 5.7.39a3.26 3.26 0 011.84 1.84c.5 1.27.39 4.29.39 5.62s.11 5.35-.4 5.62z"/>'},
    facebook:  { bg:"#1877F2", path:'<path fill="white" d="M13 10V7a1 1 0 011-1h1V3h-2a4 4 0 00-4 4v3H7v3h2v8h3v-8h2.5l.5-3H13z"/>'},
    email:     { bg:"#4d66b3", path:'<path fill="none" stroke="white" strokeWidth="1.5" d="M3 8l9 6 9-6M5 6h14a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2z"/>'},
    sms:       { bg:"#589b31", path:'<path fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>'},
};

function ChannelIcon({ ch, size = 16 }: { ch: string; size?: number }) {
    const meta = CH_SVG[ch] ?? CH_SVG.sms;
    return (
        <span
            className="inline-flex items-center justify-center rounded-full flex-shrink-0"
            style={{ width: size, height: size, background: meta.bg }}
            title={ch}
        >
            <svg viewBox="0 0 24 24" style={{ width: size * 0.6, height: size * 0.6 }}
                dangerouslySetInnerHTML={{ __html: meta.path }} />
        </span>
    );
}

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
            className="rounded-xl shadow-sm p-3 mb-2 cursor-pointer transition-all group" style={{backgroundColor:"white",border:"1px solid #e6f3d8"}}
        >
            <div className="flex items-start gap-2 mb-2">
                <Avatar name={lead.name ?? lead.wa_id} size={32} />
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate" style={{color:"#16270c"}}>
                        {lead.name || <span className="text-stone-400 italic font-normal text-xs">Unknown</span>}
                    </div>
                    <div className="text-[10px] font-mono truncate" style={{color:"#699a32"}}>+{lead.wa_id}</div>
                </div>
                <div className="text-[10px] font-bold flex-shrink-0" style={{color:"#699a32"}}>
                    {lead.lead_score}/100
                </div>
            </div>

            {/* Score bar */}
            <div className="h-1 rounded-full overflow-hidden mb-2" style={{backgroundColor:"#e6f3d8"}}>
                <div
                    className={`h-full rounded-full ${lead.lead_score >= 70 ? "bg-emerald-500" : lead.lead_score >= 40 ? "bg-amber-500" : "bg-stone-300"}`}
                    style={{ width: `${lead.lead_score}%` }}
                />
            </div>

            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                    {lead.channels.slice(0, 3).map((ch) => (
                        <ChannelIcon key={ch} ch={ch} size={16} />
                    ))}
                </div>
                {lead.total_spent > 0 && (
                    <span className="text-[10px] font-semibold" style={{color:"#427425"}}>
                        {fmtCurrency(lead.total_spent)}
                    </span>
                )}
            </div>

            {lead.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                    {lead.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="text-[9px] rounded px-1 py-0.5" style={{backgroundColor:"#e6f3d8",color:"#427425"}}>{tag}</span>
                    ))}
                </div>
            )}

            {lead.last_seen_at && (
                <div className="text-[10px] mt-1.5" style={{color:"#699a32"}}>{timeAgo(lead.last_seen_at)}</div>
            )}

            {/* Stage advance buttons — visible on hover */}
            <div className="hidden group-hover:flex gap-1 mt-2 pt-2" style={{borderTop:"1px solid #e6f3d8"}}>
                {stageIdx > 0 && (
                    <button
                        onClick={(e) => { e.stopPropagation(); onStageChange(lead.id, STAGES[stageIdx - 1].id); }}
                        className="flex-1 text-[9px] rounded py-1 transition-colors" style={{backgroundColor:"#f0f9ec",border:"1px solid #b5da8b",color:"#699a32"}}
                    >
                        ← {STAGES[stageIdx - 1].label}
                    </button>
                )}
                {stageIdx < STAGES.length - 1 && STAGES[stageIdx + 1].id !== "lost" && (
                    <button
                        onClick={(e) => { e.stopPropagation(); onStageChange(lead.id, STAGES[stageIdx + 1].id); }}
                        className="flex-1 text-[9px] rounded py-1 transition-colors" style={{backgroundColor:"#e6f3d8",border:"1px solid #b5da8b",color:"#427425"}}
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
                className="rounded-2xl shadow-xl w-full max-w-md p-5 max-h-[90vh] overflow-y-auto" style={{backgroundColor:"white"}}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <Avatar name={lead.name ?? lead.wa_id} size={44} />
                        <div>
                            <div className="text-sm font-bold" style={{color:"#16270c"}}>
                                {lead.name || "Unknown customer"}
                            </div>
                            <div className="text-xs font-mono" style={{color:"#699a32"}}>+{lead.wa_id}</div>
                        </div>
                    </div>
                    <button onClick={onClose} className="text-stone-400 hover:text-stone-600 text-lg">✕</button>
                </div>

                <div className="space-y-4">
                    <div>
                        <label className="text-xs font-semibold uppercase tracking-wider mb-1.5 block" style={{color:"#699a32"}}>
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
                        <label className="text-xs font-semibold uppercase tracking-wider mb-1.5 block" style={{color:"#699a32"}}>
                            Tags (comma separated)
                        </label>
                        <input
                            value={tags}
                            onChange={(e) => setTags(e.target.value)}
                            className="w-full text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1" style={{backgroundColor:"#f3f9ec",border:"1px solid #b5da8b",color:"#16270c"}}
                            placeholder="church, wholesale, repeat-buyer"
                        />
                    </div>

                    <div>
                        <label className="text-xs font-semibold uppercase tracking-wider mb-1.5 block" style={{color:"#699a32"}}>
                            Notes
                        </label>
                        <textarea
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            rows={3}
                            className="w-full text-sm rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1" style={{backgroundColor:"#f3f9ec",border:"1px solid #b5da8b",color:"#16270c"}}
                            placeholder="Internal notes about this lead…"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-3 py-3 rounded-xl px-3" style={{backgroundColor:"#f3f9ec",border:"1px solid #e6f3d8"}}>
                        {[
                            { label: "Orders",      value: lead.total_orders },
                            { label: "Total spent", value: fmtCurrency(lead.total_spent) },
                            { label: "Lead score",  value: `${lead.lead_score}/100` },
                            { label: "Channels",    value: lead.channels.length },
                        ].map((row) => (
                            <div key={row.label}>
                                <div className="text-[10px]" style={{color:"#699a32"}}>{row.label}</div>
                                <div className="text-sm font-bold" style={{color:"#16270c"}}>{row.value}</div>
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
        <div className={`flex-1 overflow-hidden flex flex-col ${isMobile ? "pb-20" : ""}`} style={{backgroundColor:"#f3f9ec"}}>
            {/* Header */}
            <div className={`flex items-center justify-between bg-white ${isMobile ? "px-4 py-3" : "px-6 py-4"}`} style={{borderBottom:"1px solid #cee6b2"}}>
                <div>
                    <h1 className="text-xl font-bold tracking-tight" style={{color:"#16270c"}}>Leads Pipeline</h1>
                    <p className="text-sm mt-0.5" style={{color:"#699a32"}}>
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
                            className="h-8 pl-8 pr-3 text-xs rounded-lg focus:outline-none focus:ring-1" style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#16270c",fontSize:13}}
                            style={{ fontSize: 14 }}
                        />
                    </div>
                </div>
            </div>

            {/* Stage filter pills */}
            <div className="flex gap-2 px-6 py-3 bg-white overflow-x-auto scrollbar-none" style={{borderBottom:"1px solid #cee6b2"}}>
                <button
                    onClick={() => setFilterStage("all")}
                    className={`flex-shrink-0 h-7 px-3 rounded-lg text-xs font-medium border transition-all ${
                        filterStage === "all" ? "" : "bg-white border-stone-200 hover:border-stone-400"
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
                    <div className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin" style={{borderColor:"#589b31",borderTopColor:"transparent"}} />
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
                                            <div className="text-center py-8 text-xs" style={{color:"#9ccd65"}}>No leads</div>
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