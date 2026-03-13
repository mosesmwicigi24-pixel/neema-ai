import React from "react";
import { Avatar } from "@/components/ui/Avatar";
import { timeAgo, fmtCurrency } from "@/lib/utils";
import { ACTIVITY_LOG } from "@/lib/mockData";
import { ALL_CHANNELS, CHANNEL_CONFIG } from "@/lib/channels";
import type {
    Conversation,
    Agent,
    Order,
    CatalogItem,
    SharedViewProps,
} from "@/types";

const BAR_DATA = [
    { label: "Mon", value: 820 },
    { label: "Tue", value: 1200 },
    { label: "Wed", value: 960 },
    { label: "Thu", value: 1400 },
    { label: "Fri", value: 1800 },
    { label: "Sat", value: 2100 },
    { label: "Sun", value: 950 },
];
const MAX_BAR = Math.max(...BAR_DATA.map((d) => d.value));

interface OverviewViewProps extends SharedViewProps {
    conversations: Conversation[];
    agents: Agent[];
    orders: Order[];
    catalog: CatalogItem[];
}

interface StatCardProps {
    label: string;
    value: string | number;
    sub: string;
    icon: string;
    accent: string;
    trend?: { value: number; positive: boolean };
}

function StatCard({ label, value, sub, icon, accent, trend }: StatCardProps) {
    return (
        <div
            className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 border-t-2 ${accent}`}
        >
            <div className="flex items-start justify-between mb-3">
                <span className="text-xl">{icon}</span>
                {trend && (
                    <span
                        className={`text-xs font-semibold flex items-center gap-0.5 ${trend.positive ? "text-emerald-600" : "text-red-500"}`}
                    >
                        {trend.positive ? "↑" : "↓"} {trend.value}%
                    </span>
                )}
            </div>
            <div className="text-2xl font-bold text-stone-800 mb-0.5 tabular-nums">
                {value}
            </div>
            <div className="text-xs font-semibold text-stone-500">{label}</div>
            <div className="text-xs text-stone-400 mt-0.5">{sub}</div>
        </div>
    );
}

export function OverviewView({
    conversations,
    agents,
    orders,
    catalog,
    isMobile,
}: OverviewViewProps): React.ReactElement {
    const stats = {
        openConvs: conversations.filter((c) => c.status === "open").length,
        humanConvs: conversations.filter((c) => c.intercept_mode === "human")
            .length,
        aiConvs: conversations.filter((c) => c.intercept_mode === "ai").length,
        activeAgents: agents.filter((a) => a.is_available).length,
        revenue: orders
            .filter((o) => o.status !== "cancelled")
            .reduce((s, o) => s + o.subtotal, 0),
        pendingOrders: orders.filter((o) => o.status === "pending").length,
        deliveredOrders: orders.filter((o) => o.status === "delivered").length,
        inStockItems: catalog.filter((c) => c.in_stock).length,
    };

    const channelBreakdown = ALL_CHANNELS.map((ch) => ({
        ch,
        count: conversations.filter((c) => c.channel === ch).length,
        open: conversations.filter(
            (c) => c.channel === ch && c.status === "open",
        ).length,
    })).filter((x) => x.count > 0);

    const orderStatusItems = [
        {
            label: "Delivered",
            count: stats.deliveredOrders,
            color: "bg-emerald-500",
            text: "text-emerald-600",
        },
        {
            label: "Confirmed",
            count: orders.filter((o) => o.status === "confirmed").length,
            color: "bg-blue-500",
            text: "text-blue-600",
        },
        {
            label: "Pending",
            count: stats.pendingOrders,
            color: "bg-amber-400",
            text: "text-amber-600",
        },
        {
            label: "Cancelled",
            count: orders.filter((o) => o.status === "cancelled").length,
            color: "bg-red-400",
            text: "text-red-600",
        },
    ];

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header */}
            <div className="mb-6">
                <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                    Overview
                </h1>
                <p className="text-sm text-stone-400 mt-0.5">
                    Real-time metrics and platform performance
                </p>
            </div>

            {/* Stat grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-5">
                <StatCard
                    label="Open Conversations"
                    value={stats.openConvs}
                    sub={`${stats.humanConvs} with agents`}
                    icon="💬"
                    accent="border-t-green-600"
                    trend={{ value: 12, positive: true }}
                />
                <StatCard
                    label="Active Agents"
                    value={stats.activeAgents}
                    sub={`of ${agents.length} total`}
                    icon="👥"
                    accent="border-t-emerald-400"
                />
                <StatCard
                    label="Total Revenue"
                    value={fmtCurrency(stats.revenue)}
                    sub={`${orders.length} orders`}
                    icon="💰"
                    accent="border-t-green-600"
                    trend={{ value: 8, positive: true }}
                />
                <StatCard
                    label="Pending Orders"
                    value={stats.pendingOrders}
                    sub="Awaiting confirmation"
                    icon="📦"
                    accent="border-t-orange-400"
                />
                <StatCard
                    label="AI Conversations"
                    value={stats.aiConvs}
                    sub="Fully automated"
                    icon="🤖"
                    accent="border-t-blue-400"
                />
                <StatCard
                    label="Catalog Items"
                    value={catalog.length}
                    sub={`${stats.inStockItems} in stock`}
                    icon="🍽"
                    accent="border-t-violet-400"
                />
            </div>

            {/* Charts row */}
            <div
                className={`grid gap-4 mb-4 ${isMobile ? "grid-cols-1" : "grid-cols-5"}`}
            >
                {/* Revenue bar chart */}
                <div
                    className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-3"}`}
                >
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">
                        Weekly Revenue (KES)
                    </div>
                    <div className="flex items-end gap-2 h-28">
                        {BAR_DATA.map((d, i) => {
                            const isToday = i === 5; // Saturday as highlight
                            return (
                                <div
                                    key={d.label}
                                    className="flex-1 flex flex-col items-center gap-1.5 h-full group"
                                >
                                    <div className="flex-1 flex items-end w-full relative">
                                        <div
                                            className={`w-full rounded-t-md transition-all duration-700 ${isToday ? "bg-green-700" : "bg-stone-200 group-hover:bg-green-500"}`}
                                            style={{
                                                height: `${(d.value / MAX_BAR) * 100}%`,
                                                minHeight: 4,
                                            }}
                                            title={fmtCurrency(d.value)}
                                        />
                                    </div>
                                    <span
                                        className={`text-[10px] font-medium ${isToday ? "text-green-800" : "text-stone-400"}`}
                                    >
                                        {d.label}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Order breakdown */}
                <div
                    className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-2"}`}
                >
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">
                        Order Status
                    </div>
                    <div className="space-y-3.5">
                        {orderStatusItems.map((item) => (
                            <div key={item.label}>
                                <div className="flex justify-between mb-1.5">
                                    <span className="text-xs font-medium text-stone-500">
                                        {item.label}
                                    </span>
                                    <span
                                        className={`text-xs font-bold ${item.text}`}
                                    >
                                        {item.count}
                                    </span>
                                </div>
                                <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full ${item.color} rounded-full transition-all duration-700`}
                                        style={{
                                            width: `${orders.length ? (item.count / orders.length) * 100 : 0}%`,
                                        }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Channel breakdown + activity */}
            <div
                className={`grid gap-4 ${isMobile ? "grid-cols-1" : "grid-cols-5"}`}
            >
                {/* Channel breakdown */}
                <div
                    className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-2"}`}
                >
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">
                        By Channel
                    </div>
                    <div className="space-y-3.5">
                        {channelBreakdown.map(({ ch, count, open }) => {
                            const cfg = CHANNEL_CONFIG[ch];
                            return (
                                <div
                                    key={ch}
                                    className="flex items-center gap-3"
                                >
                                    <div
                                        className="w-7 h-7 rounded-lg flex items-center justify-center text-white flex-shrink-0 text-sm"
                                        style={{ backgroundColor: cfg.color }}
                                    >
                                        {cfg.icon}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex justify-between mb-1.5">
                                            <span className="text-xs font-semibold text-stone-600">
                                                {cfg.label}
                                            </span>
                                            <span className="text-xs text-stone-400">
                                                {count} · {open} open
                                            </span>
                                        </div>
                                        <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                                            <div
                                                className="h-full rounded-full transition-all duration-700"
                                                style={{
                                                    width: `${(count / conversations.length) * 100}%`,
                                                    backgroundColor: cfg.color,
                                                }}
                                            />
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Activity log */}
                <div
                    className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-3"}`}
                >
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">
                        Activity Log
                    </div>
                    <div className="space-y-0 divide-y divide-stone-50">
                        {ACTIVITY_LOG.map((entry) => (
                            <div
                                key={entry.id}
                                className="flex items-center gap-3 py-2.5"
                            >
                                <Avatar name={entry.user} size="xs" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm text-stone-600 truncate">
                                        <span className="font-semibold text-stone-800">
                                            {entry.user}
                                        </span>{" "}
                                        {entry.action}
                                        {entry.target && (
                                            <span className="text-green-700">
                                                {" "}
                                                · {entry.target}
                                            </span>
                                        )}
                                    </p>
                                </div>
                                <span className="text-[11px] text-stone-400 flex-shrink-0">
                                    {timeAgo(entry.at)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
