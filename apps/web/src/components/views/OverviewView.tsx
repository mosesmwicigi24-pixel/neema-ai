import React from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Card, SectionHeader, StatCard } from "@/components/ui/Layout";
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

    // Conversations by channel
    const channelBreakdown = ALL_CHANNELS.map((ch) => ({
        ch,
        count: conversations.filter((c) => c.channel === ch).length,
        open: conversations.filter(
            (c) => c.channel === ch && c.status === "open",
        ).length,
    })).filter((x) => x.count > 0);

    return (
        <div
            className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            <SectionHeader
                title="Overview"
                subtitle="Real-time metrics and platform performance"
            />

            {/* Stat grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-5">
                <StatCard
                    label="Open Conversations"
                    value={stats.openConvs}
                    sub={`${stats.humanConvs} with agents`}
                    icon="💬"
                    accentColor="amber"
                    trend={{ value: 12, positive: true }}
                />
                <StatCard
                    label="Active Agents"
                    value={stats.activeAgents}
                    sub={`of ${agents.length} total`}
                    icon="👥"
                    accentColor="emerald"
                />
                <StatCard
                    label="Total Revenue"
                    value={fmtCurrency(stats.revenue)}
                    sub={`${orders.length} orders`}
                    icon="💰"
                    accentColor="amber"
                    trend={{ value: 8, positive: true }}
                />
                <StatCard
                    label="Pending Orders"
                    value={stats.pendingOrders}
                    sub="Awaiting confirmation"
                    icon="📦"
                    accentColor="orange"
                />
                <StatCard
                    label="AI Conversations"
                    value={stats.aiConvs}
                    sub="Fully automated"
                    icon="🤖"
                    accentColor="blue"
                />
                <StatCard
                    label="Catalog Items"
                    value={catalog.length}
                    sub={`${stats.inStockItems} in stock`}
                    icon="🍽"
                    accentColor="violet"
                />
            </div>

            {/* Charts row */}
            <div
                className={`grid gap-4 mb-4 ${isMobile ? "grid-cols-1" : "grid-cols-5"}`}
            >
                {/* Revenue bar chart */}
                <Card className={isMobile ? "" : "col-span-3"}>
                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4">
                        Weekly Revenue (KES)
                    </div>
                    <div className="flex items-end gap-2 h-28">
                        {BAR_DATA.map((d) => (
                            <div
                                key={d.label}
                                className="flex-1 flex flex-col items-center gap-1 h-full"
                            >
                                <div className="flex-1 flex items-end w-full">
                                    <div
                                        className="w-full rounded-t-md bg-gradient-to-t from-amber-500 to-amber-300 dark:from-amber-600 dark:to-amber-400 transition-all duration-700 min-h-[4px]"
                                        style={{
                                            height: `${(d.value / MAX_BAR) * 100}%`,
                                        }}
                                        title={fmtCurrency(d.value)}
                                    />
                                </div>
                                <span className="text-[10px] text-gray-400 font-medium">
                                    {d.label}
                                </span>
                            </div>
                        ))}
                    </div>
                </Card>

                {/* Order breakdown */}
                <Card className={isMobile ? "" : "col-span-2"}>
                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4">
                        Order Status
                    </div>
                    <div className="space-y-3">
                        {[
                            {
                                label: "Delivered",
                                count: stats.deliveredOrders,
                                color: "bg-emerald-500",
                                textColor:
                                    "text-emerald-600 dark:text-emerald-400",
                            },
                            {
                                label: "Confirmed",
                                count: orders.filter(
                                    (o) => o.status === "confirmed",
                                ).length,
                                color: "bg-blue-500",
                                textColor: "text-blue-600 dark:text-blue-400",
                            },
                            {
                                label: "Pending",
                                count: stats.pendingOrders,
                                color: "bg-amber-500",
                                textColor: "text-amber-600 dark:text-amber-400",
                            },
                            {
                                label: "Cancelled",
                                count: orders.filter(
                                    (o) => o.status === "cancelled",
                                ).length,
                                color: "bg-red-500",
                                textColor: "text-red-600 dark:text-red-400",
                            },
                        ].map((item) => (
                            <div key={item.label}>
                                <div className="flex justify-between mb-1.5">
                                    <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                                        {item.label}
                                    </span>
                                    <span
                                        className={`text-xs font-semibold ${item.textColor}`}
                                    >
                                        {item.count}
                                    </span>
                                </div>
                                <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
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
                </Card>
            </div>

            {/* Channel breakdown + activity */}
            <div
                className={`grid gap-4 ${isMobile ? "grid-cols-1" : "grid-cols-5"}`}
            >
                {/* Channel breakdown */}
                <Card className={isMobile ? "" : "col-span-2"}>
                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4">
                        Conversations by Channel
                    </div>
                    <div className="space-y-3">
                        {channelBreakdown.map(({ ch, count, open }) => {
                            const cfg = CHANNEL_CONFIG[ch];
                            return (
                                <div
                                    key={ch}
                                    className="flex items-center gap-3"
                                >
                                    <div
                                        className="w-7 h-7 rounded-lg flex items-center justify-center text-white flex-shrink-0"
                                        style={{ backgroundColor: cfg.color }}
                                    >
                                        {cfg.icon}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex justify-between mb-1">
                                            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                                                {cfg.label}
                                            </span>
                                            <span className="text-xs text-gray-400">
                                                {count} total · {open} open
                                            </span>
                                        </div>
                                        <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
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
                </Card>

                {/* Activity log */}
                <Card className={isMobile ? "" : "col-span-3"}>
                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4">
                        Activity Log
                    </div>
                    <div className="divide-y divide-gray-50 dark:divide-gray-800">
                        {ACTIVITY_LOG.map((entry) => (
                            <div
                                key={entry.id}
                                className="flex items-center gap-3 py-2.5"
                            >
                                <Avatar name={entry.user} size="xs" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm text-gray-700 dark:text-gray-300 truncate">
                                        <span className="font-semibold text-gray-900 dark:text-white">
                                            {entry.user}
                                        </span>{" "}
                                        {entry.action}
                                        {entry.target && (
                                            <span className="text-amber-600 dark:text-amber-400">
                                                {" "}
                                                · {entry.target}
                                            </span>
                                        )}
                                    </p>
                                </div>
                                <span className="text-[11px] text-gray-400 flex-shrink-0">
                                    {timeAgo(entry.at)}
                                </span>
                            </div>
                        ))}
                    </div>
                </Card>
            </div>
        </div>
    );
}