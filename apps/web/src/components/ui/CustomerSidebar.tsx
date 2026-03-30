// CustomerSidebar.tsx
// CRM right-sidebar for the Conversations view.
// Shows customer profile, cross-channel identity, insights, lead stage, and actions.

import React, { useState, useEffect, useCallback } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import { timeAgo, fmtCurrency, fmtDate } from "@/lib/utils";
import type { Conversation, Order } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

export type LeadStage =
    | "new"
    | "contacted"
    | "qualified"
    | "proposal"
    | "negotiation"
    | "won"
    | "lost";

export interface CustomerChannel {
    channel: "whatsapp" | "messenger" | "instagram" | "email" | "sms";
    identifier: string;   // wa_id, page-scoped user id, email, etc.
    label?: string;
    first_seen: string;
    last_seen: string;
    conversation_count: number;
}

export interface CustomerProfile {
    id: string;
    wa_id: string;             // primary identifier
    name: string | null;
    name_confirmed: boolean;
    email: string | null;
    phone: string | null;
    location: string | null;
    age: number | null;
    tags: string[];
    lead_stage: LeadStage;
    lead_score: number;         // 0–100
    channels: CustomerChannel[];
    merged_ids: string[];       // other wa_ids merged into this profile
    total_orders: number;
    total_spent: number;
    last_order_at: string | null;
    last_seen_at: string | null;
    first_seen_at: string | null;
    notes: string | null;
    created_at: string;
}

interface Props {
    conversation: Conversation;
    orders?: Order[];
    onToast: (msg: string, type?: "success" | "error" | "warning") => void;
    onClose: () => void;
}

// ── Lead stage metadata ───────────────────────────────────────────────────────

const STAGE_META: Record<LeadStage, { label: string; color: string; bg: string; dot: string }> = {
    new:          { label: "New",          color: "text-stone-500",   bg: "bg-stone-100",   dot: "bg-stone-400"   },
    contacted:    { label: "Contacted",    color: "text-blue-600",    bg: "bg-blue-50",     dot: "bg-blue-500"    },
    qualified:    { label: "Qualified",    color: "text-violet-600",  bg: "bg-violet-50",   dot: "bg-violet-500"  },
    proposal:     { label: "Proposal",     color: "text-amber-600",   bg: "bg-amber-50",    dot: "bg-amber-500"   },
    negotiation:  { label: "Negotiating",  color: "text-orange-600",  bg: "bg-orange-50",   dot: "bg-orange-500"  },
    won:          { label: "Won ✓",        color: "text-emerald-700", bg: "bg-emerald-50",  dot: "bg-emerald-500" },
    lost:         { label: "Lost",         color: "text-red-500",     bg: "bg-red-50",      dot: "bg-red-400"     },
};

const STAGE_ORDER: LeadStage[] = [
    "new", "contacted", "qualified", "proposal", "negotiation", "won", "lost",
];

const CHANNEL_ICONS: Record<string, string> = {
    whatsapp:  "📱",
    messenger: "💙",
    instagram: "📸",
    email:     "📧",
    sms:       "💬",
};

// ── Score bar component ───────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
    const color =
        score >= 70 ? "bg-emerald-500" :
        score >= 40 ? "bg-amber-500" :
        "bg-stone-300";
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-stone-100 rounded-full overflow-hidden">
                <div
                    className={`h-full rounded-full transition-all duration-500 ${color}`}
                    style={{ width: `${score}%` }}
                />
            </div>
            <span className="text-xs font-semibold text-stone-600 w-6 text-right">{score}</span>
        </div>
    );
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children, action }: {
    title: string;
    children: React.ReactNode;
    action?: React.ReactNode;
}) {
    return (
        <div className="mb-5">
            <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-stone-400 uppercase tracking-widest">
                    {title}
                </span>
                {action}
            </div>
            {children}
        </div>
    );
}

// ── Editable field ────────────────────────────────────────────────────────────

