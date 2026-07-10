// CustomerSidebar.tsx
// CRM right-sidebar for the Conversations view.
// - Uses the same authHeaders() pattern as api.ts (window.__neema_token)
// - All edits PATCH /api/admin/customers/{wa_id} (crm.py)
// - onNameChange propagates name updates to parent conversations list
// - Open by default; can be minimised with the chevron toggle

import React, { useState, useEffect, useCallback } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import {
    timeAgo,
    fmtCurrency,
    fmtDate,
    formatPhone,
    displayName,
} from "@/lib/utils";
import type { Conversation, Order } from "@/types";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

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
    identifier: string;
    first_seen: string;
    last_seen: string;
    conversation_count: number;
}

// An order as rendered in the panel — hub-sourced (full history across POS,
// web and WhatsApp) or, as a fallback, a local WhatsApp order_event.
export interface PanelOrder {
    id: string;
    order_number?: string | null;
    status?: string | null;
    payment_status?: string | null;
    total?: number | null;
    subtotal?: number | null;
    currency_code?: string | null;
    created_at: string;
    items?: { name: string; qty?: number; quantity?: number; total?: number }[];
    source?: "hub" | "whatsapp";
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
    lead_stage_source?: "auto" | "manual" | null;
    suggested_lead_stage?: LeadStage;
    lead_source?: string | null;
    orders?: PanelOrder[];
    orders_source?: "hub" | "whatsapp";
    hub_linked?: boolean;
    hub_customer_id?: number | null;
    hub_customer_name?: string | null;
    lead_score: number;
    channels: CustomerChannel[];
    merged_ids: string[];
    // Identity spine (real cross-channel data from the backend).
    person_id?: string | null;
    linked_identities?: {
        channel: string;
        external_id: string;
        display_name?: string | null;
        source?: string | null;
        confidence?: string | null;
    }[];
    total_orders: number;
    total_spent: number;
    avg_order_value?: number;
    tier?: "prospect" | "new" | "regular" | "loyal" | "vip" | "at_risk";
    tier_label?: string;
    buying_rhythm?: {
        days_since_last: number | null;
        avg_interval_days: number | null;
        cadence_label: string | null;
        overdue: boolean;
    };
    last_order_at: string | null;
    last_seen_at: string | null;
    first_seen_at: string | null;
    notes: string | null;
    created_at: string;
    country_iso: string | null;
    country: string | null;
    flag_url: string | null;
}

interface ProductionEnquiry {
    id: string;
    product_name: string | null;
    measurements: Record<string, string>;
    notes: string | null;
    location: string | null;
    status: "new" | "pushed" | "declined";
    hub_order_number: string | null;
    pushable: boolean;
}

