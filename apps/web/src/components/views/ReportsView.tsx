// ReportsView.tsx
// Admin reports: conversations, transfers, orders, agent performance.

import React, { useState, useEffect, useCallback } from "react";
import { fmtCurrency, fmtDate, timeAgo, formatPhone } from "@/lib/utils";
import type { Conversation, Agent, Order, SharedViewProps } from "@/types";

interface ReportsViewProps extends SharedViewProps {
    conversations: Conversation[];
    agents: Agent[];
    orders: Order[];
}

type Range = "7d" | "30d" | "90d" | "custom";
type ReportTab = "overview" | "conversations" | "orders" | "agents";

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

export function ReportsView({ conversations, agents, orders, onToast, isMobile }: ReportsViewProps) {
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
        o.contact_name || o.wa_id,
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
            `${fmtDate(o.created_at)},${o.contact_name || o.wa_id},${o.total || o.subtotal},${o.status}`
        ).join("\n");
        const blob = new Blob([header + rows], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = `neema-report-${range}.csv`; a.click();
        URL.revokeObjectURL(url);
        onToast("Report exported");
    };

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
                {(["overview", "conversations", "orders", "agents"] as ReportTab[]).map((t) => (
                    <button key={t} onClick={() => setTab(t)}
                        className={`px-4 py-2 text-xs font-semibold capitalize transition-colors border-b-2 -mb-px ${
                            tab === t
                                ? "text-[#427425] border-[#427425]"
                                : "text-[#9ccd65] border-transparent hover:text-[#427425]"
                        }`}
                    >{t}</button>
                ))}
            </div>

            {/* ── OVERVIEW ──────────────────────────────────────────────────── */}
            {tab === "overview" && (
                <div className="space-y-4">
                    <div className={`grid gap-3 ${isMobile ? "grid-cols-2" : "grid-cols-4"}`}>
                        <StatBox label="Total Conversations" value={filteredConvs.length}
                            sub={`${humanConvs} human · ${aiConvs} AI`} accent="border-l-[#589b31]" />
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
                            c.name || c.wa_id,
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