function EditableField({
    label,
    value,
    onChange,
    placeholder,
    type = "text",
}: {
    label: string;
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
    type?: string;
}) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft]     = useState(value);

    useEffect(() => { setDraft(value); }, [value]);

    return (
        <div className="group flex items-start gap-2 py-1.5 border-b border-stone-50 last:border-0">
            <span className="text-[10px] text-stone-400 w-16 flex-shrink-0 pt-0.5">{label}</span>
            {editing ? (
                <div className="flex-1 flex items-center gap-1">
                    <input
                        type={type}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") { onChange(draft); setEditing(false); }
                            if (e.key === "Escape") { setDraft(value); setEditing(false); }
                        }}
                        autoFocus
                        className="flex-1 text-xs bg-stone-50 border border-stone-200 rounded px-2 py-1 text-stone-800 focus:outline-none focus:ring-1 focus:ring-green-600"
                        placeholder={placeholder}
                    />
                    <button onClick={() => { onChange(draft); setEditing(false); }}
                        className="text-[10px] text-emerald-600 font-semibold hover:text-emerald-700">✓</button>
                    <button onClick={() => { setDraft(value); setEditing(false); }}
                        className="text-[10px] text-stone-400 hover:text-stone-600">✕</button>
                </div>
            ) : (
                <button
                    onClick={() => setEditing(true)}
                    className="flex-1 text-xs text-stone-700 text-left hover:text-green-700 transition-colors truncate"
                >
                    {value || <span className="text-stone-300 italic">{placeholder || "—"}</span>}
                </button>
            )}
        </div>
    );
}

// ── Main component ────────────────────────────────────────────────────────────