interface Props {
    conversation: Conversation;
    orders?: Order[];
    onToast: (msg: string, type?: "success" | "error" | "warning") => void;
    onClose: () => void;
    /** Called after a successful name save so parent can update conv list */
    onNameChange?: (wa_id: string, newName: string) => void;
    /** Open this person's conversation on another channel (click a linked identity). */
    onOpenIdentity?: (channel: string, externalId: string) => void;
    /** Override root container width — pass "w-full" when used inside mobile drawer */
    className?: string;
    /** Hide the built-in "Customer" header bar — useful when a parent drawer provides its own header */
    hideHeader?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const STAGE_META: Record<
    LeadStage,
    {
        label: string;
        color: string;
        bg: string;
        dot: string;
    }
> = {
    new: {
        label: "New",
        color: "text-stone-500",
        bg: "bg-stone-100",
        dot: "bg-stone-400",
    },
    contacted: {
        label: "Contacted",
        color: "text-blue-600",
        bg: "bg-blue-50",
        dot: "bg-blue-500",
    },
    qualified: {
        label: "Qualified",
        color: "text-violet-600",
        bg: "bg-violet-50",
        dot: "bg-violet-500",
    },
    proposal: {
        label: "Proposal",
        color: "text-amber-600",
        bg: "bg-amber-50",
        dot: "bg-amber-500",
    },
    negotiation: {
        label: "Negotiating",
        color: "text-orange-600",
        bg: "bg-orange-50",
        dot: "bg-orange-500",
    },
    won: {
        label: "Won ✓",
        color: "text-emerald-700",
        bg: "bg-emerald-50",
        dot: "bg-emerald-500",
    },
    lost: {
        label: "Lost",
        color: "text-red-500",
        bg: "bg-red-50",
        dot: "bg-red-400",
    },
};

// Full English country name from an ISO-3166 alpha-2 code (BW -> Botswana).
// Uses the platform Intl.DisplayNames; prefers an explicit override (e.g. a
// user-entered country) and falls back to the raw code if unavailable.
const REGION_DISPLAY =
    typeof Intl !== "undefined" && "DisplayNames" in Intl
        ? new Intl.DisplayNames(["en"], { type: "region" })
        : null;
function countryFullName(
    iso: string | null | undefined,
    override?: string | null,
): string {
    const o = override?.trim();
    if (o) return o;
    if (!iso) return "";
    try {
        return REGION_DISPLAY?.of(iso.toUpperCase()) ?? iso.toUpperCase();
    } catch {
        return iso.toUpperCase();
    }
}

// Customer segment badge — a quick read of who you're talking to.
const TIER_META: Record<string, { label: string; cls: string; title: string }> = {
    vip:      { label: "VIP",      cls: "bg-amber-100 text-amber-800 border-amber-300",   title: "Top spender / very frequent buyer" },
    loyal:    { label: "Loyal",    cls: "bg-emerald-100 text-emerald-700 border-emerald-300", title: "Repeat customer" },
    regular:  { label: "Regular",  cls: "bg-sky-100 text-sky-700 border-sky-300",         title: "A few orders" },
    new:      { label: "New",      cls: "bg-stone-100 text-stone-600 border-stone-300",   title: "First order" },
    prospect: { label: "Prospect", cls: "bg-stone-50 text-stone-400 border-stone-200",    title: "No orders yet" },
    at_risk:  { label: "At risk",  cls: "bg-red-100 text-red-700 border-red-300",         title: "Good customer who's gone quiet — worth a nudge" },
};

// Where a lead first found us (captured by the AI or set by an operator).
const SOURCE_META: Record<string, { label: string; icon: string }> = {
    facebook:  { label: "Facebook",  icon: "📘" },
    instagram: { label: "Instagram", icon: "📸" },
    tiktok:    { label: "TikTok",    icon: "🎵" },
    youtube:   { label: "YouTube",   icon: "▶️" },
    whatsapp:  { label: "WhatsApp",  icon: "💬" },
    referral:  { label: "Referral",  icon: "🤝" },
    walk_in:   { label: "Walk-in",   icon: "🚶" },
    website:   { label: "Website",   icon: "🌐" },
    google:    { label: "Google",    icon: "🔍" },
    other:     { label: "Other",     icon: "•" },
};

const STAGE_ORDER: LeadStage[] = [
    "new",
    "contacted",
    "qualified",
    "proposal",
    "negotiation",
    "won",
    "lost",
];

// ── Lead-pipeline stepper ────────────────────────────────────────────────────
// Horizontal gold stepper matched to the reference design. Displays the linear
// path New → Contacted → Qualified → Proposal → Won, with Lost as a faded
// terminal branch. (Negotiating stays a valid data stage; it maps onto Proposal
// for progress purposes — see stepState below.)
const PIPELINE_STAGES: LeadStage[] = [
    "new",
    "contacted",
    "qualified",
    "proposal",
    "won",
    "lost",
];
// Forward progression used to decide which nodes are already completed.
const PIPELINE_FORWARD: LeadStage[] = [
    "new",
    "contacted",
    "qualified",
    "proposal",
    "negotiation",
    "won",
];
// Goldenrod palette sampled from the reference photo.
const PIPE_GOLD = "#c89b3c"; // completed node outline/check, connectors, labels
const PIPE_GOLD_SOLID = "#a97c14"; // current (active) filled node + its label
const PIPE_IDLE = "#e7e5e4"; // not-yet-reached connector / node border
const PIPE_IDLE_TEXT = "#a8a29e"; // not-yet-reached label
const PIPE_LOST = "#f4cccc"; // Lost terminal border + connector (faded pink)
const PIPE_LOST_ICON = "#efa3a3"; // Lost ✕ icon
const PIPE_LOST_TEXT = "#e08a8a"; // Lost label

// Clean labels for the stepper (STAGE_META.won is "Won ✓" — drop the glyph
// here since the node circle already shows a checkmark).
const PIPE_LABEL: Record<LeadStage, string> = {
    new: "New",
    contacted: "Contacted",
    qualified: "Qualified",
    proposal: "Proposal",
    negotiation: "Negotiating",
    won: "Won",
    lost: "Lost",
};

type StepState = "active" | "done" | "future";
function stepState(stage: LeadStage, active: LeadStage): StepState {
    if (stage === active) return "active";
    if (stage === "lost") return "future"; // Lost is only ever active when current
    if (active === "lost") {
        // Customer is lost: everything up to Proposal is done, Won is skipped.
        return stage === "won" ? "future" : "done";
    }
    const a = PIPELINE_FORWARD.indexOf(active);
    const s = PIPELINE_FORWARD.indexOf(stage);
    return s > -1 && a > -1 && s < a ? "done" : "future";
}

// Channel label + brand colour for the cross-channel identities list.
const CH_META: Record<string, { label: string; color: string }> = {
    whatsapp: { label: "WhatsApp", color: "#25D366" },
    messenger: { label: "Messenger", color: "#0084FF" },
    facebook: { label: "Facebook", color: "#1877F2" },
    instagram: { label: "Instagram", color: "#E1306C" },
    email: { label: "Email", color: "#6366f1" },
    sms: { label: "SMS", color: "#64748b" },
};

// SVG channel icons
const CHANNEL_ICON_SVG: Record<string, { svg: string; bg: string }> = {
    whatsapp: {
        bg: "#25D366",
        svg: '<path d="M16 2C8.28 2 2 8.28 2 16c0 2.44.64 4.73 1.76 6.72L2 30l7.44-1.72A13.92 13.92 0 0016 30c7.72 0 14-6.28 14-14S23.72 2 16 2zm0 25.6a11.56 11.56 0 01-5.88-1.6l-.42-.26-4.42 1.02.98-4.3-.28-.44A11.6 11.6 0 014.4 16C4.4 9.6 9.6 4.4 16 4.4S27.6 9.6 27.6 16 22.4 27.6 16 27.6zm6.36-8.68c-.34-.18-2.02-.98-2.34-1.1-.32-.1-.54-.18-.78.18-.22.34-.88 1.1-1.08 1.32-.2.24-.4.26-.74.08-.34-.18-1.44-.52-2.74-1.66a10.3 10.3 0 01-1.9-2.32c-.2-.34-.02-.52.14-.7.16-.16.34-.42.52-.62.16-.22.22-.36.34-.6.1-.24.06-.44-.02-.62-.08-.18-.78-1.86-1.06-2.54-.28-.68-.56-.58-.78-.6-.2-.02-.42-.02-.66-.02s-.6.08-.92.44c-.32.34-1.2 1.16-1.2 2.84 0 1.66 1.22 3.28 1.4 3.5.16.22 2.42 3.7 5.86 5.18.82.36 1.46.56 1.96.72.82.26 1.56.22 2.16.14.66-.1 2.02-.82 2.3-1.62.28-.78.28-1.46.2-1.62-.1-.14-.32-.22-.66-.4z"/>',
    },
    messenger: {
        bg: "#0099FF",
        svg: '<path d="M16 2C8.27 2 2 7.93 2 15.2c0 3.82 1.6 7.25 4.2 9.72V30l4.88-2.68A14.5 14.5 0 0016 28.4c7.73 0 14-5.93 14-13.2S23.73 2 16 2zm1.38 17.78l-3.56-3.8-6.96 3.8L13.2 12l3.66 3.8L23.72 12l-6.34 7.78z"/>',
    },
    facebook: {
        bg: "#1877F2",
        svg: '<path d="M14.5 21v-6.5h2.2l.33-2.6h-2.53v-1.66c0-.75.2-1.26 1.28-1.26h1.37V6.6c-.24-.03-1.05-.1-2-.1-1.98 0-3.33 1.2-3.33 3.42v1.98H9.6v2.6h2.19V21h2.72z"/>',
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
            <svg
                viewBox="0 0 24 24"
                className="w-3 h-3"
                fill="white"
                dangerouslySetInnerHTML={{ __html: meta.svg }}
            />
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
        } catch {
            /* not in browser context */
        }
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
    const color =
        score >= 70
            ? "bg-emerald-500"
            : score >= 40
              ? "bg-amber-500"
              : "bg-stone-300";
    return (
        <div className="flex items-center gap-2">
            <div
                className="flex-1 h-1.5 rounded-full overflow-hidden"
                style={{ backgroundColor: "#f1f5f9" }}
            >
                <div
                    className={`h-full rounded-full transition-all duration-500 ${color}`}
                    style={{ width: `${score}%` }}
                />
            </div>
            <span className="text-xs font-semibold text-stone-600 w-6 text-right">
                {score}
            </span>
        </div>
    );
}

function Section({
    title,
    children,
    action,
}: {
    title: string;
    children: React.ReactNode;
    action?: React.ReactNode;
}) {
    return (
        <div className="mb-5">
            <div className="flex items-center justify-between mb-2">
                <span
                    className="text-[10px] font-bold uppercase tracking-widest"
                    style={{ color: "#334155" }}
                >
                    {title}
                </span>
                {action}
            </div>
            {children}
        </div>
    );
}

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
    const [draft, setDraft] = useState(value);
    useEffect(() => {
        setDraft(value);
    }, [value]);

