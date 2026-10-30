// ReportsView.tsx
// Admin reports: conversations, transfers, orders, agent performance.

import React, { useState, useEffect, useCallback } from "react";
import { fmtCurrency, fmtDate, timeAgo, formatPhone, displayName } from "@/lib/utils";
import { apiErrorDetail, conversationsApi, mapConversation, reportsApi, type PhotoCheckItem, type PhotoChecks, type PhotoVerdict, type RecoveryResults, type UnansweredItem } from "@/lib/api";
import { mediaSrc } from "@/lib/callCard";
import type { Conversation, Agent, Order, SharedViewProps } from "@/types";

interface ReportsViewProps extends SharedViewProps {
    agents: Agent[];
    orders: Order[];
}

type Range = "7d" | "30d" | "90d" | "custom";
type ReportTab = "overview" | "conversations" | "orders" | "agents" | "unanswered" | "followups" | "photos";
const TAB_LABEL: Record<ReportTab, string> = {
    overview: "Overview", conversations: "Conversations", orders: "Orders", agents: "Agents",
    unanswered: "Never answered", followups: "Follow-ups", photos: "Photo checks",
};
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

function rangeLabel(r: Range) {
    return { "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days", custom: "Custom range" }[r];
}

function daysAgo(n: number) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d;
}

function inRange(dateStr: string, from: Date, to: Date) {
    const d = new Date(dateStr);
    return d >= from && d <= to;
}

function StatBox({ label, value, sub, accent }: {
    label: string; value: string | number; sub?: string; accent?: string;
}) {
    return (
        <div className={`bg-white rounded-xl border shadow-sm p-4 border-l-4 ${accent ?? "border-l-[#589b31]"}`}>
            <div className="text-xs font-semibold text-[#9ccd65] uppercase tracking-wider mb-2">{label}</div>
            <div className="text-2xl font-bold text-[#16270c] tabular-nums">{value}</div>
            {sub && <div className="text-xs text-[#9ccd65] mt-0.5">{sub}</div>}
        </div>
    );
}

function MiniBar({ data, color = "#589b31" }: { data: { label: string; value: number }[]; color?: string }) {
    const max = Math.max(...data.map((d) => d.value), 1);
    return (
        <div className="flex items-end gap-1 h-20 pt-2">
            {data.map((d, i) => (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <div className="w-full rounded-t transition-all duration-700" style={{
                        height: `${(d.value / max) * 100}%`,
                        minHeight: d.value > 0 ? 3 : 0,
                        backgroundColor: color,
                        opacity: 0.7 + (d.value / max) * 0.3,
                    }} title={`${d.label}: ${d.value}`} />
                    <span className="text-[9px] text-[#9ccd65]">{d.label}</span>
                </div>
            ))}
        </div>
    );
}