export function CustomerSidebar({ conversation, orders = [], onToast, onClose }: Props) {
    const [activeTab, setActiveTab] = useState<"profile" | "insights" | "activity">("profile");
    const [profile, setProfile]     = useState<CustomerProfile | null>(null);
    const [loading, setLoading]     = useState(true);
    const [saving, setSaving]       = useState(false);
    const [editNotes, setEditNotes] = useState(false);
    const [noteDraft, setNoteDraft] = useState("");
    const [showMerge, setShowMerge] = useState(false);
    const [mergeQuery, setMergeQuery] = useState("");
    const [tagInput, setTagInput]   = useState("");

    // Load customer profile
    const loadProfile = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch(
                `/api/admin/customers/${conversation.wa_id}`,
                { headers: { Authorization: `Bearer ${(window as any).__neema_token}` } }
            );
            if (res.ok) {
                const data = await res.json();
                setProfile(data);
                setNoteDraft(data.notes || "");
            } else {
                // Build a minimal profile from conversation data
                setProfile({
                    id: conversation.wa_id,
                    wa_id: conversation.wa_id,
                    name: conversation.name ?? null,
                    name_confirmed: false,
                    email: null,
                    phone: conversation.wa_id,
                    location: null,
                    age: null,
                    tags: [],
                    lead_stage: "new",
                    lead_score: 0,
                    channels: [{
                        channel: (conversation.channel as any) || "whatsapp",
                        identifier: conversation.wa_id,
                        first_seen: conversation.last_message_at,
                        last_seen: conversation.last_message_at,
                        conversation_count: 1,
                    }],
                    merged_ids: [],
                    total_orders: 0,
                    total_spent: 0,
                    last_order_at: null,
                    last_seen_at: conversation.last_message_at,
                    first_seen_at: conversation.last_message_at,
                    notes: null,
                    created_at: conversation.last_message_at,
                });
            }
        } catch {
            setProfile(null);
        } finally {
            setLoading(false);
        }
    }, [conversation.wa_id]);

    useEffect(() => { loadProfile(); }, [loadProfile]);

    // Patch profile field
    const patch = async (updates: Partial<CustomerProfile>) => {
        if (!profile) return;
        setSaving(true);
        const optimistic = { ...profile, ...updates };
        setProfile(optimistic);
        try {
            await fetch(`/api/admin/customers/${profile.wa_id}`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${(window as any).__neema_token}`,
                },
                body: JSON.stringify(updates),
            });
            onToast("Saved");
        } catch {
            onToast("Failed to save", "error");
            setProfile(profile); // rollback
        } finally {
            setSaving(false);
        }
    };

    const addTag = () => {
        if (!tagInput.trim() || !profile) return;
        const tags = [...(profile.tags || []), tagInput.trim()];
        patch({ tags });
        setTagInput("");
    };

    const removeTag = (tag: string) => {
        if (!profile) return;
        patch({ tags: profile.tags.filter((t) => t !== tag) });
    };

    // Compute insights from orders
    const customerOrders = orders.filter(
        (o) => o.wa_id === conversation.wa_id || o.contact_phone === conversation.wa_id
    );
    const totalSpent = customerOrders.reduce((s, o) => s + (o.total || o.subtotal || 0), 0);
    const lastOrder  = customerOrders.sort((a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )[0];

    // Lead score computation (simple heuristic)
    const computedScore = Math.min(100, Math.round(
        (customerOrders.length * 15) +
        (totalSpent > 10000 ? 30 : totalSpent > 3000 ? 15 : 0) +
        (profile?.email ? 10 : 0) +
        (profile?.name ? 10 : 0) +
        (profile?.location ? 5 : 0) +
        (profile?.channels && profile.channels.length > 1 ? 15 : 0)
    ));

    if (loading) {
        return (
            <div className="w-72 flex-shrink-0 border-l border-stone-100 bg-white flex items-center justify-center">
                <div className="w-5 h-5 border-2 border-green-700 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (!profile) return null;

    const stageMeta = STAGE_META[profile.lead_stage] || STAGE_META.new;

    return (
        <div className="w-72 flex-shrink-0 border-l border-stone-100 bg-white flex flex-col overflow-hidden">
            {/* Header */}
            <div className="px-4 py-3 border-b border-stone-100 flex items-center justify-between bg-white">
                <span className="text-xs font-bold text-stone-700 uppercase tracking-widest">
                    Customer
                </span>
                <button
                    onClick={onClose}
                    className="text-stone-400 hover:text-stone-600 transition-colors"
                    title="Close panel"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                </button>
            </div>

            {/* Profile hero */}
            <div className="px-4 pt-4 pb-3 border-b border-stone-100">
                <div className="flex items-start gap-3 mb-3">
                    <Avatar name={profile.name ?? profile.wa_id} size={44} />
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-bold text-stone-800 truncate">
                            {profile.name || <span className="text-stone-400 italic font-normal">Unknown</span>}
                            {profile.name_confirmed && (
                                <span className="ml-1 text-[9px] text-emerald-600 font-bold">✓</span>
                            )}
                        </div>
                        <div className="text-xs text-stone-400 font-mono">+{profile.wa_id}</div>
                        <div className="flex items-center gap-1.5 mt-1.5">
                            <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${stageMeta.bg} ${stageMeta.color}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${stageMeta.dot}`} />
                                {stageMeta.label}
                            </span>
                            {saving && (
                                <span className="text-[10px] text-stone-400">saving…</span>
                            )}
                        </div>
                    </div>
                </div>

                {/* Lead score */}
                <div className="mb-2">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-stone-400 font-medium">Lead Score</span>
                        <span className="text-[10px] text-stone-500">{computedScore}/100</span>
                    </div>
                    <ScoreBar score={computedScore} />
                </div>

                {/* Channels */}
                <div className="flex flex-wrap gap-1 mt-2">
                    {profile.channels.map((ch) => (
                        <span
                            key={ch.channel + ch.identifier}
                            className="inline-flex items-center gap-0.5 text-[10px] bg-stone-50 border border-stone-200 rounded px-1.5 py-0.5 text-stone-600"
                            title={`${ch.channel}: ${ch.identifier} · ${ch.conversation_count} conv`}
                        >
                            {CHANNEL_ICONS[ch.channel] || "🔗"} {ch.channel}
                        </span>
                    ))}
                    {profile.merged_ids.length > 0 && (
                        <span className="text-[10px] text-violet-600 font-medium">
                            +{profile.merged_ids.length} merged
                        </span>
                    )}
                </div>
            </div>

            {/* Quick stats */}
            <div className="grid grid-cols-3 border-b border-stone-100">
                {[
                    { label: "Orders", value: customerOrders.length },
                    { label: "Spent",  value: fmtCurrency(totalSpent) },
                    { label: "Convs",  value: profile.channels.reduce((s, c) => s + c.conversation_count, 0) },
                ].map((stat) => (
                    <div key={stat.label} className="px-3 py-2.5 text-center border-r border-stone-100 last:border-0">
                        <div className="text-sm font-bold text-stone-800">{stat.value}</div>
                        <div className="text-[10px] text-stone-400">{stat.label}</div>
                    </div>
                ))}
            </div>

            {/* Tabs */}
            <div className="flex border-b border-stone-100">
                {(["profile", "insights", "activity"] as const).map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`flex-1 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
                            activeTab === tab
                                ? "text-green-700 border-b-2 border-green-700"
                                : "text-stone-400 hover:text-stone-600"
                        }`}
                    >
                        {tab}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">

                {/* ── PROFILE TAB ──────────────────────────────── */}
                {activeTab === "profile" && (
                    <>
                        <Section title="Contact Details">
                            <EditableField label="Name"     value={profile.name     || ""} onChange={(v) => patch({ name: v })}     placeholder="Full name" />
                            <EditableField label="Email"    value={profile.email    || ""} onChange={(v) => patch({ email: v })}    placeholder="email@example.com" type="email" />
                            <EditableField label="Phone"    value={profile.phone    || ""} onChange={(v) => patch({ phone: v })}    placeholder="+254..." />
                            <EditableField label="Location" value={profile.location || ""} onChange={(v) => patch({ location: v })} placeholder="City / Estate" />
                            <EditableField label="Age"      value={profile.age ? String(profile.age) : ""} onChange={(v) => patch({ age: parseInt(v) || null })} placeholder="e.g. 35" type="number" />
                        </Section>

                        <Section title="Lead Stage">
                            <div className="flex flex-wrap gap-1">
                                {STAGE_ORDER.map((stage) => {
                                    const m = STAGE_META[stage];
                                    const active = profile.lead_stage === stage;
                                    return (
                                        <button
                                            key={stage}
                                            onClick={() => patch({ lead_stage: stage })}
                                            className={`text-[10px] font-semibold px-2 py-1 rounded-lg border transition-all ${
                                                active
                                                    ? `${m.bg} ${m.color} border-current`
                                                    : "bg-white text-stone-400 border-stone-200 hover:border-stone-400"
                                            }`}
                                        >
                                            {m.label}
                                        </button>
                                    );
                                })}
                            </div>
                        </Section>

                        <Section title="Tags">
                            <div className="flex flex-wrap gap-1 mb-2">
                                {profile.tags.map((tag) => (
                                    <span
                                        key={tag}
                                        className="inline-flex items-center gap-1 text-[10px] bg-stone-100 text-stone-700 rounded px-1.5 py-0.5"
                                    >
                                        {tag}
                                        <button
                                            onClick={() => removeTag(tag)}
                                            className="text-stone-400 hover:text-red-500 ml-0.5"
                                        >×</button>
                                    </span>
                                ))}
                            </div>
                            <div className="flex gap-1">
                                <input
                                    value={tagInput}
                                    onChange={(e) => setTagInput(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addTag()}
                                    placeholder="Add tag…"
                                    className="flex-1 text-xs bg-stone-50 border border-stone-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-green-600 text-stone-700"
                                />
                                <button
                                    onClick={addTag}
                                    className="text-xs text-green-700 font-semibold px-2 py-1 bg-green-50 border border-green-200 rounded hover:bg-green-100"
                                >+</button>
                            </div>
                        </Section>

                        <Section title="Notes">
                            {editNotes ? (
                                <div>
                                    <textarea
                                        value={noteDraft}
                                        onChange={(e) => setNoteDraft(e.target.value)}
                                        rows={4}
                                        className="w-full text-xs bg-stone-50 border border-stone-200 rounded-lg px-2.5 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-green-600 text-stone-700"
                                        placeholder="Internal notes about this customer…"
                                    />
                                    <div className="flex gap-2 mt-1.5">
                                        <button
                                            onClick={() => { patch({ notes: noteDraft }); setEditNotes(false); }}
                                            className="text-[10px] text-emerald-600 font-semibold"
                                        >Save</button>
                                        <button
                                            onClick={() => { setNoteDraft(profile.notes || ""); setEditNotes(false); }}
                                            className="text-[10px] text-stone-400"
                                        >Cancel</button>
                                    </div>
                                </div>
                            ) : (
                                <button
                                    onClick={() => setEditNotes(true)}
                                    className="w-full text-left text-xs text-stone-600 bg-stone-50 rounded-lg px-2.5 py-2 hover:bg-stone-100 transition-colors min-h-[40px]"
                                >
                                    {profile.notes || <span className="text-stone-300 italic">Click to add notes…</span>}
                                </button>
                            )}
                        </Section>

                        <Section
                            title="Cross-channel Identity"
                            action={
                                <button
                                    onClick={() => setShowMerge(!showMerge)}
                                    className="text-[10px] text-green-700 font-semibold hover:text-green-600"
                                >
                                    {showMerge ? "Cancel" : "+ Merge"}
                                </button>
                            }
                        >
                            {profile.channels.map((ch) => (
                                <div key={ch.channel + ch.identifier} className="flex items-center gap-2 py-1.5 border-b border-stone-50 last:border-0">
                                    <span className="text-sm">{CHANNEL_ICONS[ch.channel] || "🔗"}</span>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[10px] font-semibold text-stone-700 capitalize">{ch.channel}</div>
                                        <div className="text-[10px] text-stone-400 truncate font-mono">{ch.identifier}</div>
                                    </div>
                                    <div className="text-[10px] text-stone-400 text-right flex-shrink-0">
                                        <div>{ch.conversation_count} conv</div>
                                        <div>{timeAgo(ch.last_seen)}</div>
                                    </div>
                                </div>
                            ))}
                            {profile.merged_ids.length > 0 && (
                                <div className="mt-2 p-2 bg-violet-50 rounded-lg border border-violet-100">
                                    <div className="text-[10px] font-semibold text-violet-700 mb-1">
                                        Merged profiles ({profile.merged_ids.length})
                                    </div>
                                    {profile.merged_ids.map((mid) => (
                                        <div key={mid} className="text-[10px] text-violet-600 font-mono">{mid}</div>
                                    ))}
                                </div>
                            )}
                            {showMerge && (
                                <div className="mt-2 p-2.5 bg-amber-50 rounded-lg border border-amber-200">
                                    <div className="text-[10px] font-semibold text-amber-700 mb-1.5">
                                        Merge with another profile
                                    </div>
                                    <input
                                        value={mergeQuery}
                                        onChange={(e) => setMergeQuery(e.target.value)}
                                        placeholder="Phone / wa_id to merge…"
                                        className="w-full text-xs bg-white border border-amber-200 rounded px-2 py-1 mb-2 focus:outline-none focus:ring-1 focus:ring-amber-400 text-stone-700"
                                    />
                                    <Btn
                                        small
                                        variant="primary"
                                        onClick={async () => {
                                            if (!mergeQuery.trim()) return;
                                            try {
                                                await fetch(`/api/admin/customers/${profile.wa_id}/merge`, {
                                                    method: "POST",
                                                    headers: {
                                                        "Content-Type": "application/json",
                                                        Authorization: `Bearer ${(window as any).__neema_token}`,
                                                    },
                                                    body: JSON.stringify({ merge_with: mergeQuery.trim() }),
                                                });
                                                onToast("Profiles merged");
                                                setShowMerge(false);
                                                setMergeQuery("");
                                                loadProfile();
                                            } catch {
                                                onToast("Failed to merge", "error");
                                            }
                                        }}
                                    >
                                        Merge
                                    </Btn>
                                </div>
                            )}
                        </Section>
                    </>
                )}

                {/* ── INSIGHTS TAB ─────────────────────────────── */}
                {activeTab === "insights" && (
                    <>
                        <Section title="Purchase Summary">
                            <div className="space-y-2">
                                {[
                                    { label: "Total orders",    value: customerOrders.length },
                                    { label: "Total spent",     value: fmtCurrency(totalSpent) },
                                    { label: "Avg order value", value: customerOrders.length ? fmtCurrency(Math.round(totalSpent / customerOrders.length)) : "—" },
                                    { label: "Last order",      value: lastOrder ? timeAgo(lastOrder.created_at) : "—" },
                                    { label: "Customer since",  value: profile.first_seen_at ? fmtDate(profile.first_seen_at) : "—" },
                                ].map((row) => (
                                    <div key={row.label} className="flex items-center justify-between">
                                        <span className="text-xs text-stone-500">{row.label}</span>
                                        <span className="text-xs font-semibold text-stone-800">{row.value}</span>
                                    </div>
                                ))}
                            </div>
                        </Section>

                        {customerOrders.length > 0 && (
                            <Section title="Top Products">
                                {(() => {
                                    // Aggregate items across orders
                                    const itemMap: Record<string, { name: string; qty: number; total: number }> = {};
                                    customerOrders.forEach((o) => {
                                        (o.items || []).forEach((i) => {
                                            const key = i.name;
                                            if (!itemMap[key]) itemMap[key] = { name: i.name, qty: 0, total: 0 };
                                            itemMap[key].qty   += (i.qty || i.quantity || 1);
                                            itemMap[key].total += (i.total || 0);
                                        });
                                    });
                                    return Object.values(itemMap)
                                        .sort((a, b) => b.total - a.total)
                                        .slice(0, 4)
                                        .map((item) => (
                                            <div key={item.name} className="flex items-center justify-between py-1.5 border-b border-stone-50 last:border-0">
                                                <span className="text-xs text-stone-600 truncate flex-1 mr-2">{item.name}</span>
                                                <div className="text-right flex-shrink-0">
                                                    <div className="text-xs font-semibold text-stone-800">{fmtCurrency(item.total)}</div>
                                                    <div className="text-[10px] text-stone-400">×{item.qty}</div>
                                                </div>
                                            </div>
                                        ));
                                })()}
                            </Section>
                        )}

                        <Section title="Engagement">
                            <div className="space-y-2">
                                {[
                                    { label: "Channels used",    value: profile.channels.length },
                                    { label: "Last seen",        value: profile.last_seen_at ? timeAgo(profile.last_seen_at) : "—" },
                                    { label: "Lead score",       value: `${computedScore}/100` },
                                    { label: "Stage",            value: STAGE_META[profile.lead_stage]?.label || "—" },
                                ].map((row) => (
                                    <div key={row.label} className="flex items-center justify-between">
                                        <span className="text-xs text-stone-500">{row.label}</span>
                                        <span className="text-xs font-semibold text-stone-800">{row.value}</span>
                                    </div>
                                ))}
                            </div>
                        </Section>

                        <Section title="Lead Score Breakdown">
                            <div className="space-y-1.5">
                                {[
                                    { label: "Has orders",        pts: customerOrders.length * 15, max: 45 },
                                    { label: "Spend level",       pts: totalSpent > 10000 ? 30 : totalSpent > 3000 ? 15 : 0, max: 30 },
                                    { label: "Email known",       pts: profile.email ? 10 : 0, max: 10 },
                                    { label: "Name confirmed",    pts: profile.name ? 10 : 0, max: 10 },
                                    { label: "Multi-channel",     pts: profile.channels.length > 1 ? 15 : 0, max: 15 },
                                ].map((row) => (
                                    <div key={row.label}>
                                        <div className="flex justify-between mb-0.5">
                                            <span className="text-[10px] text-stone-500">{row.label}</span>
                                            <span className="text-[10px] text-stone-600">{row.pts}/{row.max}</span>
                                        </div>
                                        <div className="h-1 bg-stone-100 rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-green-500 rounded-full"
                                                style={{ width: `${(row.pts / row.max) * 100}%` }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </Section>
                    </>
                )}

                {/* ── ACTIVITY TAB ─────────────────────────────── */}
                {activeTab === "activity" && (
                    <>
                        <Section title="Recent Orders">
                            {customerOrders.length === 0 ? (
                                <p className="text-xs text-stone-400 text-center py-3">No orders yet</p>
                            ) : (
                                <div className="space-y-2">
                                    {customerOrders.slice(0, 5).map((o) => (
                                        <div key={o.id} className="p-2.5 bg-stone-50 rounded-lg border border-stone-100">
                                            <div className="flex items-center justify-between mb-1">
                                                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                                    o.status === "delivered" ? "bg-emerald-50 text-emerald-700" :
                                                    o.status === "confirmed" ? "bg-blue-50 text-blue-700" :
                                                    o.status === "cancelled" ? "bg-red-50 text-red-600" :
                                                    "bg-amber-50 text-amber-700"
                                                }`}>
                                                    {o.status}
                                                </span>
                                                <span className="text-[10px] text-stone-400">{timeAgo(o.created_at)}</span>
                                            </div>
                                            <div className="text-xs font-semibold text-stone-800">{fmtCurrency(o.total || o.subtotal)}</div>
                                            <div className="text-[10px] text-stone-500 mt-0.5 truncate">
                                                {(o.items || []).map((i) => i.name).join(", ") || "—"}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </Section>

                        <Section title="Conversation History">
                            {profile.channels.map((ch) => (
                                <div key={ch.channel + ch.identifier} className="flex items-start gap-2 py-2 border-b border-stone-50 last:border-0">
                                    <span className="text-base">{CHANNEL_ICONS[ch.channel]}</span>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs font-semibold text-stone-700 capitalize">{ch.channel}</div>
                                        <div className="text-[10px] text-stone-400">
                                            {ch.conversation_count} conversation{ch.conversation_count !== 1 ? "s" : ""}
                                        </div>
                                        <div className="text-[10px] text-stone-400">
                                            First: {fmtDate(ch.first_seen)} · Last: {timeAgo(ch.last_seen)}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </Section>
                    </>
                )}
            </div>

            {/* Quick actions footer */}
            <div className="px-4 py-3 border-t border-stone-100 bg-white">
                <div className="text-[10px] font-bold text-stone-400 uppercase tracking-widest mb-2">Actions</div>
                <div className="flex flex-wrap gap-1.5">
                    <button
                        onClick={() => patch({ lead_stage: "won" })}
                        className="flex-1 text-[10px] font-semibold py-1.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors"
                    >
                        ✓ Mark Won
                    </button>
                    <button
                        onClick={() => patch({ lead_stage: "lost" })}
                        className="flex-1 text-[10px] font-semibold py-1.5 rounded-lg bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 transition-colors"
                    >
                        ✕ Mark Lost
                    </button>
                    <button
                        onClick={() => {
                            const stage = STAGE_ORDER[Math.min(STAGE_ORDER.indexOf(profile.lead_stage) + 1, STAGE_ORDER.indexOf("won"))];
                            patch({ lead_stage: stage });
                        }}
                        className="w-full text-[10px] font-semibold py-1.5 rounded-lg bg-stone-50 text-stone-700 border border-stone-200 hover:bg-stone-100 transition-colors"
                    >
                        → Advance Stage
                    </button>
                </div>
            </div>
        </div>
    );
}