    return (
        <div
            className="group flex items-start gap-2 py-1.5 border-b last:border-0"
            style={{ borderColor: "#f1f5f9" }}
        >
            <span
                className="text-[10px] w-16 flex-shrink-0 pt-0.5"
                style={{ color: "#334155" }}
            >
                {label}
            </span>
            {editing ? (
                <div className="flex-1 flex items-center gap-1">
                    <input
                        type={type}
                        value={draft}
                        autoFocus
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                onChange(draft);
                                setEditing(false);
                            }
                            if (e.key === "Escape") {
                                setDraft(value);
                                setEditing(false);
                            }
                        }}
                        className="flex-1 text-xs rounded px-2 py-1 focus:outline-none focus:ring-1"
                        style={{
                            backgroundColor: "white",
                            border: "1px solid #b5da8b",
                            color: "#16270c",
                        }}
                        placeholder={placeholder}
                    />
                    <button
                        onClick={() => {
                            onChange(draft);
                            setEditing(false);
                        }}
                        className="text-[10px] text-emerald-600 font-semibold hover:text-emerald-700"
                    >
                        ✓
                    </button>
                    <button
                        onClick={() => {
                            setDraft(value);
                            setEditing(false);
                        }}
                        className="text-[10px] text-stone-400 hover:text-stone-600"
                    >
                        ✕
                    </button>
                </div>
            ) : (
                <button
                    onClick={() => setEditing(true)}
                    className="flex-1 text-xs text-left transition-colors truncate"
                    style={{ color: "#16270c" }}
                >
                    {value || (
                        <span className="text-stone-300 italic">
                            {placeholder || "—"}
                        </span>
                    )}
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
    onOpenIdentity,
    className,
    hideHeader,
}: Props) {
    const [activeTab, setActiveTab] = useState<
        "profile" | "insights" | "activity"
    >("profile");
    const [profile, setProfile] = useState<CustomerProfile | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [editNotes, setEditNotes] = useState(false);
    const [noteDraft, setNoteDraft] = useState("");
    const [showMerge, setShowMerge] = useState(false);
    const [mergeQuery, setMergeQuery] = useState("");
    const [tagInput, setTagInput] = useState("");
    // Made-to-order enquiry pending on this conversation (measurement form).
    const [enquiry, setEnquiry] = useState<ProductionEnquiry | null>(null);
    const [pushing, setPushing] = useState(false);

    // Customer key: wa_id for WhatsApp, else the channel-native handle (PSID /
    // IGSID). WhatsApp's wa_id IS its external_id, so this is wa_id there too.
    // Without this, Messenger/IG/FB contacts (wa_id === null) hit
    // /admin/customers/null and every edit silently reverts on reload.
    const custId = conversation.wa_id ?? conversation.external_id ?? "";
    const chParam = conversation.channel
        ? `?channel=${encodeURIComponent(conversation.channel)}`
        : "";

    const loadProfile = useCallback(async () => {
        setLoading(true);
        try {
            const data = await crmReq<CustomerProfile>(
                "GET",
                `/admin/customers/${encodeURIComponent(custId)}${chParam}`,
            );
            setProfile(data);
            setNoteDraft(data.notes || "");
        } catch {
            // Fallback: minimal profile from conversation data
            setProfile({
                id: custId,
                wa_id: custId,
                name: conversation.name ?? null,
                name_confirmed: false,
                email: null,
                phone: conversation.wa_id,
                location: null,
                age: null,
                tags: [],
                lead_stage: "new",
                lead_score: 0,
                channels: [
                    {
                        channel: (conversation.channel as any) || "whatsapp",
                        identifier: conversation.wa_id,
                        first_seen: conversation.last_message_at,
                        last_seen: conversation.last_message_at,
                        conversation_count: 1,
                    },
                ],
                merged_ids: [],
                linked_identities: [],
                total_orders: 0,
                total_spent: 0,
                last_order_at: null,
                last_seen_at: conversation.last_message_at,
                first_seen_at: conversation.last_message_at,
                notes: null,
                created_at: conversation.last_message_at,
                country_iso: (conversation as any).country_iso ?? null,
                country:     (conversation as any).country     ?? null,
                flag_url:    (conversation as any).flag_url    ?? null,
            });
        } finally {
            setLoading(false);
        }
    }, [
        custId,
        chParam,
        conversation.wa_id,
        conversation.name,
        conversation.channel,
        conversation.last_message_at,
    ]);

    useEffect(() => {
        loadProfile();
    }, [loadProfile]);

    const patch = useCallback(
        async (updates: Partial<CustomerProfile & { notes: string }>) => {
            if (!profile) return;
            setSaving(true);
            const prev = profile;
            setProfile({ ...profile, ...updates });
            // Persist against the channel-native key (profile.wa_id is the shim
            // wa_id for non-WhatsApp contacts), with the channel so the backend
            // resolves the right person even before a shim User exists.
            const key = profile.wa_id || custId;
            try {
                await crmReq(
                    "PATCH",
                    `/admin/customers/${encodeURIComponent(key)}${chParam}`,
                    updates,
                );
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
        },
        [profile, onToast, onNameChange, custId, chParam],
    );

    // Pending made-to-order enquiry for this conversation (measurement form).
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const r = await crmReq<{ enquiry: ProductionEnquiry | null }>(
                    "GET",
                    `/admin/production/conversation/${conversation.id}`,
                );
                if (!cancelled) setEnquiry(r.enquiry ?? null);
            } catch {
                if (!cancelled) setEnquiry(null);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [conversation.id]);

    const pushProduction = async () => {
        if (!enquiry) return;
        setPushing(true);
        try {
            const r = await crmReq<{ hub_order_number?: string }>(
                "POST",
                `/admin/production/${enquiry.id}/push`,
            );
            setEnquiry({ ...enquiry, status: "pushed", hub_order_number: r.hub_order_number ?? null });
            onToast(r.hub_order_number ? `Sent to production · ${r.hub_order_number}` : "Sent to production");
        } catch {
            onToast("Couldn't send to production", "error");
        } finally {
            setPushing(false);
        }
    };

    const declineProduction = async () => {
        if (!enquiry) return;
        const prev = enquiry;
        setEnquiry({ ...enquiry, status: "declined" });
        try {
            await crmReq("POST", `/admin/production/${enquiry.id}/decline`);
        } catch {
            setEnquiry(prev);
            onToast("Couldn't dismiss", "error");
        }
    };

    const addTag = () => {
        if (!tagInput.trim() || !profile) return;
        patch({ tags: [...(profile.tags || []), tagInput.trim()] });
        setTagInput("");
    };
    const removeTag = (tag: string) => {
        if (!profile) return;
        patch({ tags: profile.tags.filter((t) => t !== tag) });
    };

    // Prefer the hub-sourced order history (full purchase history across POS,
    // web AND WhatsApp) served on the profile; fall back to the local WhatsApp
    // orders list only when the profile hasn't provided one.
    const customerOrders: PanelOrder[] = (profile?.orders ??
        (orders.filter(
            (o) =>
                o.wa_id === conversation.wa_id ||
                o.contact_phone === conversation.wa_id,
        ) as unknown as PanelOrder[]));
    // Lifetime spend comes from the hub (profile.total_spent); the client sum is
    // only a fallback over whatever recent orders we have on hand.
    const totalSpent =
        profile?.total_spent ||
        customerOrders.reduce((s, o) => s + (o.total || o.subtotal || 0), 0);
    const lastOrder = [...customerOrders].sort(
        (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];

    const computedScore = Math.min(
        100,
        Math.round(
            Math.min(customerOrders.length * 15, 45) +
                (totalSpent > 10000 ? 30 : totalSpent > 3000 ? 15 : 0) +
                (profile?.email ? 10 : 0) +
                (profile?.name ? 10 : 0) +
                (profile?.location ? 5 : 0) +
                ((profile?.channels?.length ?? 0) > 1 ? 15 : 0),
        ),
    );

    if (loading) {
        return (
            <div
                className="w-80 flex-shrink-0 flex items-center justify-center"
                style={{
                    backgroundColor: "#f8fafc",
                    borderLeft: "1px solid #e2e8f0",
                }}
            >
                <div
                    className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin"
                    style={{
                        borderColor: "#1e293b",
                        borderTopColor: "transparent",
                    }}
                />
            </div>
        );
    }

    if (!profile) return null;

    const stageMeta = STAGE_META[profile.lead_stage] ?? STAGE_META.new;

    return (
        <div
            className={className ?? "w-80 flex-shrink-0 flex flex-col overflow-hidden"}
            style={{
                backgroundColor: "#ffffff",
                ...(className ? {} : { borderLeft: "1px solid #e2e8f0" }),
            }}
        >
            {/* Header */}
            {!hideHeader && (
            <div
                className="px-4 py-3 flex items-center justify-between"
                style={{ borderBottom: "1px solid #e2e8f0" }}
            >
                <span
                    className="text-xs font-bold uppercase tracking-widest"
                    style={{ color: "#1e293b" }}
                >
                    Customer
                </span>
                <button
                    onClick={onClose}
                    title="Collapse sidebar"
                    className="text-stone-400 hover:text-stone-600 transition-colors"
                >
                    <svg
                        className="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M9 5l7 7-7 7"
                        />
                    </svg>
                </button>
            </div>
            )}

            {/* Profile hero */}
            <div
                className="px-4 pt-4 pb-3"
                style={{ borderBottom: "1px solid #e2e8f0" }}
            >
                <div className="flex items-start gap-3 mb-3">
                    <Avatar
                        name={displayName(profile.name, profile.wa_id)}
                        size={44}
                    />
                    <div className="flex-1 min-w-0">
                        <div
                            className="text-sm font-bold truncate"
                            style={{ color: "#16270c" }}
                        >
                            {profile.name || (
                                <span className="text-stone-400 italic font-normal">
                                    Unknown
                                </span>
                            )}
                            {profile.name_confirmed && (
                                <span className="ml-1 text-[9px] text-emerald-600 font-bold">
                                    ✓
                                </span>
                            )}
                        </div>
                        <div className="text-xs text-stone-400 font-mono flex items-center gap-1.5">
                            {profile.country_iso && (
                                <img
                                    src={`https://flagcdn.com/${profile.country_iso.toLowerCase()}.svg`}
                                    alt={profile.country || profile.country_iso}
                                    title={profile.country || undefined}
                                    className="inline-block rounded-sm"
                                    style={{ width: 16, height: 12, objectFit: "cover" }}
                                />
                            )}
                            <span>{formatPhone(
                                (profile.phone || "").replace(/\D/g, "").length >= 7
                                    ? profile.phone!
                                    : profile.wa_id,
                            )}</span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                            <span
                                className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${stageMeta.bg} ${stageMeta.color}`}
                            >
                                <span
                                    className={`w-1.5 h-1.5 rounded-full ${stageMeta.dot}`}
                                />
                                {stageMeta.label}
                            </span>
                            {/* Country flag + ISO */}
                            {profile.country_iso && (
                                <span
                                    className="inline-flex items-center gap-1 text-[10px] text-stone-500 cursor-default select-none"
                                    title={
                                        profile.country ?? profile.country_iso
                                    }
                                >
                                    <img
                                        src={
                                            profile.flag_url ??
                                            `https://flagcdn.com/w20/${profile.country_iso.toLowerCase()}.png`
                                        }
                                        alt={profile.country_iso}
                                        className="w-4 h-4 rounded-sm object-cover border border-stone-200 shadow-sm"
                                    />
                                    <span>
                                        {countryFullName(
                                            profile.country_iso,
                                            profile.country,
                                        )}
                                    </span>
                                </span>
                            )}
                            {saving && (
                                <span className="text-[10px] text-stone-400 animate-pulse">
                                    saving…
                                </span>
                            )}
                        </div>
                    </div>
                </div>

                <div className="mb-2">
                    <div className="flex justify-between mb-1">
                        <span className="text-[10px] text-stone-400 font-medium">
                            Lead Score
                        </span>
                        <span className="text-[10px] text-stone-500">
                            {computedScore}/100
                        </span>
                    </div>
                    <ScoreBar score={computedScore} />
                </div>

                {/* Segment badge + buying rhythm — quick read while chatting */}
                {profile.tier && (
                    <div className="flex flex-wrap items-center gap-1.5 mt-2">
                        <span
                            title={TIER_META[profile.tier]?.title}
                            className={`inline-flex items-center text-[10px] font-semibold rounded px-1.5 py-0.5 border ${TIER_META[profile.tier]?.cls || ""}`}
                        >
                            {profile.tier_label || TIER_META[profile.tier]?.label}
                        </span>
                        {profile.buying_rhythm?.cadence_label && (
                            <span className="text-[10px] text-stone-500">
                                Buys {profile.buying_rhythm.cadence_label}
                            </span>
                        )}
                        {profile.buying_rhythm?.overdue && (
                            <span
                                title="Past their usual buying gap — a good moment to reach out"
                                className="inline-flex items-center text-[10px] font-semibold rounded px-1.5 py-0.5 border bg-amber-50 text-amber-700 border-amber-300"
                            >
                                ⏰ Overdue
                            </span>
                        )}
                    </div>
                )}

                <div className="flex flex-wrap gap-1 mt-2">
                    {(profile.channels || []).map((ch) => (
                        <button
                            key={ch.channel + ch.identifier}
                            type="button"
                            onClick={() => onOpenIdentity?.(ch.channel, ch.identifier)}
                            title={`Open ${ch.channel} conversation`}
                            className="inline-flex items-center gap-0.5 text-[10px] rounded px-1.5 py-0.5 capitalize cursor-pointer hover:brightness-95"
                            style={{
                                backgroundColor: "#f1f5f9",
                                border: "1px solid #b5da8b",
                                color: "#1e293b",
                            }}
                        >
                            <ChannelBadge channel={ch.channel} /> {ch.channel}
                        </button>
                    ))}
                    {(() => {
                        // A captured phone gives this customer a WhatsApp door even
                        // before their first WhatsApp message — one tap to wa.me.
                        const digits = (profile.phone || "").replace(/\D/g, "");
                        const hasWaChannel = (profile.channels || []).some(
                            (c) => c.channel === "whatsapp",
                        );
                        if (!hasWaChannel && digits.length >= 7 && digits.length <= 15) {
                            return (
                                <button
                                    type="button"
                                    onClick={() =>
                                        window.open(`https://wa.me/${digits}`, "_blank", "noopener")
                                    }
                                    title="Open WhatsApp chat"
                                    className="inline-flex items-center gap-0.5 text-[10px] rounded px-1.5 py-0.5 capitalize cursor-pointer hover:brightness-95"
                                    style={{
                                        backgroundColor: "#f0fdf4",
                                        border: "1px solid #b5da8b",
                                        color: "#1e293b",
                                    }}
                                >
                                    <ChannelBadge channel="whatsapp" /> whatsapp
                                </button>
                            );
                        }
                        return null;
                    })()}
                    {profile.merged_ids.length > 0 && (
                        <span className="text-[10px] text-violet-600 font-medium">
                            +{profile.merged_ids.length} merged
                        </span>
                    )}
                </div>
            </div>

            {/* Quick stats */}
            <div
                className="grid grid-cols-3"
                style={{ borderBottom: "1px solid #e2e8f0" }}
            >
                {[
                    {
                        label: "Orders",
                        value: profile.total_orders || customerOrders.length,
                    },
                    {
                        label: "Spent",
                        value: fmtCurrency(totalSpent),
                    },
                    {
                        label: "Convs",
                        value:
                            (profile.channels || []).reduce(
                                (s, c) => s + c.conversation_count,
                                0,
                            ) || 1,
                    },
                ].map((s) => (
                    <div
                        key={s.label}
                        className="px-3 py-2.5 text-center last:border-0"
                        style={{ borderRight: "1px solid #e2e8f0" }}
                    >
                        <div
                            className="text-sm font-bold"
                            style={{ color: "#16270c" }}
                        >
                            {s.value}
                        </div>
                        <div
                            className="text-[10px]"
                            style={{ color: "#334155" }}
                        >
                            {s.label}
                        </div>
                    </div>
                ))}
            </div>

            {/* Tabs */}
            <div className="flex" style={{ borderBottom: "1px solid #e2e8f0" }}>
                {(["profile", "insights", "activity"] as const).map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`flex-1 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors border-b-2 ${
                            activeTab === tab
                                ? ""
                                : "border-transparent text-[#94a3b8]"
                        }`}
                        style={
                            activeTab === tab
                                ? { color: "#1e293b", borderColor: "#1e293b" }
                                : undefined
                        }
                    >
                        {tab}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div
                className="flex-1 overflow-y-auto px-4 py-4"
                style={{ backgroundColor: "#f8fafc" }}
            >
                {activeTab === "profile" && (
                    <>
                        <Section title="Contact Details">
                            {profile.lead_source && (
                                <div
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "space-between",
                                        padding: "6px 0",
                                        fontSize: 13,
                                    }}
                                >
                                    <span style={{ color: "var(--muted, #6b7280)" }}>
                                        Source
                                    </span>
                                    <span
                                        style={{
                                            display: "inline-flex",
                                            alignItems: "center",
                                            gap: 6,
                                            fontWeight: 500,
                                        }}
                                        title="Where this lead first found us"
                                    >
                                        <span>
                                            {(SOURCE_META[profile.lead_source] ??
                                                SOURCE_META.other).icon}
                                        </span>
                                        {(SOURCE_META[profile.lead_source] ??
                                            { label: profile.lead_source }).label}
                                    </span>
                                </div>
                            )}
                            <EditableField
                                label="Name"
                                value={profile.name || ""}
                                onChange={(v) => patch({ name: v })}
                                placeholder="Full name"
                            />
                            <EditableField
                                label="Email"
                                value={profile.email || ""}
                                onChange={(v) => patch({ email: v })}
                                placeholder="email@example.com"
                                type="email"
                            />
                            <EditableField
                                label="Phone"
                                value={profile.phone || ""}
                                onChange={(v) => patch({ phone: v })}
                                placeholder="+254..."
                            />
                            <EditableField
                                label="Country"
                                value={profile.country || ""}
                                onChange={(v) => patch({ country: v })}
                                placeholder="Resolved from phone"
                            />
                            <EditableField
                                label="Location"
                                value={profile.location || ""}
                                onChange={(v) => patch({ location: v })}
                                placeholder="City / Estate"
                            />
                            <EditableField
                                label="Age"
                                value={profile.age ? String(profile.age) : ""}
                                onChange={(v) =>
                                    patch({ age: parseInt(v) || (null as any) })
                                }
                                placeholder="e.g. 35"
                                type="number"
                            />
                        </Section>

                        <Section title="Lead Pipeline">
                            {profile.lead_stage_source === "auto" && (
                                <div className="text-[10px] text-violet-600 mb-1.5 flex items-center gap-1">
                                    <span className="inline-flex items-center rounded px-1 py-0.5 bg-violet-50 border border-violet-200 font-semibold">
                                        ✦ AI
                                    </span>
                                    set from the conversation — click any stage to override.
                                </div>
                            )}
                            <div className="flex items-center relative pb-5 px-0.5">
                                {PIPELINE_STAGES.flatMap((stage, i) => {
                                    const state = stepState(
                                        stage,
                                        profile.lead_stage,
                                    );
                                    const isLost = stage === "lost";
                                    const reached =
                                        state === "done" || state === "active";

                                    // Circle appearance per state
                                    let circleStyle: React.CSSProperties;
                                    if (state === "active") {
                                        circleStyle = isLost
                                            ? {
                                                  backgroundColor: "#ef4444",
                                                  borderColor: "#ef4444",
                                                  color: "#ffffff",
                                              }
                                            : {
                                                  backgroundColor:
                                                      PIPE_GOLD_SOLID,
                                                  borderColor: PIPE_GOLD_SOLID,
                                                  color: "#ffffff",
                                              };
                                    } else if (state === "done") {
                                        circleStyle = {
                                            backgroundColor: "#ffffff",
                                            borderColor: PIPE_GOLD,
                                            color: PIPE_GOLD,
                                        };
                                    } else if (isLost) {
                                        circleStyle = {
                                            backgroundColor: "#ffffff",
                                            borderColor: PIPE_LOST,
                                            color: PIPE_LOST_ICON,
                                        };
                                    } else {
                                        circleStyle = {
                                            backgroundColor: "#ffffff",
                                            borderColor: PIPE_IDLE,
                                            color: "transparent",
                                        };
                                    }

                                    // Label colour + weight per state
                                    const labelColor =
                                        state === "active"
                                            ? isLost
                                                ? "#ef4444"
                                                : PIPE_GOLD_SOLID
                                            : state === "done"
                                              ? PIPE_GOLD
                                              : isLost
                                                ? PIPE_LOST_TEXT
                                                : PIPE_IDLE_TEXT;

                                    // Show ✕ for Lost, ✓ for reached forward nodes
                                    const showCheck = reached && !isLost;
                                    const showX =
                                        isLost &&
                                        (state === "active" ||
                                            state === "future");

                                    // Connector colour (segment before this node)
                                    const connColor = isLost
                                        ? PIPE_LOST
                                        : reached
                                          ? PIPE_GOLD
                                          : PIPE_IDLE;

                                    const els: React.ReactNode[] = [];
                                    if (i > 0) {
                                        els.push(
                                            <div
                                                key={`c-${stage}`}
                                                className="flex-1 h-0.5 rounded-full"
                                                style={{
                                                    backgroundColor: connColor,
                                                }}
                                            />,
                                        );
                                    }
                                    els.push(
                                        <button
                                            key={`n-${stage}`}
                                            onClick={() =>
                                                patch({ lead_stage: stage })
                                            }
                                            title={PIPE_LABEL[stage]}
                                            className="relative flex-shrink-0"
                                        >
                                            <span
                                                className="flex items-center justify-center w-6 h-6 rounded-full border-2 transition-colors"
                                                style={circleStyle}
                                            >
                                                {showCheck && (
                                                    <svg
                                                        viewBox="0 0 24 24"
                                                        fill="none"
                                                        stroke="currentColor"
                                                        strokeWidth={3.5}
                                                        className="w-3 h-3"
                                                    >
                                                        <path
                                                            strokeLinecap="round"
                                                            strokeLinejoin="round"
                                                            d="M5 13l4 4L19 7"
                                                        />
                                                    </svg>
                                                )}
                                                {showX && (
                                                    <svg
                                                        viewBox="0 0 24 24"
                                                        fill="none"
                                                        stroke="currentColor"
                                                        strokeWidth={3.5}
                                                        className="w-3 h-3"
                                                    >
                                                        <path
                                                            strokeLinecap="round"
                                                            strokeLinejoin="round"
                                                            d="M6 6l12 12M18 6L6 18"
                                                        />
                                                    </svg>
                                                )}
                                            </span>
                                            <span
                                                className={`absolute top-[26px] left-1/2 -translate-x-1/2 text-[9px] whitespace-nowrap ${
                                                    state === "active"
                                                        ? "font-bold"
                                                        : "font-semibold"
                                                }`}
                                                style={{ color: labelColor }}
                                            >
                                                {PIPE_LABEL[stage]}
                                            </span>
                                        </button>,
                                    );
                                    return els;
                                })}
                            </div>
                        </Section>

                        <Section title="Tags">
                            <div className="flex flex-wrap gap-1 mb-2">
                                {(profile.tags || []).map((tag) => (
                                    <span
                                        key={tag}
                                        className="inline-flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5"
                                        style={{
                                            backgroundColor: "#f1f5f9",
                                            color: "#1e293b",
                                        }}
                                    >
                                        {tag}
                                        <button
                                            onClick={() => removeTag(tag)}
                                            className="text-stone-400 hover:text-red-500 ml-0.5"
                                        >
                                            ×
                                        </button>
                                    </span>
                                ))}
                            </div>
                            <div className="flex gap-1">
                                <input
                                    value={tagInput}
                                    onChange={(e) =>
                                        setTagInput(e.target.value)
                                    }
                                    onKeyDown={(e) =>
                                        e.key === "Enter" && addTag()
                                    }
                                    placeholder="Add tag…"
                                    className="flex-1 text-xs rounded px-2 py-1 focus:outline-none"
                                    style={{
                                        backgroundColor: "white",
                                        border: "1px solid #b5da8b",
                                        color: "#16270c",
                                    }}
                                />
                                <button
                                    onClick={addTag}
                                    className="text-xs font-semibold px-2 py-1 rounded transition-colors"
                                    style={{
                                        backgroundColor: "#f8fafc",
                                        color: "#1e293b",
                                        border: "1px solid #b5da8b",
                                    }}
                                >
                                    +
                                </button>
                            </div>
                        </Section>

                        <Section title="Notes">
                            {editNotes ? (
                                <div>
                                    <textarea
                                        value={noteDraft}
                                        onChange={(e) =>
                                            setNoteDraft(e.target.value)
                                        }
                                        rows={4}
                                        className="w-full text-xs rounded-lg px-2.5 py-2 resize-none focus:outline-none"
                                        style={{
                                            backgroundColor: "white",
                                            border: "1px solid #b5da8b",
                                            color: "#16270c",
                                        }}
                                        placeholder="Internal notes about this customer…"
                                    />
                                    <div className="flex gap-2 mt-1.5">
                                        <button
                                            onClick={() => {
                                                patch({ notes: noteDraft });
                                                setEditNotes(false);
                                            }}
                                            className="text-[10px] text-emerald-600 font-semibold"
                                        >
                                            Save
                                        </button>
                                        <button
                                            onClick={() => {
                                                setNoteDraft(
                                                    profile.notes || "",
                                                );
                                                setEditNotes(false);
                                            }}
                                            className="text-[10px] text-stone-400"
                                        >
                                            Cancel
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <button
                                    onClick={() => setEditNotes(true)}
                                    className="w-full text-left text-xs rounded-lg px-2.5 py-2 transition-colors min-h-[40px]"
                                    style={{
                                        backgroundColor: "white",
                                        border: "1px solid #f1f5f9",
                                        color: "#16270c",
                                    }}
                                >
                                    {profile.notes || (
                                        <span className="text-stone-300 italic">
                                            Click to add notes…
                                        </span>
                                    )}
                                </button>
                            )}
                        </Section>

                        <Section
                            title="Cross-channel Identity"
                            action={
                                <button
                                    onClick={() => setShowMerge(!showMerge)}
                                    className="flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-lg transition-colors"
                                    style={
                                        showMerge
                                            ? {
                                                  backgroundColor: "#e2e8f0",
                                                  color: "#1e293b",
                                                  border: "1px solid #cbd5e1",
                                              }
                                            : {
                                                  backgroundColor: "#f8fafc",
                                                  color: "#1e293b",
                                                  border: "1px solid #b5da8b",
                                              }
                                    }
                                >
                                    <svg
                                        className="w-2.5 h-2.5"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2.5}
                                            d={
                                                showMerge
                                                    ? "M6 18L18 6M6 6l12 12"
                                                    : "M12 4v16m8-8H4"
                                            }
                                        />
                                    </svg>
                                    {showMerge ? "Cancel" : "Merge"}
                                </button>
                            }
                        >
                            {(profile.channels || []).map((ch) => (
                                <div
                                    key={ch.channel + ch.identifier}
                                    className="flex items-center gap-2 py-1.5 border-b border-stone-50 last:border-0"
                                >
                                    <ChannelBadge channel={ch.channel} />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[10px] font-semibold text-stone-700 capitalize">
                                            {ch.channel}
                                        </div>
                                        <div className="text-[10px] text-stone-400 truncate font-mono">
                                            {formatPhone(ch.identifier)}
                                        </div>
                                    </div>
                                    <div className="text-[10px] text-stone-400 text-right flex-shrink-0">
                                        <div>{ch.conversation_count} conv</div>
                                        <div>{timeAgo(ch.last_seen)}</div>
                                    </div>
                                </div>
                            ))}
                            {/* Linked identities — the real cross-channel spine */}
                            {(profile.linked_identities?.length ?? 0) > 0 && (
                                <div className="mt-2 space-y-1">
                                    {profile.linked_identities!.map((id) => {
                                        const meta = CH_META[id.channel] ?? { label: id.channel, color: "#64748b" };
                                        // A real WhatsApp number (not a phantom Meta id) opens a
                                        // wa.me chat; every other channel jumps to that
                                        // conversation inside Neema. Both are one tap.
                                        const digits = (id.external_id || "").replace(/\D/g, "");
                                        const isRealPhone = id.channel === "whatsapp" && digits.length >= 7 && digits.length <= 15;
                                        const clickable = isRealPhone || !!onOpenIdentity;
                                        const onClick = () => {
                                            if (isRealPhone) {
                                                window.open(`https://wa.me/${digits}`, "_blank", "noopener");
                                            } else {
                                                onOpenIdentity?.(id.channel, id.external_id);
                                            }
                                        };
                                        return (
                                            <button
                                                key={id.channel + id.external_id}
                                                type="button"
                                                onClick={clickable ? onClick : undefined}
                                                disabled={!clickable}
                                                title={isRealPhone ? "Open WhatsApp chat" : `Open ${meta.label} conversation`}
                                                className={`w-full flex items-center gap-2 p-2 rounded-lg text-left transition-colors ${clickable ? "hover:brightness-95 cursor-pointer" : "cursor-default"}`}
                                                style={{ backgroundColor: "#f8fafc", border: "1px solid #e2e8f0" }}
                                            >
                                                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: meta.color }} />
                                                <div className="min-w-0 flex-1">
                                                    <div className="text-[10px] font-semibold" style={{ color: meta.color }}>{meta.label}</div>
                                                    <div className="text-[10px] font-mono truncate" style={{ color: "#64748b" }}>
                                                        {id.channel === "whatsapp" ? formatPhone(id.external_id) : id.external_id}
                                                    </div>
                                                </div>
                                                {clickable && (
                                                    <span className="text-[11px] flex-shrink-0" style={{ color: meta.color }} aria-hidden>↗</span>
                                                )}
                                                {id.confidence && (
                                                    <span className="text-[9px] px-1.5 py-0.5 rounded-full flex-shrink-0" style={{ backgroundColor: "#f1f5f9", color: "#64748b" }}>
                                                        {id.confidence}
                                                    </span>
                                                )}
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                            {profile.merged_ids.length > 0 && (
                                <div className="mt-2 p-2 rounded-lg" style={{ backgroundColor: "#f1f5f9", border: "1px solid #e2e8f0" }}>
                                    <div className="text-[10px] font-semibold mb-1" style={{ color: "#1e293b" }}>
                                        Merged ({profile.merged_ids.length})
                                    </div>
                                    {profile.merged_ids.map((mid) => (
                                        <div key={mid} className="flex items-center justify-between gap-2 py-0.5">
                                            <span className="text-[10px] font-mono" style={{ color: "#0f172a" }}>{formatPhone(mid)}</span>
                                            <button
                                                onClick={async () => {
                                                    try {
                                                        await crmReq("POST", `/admin/customers/${encodeURIComponent(profile.wa_id || custId)}/unmerge${chParam}`, { merge_with: mid });
                                                        onToast("Unmerged");
                                                        loadProfile();
                                                    } catch {
                                                        onToast("Failed to unmerge", "error");
                                                    }
                                                }}
                                                className="text-[9px] font-semibold px-1.5 py-0.5 rounded hover:opacity-80 flex-shrink-0"
                                                style={{ color: "#1e293b", border: "1px solid #cbd5e1" }}
                                            >
                                                Unmerge
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {showMerge && (
                                <div
                                    className="mt-3 rounded-xl border-2 border-dashed overflow-hidden"
                                    style={{
                                        borderColor: "#cbd5e1",
                                        backgroundColor: "#f8fafc",
                                    }}
                                >
                                    <div className="px-3 pt-3 pb-2">
                                        <div className="flex items-center gap-2 mb-2">
                                            <div
                                                className="w-7 h-7 rounded-lg flex items-center justify-center text-sm flex-shrink-0"
                                                style={{
                                                    backgroundColor: "#e2e8f0",
                                                    color: "#1e293b",
                                                }}
                                            >
                                                ⊕
                                            </div>
                                            <div>
                                                <div
                                                    className="text-xs font-bold"
                                                    style={{ color: "#1e293b" }}
                                                >
                                                    Merge Profiles
                                                </div>
                                                <div
                                                    className="text-[10px]"
                                                    style={{ color: "#334155" }}
                                                >
                                                    Combine duplicate customer
                                                    records
                                                </div>
                                            </div>
                                        </div>
                                        <p
                                            className="text-[10px] mb-2.5 leading-relaxed"
                                            style={{ color: "#1e293b" }}
                                        >
                                            Enter the phone / wa_id of the
                                            profile to merge{" "}
                                            <em>into this one</em>. Their orders
                                            and channels will be combined here.
                                        </p>
                                        <input
                                            value={mergeQuery}
                                            onChange={(e) =>
                                                setMergeQuery(e.target.value)
                                            }
                                            placeholder="e.g. 254700123456"
                                            className="w-full text-xs rounded-lg px-2.5 py-2 mb-2.5 focus:outline-none focus:ring-2"
                                            style={{
                                                backgroundColor: "white",
                                                border: "1.5px solid #cbd5e1",
                                                color: "#16270c",
                                                fontSize: 12,
                                            }}
                                            onFocus={(e) => {
                                                (
                                                    e.target as HTMLInputElement
                                                ).style.borderColor = "#1e293b";
                                            }}
                                            onBlur={(e) => {
                                                (
                                                    e.target as HTMLInputElement
                                                ).style.borderColor = "#cbd5e1";
                                            }}
                                        />
                                        <div className="flex gap-1.5">
                                            <button
                                                onClick={async () => {
                                                    if (!mergeQuery.trim())
                                                        return;
                                                    try {
                                                        await crmReq(
                                                            "POST",
                                                            `/admin/customers/${encodeURIComponent(profile.wa_id || custId)}/merge${chParam}`,
                                                            {
                                                                merge_with:
                                                                    mergeQuery.trim(),
                                                            },
                                                        );
                                                        onToast(
                                                            "Profiles merged successfully",
                                                        );
                                                        setShowMerge(false);
                                                        setMergeQuery("");
                                                        loadProfile();
                                                    } catch {
                                                        onToast(
                                                            "Failed to merge profiles",
                                                            "error",
                                                        );
                                                    }
                                                }}
                                                className="flex-1 text-[10px] font-bold py-1.5 rounded-lg text-white transition-colors"
                                                style={{
                                                    backgroundColor: "#1e293b",
                                                }}
                                            >
                                                ⊕ Merge now
                                            </button>
                                            <button
                                                onClick={() => {
                                                    setShowMerge(false);
                                                    setMergeQuery("");
                                                }}
                                                className="text-[10px] font-semibold px-3 py-1.5 rounded-lg border transition-colors"
                                                style={{
                                                    borderColor: "#cbd5e1",
                                                    color: "#1e293b",
                                                    backgroundColor: "white",
                                                }}
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
                                    {
                                        label: "Total orders",
                                        value:
                                            profile.total_orders ||
                                            customerOrders.length,
                                    },
                                    {
                                        label: "Total spent",
                                        value: fmtCurrency(totalSpent),
                                    },
                                    {
                                        label: "Avg order value",
                                        value: profile.avg_order_value
                                            ? fmtCurrency(
                                                  Math.round(
                                                      profile.avg_order_value,
                                                  ),
                                              )
                                            : profile.total_orders ||
                                                customerOrders.length
                                              ? fmtCurrency(
                                                    Math.round(
                                                        totalSpent /
                                                            (profile.total_orders ||
                                                                customerOrders.length),
                                                    ),
                                                )
                                              : "—",
                                    },
                                    {
                                        label: "Last order",
                                        value: lastOrder
                                            ? timeAgo(lastOrder.created_at)
                                            : profile.last_order_at
                                              ? timeAgo(profile.last_order_at)
                                              : "—",
                                    },
                                    {
                                        label: "Customer since",
                                        value: profile.first_seen_at
                                            ? fmtDate(profile.first_seen_at)
                                            : "—",
                                    },
                                ].map((row) => (
                                    <div
                                        key={row.label}
                                        className="flex items-center justify-between"
                                    >
                                        <span
                                            className="text-xs"
                                            style={{ color: "#334155" }}
                                        >
                                            {row.label}
                                        </span>
                                        <span
                                            className="text-xs font-semibold"
                                            style={{ color: "#16270c" }}
                                        >
                                            {row.value}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </Section>

                        {profile.buying_rhythm && (
                            <Section title="Buying Rhythm">
                                <div className="space-y-2">
                                    {[
                                        {
                                            label: "Buys",
                                            value: profile.buying_rhythm.cadence_label || "—",
                                        },
                                        {
                                            label: "Avg gap between orders",
                                            value: profile.buying_rhythm.avg_interval_days
                                                ? `${profile.buying_rhythm.avg_interval_days} days`
                                                : "—",
                                        },
                                        {
                                            label: "Since last order",
                                            value:
                                                profile.buying_rhythm.days_since_last != null
                                                    ? `${profile.buying_rhythm.days_since_last} days`
                                                    : "—",
                                        },
                                    ].map((row) => (
                                        <div
                                            key={row.label}
                                            className="flex items-center justify-between"
                                        >
                                            <span className="text-xs" style={{ color: "#334155" }}>
                                                {row.label}
                                            </span>
                                            <span
                                                className="text-xs font-semibold"
                                                style={{ color: "#16270c" }}
                                            >
                                                {row.value}
                                            </span>
                                        </div>
                                    ))}
                                    {profile.buying_rhythm.overdue && (
                                        <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mt-1">
                                            ⏰ Overdue — it's been longer than their usual gap.
                                            A good moment to check in.
                                        </div>
                                    )}
                                </div>
                            </Section>
                        )}

                        {customerOrders.length > 0 && (
                            <Section title="Top Products">
                                {(() => {
                                    const itemMap: Record<
                                        string,
                                        {
                                            name: string;
                                            qty: number;
                                            total: number;
                                        }
                                    > = {};
                                    customerOrders.forEach((o) =>
                                        (o.items || []).forEach((i) => {
                                            if (!itemMap[i.name])
                                                itemMap[i.name] = {
                                                    name: i.name,
                                                    qty: 0,
                                                    total: 0,
                                                };
                                            itemMap[i.name].qty +=
                                                i.qty || i.quantity || 1;
                                            itemMap[i.name].total +=
                                                i.total || 0;
                                        }),
                                    );
                                    return Object.values(itemMap)
                                        .sort((a, b) => b.total - a.total)
                                        .slice(0, 4)
                                        .map((item) => (
                                            <div
                                                key={item.name}
                                                className="flex items-center justify-between py-1.5 border-b border-stone-50 last:border-0"
                                            >
                                                <span className="text-xs text-stone-600 truncate flex-1 mr-2">
                                                    {item.name}
                                                </span>
                                                <div className="text-right flex-shrink-0">
                                                    <div className="text-xs font-semibold text-stone-800">
                                                        {fmtCurrency(
                                                            item.total,
                                                        )}
                                                    </div>
                                                    <div className="text-[10px] text-stone-400">
                                                        ×{item.qty}
                                                    </div>
                                                </div>
                                            </div>
                                        ));
                                })()}
                            </Section>
                        )}

                        <Section title="Lead Score Breakdown">
                            {[
                                {
                                    label: "Orders",
                                    pts: Math.min(
                                        (profile.total_orders ||
                                            customerOrders.length) * 15,
                                        45,
                                    ),
                                    max: 45,
                                },
                                {
                                    label: "Spend level",
                                    pts:
                                        totalSpent > 10000
                                            ? 30
                                            : totalSpent > 3000
                                              ? 15
                                              : 0,
                                    max: 30,
                                },
                                {
                                    label: "Email known",
                                    pts: profile.email ? 10 : 0,
                                    max: 10,
                                },
                                {
                                    label: "Name known",
                                    pts: profile.name ? 10 : 0,
                                    max: 10,
                                },
                                {
                                    label: "Multi-channel",
                                    pts:
                                        (profile.channels?.length ?? 0) > 1
                                            ? 15
                                            : 0,
                                    max: 15,
                                },
                            ].map((row) => (
                                <div key={row.label} className="mb-2">
                                    <div className="flex justify-between mb-0.5">
                                        <span className="text-[10px] text-stone-500">
                                            {row.label}
                                        </span>
                                        <span className="text-[10px] text-stone-600">
                                            {row.pts}/{row.max}
                                        </span>
                                    </div>
                                    <div className="h-1 bg-stone-100 rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-green-500 rounded-full"
                                            style={{
                                                width: `${row.max ? (row.pts / row.max) * 100 : 0}%`,
                                            }}
                                        />
                                    </div>
                                </div>
                            ))}
                        </Section>
                    </>
                )}

                {activeTab === "activity" && (
                    <>
                        <Section title="Recent Orders">
                            {profile.hub_linked && (
                                <div
                                    className="mb-2 flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px]"
                                    style={{
                                        backgroundColor: "#eef7e3",
                                        border: "1px solid #e2e8f0",
                                        color: "#3f6417",
                                    }}
                                    title="Matched to a shop customer by phone number — same person across the counter and WhatsApp"
                                >
                                    <span>📇</span>
                                    <span>
                                        Same customer in the shop
                                        {profile.hub_customer_name
                                            ? ` · ${profile.hub_customer_name}`
                                            : ""}{" "}
                                        — showing full in-shop + WhatsApp history
                                    </span>
                                </div>
                            )}
                            {customerOrders.length === 0 ? (
                                <p className="text-xs text-stone-400 text-center py-3">
                                    No orders yet
                                </p>
                            ) : (
                                <div className="space-y-2">
                                    {customerOrders.slice(0, 5).map((o) => (
                                        <div
                                            key={o.id}
                                            className="p-2.5 rounded-lg"
                                            style={{
                                                backgroundColor: "white",
                                                border: "1px solid #f1f5f9",
                                            }}
                                        >
                                            <div className="flex items-center justify-between mb-1">
                                                <span
                                                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                                        o.status === "delivered"
                                                            ? "bg-emerald-50 text-emerald-700"
                                                            : o.status ===
                                                                "confirmed"
                                                              ? "bg-blue-50 text-blue-700"
                                                              : o.status ===
                                                                  "cancelled"
                                                                ? "bg-red-50 text-red-600"
                                                                : "bg-amber-50 text-amber-700"
                                                    }`}
                                                >
                                                    {o.status}
                                                </span>
                                                <span className="text-[10px] text-stone-400">
                                                    {timeAgo(o.created_at)}
                                                </span>
                                            </div>
                                            <div
                                                className="text-xs font-semibold"
                                                style={{ color: "#16270c" }}
                                            >
                                                {fmtCurrency(
                                                    o.total ?? o.subtotal ?? 0,
                                                )}
                                            </div>
                                            <div
                                                className="text-[10px] mt-0.5 truncate"
                                                style={{ color: "#334155" }}
                                            >
                                                {(o.items || [])
                                                    .map((i) => i.name)
                                                    .join(", ") || "—"}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </Section>

                        <Section title="Channel History">
                            {(profile.channels || []).map((ch) => (
                                <div
                                    key={ch.channel + ch.identifier}
                                    className="flex items-start gap-2 py-2 border-b border-stone-50 last:border-0"
                                >
                                    <span className="text-base">
                                        <ChannelBadge channel={ch.channel} />
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <div
                                            className="text-xs font-semibold capitalize"
                                            style={{ color: "#16270c" }}
                                        >
                                            {ch.channel}
                                        </div>
                                        <div className="text-[10px] text-stone-400">
                                            {ch.conversation_count} conversation
                                            {ch.conversation_count !== 1
                                                ? "s"
                                                : ""}
                                        </div>
                                        <div className="text-[10px] text-stone-400">
                                            First:{" "}
                                            {ch.first_seen
                                                ? fmtDate(ch.first_seen)
                                                : "—"}{" "}
                                            · Last:{" "}
                                            {ch.last_seen
                                                ? timeAgo(ch.last_seen)
                                                : "—"}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </Section>
                    </>
                )}
            </div>

            {/* Made-to-order enquiry (measurement form → hub production) */}
            {enquiry && (
                <div className="px-4 py-3 bg-white" style={{ borderTop: "1px solid #e2e8f0" }}>
                    <div
                        className="text-[10px] font-bold uppercase tracking-widest mb-2"
                        style={{ color: "#334155" }}
                    >
                        🧵 Made-to-order request
                    </div>
                    <div className="rounded-lg p-2.5" style={{ background: "#f0f9ec", border: "1px solid #dde8d5" }}>
                        <div className="text-xs font-semibold" style={{ color: "#1a2e0f" }}>
                            {enquiry.product_name || "Custom item"}
                        </div>
                        {Object.keys(enquiry.measurements || {}).length > 0 && (
                            <div className="text-[10px] mt-1 leading-relaxed" style={{ color: "#3a5c28" }}>
                                {Object.entries(enquiry.measurements)
                                    .map(([k, v]) => `${k}: ${v}`)
                                    .join(" · ")}
                            </div>
                        )}
                        {enquiry.notes && (
                            <div className="text-[10px] mt-1" style={{ color: "#3a5c28" }}>
                                Notes: {enquiry.notes}
                            </div>
                        )}
                        {enquiry.status === "pushed" ? (
                            <div className="text-[10px] mt-2 font-semibold" style={{ color: "#427425" }}>
                                ✓ In production{enquiry.hub_order_number ? ` · ${enquiry.hub_order_number}` : ""}
                            </div>
                        ) : enquiry.status === "declined" ? (
                            <div className="text-[10px] mt-2" style={{ color: "#94a3b8" }}>
                                Dismissed
                            </div>
                        ) : (
                            <>
                                <div className="flex gap-1.5 mt-2">
                                    <button
                                        onClick={pushProduction}
                                        disabled={pushing || !enquiry.pushable}
                                        className="flex-1 text-[10px] font-semibold py-1.5 rounded-lg text-white transition-colors disabled:opacity-60"
                                        style={{ background: pushing ? "#9db98a" : "#589b31" }}
                                    >
                                        {pushing ? "Sending…" : "→ Push to production"}
                                    </button>
                                    <button
                                        onClick={declineProduction}
                                        className="text-[10px] font-semibold py-1.5 px-2.5 rounded-lg"
                                        style={{ background: "#f8fafc", color: "#64748b", border: "1px solid #e2e8f0" }}
                                    >
                                        Dismiss
                                    </button>
                                </div>
                                {!enquiry.pushable && (
                                    <div className="text-[9px] mt-1.5" style={{ color: "#94a3b8" }}>
                                        No linked hub product — set this order up in the hub manually.
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            )}

            {/* Quick actions */}
            <div
                className="px-4 py-3 bg-white"
                style={{ borderTop: "1px solid #e2e8f0" }}
            >
                <div
                    className="text-[10px] font-bold uppercase tracking-widest mb-2"
                    style={{ color: "#334155" }}
                >
                    Quick Actions
                </div>
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
                            const idx = STAGE_ORDER.indexOf(profile.lead_stage);
                            const next =
                                STAGE_ORDER[
                                    Math.min(
                                        idx + 1,
                                        STAGE_ORDER.indexOf("won"),
                                    )
                                ];
                            if (next !== profile.lead_stage)
                                patch({ lead_stage: next });
                        }}
                        className="w-full text-[10px] font-semibold py-1.5 rounded-lg transition-colors"
                        style={{
                            backgroundColor: "#f8fafc",
                            color: "#1e293b",
                            border: "1px solid #b5da8b",
                        }}
                    >
                        → Advance Stage
                    </button>
                </div>
            </div>
        </div>
    );
}