function Table({ cols, rows, emptyText = "No data" }: {
    cols: string[];
    rows: (string | number | React.ReactNode)[][];
    emptyText?: string;
}) {
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-xs">
                <thead>
                    <tr className="border-b border-[#e6f3d8]">
                        {cols.map((c) => (
                            <th key={c} className="text-left py-2.5 px-3 text-[10px] font-bold text-[#9ccd65] uppercase tracking-wider whitespace-nowrap">
                                {c}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {rows.length === 0 ? (
                        <tr><td colSpan={cols.length} className="py-8 text-center text-[#9ccd65]">{emptyText}</td></tr>
                    ) : (
                        rows.map((row, i) => (
                            <tr key={i} className="border-b border-[#f3f9ec] hover:bg-[#f3f9ec] transition-colors">
                                {row.map((cell, j) => (
                                    <td key={j} className="py-2.5 px-3 text-[#16270c] whitespace-nowrap">{cell}</td>
                                ))}
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );
}

// Neema's threads whose customer's last real message never got an answer —
// they count as read (Unread is for threads a person holds), so this is where
// someone finds them to follow up. Reactions, "thanks", "okay" are left out;
// anything under a day old is still the missed-reply sweep's to answer.
function UnansweredPanel({ onToast }: { onToast: ReportsViewProps["onToast"] }) {
    const [items, setItems] = useState<UnansweredItem[] | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    useEffect(() => {
        let alive = true;
        reportsApi.unanswered().then((r) => { if (alive) setItems(r.items); })
            .catch((e) => { if (alive) setFailed(apiErrorDetail(e) || "Couldn't load the list"); });
        return () => { alive = false; };
    }, []);
    const download = async () => {
        setSaving(true);
        try { await reportsApi.downloadUnanswered(); }
        catch (e) { onToast(apiErrorDetail(e) || "Couldn't download the list", "error"); }
        finally { setSaving(false); }
    };
    return (
        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-[#e6f3d8] flex flex-wrap items-center justify-between gap-2">
                <div>
                    <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">
                        {items ? `${items.length} customer${items.length === 1 ? "" : "s"} never answered` : "Never answered"}
                    </span>
                    <p className="text-[11px] text-[#78716c] mt-0.5">
                        Neema&apos;s chats where the customer&apos;s last message, a day old or more, got no reply.
                        Reactions, thanks and &ldquo;okay&rdquo; are left out. Search the name in the inbox to answer.
                    </p>
                </div>
                <button onClick={download} disabled={saving || !items?.length}
                    className="h-9 px-4 rounded-lg text-xs font-semibold bg-[#589b31] text-white hover:bg-[#427425] disabled:opacity-50">
                    {saving ? "Preparing…" : "Download CSV"}
                </button>
            </div>
            {failed ? (
                <p className="px-4 py-6 text-sm text-[#b91c1c]">{failed}</p>
            ) : !items ? (
                <p className="px-4 py-6 text-sm text-[#699a32]">Loading…</p>
            ) : (
                <Table
                    cols={["Customer", "Channel", "Their last message", "Waiting"]}
                    emptyText="Every customer has had an answer."
                    rows={items.slice(0, 200).map((it) => [
                        displayName(it.name, it.contact),
                        <span className="capitalize">{it.channel}</span>,
                        <span className="block max-w-[420px] truncate" title={it.said}>{it.said}</span>,
                        `${it.days_waiting} day${it.days_waiting === 1 ? "" : "s"}`,
                    ])}
                />
            )}
        </div>
    );
}

// Every customer photo the photo check judged (owner, 2026-10-29): is it
// something we sell, or an AI-made / extra-embroidery design a person must
// price? In shadow mode nothing changes for the customer — the owner marks
// each result right or wrong here, and those marks set how strict it is
// before referrals go live.
const VERDICT: Record<PhotoVerdict, { label: string; tone: string; what: string }> = {
    refer:       { label: "Refer to a person", tone: "bg-[#fef2f2] text-[#b91c1c] border-[#fecaca]", what: "Extra embroidery, a design to make, far from our range, or AI-made with nothing like it" },
    ours:        { label: "Our product",       tone: "bg-[#ecfdf5] text-[#047857] border-[#a7f3d0]", what: "Neema answers as usual" },
    close:       { label: "Close to ours",     tone: "bg-[#f0f9ff] text-[#0369a1] border-[#bae6fd]", what: "Our product in another colour or size — Neema answers" },
    not_product: { label: "Not a product",     tone: "bg-[#f5f5f4] text-[#57534e] border-[#e7e5e4]", what: "A receipt, a person, a document…" },
    unknown:     { label: "Not checked",       tone: "bg-[#f5f5f4] text-[#78716c] border-[#e7e5e4]", what: "The check could not run" },
};
const VERDICT_ORDER: PhotoVerdict[] = ["refer", "ours", "close", "not_product", "unknown"];

function PhotoCheckCard({ item, onMark }: {
    item: PhotoCheckItem;
    onMark: (item: PhotoCheckItem, mark: "right" | "wrong" | null, note?: string) => Promise<void>;
}) {
    const v = VERDICT[item.verdict] ?? VERDICT.unknown;
    const src = mediaSrc(item.photo_url, API_BASE);
    const [note, setNote] = useState(item.owner_note ?? "");
    const [busy, setBusy] = useState(false);
    const mark = async (m: "right" | "wrong" | null) => {
        setBusy(true);
        try { await onMark(item, m, m === "wrong" ? note : undefined); } finally { setBusy(false); }
    };
    return (
        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden flex flex-col">
            <div className="aspect-[4/3] bg-[#f6faf1] flex items-center justify-center overflow-hidden">
                {src
                    ? <a href={src} target="_blank" rel="noreferrer" className="w-full h-full">
                        <img src={src} alt="Customer photo" loading="lazy" className="w-full h-full object-cover" />
                      </a>
                    : <span className="text-xs text-[#9ccd65]">Photo no longer available</span>}
            </div>
            <div className="p-3 flex flex-col gap-2 flex-1">
                <div className="flex items-center justify-between gap-2">
                    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${v.tone}`}>{v.label}</span>
                    <span className="text-[11px] text-[#78716c]" title={fmtDate(item.at)}>{timeAgo(item.at)}</span>
                </div>
                <p className="text-xs font-semibold text-[#1c1917] truncate">
                    {displayName(item.name, item.contact)} <span className="font-normal text-[#78716c] capitalize">· {item.channel}</span>
                </p>
                {item.product && <p className="text-[11px] text-[#427425]">Closest: {item.product}</p>}
                <ul className="text-[11px] text-[#44403c] list-disc pl-4 space-y-0.5">
                    {item.reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
                {item.ai_made === "likely" && (
                    <span className="self-start text-[10px] font-semibold px-1.5 py-0.5 rounded bg-[#faf5ff] text-[#7e22ce]">Looks AI-made</span>
                )}
                {item.acted && <span className="text-[10px] text-[#b91c1c]">Handed to a person</span>}
                <div className="mt-auto pt-2 border-t border-[#e6f3d8] flex flex-col gap-1.5">
                    {item.owner_mark === "wrong" || item.owner_mark === null ? (
                        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000}
                            placeholder="If wrong, what should it be? (optional)"
                            className="h-8 px-2 rounded-md border border-[#cee6b2] text-[11px] focus:outline-none focus:border-[#589b31]" />
                    ) : null}
                    <div className="flex gap-1.5">
                        <button disabled={busy} onClick={() => mark(item.owner_mark === "right" ? null : "right")}
                            className={`flex-1 h-8 rounded-md text-[11px] font-semibold border disabled:opacity-50 ${item.owner_mark === "right" ? "bg-[#589b31] text-white border-[#589b31]" : "bg-white text-[#427425] border-[#cee6b2] hover:bg-[#f6faf1]"}`}>
                            {item.owner_mark === "right" ? "✓ Right" : "Right"}
                        </button>
                        <button disabled={busy} onClick={() => mark(item.owner_mark === "wrong" && note === (item.owner_note ?? "") ? null : "wrong")}
                            className={`flex-1 h-8 rounded-md text-[11px] font-semibold border disabled:opacity-50 ${item.owner_mark === "wrong" ? "bg-[#b91c1c] text-white border-[#b91c1c]" : "bg-white text-[#b91c1c] border-[#fecaca] hover:bg-[#fef2f2]"}`}>
                            {item.owner_mark === "wrong" ? "✗ Wrong" : "Wrong"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function PhotoChecksPanel({ onToast }: { onToast: ReportsViewProps["onToast"] }) {
    const [data, setData] = useState<PhotoChecks | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [filter, setFilter] = useState<PhotoVerdict | "">("");
    const [days, setDays] = useState(7);
    useEffect(() => {
        let alive = true;
        reportsApi.photoChecks(days).then((r) => { if (alive) setData(r); })
            .catch((e) => { if (alive) setFailed(apiErrorDetail(e) || "Couldn't load the photo checks"); });
        return () => { alive = false; };
    }, [days]);
    const onMark = useCallback(async (item: PhotoCheckItem, mark: "right" | "wrong" | null, note?: string) => {
        try {
            const r = await reportsApi.markPhotoCheck(item.id, mark, note);
            setData((d) => {
                if (!d) return d;
                const before = item.owner_mark;
                const marked = { ...d.marked };
                if (before) marked[before] -= 1;
                if (mark) marked[mark] += 1;
                return {
                    ...d, marked,
                    items: d.items.map((x) => x.id === item.id
                        ? { ...x, owner_mark: r.owner_mark as PhotoCheckItem["owner_mark"], owner_note: r.owner_note }
                        : x),
                };
            });
        } catch (e) {
            onToast(apiErrorDetail(e) || "Couldn't save the mark", "error");
        }
    }, [onToast]);
    const items = (data?.items ?? []).filter((i) => !filter || i.verdict === filter);
    const total = data ? VERDICT_ORDER.reduce((n, v) => n + (data.counts[v] ?? 0), 0) : 0;
    return (
        <div className="flex flex-col gap-4">
            <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm px-4 py-3 flex flex-wrap items-start justify-between gap-3">
                <div className="max-w-[640px]">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">Photo checks</span>
                        {data && (
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${data.mode === "live" ? "bg-[#fef2f2] text-[#b91c1c]" : data.mode === "shadow" ? "bg-[#fffbeb] text-[#b45309]" : "bg-[#f5f5f4] text-[#57534e]"}`}>
                                {data.mode === "live" ? "Live — referring" : data.mode === "shadow" ? "Shadow — recording only" : "Off"}
                            </span>
                        )}
                    </div>
                    <p className="text-[11px] text-[#78716c] mt-1">
                        Every photo a customer sends is compared with what we sell. Extra embroidery, a design or logo to make,
                        anything far from our range, or an AI-made image with nothing like it in our catalogue is for a person.
                        {data?.mode === "shadow" && " In shadow mode nothing changes for the customer: mark each result right or wrong, and the marks set how strict it is before referrals go live."}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {data && <span className="text-[11px] text-[#427425]">Marked: {data.marked.right} right · {data.marked.wrong} wrong</span>}
                    <select value={days} onChange={(e) => { setData(null); setFailed(null); setDays(Number(e.target.value)); }}
                        className="h-8 px-2 rounded-md border border-[#cee6b2] text-xs bg-white">
                        <option value={1}>Last day</option>
                        <option value={7}>Last 7 days</option>
                        <option value={30}>Last 30 days</option>
                        <option value={90}>Last 90 days</option>
                    </select>
                </div>
            </div>
            {data && (
                <div className="flex flex-wrap gap-1.5">
                    <button onClick={() => setFilter("")}
                        className={`h-8 px-3 rounded-full text-xs font-semibold border ${filter === "" ? "bg-[#427425] text-white border-[#427425]" : "bg-white text-[#427425] border-[#cee6b2]"}`}>
                        All · {total}
                    </button>
                    {VERDICT_ORDER.filter((v) => (data.counts[v] ?? 0) > 0 || v === "refer").map((v) => (
                        <button key={v} onClick={() => setFilter(v)} title={VERDICT[v].what}
                            className={`h-8 px-3 rounded-full text-xs font-semibold border ${filter === v ? "bg-[#427425] text-white border-[#427425]" : "bg-white text-[#427425] border-[#cee6b2]"}`}>
                            {VERDICT[v].label} · {data.counts[v] ?? 0}
                        </button>
                    ))}
                </div>
            )}
            {failed ? (
                <p className="px-4 py-6 text-sm text-[#b91c1c]">{failed}</p>
            ) : !data ? (
                <p className="px-4 py-6 text-sm text-[#699a32]">Loading…</p>
            ) : !items.length ? (
                <p className="px-4 py-6 text-sm text-[#78716c]">No customer photos checked in this period yet.</p>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                    {items.slice(0, 200).map((it) => <PhotoCheckCard key={it.id} item={it} onMark={onMark} />)}
                </div>
            )}
        </div>
    );
}

// What Neema's own follow-ups achieved. Each message a daily sweep sends is
// recorded; a send counts as answered when the customer wrote back within 72
// hours, and as converted when they ordered within 7 days (a payment reminder:
// when that order was paid). Sends younger than 72 hours are still waiting and
// kept out of the rates.
const FOLLOW_UP: Record<RecoveryResults["jobs"][number]["job"], { name: string; what: string; won: string }> = {
    quote_follow_up:  { name: "After a price",        what: "A price was given and the customer went quiet.", won: "ordered" },
    cart_recovery:    { name: "Cart left behind",     what: "Items were picked but the order never confirmed (daily, 11:00).", won: "ordered" },
    payment_followup: { name: "Payment reminder",     what: "An order's payment link went unpaid (daily, 10:00).", won: "paid" },
    reengage:         { name: "Check-in",             what: "A conversation went cold (daily, 15:00, up to 15 a day).", won: "ordered" },
};

function pct(v: number | null) {
    return v === null ? "—" : `${v}%`;
}

function FollowUpsPanel() {
    const [days, setDays] = useState(30);
    const [data, setData] = useState<RecoveryResults | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    useEffect(() => {
        let alive = true;
        reportsApi.recovery(days).then((r) => { if (alive) setData(r); })
            .catch((e) => { if (alive) setFailed(apiErrorDetail(e) || "Couldn't load the follow-up results"); });
        return () => { alive = false; };
    }, [days]);
    return (
        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-[#e6f3d8] flex flex-wrap items-center justify-between gap-2">
                <div>
                    <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">What the follow-ups achieved</span>
                    <p className="text-[11px] text-[#78716c] mt-0.5">
                        Answered = the customer wrote back within 72 hours. Ordered = they placed an order within 7 days;
                        for payment reminders, the order was paid. Messages under 72 hours old are still waiting and not in the rates.
                        {data?.tracking_since && <> Daily follow-ups recorded since {fmtDate(data.tracking_since)}.</>}
                    </p>
                </div>
                <select value={days} onChange={(e) => { setData(null); setFailed(null); setDays(Number(e.target.value)); }} aria-label="Period"
                    className="h-9 px-3 rounded-lg border border-[#cee6b2] text-xs text-[#427425] bg-white">
                    <option value={7}>Last 7 days</option>
                    <option value={30}>Last 30 days</option>
                    <option value={90}>Last 90 days</option>
                </select>
            </div>
            {failed ? (
                <p className="px-4 py-6 text-sm text-[#b91c1c]">{failed}</p>
            ) : !data ? (
                <p className="px-4 py-6 text-sm text-[#699a32]">Loading…</p>
            ) : (
                <Table
                    cols={["Follow-up", "Sent", "Waiting", "Answered", "Ordered / paid"]}
                    rows={data.jobs.map((j) => {
                        const f = FOLLOW_UP[j.job];
                        return [
                            <span key="name" className="block whitespace-normal min-w-[220px] max-w-[360px]">
                                <span className="font-semibold text-[#16270c]">{f.name}</span>
                                <span className="block text-[11px] text-[#78716c]">{f.what}</span>
                            </span>,
                            j.sent,
                            j.waiting,
                            j.settled ? <span><b>{pct(j.reply_rate)}</b> <span className="text-[#78716c]">({j.replied} of {j.settled})</span></span> : "—",
                            j.settled ? <span><b>{pct(j.convert_rate)}</b> <span className="text-[#78716c]">({j.converted} {f.won})</span></span> : "—",
                        ];
                    })}
                />
            )}
        </div>
    );
}

export function ReportsView({ agents, orders, onToast, isMobile }: ReportsViewProps) {
    // Reports aggregate a date range over EVERY conversation, so they fetch
    // the full list themselves, only while this view is open. The dashboard
    // used to fetch it for everyone every 60 seconds; the inbox now pages.
    // Computing these from the inbox's loaded rows would report on one page.
    const [allConvs, setAllConvs] = useState<Conversation[] | null>(null);
    useEffect(() => {
        let alive = true;
        conversationsApi.list()
            .then((rows) => { if (alive) setAllConvs(rows.map(mapConversation)); })
            .catch(() => {
                if (!alive) return;
                setAllConvs([]);
                onToast?.("Could not load conversations for this report.", "error");
            });
        return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    const conversations = allConvs ?? [];
    const [tab,       setTab]       = useState<ReportTab>("overview");
    const [range,     setRange]     = useState<Range>("30d");
    const [customFrom, setCustomFrom] = useState("");
    const [customTo,   setCustomTo]   = useState("");

    // Date range computation
    const { from, to } = (() => {
        const to = new Date();
        if (range === "7d")     return { from: daysAgo(7),  to };
        if (range === "30d")    return { from: daysAgo(30), to };
        if (range === "90d")    return { from: daysAgo(90), to };
        if (range === "custom" && customFrom && customTo)
            return { from: new Date(customFrom), to: new Date(customTo) };
        return { from: daysAgo(30), to };
    })();

    const filteredConvs   = conversations.filter((c) => inRange(c.last_message_at, from, to));
    const filteredOrders  = orders.filter((o) => inRange(o.created_at, from, to));

    // ── Overview stats ────────────────────────────────────────────────────────
    const totalRevenue    = filteredOrders.filter((o) => o.status !== "cancelled").reduce((s, o) => s + (o.total || 0), 0);
    const humanConvs      = filteredConvs.filter((c) => c.intercept_mode === "human").length;
    const aiConvs         = filteredConvs.filter((c) => c.intercept_mode === "ai").length;
    const pendingOrders   = filteredOrders.filter((o) => o.status === "pending").length;
    const deliveredOrders = filteredOrders.filter((o) => o.status === "delivered").length;

    // ── Per-day conversation chart ────────────────────────────────────────────
    const days = range === "7d" ? 7 : range === "30d" ? 14 : 30;
    const convByDay = Array.from({ length: Math.min(days, 14) }, (_, i) => {
        const d = new Date(to);
        d.setDate(to.getDate() - (Math.min(days, 14) - 1 - i));
        const key = d.toDateString();
        return {
            label: d.toLocaleDateString("en", { weekday: "short" }),
            value: filteredConvs.filter((c) => new Date(c.last_message_at).toDateString() === key).length,
        };
    });

    const orderByDay = Array.from({ length: Math.min(days, 14) }, (_, i) => {
        const d = new Date(to);
        d.setDate(to.getDate() - (Math.min(days, 14) - 1 - i));
        const key = d.toDateString();
        return {
            label: d.toLocaleDateString("en", { weekday: "short" }),
            value: filteredOrders.filter((o) => new Date(o.created_at).toDateString() === key).reduce((s, o) => s + (o.total || 0), 0),
        };
    });

    // ── Agent performance ─────────────────────────────────────────────────────
    const agentStats = agents.map((a) => {
        const handled = filteredConvs.filter((c) => c.assigned_agent_id === a.id).length;
        const revenue = filteredOrders
            .filter((o) => o.wa_id && filteredConvs.find((c) => c.wa_id === o.wa_id && c.assigned_agent_id === a.id))
            .reduce((s, o) => s + (o.total || 0), 0);
        return { ...a, handled, revenue };
    }).sort((a, b) => b.handled - a.handled);

    // ── Order breakdown ───────────────────────────────────────────────────────
    const orderRows = filteredOrders.slice(0, 20).map((o) => [
        displayName(o.contact_name, o.contact_phone || o.wa_id),
        formatPhone(o.contact_phone || o.wa_id),
        fmtCurrency(o.total || o.subtotal),
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
            o.status === "delivered" ? "bg-emerald-50 text-emerald-700" :
            o.status === "confirmed" ? "bg-blue-50 text-blue-700" :
            o.status === "cancelled" ? "bg-red-50 text-red-600" :
            "bg-amber-50 text-amber-700"
        }`}>{o.status}</span>,
        fmtDate(o.created_at),
    ]);

    const exportCSV = () => {
        const header = "Date,Customer,Amount,Status\n";
        const rows = filteredOrders.map((o) =>
            `${fmtDate(o.created_at)},${displayName(o.contact_name, o.contact_phone || o.wa_id)},${o.total || o.subtotal},${o.status}`
        ).join("\n");
        const blob = new Blob([header + rows], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = `neema-report-${range}.csv`; a.click();
        URL.revokeObjectURL(url);
        onToast("Report exported");
    };

    // Never show zeros that look like real figures while the data is loading.
    if (allConvs === null) {
        return (
            <div className={`flex-1 flex items-center justify-center bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}>
                <p className="text-sm text-[#699a32]">Loading every conversation for the report…</p>
            </div>
        );
    }

    return (
        <div className={`flex-1 overflow-y-auto bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}>

            {/* Header */}
            <div className="flex items-start justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-[#16270c] tracking-tight">Reports</h1>
                    <p className="text-sm text-[#699a32] mt-0.5">{rangeLabel(range)} · {filteredConvs.length} conversations</p>
                </div>
                <div className="flex items-center gap-2">
                    {/* Range selector */}
                    <select
                        value={range}
                        onChange={(e) => setRange(e.target.value as Range)}
                        className="h-9 px-3 text-xs bg-white border border-[#b5da8b] rounded-lg text-[#16270c] font-medium focus:outline-none focus:ring-2 focus:ring-[#589b31] appearance-none cursor-pointer"
                        style={{ fontSize: 13 }}
                    >
                        <option value="7d">Last 7 days</option>
                        <option value="30d">Last 30 days</option>
                        <option value="90d">Last 90 days</option>
                        <option value="custom">Custom range</option>
                    </select>
                    {range === "custom" && (
                        <>
                            <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)}
                                className="h-9 px-2 text-xs bg-white border border-[#b5da8b] rounded-lg text-[#16270c]" />
                            <span className="text-[#9ccd65] text-xs">to</span>
                            <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)}
                                className="h-9 px-2 text-xs bg-white border border-[#b5da8b] rounded-lg text-[#16270c]" />
                        </>
                    )}
                    <button
                        onClick={exportCSV}
                        className="h-9 px-4 rounded-lg text-xs font-semibold bg-[#589b31] text-white hover:bg-[#427425] transition-colors flex items-center gap-1.5"
                    >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        Export CSV
                    </button>
                </div>
            </div>

            {/* Tab nav */}
            <div className="flex gap-1 mb-5 border-b border-[#cee6b2]">
                {(["overview", "conversations", "orders", "agents", "unanswered", "followups", "photos"] as ReportTab[]).map((t) => (
                    <button key={t} onClick={() => setTab(t)}
                        className={`px-4 py-2 text-xs font-semibold transition-colors border-b-2 -mb-px ${
                            tab === t
                                ? "text-[#427425] border-[#427425]"
                                : "text-[#9ccd65] border-transparent hover:text-[#427425]"
                        }`}
                    >{TAB_LABEL[t]}</button>
                ))}
            </div>

            {/* ── OVERVIEW ──────────────────────────────────────────────────── */}
            {tab === "overview" && (
                <div className="space-y-4">
                    <div className={`grid gap-3 ${isMobile ? "grid-cols-2" : "grid-cols-4"}`}>
                        <StatBox label="Total Conversations" value={filteredConvs.length}
                            sub={`${humanConvs} human · ${aiConvs} Neema`} accent="border-l-[#589b31]" />
                        <StatBox label="Revenue" value={fmtCurrency(totalRevenue)}
                            sub={`${filteredOrders.length} orders`} accent="border-l-[#427425]" />
                        <StatBox label="Pending Orders" value={pendingOrders}
                            sub="Awaiting confirmation" accent="border-l-[#bcc13e]" />
                        <StatBox label="Delivered Orders" value={deliveredOrders}
                            sub={`${filteredOrders.length > 0 ? Math.round((deliveredOrders/filteredOrders.length)*100) : 0}% delivery rate`}
                            accent="border-l-[#2a48a2]" />
                    </div>

                    <div className={`grid gap-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"}`}>
                        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm p-5">
                            <div className="text-xs font-bold text-[#9ccd65] uppercase tracking-wider mb-3">
                                Conversations over time
                            </div>
                            <MiniBar data={convByDay} color="#589b31" />
                        </div>
                        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm p-5">
                            <div className="text-xs font-bold text-[#9ccd65] uppercase tracking-wider mb-3">
                                Revenue over time (KES)
                            </div>
                            <MiniBar data={orderByDay} color="#2a48a2" />
                        </div>
                    </div>

                    <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm p-5">
                        <div className="text-xs font-bold text-[#9ccd65] uppercase tracking-wider mb-4">Order Status Breakdown</div>
                        <div className="grid grid-cols-4 gap-3">
                            {[
                                { label: "Pending",   color: "#bcc13e", count: filteredOrders.filter((o) => o.status === "pending").length },
                                { label: "Confirmed", color: "#2a48a2", count: filteredOrders.filter((o) => o.status === "confirmed").length },
                                { label: "Delivered", color: "#589b31", count: filteredOrders.filter((o) => o.status === "delivered").length },
                                { label: "Cancelled", color: "#c0392b", count: filteredOrders.filter((o) => o.status === "cancelled").length },
                            ].map((item) => (
                                <div key={item.label} className="text-center">
                                    <div className="text-xl font-bold tabular-nums" style={{ color: item.color }}>{item.count}</div>
                                    <div className="text-xs text-[#9ccd65] mt-0.5">{item.label}</div>
                                    <div className="h-1 rounded-full mt-2 bg-[#e6f3d8] overflow-hidden">
                                        <div className="h-full rounded-full" style={{
                                            width: `${filteredOrders.length ? (item.count / filteredOrders.length) * 100 : 0}%`,
                                            backgroundColor: item.color,
                                        }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* ── CONVERSATIONS ─────────────────────────────────────────────── */}
            {tab === "conversations" && (
                <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-[#e6f3d8] flex items-center justify-between">
                        <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">
                            {filteredConvs.length} conversations in period
                        </span>
                    </div>
                    <Table
                        cols={["Customer", "Channel", "Status", "Mode", "Last Activity", "Agent"]}
                        rows={filteredConvs.slice(0, 50).map((c) => [
                            displayName(c.name, c.wa_id),
                            <span className="capitalize">{c.channel || "whatsapp"}</span>,
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${c.status === "open" ? "bg-[#f0f9ec] text-[#427425]" : "bg-[#e6f3d8] text-[#699a32]"}`}>{c.status}</span>,
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${c.intercept_mode === "human" ? "bg-amber-50 text-amber-700" : c.intercept_mode === "ai" ? "bg-blue-50 text-blue-700" : "bg-[#e6f3d8] text-[#699a32]"}`}>{c.intercept_mode}</span>,
                            timeAgo(c.last_message_at),
                            agents.find((a) => a.id === c.assigned_agent_id)?.name || "—",
                        ])}
                    />
                </div>
            )}

            {/* ── ORDERS ────────────────────────────────────────────────────── */}
            {tab === "orders" && (
                <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-[#e6f3d8] flex items-center justify-between">
                        <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">
                            {filteredOrders.length} orders · {fmtCurrency(totalRevenue)} total
                        </span>
                    </div>
                    <Table cols={["Customer", "Phone", "Amount", "Status", "Date"]} rows={orderRows} />
                </div>
            )}

            {/* ── NEVER ANSWERED ────────────────────────────────────────────── */}
            {tab === "unanswered" && <UnansweredPanel onToast={onToast} />}
            {tab === "photos" && <PhotoChecksPanel onToast={onToast} />}

            {/* ── FOLLOW-UPS ────────────────────────────────────────────────── */}
            {tab === "followups" && <FollowUpsPanel />}

            {/* ── AGENTS ────────────────────────────────────────────────────── */}
            {tab === "agents" && (
                <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-[#e6f3d8]">
                        <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">Agent Performance</span>
                    </div>
                    <Table
                        cols={["Agent", "Role", "Conversations", "Revenue", "Status"]}
                        rows={agentStats.map((a) => [
                            a.name,
                            <span className="capitalize text-[10px] px-1.5 py-0.5 bg-[#f0f9ec] text-[#427425] border border-[#b5da8b] rounded font-semibold">{a.role}</span>,
                            a.handled,
                            fmtCurrency(a.revenue),
                            <span className={`flex items-center gap-1 text-[10px] font-medium ${a.is_available ? "text-[#589b31]" : "text-[#9ccd65]"}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${a.is_available ? "bg-[#589b31]" : "bg-stone-300"}`} />
                                {a.is_available ? "Online" : "Offline"}
                            </span>,
                        ])}
                    />
                </div>
            )}
        </div>
    );
}