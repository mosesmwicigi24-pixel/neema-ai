// CustomerSidebar.tsx
// CRM right-sidebar for the Conversations view.
// - Uses the same authHeaders() pattern as api.ts (window.__neema_token)
// - All edits PATCH /api/admin/customers/{wa_id} (crm.py)
// - onNameChange propagates name updates to parent conversations list
// - Open by default; can be minimised with the chevron toggle

import React, { useState, useEffect, useCallback } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import { timeAgo, fmtCurrency, fmtDate } from "@/lib/utils";
import type { Conversation, Order } from "@/types";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type LeadStage =
    | "new" | "contacted" | "qualified"
    | "proposal" | "negotiation" | "won" | "lost";

export interface CustomerChannel {
    channel: "whatsapp" | "messenger" | "instagram" | "email" | "sms";
    identifier: string;
    first_seen: string;
    last_seen: string;
    conversation_count: number;
}

export interface CustomerProfile {
    id: string;
    wa_id: string;
    name: string | null;
    name_confirmed: boolean;
    email: string | null;
    phone: string | null;
    location: string | null;
    age: number | null;
    tags: string[];
    lead_stage: LeadStage;
    lead_score: number;
    channels: CustomerChannel[];
    merged_ids: string[];
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
    /** Called after a successful name save so parent can update conv list */
    onNameChange?: (wa_id: string, newName: string) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const STAGE_META: Record<LeadStage, {
    label: string; color: string; bg: string; dot: string;
}> = {
    new:         { label: "New",         color: "text-stone-500",   bg: "bg-stone-100",  dot: "bg-stone-400"   },
    contacted:   { label: "Contacted",   color: "text-blue-600",    bg: "bg-blue-50",    dot: "bg-blue-500"    },
    qualified:   { label: "Qualified",   color: "text-violet-600",  bg: "bg-violet-50",  dot: "bg-violet-500"  },
    proposal:    { label: "Proposal",    color: "text-amber-600",   bg: "bg-amber-50",   dot: "bg-amber-500"   },
    negotiation: { label: "Negotiating", color: "text-orange-600",  bg: "bg-orange-50",  dot: "bg-orange-500"  },
    won:         { label: "Won ✓",       color: "text-emerald-700", bg: "bg-emerald-50", dot: "bg-emerald-500" },
    lost:        { label: "Lost",        color: "text-red-500",     bg: "bg-red-50",     dot: "bg-red-400"     },
};

const STAGE_ORDER: LeadStage[] = [
    "new", "contacted", "qualified", "proposal", "negotiation", "won", "lost",
];

// SVG channel icons
const CHANNEL_ICON_SVG: Record<string, { svg: string; bg: string }> = {
    whatsapp:  {
        bg: "#25D366",
        svg: '<path d="M16 2C8.28 2 2 8.28 2 16c0 2.44.64 4.73 1.76 6.72L2 30l7.44-1.72A13.92 13.92 0 0016 30c7.72 0 14-6.28 14-14S23.72 2 16 2zm0 25.6a11.56 11.56 0 01-5.88-1.6l-.42-.26-4.42 1.02.98-4.3-.28-.44A11.6 11.6 0 014.4 16C4.4 9.6 9.6 4.4 16 4.4S27.6 9.6 27.6 16 22.4 27.6 16 27.6zm6.36-8.68c-.34-.18-2.02-.98-2.34-1.1-.32-.1-.54-.18-.78.18-.22.34-.88 1.1-1.08 1.32-.2.24-.4.26-.74.08-.34-.18-1.44-.52-2.74-1.66a10.3 10.3 0 01-1.9-2.32c-.2-.34-.02-.52.14-.7.16-.16.34-.42.52-.62.16-.22.22-.36.34-.6.1-.24.06-.44-.02-.62-.08-.18-.78-1.86-1.06-2.54-.28-.68-.56-.58-.78-.6-.2-.02-.42-.02-.66-.02s-.6.08-.92.44c-.32.34-1.2 1.16-1.2 2.84 0 1.66 1.22 3.28 1.4 3.5.16.22 2.42 3.7 5.86 5.18.82.36 1.46.56 1.96.72.82.26 1.56.22 2.16.14.66-.1 2.02-.82 2.3-1.62.28-.78.28-1.46.2-1.62-.1-.14-.32-.22-.66-.4z"/>',
    },
    messenger: {
        bg: "#0099FF",
        svg: '<path d="M16 2C8.27 2 2 7.93 2 15.2c0 3.82 1.6 7.25 4.2 9.72V30l4.88-2.68A14.5 14.5 0 0016 28.4c7.73 0 14-5.93 14-13.2S23.73 2 16 2zm1.38 17.78l-3.56-3.8-6.96 3.8L13.2 12l3.66 3.8L23.72 12l-6.34 7.78z"/>',
    },
    instagram: {
        bg: "linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)",
        svg: '<path d="M16 5.8c3.36 0 3.76.01 5.08.07 1.22.06 1.9.27 2.34.44.59.23 1.01.5 1.45.94.44.44.71.86.94 1.45.17.44.38 1.12.44 2.34.06 1.32.07 1.72.07 5.08s-.01 3.76-.07 5.08c-.06 1.22-.27 1.9-.44 2.34-.23.59-.5 1.01-.94 1.45-.44.44-.86.71-1.45.94-.44.17-1.12.38-2.34.44-1.32.06-1.72.07-5.08.07s-3.76-.01-5.08-.07c-1.22-.06-1.9-.27-2.34-.44-.59-.23-1.01-.5-1.45-.94-.44-.44-.71-.86-.94-1.45-.17-.44-.38-1.12-.44-2.34C5.81 19.76 5.8 19.36 5.8 16s.01-3.76.07-5.08c.06-1.22.27-1.9.44-2.34.23-.59.5-1.01.94-1.45.44-.44.86-.71 1.45-.94.44-.17 1.12-.38 2.34-.44C12.24 5.81 12.64 5.8 16 5.8m0-2.3c-3.42 0-3.85.01-5.19.08-1.34.06-2.25.28-3.05.6-.82.32-1.52.75-2.21 1.44-.69.69-1.12 1.39-1.44 2.21-.32.8-.54 1.71-.6 3.05C3.51 12.15 3.5 12.58 3.5 16s.01 3.85.08 5.19c.06 1.34.28 2.25.6 3.05.32.82.75 1.52 1.44 2.21.69.69 1.39 1.12 2.21 1.44.8.32 1.71.54 3.05.6 1.34.06 1.77.08 5.19.08s3.85-.01 5.19-.08c1.34-.06 2.25-.28 3.05-.6.82-.32 1.52-.75 2.21-1.44.69-.69 1.12-1.39 1.44-2.21.32-.8.54-1.71.6-3.05.06-1.34.08-1.77.08-5.19s-.01-3.85-.08-5.19c-.06-1.34-.28-2.25-.6-3.05-.32-.82-.75-1.52-1.44-2.21-.69-.69-1.39-1.12-2.21-1.44-.8-.32-1.71-.54-3.05-.6C19.85 3.51 19.42 3.5 16 3.5zm0 6.19a6.31 6.31 0 100 12.62A6.31 6.31 0 0016 9.69zm0 10.4a4.09 4.09 0 110-8.18 4.09 4.09 0 010 8.18zm8.01-10.65a1.47 1.47 0 100 2.94 1.47 1.47 0 000-2.94z"/>',
    },
    email: {
        bg: "#4d66b3",
        svg: '<rect x="3" y="6" width="18" height="14" rx="2" stroke="white" strokeWidth="1.5" fill="none"/><path d="M3 9l9 6 9-6" stroke="white" strokeWidth="1.5"/>',
    },
    sms: {
        bg: "#2c4e18",
        svg: '<path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" stroke="white" strokeWidth="1.5" fill="none"/>',
    },
};

function ChannelBadge({ channel }: { channel: string }) {
    const meta = CHANNEL_ICON_SVG[channel] ?? CHANNEL_ICON_SVG.sms;
    return (
        <span
            className="inline-flex items-center justify-center w-5 h-5 rounded-full flex-shrink-0"
            style={{ background: meta.bg }}
            title={channel}
        >
            <svg viewBox="0 0 24 24" className="w-3 h-3" fill="white" dangerouslySetInnerHTML={{ __html: meta.svg }} />
        </span>
    );
}

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

// ─────────────────────────────────────────────────────────────────────────────
// Auth helper — mirrors api.ts authHeaders() pattern exactly
// ─────────────────────────────────────────────────────────────────────────────

async function crmHeaders(): Promise<HeadersInit> {
    let token: string | undefined;
    if (typeof window !== "undefined") {
        token = (window as any).__neema_token;
    }
    if (!token) {
        try {
            const { getSession } = await import("next-auth/react");
            const session = await getSession();
            token = (session as any)?.accessToken;
            if (token && typeof window !== "undefined") {
                (window as any).__neema_token = token;
            }
        } catch { /* not in browser context */ }
    }
    return {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
}

async function crmReq<T>(
    method: string,
    path: string,
    body?: unknown,
): Promise<T> {
    const headers = await crmHeaders();
    const res = await fetch(`${BASE}${path}`, {
        method,
        headers,
        credentials: "include",
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (!res.ok) {
        const err = await res.text();
        throw new Error(`${method} ${path} → ${res.status}: ${err}`);
    }
    if (res.status === 204) return undefined as T;
    return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Small sub-components
// ─────────────────────────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
    const color = score >= 70 ? "bg-emerald-500" : score >= 40 ? "bg-amber-500" : "bg-stone-300";
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{backgroundColor:"#e6f3d8"}}>
                <div className={`h-full rounded-full transition-all duration-500 ${color}`}
                    style={{ width: `${score}%` }} />
            </div>
            <span className="text-xs font-semibold text-stone-600 w-6 text-right">{score}</span>
        </div>
    );
}

function Section({ title, children, action }: {
    title: string; children: React.ReactNode; action?: React.ReactNode;
}) {
    return (
        <div className="mb-5">
            <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest" style={{color:"#699a32"}}>{title}</span>
                {action}
            </div>
            {children}
        </div>
    );
}

function EditableField({ label, value, onChange, placeholder, type = "text" }: {
    label: string; value: string; onChange: (v: string) => void;
    placeholder?: string; type?: string;
}) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft]     = useState(value);
    useEffect(() => { setDraft(value); }, [value]);

    return (
        <div className="group flex items-start gap-2 py-1.5 border-b last:border-0" style={{borderColor:"#e6f3d8"}}>
            <span className="text-[10px] w-16 flex-shrink-0 pt-0.5" style={{color:"#699a32"}}>{label}</span>
            {editing ? (
                <div className="flex-1 flex items-center gap-1">
                    <input type={type} value={draft} autoFocus
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter")  { onChange(draft); setEditing(false); }
                            if (e.key === "Escape") { setDraft(value); setEditing(false); }
                        }}
                        className="flex-1 text-xs rounded px-2 py-1 focus:outline-none focus:ring-1" style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#16270c"}}
                        placeholder={placeholder} />
                    <button onClick={() => { onChange(draft); setEditing(false); }}
                        className="text-[10px] text-emerald-600 font-semibold hover:text-emerald-700">✓</button>
                    <button onClick={() => { setDraft(value); setEditing(false); }}
                        className="text-[10px] text-stone-400 hover:text-stone-600">✕</button>
                </div>
            ) : (
                <button onClick={() => setEditing(true)}
                    className="flex-1 text-xs text-left transition-colors truncate" style={{color:"#16270c"}}>
                    {value || <span className="text-stone-300 italic">{placeholder || "—"}</span>}
                </button>
            )}
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export function CustomerSidebar({
    conversation,
    orders = [],
    onToast,
    onClose,
    onNameChange,
}: Props) {
    const [activeTab, setActiveTab] = useState<"profile" | "insights" | "activity">("profile");
    const [profile, setProfile]     = useState<CustomerProfile | null>(null);
    const [loading, setLoading]     = useState(true);
    const [saving, setSaving]       = useState(false);
    const [editNotes, setEditNotes] = useState(false);
    const [noteDraft, setNoteDraft] = useState("");
    const [showMerge, setShowMerge] = useState(false);
    const [mergeQuery, setMergeQuery] = useState("");
    const [tagInput, setTagInput]   = useState("");

    const loadProfile = useCallback(async () => {
        setLoading(true);
        try {
            const data = await crmReq<CustomerProfile>(
                "GET", `/admin/customers/${conversation.wa_id}`,
            );
            setProfile(data);
            setNoteDraft(data.notes || "");
        } catch {
            // Fallback: minimal profile from conversation data
            setProfile({
                id: conversation.wa_id, wa_id: conversation.wa_id,
                name: conversation.name ?? null, name_confirmed: false,
                email: null, phone: conversation.wa_id, location: null, age: null,
                tags: [], lead_stage: "new", lead_score: 0,
                channels: [{
                    channel: (conversation.channel as any) || "whatsapp",
                    identifier: conversation.wa_id,
                    first_seen: conversation.last_message_at,
                    last_seen: conversation.last_message_at,
                    conversation_count: 1,
                }],
                merged_ids: [], total_orders: 0, total_spent: 0,
                last_order_at: null,
                last_seen_at: conversation.last_message_at,
                first_seen_at: conversation.last_message_at,
                notes: null, created_at: conversation.last_message_at,
            });
        } finally {
            setLoading(false);
        }
    }, [conversation.wa_id, conversation.name, conversation.channel, conversation.last_message_at]);

    useEffect(() => { loadProfile(); }, [loadProfile]);

    const patch = useCallback(async (updates: Partial<CustomerProfile & { notes: string }>) => {
        if (!profile) return;
        setSaving(true);
        const prev = profile;
        setProfile({ ...profile, ...updates });
        try {
            await crmReq("PATCH", `/admin/customers/${profile.wa_id}`, updates);
            onToast("Saved");
            if ("name" in updates && updates.name) {
                onNameChange?.(profile.wa_id, updates.name);
            }
        } catch {
            onToast("Failed to save", "error");
            setProfile(prev);
        } finally {
            setSaving(false);
        }
    }, [profile, onToast, onNameChange]);

    const addTag = () => {
        if (!tagInput.trim() || !profile) return;
        patch({ tags: [...(profile.tags || []), tagInput.trim()] });
        setTagInput("");
    };
    const removeTag = (tag: string) => {
        if (!profile) return;
        patch({ tags: profile.tags.filter((t) => t !== tag) });
    };

    const customerOrders = orders.filter(
        (o) => o.wa_id === conversation.wa_id || o.contact_phone === conversation.wa_id
    );
    const totalSpent = customerOrders.reduce((s, o) => s + (o.total || o.subtotal || 0), 0);
    const lastOrder  = [...customerOrders].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )[0];

    const computedScore = Math.min(100, Math.round(
        Math.min(customerOrders.length * 15, 45) +
        (totalSpent > 10000 ? 30 : totalSpent > 3000 ? 15 : 0) +
        (profile?.email    ? 10 : 0) +
        (profile?.name     ? 10 : 0) +
        (profile?.location ?  5 : 0) +
        ((profile?.channels?.length ?? 0) > 1 ? 15 : 0)
    ));

    if (loading) {
        return (
            <div className="w-72 flex-shrink-0 flex items-center justify-center" style={{backgroundColor:"#f3f9ec",borderLeft:"1px solid #cee6b2"}}>
                <div className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin" style={{borderColor:"#589b31",borderTopColor:"transparent"}} />
            </div>
        );
    }

    if (!profile) return null;

    const stageMeta = STAGE_META[profile.lead_stage] ?? STAGE_META.new;

    return (
        <div className="w-72 flex-shrink-0 flex flex-col overflow-hidden" style={{ backgroundColor:"#ffffff", borderLeft:"1px solid #cee6b2" }}>

            {/* Header */}
            <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom:"1px solid #cee6b2" }}>
                <span className="text-xs font-bold uppercase tracking-widest" style={{color:"#427425"}}>Customer</span>
                <button onClick={onClose} title="Collapse sidebar"
                    className="text-stone-400 hover:text-stone-600 transition-colors">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                </button>
            </div>

            {/* Profile hero */}
            <div className="px-4 pt-4 pb-3" style={{ borderBottom:"1px solid #cee6b2" }}>
                <div className="flex items-start gap-3 mb-3">
                    <Avatar name={profile.name ?? profile.wa_id} size={44} />
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-bold truncate" style={{color:"#16270c"}}>
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
                            {saving && <span className="text-[10px] text-stone-400 animate-pulse">saving…</span>}
                        </div>
                    </div>
                </div>

                <div className="mb-2">
                    <div className="flex justify-between mb-1">
                        <span className="text-[10px] text-stone-400 font-medium">Lead Score</span>
                        <span className="text-[10px] text-stone-500">{computedScore}/100</span>
                    </div>
                    <ScoreBar score={computedScore} />
                </div>

                <div className="flex flex-wrap gap-1 mt-2">
                    {(profile.channels || []).map((ch) => (
                        <span key={ch.channel + ch.identifier}
                            title={`${ch.channel}: ${ch.identifier} · ${ch.conversation_count} conv`}
                            className="inline-flex items-center gap-0.5 text-[10px] rounded px-1.5 py-0.5 capitalize" style={{backgroundColor:"#e6f3d8",border:"1px solid #b5da8b",color:"#427425"}}>
                            <ChannelBadge channel={ch.channel} /> {ch.channel}
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
            <div className="grid grid-cols-3" style={{ borderBottom:"1px solid #cee6b2" }}>
                {[
                    { label: "Orders", value: customerOrders.length || profile.total_orders },
                    { label: "Spent",  value: fmtCurrency(totalSpent || profile.total_spent) },
                    { label: "Convs",  value: (profile.channels || []).reduce((s, c) => s + c.conversation_count, 0) || 1 },
                ].map((s) => (
                    <div key={s.label} className="px-3 py-2.5 text-center last:border-0" style={{ borderRight:"1px solid #cee6b2" }}>
                        <div className="text-sm font-bold" style={{color:"#16270c"}}>{s.value}</div>
                        <div className="text-[10px]" style={{color:"#699a32"}}>{s.label}</div>
                    </div>
                ))}
            </div>

            {/* Tabs */}
            <div className="flex" style={{borderBottom:"1px solid #cee6b2"}}>
                {(["profile", "insights", "activity"] as const).map((tab) => (
                    <button key={tab} onClick={() => setActiveTab(tab)}
                        className={`flex-1 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors border-b-2 ${
                            activeTab === tab ? "" : "border-transparent text-[#9ccd65]"
                        }`}
                        style={activeTab === tab ? { color:"#427425", borderColor:"#589b31" } : undefined}
                    >
                        {tab}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto px-4 py-4" style={{backgroundColor:"#f3f9ec"}}>

                {activeTab === "profile" && (
                    <>
                        <Section title="Contact Details">
                            <EditableField label="Name"     value={profile.name || ""}     onChange={(v) => patch({ name: v })}     placeholder="Full name" />
                            <EditableField label="Email"    value={profile.email || ""}    onChange={(v) => patch({ email: v })}    placeholder="email@example.com" type="email" />
                            <EditableField label="Phone"    value={profile.phone || ""}    onChange={(v) => patch({ phone: v })}    placeholder="+254..." />
                            <EditableField label="Location" value={profile.location || ""} onChange={(v) => patch({ location: v })} placeholder="City / Estate" />
                            <EditableField label="Age"      value={profile.age ? String(profile.age) : ""}
                                onChange={(v) => patch({ age: parseInt(v) || (null as any) })}
                                placeholder="e.g. 35" type="number" />
                        </Section>

                        <Section title="Lead Stage">
                            <div className="flex flex-wrap gap-1">
                                {STAGE_ORDER.map((stage) => {
                                    const m = STAGE_META[stage];
                                    const active = profile.lead_stage === stage;
                                    return (
                                        <button key={stage} onClick={() => patch({ lead_stage: stage })}
                                            className={`text-[10px] font-semibold px-2 py-1 rounded-lg border transition-all ${
                                                active ? `${m.bg} ${m.color} border-current` : "bg-white text-stone-400 border-stone-200 hover:border-stone-400"
                                            }`}>
                                            {m.label}
                                        </button>
                                    );
                                })}
                            </div>
                        </Section>

                        <Section title="Tags">
                            <div className="flex flex-wrap gap-1 mb-2">
                                {(profile.tags || []).map((tag) => (
                                    <span key={tag} className="inline-flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5" style={{backgroundColor:"#e6f3d8",color:"#427425"}}>
                                        {tag}
                                        <button onClick={() => removeTag(tag)}
                                            className="text-stone-400 hover:text-red-500 ml-0.5">×</button>
                                    </span>
                                ))}
                            </div>
                            <div className="flex gap-1">
                                <input value={tagInput} onChange={(e) => setTagInput(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addTag()}
                                    placeholder="Add tag…"
                                    className="flex-1 text-xs rounded px-2 py-1 focus:outline-none" style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#16270c"}} />
                                <button onClick={addTag}
                                    className="text-xs font-semibold px-2 py-1 rounded transition-colors" style={{backgroundColor:"#f0f9ec",color:"#589b31",border:"1px solid #b5da8b"}}>+</button>
                            </div>
                        </Section>

                        <Section title="Notes">
                            {editNotes ? (
                                <div>
                                    <textarea value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)}
                                        rows={4}
                                        className="w-full text-xs rounded-lg px-2.5 py-2 resize-none focus:outline-none" style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#16270c"}}
                                        placeholder="Internal notes about this customer…" />
                                    <div className="flex gap-2 mt-1.5">
                                        <button onClick={() => { patch({ notes: noteDraft }); setEditNotes(false); }}
                                            className="text-[10px] text-emerald-600 font-semibold">Save</button>
                                        <button onClick={() => { setNoteDraft(profile.notes || ""); setEditNotes(false); }}
                                            className="text-[10px] text-stone-400">Cancel</button>
                                    </div>
                                </div>
                            ) : (
                                <button onClick={() => setEditNotes(true)}
                                    className="w-full text-left text-xs rounded-lg px-2.5 py-2 transition-colors min-h-[40px]" style={{backgroundColor:"white",border:"1px solid #e6f3d8",color:"#16270c"}}>
                                    {profile.notes || <span className="text-stone-300 italic">Click to add notes…</span>}
                                </button>
                            )}
                        </Section>

                        <Section title="Cross-channel Identity"
                            action={
                                <button onClick={() => setShowMerge(!showMerge)}
                                    className="flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-lg transition-colors"
                                    style={showMerge
                                        ? { backgroundColor:"#e4e6b2", color:"#717425", border:"1px solid #cacd65" }
                                        : { backgroundColor:"#f0f9ec", color:"#589b31", border:"1px solid #b5da8b" }}>
                                    <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                                            d={showMerge ? "M6 18L18 6M6 6l12 12" : "M12 4v16m8-8H4"} />
                                    </svg>
                                    {showMerge ? "Cancel" : "Merge"}
                                </button>
                            }>
                            {(profile.channels || []).map((ch) => (
                                <div key={ch.channel + ch.identifier}
                                    className="flex items-center gap-2 py-1.5 border-b border-stone-50 last:border-0">
                                    <ChannelBadge channel={ch.channel} />
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
                                        Merged ({profile.merged_ids.length})
                                    </div>
                                    {profile.merged_ids.map((mid) => (
                                        <div key={mid} className="text-[10px] text-violet-600 font-mono">{mid}</div>
                                    ))}
                                </div>
                            )}
                            {showMerge && (
                                <div className="mt-3 rounded-xl border-2 border-dashed overflow-hidden"
                                    style={{ borderColor: "#bcc13e", backgroundColor: "#f8f9ec" }}>
                                    <div className="px-3 pt-3 pb-2">
                                        <div className="flex items-center gap-2 mb-2">
                                            <div className="w-7 h-7 rounded-lg flex items-center justify-center text-sm flex-shrink-0"
                                                style={{ backgroundColor: "#e4e6b2", color: "#717425" }}>⊕</div>
                                            <div>
                                                <div className="text-xs font-bold" style={{ color: "#717425" }}>Merge Profiles</div>
                                                <div className="text-[10px]" style={{ color: "#979a32" }}>Combine duplicate customer records</div>
                                            </div>
                                        </div>
                                        <p className="text-[10px] mb-2.5 leading-relaxed" style={{ color: "#717425" }}>
                                            Enter the phone / wa_id of the profile to merge <em>into this one</em>. Their orders and channels will be combined here.
                                        </p>
                                        <input value={mergeQuery} onChange={(e) => setMergeQuery(e.target.value)}
                                            placeholder="e.g. 254700123456"
                                            className="w-full text-xs rounded-lg px-2.5 py-2 mb-2.5 focus:outline-none focus:ring-2"
                                            style={{
                                                backgroundColor: "white",
                                                border: "1.5px solid #cacd65",
                                                color: "#16270c",
                                                fontSize: 12,
                                            }}
                                            onFocus={(e) => { (e.target as HTMLInputElement).style.borderColor = "#589b31"; }}
                                            onBlur={(e)  => { (e.target as HTMLInputElement).style.borderColor = "#cacd65"; }}
                                        />
                                        <div className="flex gap-1.5">
                                            <button
                                                onClick={async () => {
                                                    if (!mergeQuery.trim()) return;
                                                    try {
                                                        await crmReq("POST", `/admin/customers/${profile.wa_id}/merge`, {
                                                            merge_with: mergeQuery.trim(),
                                                        });
                                                        onToast("Profiles merged successfully");
                                                        setShowMerge(false);
                                                        setMergeQuery("");
                                                        loadProfile();
                                                    } catch {
                                                        onToast("Failed to merge profiles", "error");
                                                    }
                                                }}
                                                className="flex-1 text-[10px] font-bold py-1.5 rounded-lg text-white transition-colors"
                                                style={{ backgroundColor: "#589b31" }}
                                            >
                                                ⊕ Merge now
                                            </button>
                                            <button
                                                onClick={() => { setShowMerge(false); setMergeQuery(""); }}
                                                className="text-[10px] font-semibold px-3 py-1.5 rounded-lg border transition-colors"
                                                style={{ borderColor: "#cacd65", color: "#717425", backgroundColor: "white" }}
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </Section>
                    </>
                )}

                {activeTab === "insights" && (
                    <>
                        <Section title="Purchase Summary">
                            <div className="space-y-2">
                                {[
                                    { label: "Total orders",    value: customerOrders.length || profile.total_orders },
                                    { label: "Total spent",     value: fmtCurrency(totalSpent || profile.total_spent) },
                                    { label: "Avg order value", value: (customerOrders.length || profile.total_orders)
                                        ? fmtCurrency(Math.round((totalSpent || profile.total_spent) / (customerOrders.length || profile.total_orders)))
                                        : "—" },
                                    { label: "Last order",  value: lastOrder ? timeAgo(lastOrder.created_at) : profile.last_order_at ? timeAgo(profile.last_order_at) : "—" },
                                    { label: "Customer since", value: profile.first_seen_at ? fmtDate(profile.first_seen_at) : "—" },
                                ].map((row) => (
                                    <div key={row.label} className="flex items-center justify-between">
                                        <span className="text-xs" style={{color:"#699a32"}}>{row.label}</span>
                                        <span className="text-xs font-semibold" style={{color:"#16270c"}}>{row.value}</span>
                                    </div>
                                ))}
                            </div>
                        </Section>

                        {customerOrders.length > 0 && (
                            <Section title="Top Products">
                                {(() => {
                                    const itemMap: Record<string, { name: string; qty: number; total: number }> = {};
                                    customerOrders.forEach((o) => (o.items || []).forEach((i) => {
                                        if (!itemMap[i.name]) itemMap[i.name] = { name: i.name, qty: 0, total: 0 };
                                        itemMap[i.name].qty   += (i.qty || i.quantity || 1);
                                        itemMap[i.name].total += (i.total || 0);
                                    }));
                                    return Object.values(itemMap).sort((a, b) => b.total - a.total).slice(0, 4)
                                        .map((item) => (
                                            <div key={item.name}
                                                className="flex items-center justify-between py-1.5 border-b border-stone-50 last:border-0">
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

                        <Section title="Lead Score Breakdown">
                            {[
                                { label: "Orders",        pts: Math.min(customerOrders.length * 15, 45), max: 45 },
                                { label: "Spend level",   pts: totalSpent > 10000 ? 30 : totalSpent > 3000 ? 15 : 0, max: 30 },
                                { label: "Email known",   pts: profile.email    ? 10 : 0, max: 10 },
                                { label: "Name known",    pts: profile.name     ? 10 : 0, max: 10 },
                                { label: "Multi-channel", pts: (profile.channels?.length ?? 0) > 1 ? 15 : 0, max: 15 },
                            ].map((row) => (
                                <div key={row.label} className="mb-2">
                                    <div className="flex justify-between mb-0.5">
                                        <span className="text-[10px] text-stone-500">{row.label}</span>
                                        <span className="text-[10px] text-stone-600">{row.pts}/{row.max}</span>
                                    </div>
                                    <div className="h-1 bg-stone-100 rounded-full overflow-hidden">
                                        <div className="h-full bg-green-500 rounded-full"
                                            style={{ width: `${row.max ? (row.pts / row.max) * 100 : 0}%` }} />
                                    </div>
                                </div>
                            ))}
                        </Section>
                    </>
                )}

                {activeTab === "activity" && (
                    <>
                        <Section title="Recent Orders">
                            {customerOrders.length === 0 ? (
                                <p className="text-xs text-stone-400 text-center py-3">No orders yet</p>
                            ) : (
                                <div className="space-y-2">
                                    {customerOrders.slice(0, 5).map((o) => (
                                        <div key={o.id} className="p-2.5 rounded-lg" style={{backgroundColor:"white",border:"1px solid #e6f3d8"}}>
                                            <div className="flex items-center justify-between mb-1">
                                                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                                    o.status === "delivered" ? "bg-emerald-50 text-emerald-700" :
                                                    o.status === "confirmed" ? "bg-blue-50 text-blue-700" :
                                                    o.status === "cancelled" ? "bg-red-50 text-red-600" :
                                                    "bg-amber-50 text-amber-700"
                                                }`}>{o.status}</span>
                                                <span className="text-[10px] text-stone-400">{timeAgo(o.created_at)}</span>
                                            </div>
                                            <div className="text-xs font-semibold" style={{color:"#16270c"}}>{fmtCurrency(o.total || o.subtotal)}</div>
                                            <div className="text-[10px] mt-0.5 truncate" style={{color:"#699a32"}}>
                                                {(o.items || []).map((i) => i.name).join(", ") || "—"}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </Section>

                        <Section title="Channel History">
                            {(profile.channels || []).map((ch) => (
                                <div key={ch.channel + ch.identifier}
                                    className="flex items-start gap-2 py-2 border-b border-stone-50 last:border-0">
                                    <span className="text-base"><ChannelBadge channel={ch.channel} /></span>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs font-semibold capitalize" style={{color:"#16270c"}}>{ch.channel}</div>
                                        <div className="text-[10px] text-stone-400">
                                            {ch.conversation_count} conversation{ch.conversation_count !== 1 ? "s" : ""}
                                        </div>
                                        <div className="text-[10px] text-stone-400">
                                            First: {ch.first_seen ? fmtDate(ch.first_seen) : "—"} · Last: {ch.last_seen ? timeAgo(ch.last_seen) : "—"}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </Section>
                    </>
                )}
            </div>

            {/* Quick actions */}
            <div className="px-4 py-3 bg-white" style={{borderTop:"1px solid #cee6b2"}}>
                <div className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{color:"#699a32"}}>Quick Actions</div>
                <div className="flex flex-wrap gap-1.5">
                    <button onClick={() => patch({ lead_stage: "won" })}
                        className="flex-1 text-[10px] font-semibold py-1.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors">
                        ✓ Mark Won
                    </button>
                    <button onClick={() => patch({ lead_stage: "lost" })}
                        className="flex-1 text-[10px] font-semibold py-1.5 rounded-lg bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 transition-colors">
                        ✕ Mark Lost
                    </button>
                    <button onClick={() => {
                        const idx  = STAGE_ORDER.indexOf(profile.lead_stage);
                        const next = STAGE_ORDER[Math.min(idx + 1, STAGE_ORDER.indexOf("won"))];
                        if (next !== profile.lead_stage) patch({ lead_stage: next });
                    }}
                        className="w-full text-[10px] font-semibold py-1.5 rounded-lg transition-colors" style={{backgroundColor:"#f0f9ec",color:"#427425",border:"1px solid #b5da8b"}}>
                        → Advance Stage
                    </button>
                </div>
            </div>
        </div>
    );
}