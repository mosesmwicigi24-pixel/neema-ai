import React, { useEffect, useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { timeAgo, fmtCurrency, fmtDate } from "@/lib/utils";
import { ALL_CHANNELS, CHANNEL_CONFIG } from "@/lib/channels";
import { statsApi } from "@/lib/api";
import type { Conversation, Agent, Order, CatalogItem, SharedViewProps } from "@/types";
import type { ApiStats } from "@/lib/api";

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
    loading?: boolean;
}

function StatCard({ label, value, sub, icon, accent, trend, loading }: StatCardProps) {
    return (
        <div className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 border-t-2 ${accent}`}>
            <div className="flex items-start justify-between mb-3">
                <span className="text-xl">{icon}</span>
                {trend && (
                    <span className={`text-xs font-semibold flex items-center gap-0.5 ${trend.positive ? "text-emerald-600" : "text-red-500"}`}>
                        {trend.positive ? "↑" : "↓"} {trend.value}%
                    </span>
                )}
            </div>
            {loading ? (
                <div className="h-8 w-16 bg-stone-100 rounded animate-pulse mb-1" />
            ) : (
                <div className="text-2xl font-bold text-stone-800 mb-0.5 tabular-nums">{value}</div>
            )}
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
    onToast,
}: OverviewViewProps): React.ReactElement {
    const [apiStats,     setApiStats]     = useState<ApiStats | null>(null);
    const [statsLoading, setStatsLoading] = useState(true);

    useEffect(() => {
        setStatsLoading(true);
        statsApi.overview()
            .then(setApiStats)
            .catch(() => setApiStats(null))
            .finally(() => setStatsLoading(false));

        const timer = setInterval(() => {
            statsApi.overview().then(setApiStats).catch(() => {});
        }, 30000);
        return () => clearInterval(timer);
    }, []);

    // Use API stats when available, computed from props as fallback
    const stats = {
        openConvs:      apiStats?.open_conversations   ?? conversations.filter((c) => c.status === "open").length,
        humanConvs:     apiStats?.human_conversations  ?? conversations.filter((c) => c.intercept_mode === "human").length,
        aiConvs:        apiStats?.ai_conversations     ?? conversations.filter((c) => c.intercept_mode === "ai").length,
        activeAgents:   apiStats?.active_agents        ?? agents.filter((a) => a.is_available).length,
        totalAgents:    apiStats?.total_agents         ?? agents.length,
        revenue:        apiStats?.total_revenue        ?? orders.filter((o) => o.status !== "cancelled").reduce((s, o) => s + (o.subtotal ?? 0), 0),
        totalOrders:    apiStats?.total_orders         ?? orders.length,
        pendingOrders:  apiStats?.pending_orders       ?? orders.filter((o) => o.status === "pending").length,
        deliveredOrders:apiStats?.delivered_orders     ?? orders.filter((o) => o.status === "delivered").length,
        confirmedOrders:apiStats?.confirmed_orders     ?? orders.filter((o) => o.status === "confirmed").length,
        cancelledOrders:apiStats?.cancelled_orders     ?? orders.filter((o) => o.status === "cancelled").length,
        inStockItems:   apiStats?.in_stock_items       ?? catalog.filter((c) => c.in_stock).length,
        totalItems:     apiStats?.total_items          ?? catalog.length,
    };

    // Channel breakdown
    const channelBreakdown = apiStats?.channel_breakdown
        ? apiStats.channel_breakdown.filter((x) => x.count > 0).map((x) => ({
              ch: x.channel, count: x.count, open: x.open,
          }))
        : ALL_CHANNELS.map((ch) => ({
              ch,
              count: conversations.filter((c) => c.channel === ch).length,
              open:  conversations.filter((c) => c.channel === ch && c.status === "open").length,
          })).filter((x) => x.count > 0);

    const totalConvs = Math.max(conversations.length, 1);

    const orderStatusItems = [
        { label: "Delivered", count: stats.deliveredOrders, color: "bg-emerald-500", text: "text-emerald-600" },
        { label: "Confirmed", count: stats.confirmedOrders, color: "bg-blue-500",    text: "text-blue-600"    },
        { label: "Pending",   count: stats.pendingOrders,   color: "bg-amber-400",   text: "text-amber-600"   },
        { label: "Cancelled", count: stats.cancelledOrders, color: "bg-red-400",     text: "text-red-500"     },
    ];

    // Build real activity feed from live props data
    const recentActivity: {
        id: string; user: string; action: string; target?: string; at: string; icon: string;
    }[] = [];

    // Recent orders
    [...orders]
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
        .slice(0, 4)
        .forEach((o) => {
            recentActivity.push({
                id:     `order-${o.id}`,
                user:   o.contact_name || o.contact_phone,
                action: `placed an order`,
                target: fmtCurrency(o.total || o.subtotal),
                at:     o.created_at,
                icon:   "📦",
            });
        });

    // Recent human intercepts from conversations
    conversations
        .filter((c) => c.intercept_mode === "human" && c.last_message_at)
        .sort((a, b) => new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime())
        .slice(0, 3)
        .forEach((c) => {
            const agentName = agents.find((a) => a.id === c.assigned_agent_id)?.name ?? "An agent";
            recentActivity.push({
                id:     `conv-${c.id}`,
                user:   agentName,
                action: "intercepted conversation with",
                target: c.name ?? c.wa_id,
                at:     c.last_message_at,
                icon:   "⚡",
            });
        });

    // Sort combined activity by time
    recentActivity.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
    const activityFeed = recentActivity.slice(0, 8);

    // Revenue per day from real orders (last 7 days)
    const now = new Date();
    const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const barData = Array.from({ length: 7 }, (_, i) => {
        const d   = new Date(now);
        d.setDate(now.getDate() - (6 - i));
        const key = d.toDateString();
        const val = orders
            .filter((o) => {
                const od = new Date(o.created_at);
                return od.toDateString() === key && o.status !== "cancelled";
            })
            .reduce((s, o) => s + (o.total || o.subtotal || 0), 0);
        return { label: DAY_LABELS[d.getDay()], value: val, isToday: i === 6 };
    });
    const maxBar = Math.max(...barData.map((d) => d.value), 1);

    // Top products from real orders
    const productMap: Record<string, { name: string; qty: number; revenue: number }> = {};
    orders.filter((o) => o.status !== "cancelled").forEach((o) => {
        (o.items ?? []).forEach((item) => {
            const k = item.name;
            if (!productMap[k]) productMap[k] = { name: k, qty: 0, revenue: 0 };
            productMap[k].qty     += (item.qty || item.quantity || 1);
            productMap[k].revenue += (item.total || (item.unit_price * (item.quantity || item.qty || 1)) || 0);
        });
    });
    const topProducts = Object.values(productMap)
        .sort((a, b) => b.revenue - a.revenue)
        .slice(0, 5);

    return (
        <div className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}>

            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">Overview</h1>
                    <p className="text-sm text-stone-400 mt-0.5">Real-time metrics and platform performance</p>
                </div>
                {statsLoading && (
                    <div className="flex items-center gap-1.5 text-xs text-stone-400">
                        <div className="w-3 h-3 border-2 border-stone-300 border-t-green-600 rounded-full animate-spin" />
                        Refreshing…
                    </div>
                )}
            </div>

            {/* Stat grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-5">
                <StatCard label="Open Conversations" value={stats.openConvs}
                    sub={`${stats.humanConvs} with agents`} icon="💬" accent="border-t-green-600"
                    loading={statsLoading && !apiStats} />
                <StatCard label="Active Agents" value={stats.activeAgents}
                    sub={`of ${stats.totalAgents} total`} icon="👥" accent="border-t-emerald-400"
                    loading={statsLoading && !apiStats} />
                <StatCard label="Total Revenue" value={fmtCurrency(stats.revenue)}
                    sub={`${stats.totalOrders} orders`} icon="💰" accent="border-t-green-600"
                    loading={statsLoading && !apiStats} />
                <StatCard label="Pending Orders" value={stats.pendingOrders}
                    sub="Awaiting confirmation" icon="📦" accent="border-t-orange-400"
                    loading={statsLoading && !apiStats} />
                <StatCard label="AI Conversations" value={stats.aiConvs}
                    sub="Fully automated" icon="🤖" accent="border-t-blue-400"
                    loading={statsLoading && !apiStats} />
                <StatCard label="Catalog Items" value={stats.totalItems}
                    sub={`${stats.inStockItems} in stock`} icon="📦" accent="border-t-violet-400"
                    loading={statsLoading && !apiStats} />
            </div>

            {/* Charts row */}
            <div className={`grid gap-4 mb-4 ${isMobile ? "grid-cols-1" : "grid-cols-5"}`}>

                {/* Revenue bar chart — real 7-day data */}
                <div className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-3"}`}>
                    <div className="flex items-center justify-between mb-4">
                        <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider">
                            7-Day Revenue (KES)
                        </div>
                        <div className="text-xs font-bold text-green-800">
                            {fmtCurrency(barData.reduce((s, d) => s + d.value, 0))}
                        </div>
                    </div>
                    <div className="flex items-end gap-2 h-28">
                        {barData.map((d, i) => (
                            <div key={i} className="flex-1 flex flex-col items-center gap-1.5 h-full group">
                                <div className="flex-1 flex items-end w-full">
                                    <div
                                        className={`w-full rounded-t-md transition-all duration-700 ${d.isToday ? "bg-green-700" : "bg-stone-200 group-hover:bg-green-400"}`}
                                        style={{ height: `${(d.value / maxBar) * 100}%`, minHeight: d.value > 0 ? 4 : 0 }}
                                        title={fmtCurrency(d.value)}
                                    />
                                </div>
                                <span className={`text-[10px] font-medium ${d.isToday ? "text-green-800" : "text-stone-400"}`}>
                                    {d.label}
                                </span>
                            </div>
                        ))}
                    </div>
                    {barData.every((d) => d.value === 0) && (
                        <p className="text-xs text-stone-400 text-center mt-2">No orders in the last 7 days</p>
                    )}
                </div>

                {/* Order status breakdown */}
                <div className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-2"}`}>
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">Order Status</div>
                    <div className="space-y-3.5">
                        {orderStatusItems.map((item) => (
                            <div key={item.label}>
                                <div className="flex justify-between mb-1.5">
                                    <span className="text-xs font-medium text-stone-500">{item.label}</span>
                                    <span className={`text-xs font-bold ${item.text}`}>{item.count}</span>
                                </div>
                                <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full ${item.color} rounded-full transition-all duration-700`}
                                        style={{ width: `${stats.totalOrders ? (item.count / stats.totalOrders) * 100 : 0}%` }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Bottom row */}
            <div className={`grid gap-4 mb-4 ${isMobile ? "grid-cols-1" : "grid-cols-5"}`}>

                {/* Channel breakdown */}
                <div className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-2"}`}>
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">By Channel</div>
                    {channelBreakdown.length === 0 ? (
                        <p className="text-xs text-stone-400 text-center py-6">No channel data yet</p>
                    ) : (
                        <div className="space-y-3.5">
                            {channelBreakdown.map(({ ch, count, open }) => {
                                const cfg = CHANNEL_CONFIG[ch as keyof typeof CHANNEL_CONFIG];
                                if (!cfg) return null;
                                return (
                                    <div key={ch} className="flex items-center gap-3">
                                        <div className="w-7 h-7 rounded-lg flex items-center justify-center text-white flex-shrink-0 text-sm"
                                            style={{ backgroundColor: cfg.color }}>
                                            {cfg.icon}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex justify-between mb-1.5">
                                                <span className="text-xs font-semibold text-stone-600">{cfg.label}</span>
                                                <span className="text-xs text-stone-400">{count} · {open} open</span>
                                            </div>
                                            <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                                                <div className="h-full rounded-full transition-all duration-700"
                                                    style={{ width: `${(count / totalConvs) * 100}%`, backgroundColor: cfg.color }} />
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* Activity feed — real data */}
                <div className={`bg-white rounded-xl border border-stone-100 shadow-sm p-5 ${isMobile ? "" : "col-span-3"}`}>
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">Recent Activity</div>
                    {activityFeed.length === 0 ? (
                        <p className="text-xs text-stone-400 text-center py-6">No activity yet</p>
                    ) : (
                        <div className="space-y-0 divide-y divide-stone-50">
                            {activityFeed.map((entry) => (
                                <div key={entry.id} className="flex items-center gap-3 py-2.5">
                                    <div className="w-7 h-7 rounded-lg bg-stone-50 border border-stone-100 flex items-center justify-center text-sm flex-shrink-0">
                                        {entry.icon}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-xs text-stone-600 truncate">
                                            <span className="font-semibold text-stone-800">{entry.user}</span>{" "}
                                            {entry.action}
                                            {entry.target && (
                                                <span className="text-green-700"> · {entry.target}</span>
                                            )}
                                        </p>
                                    </div>
                                    <span className="text-[10px] text-stone-400 flex-shrink-0">{timeAgo(entry.at)}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* Top products — real data */}
            {topProducts.length > 0 && (
                <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-4">Top Products by Revenue</div>
                    <div className="space-y-2">
                        {topProducts.map((p, i) => {
                            const maxRev = topProducts[0].revenue || 1;
                            return (
                                <div key={p.name} className="flex items-center gap-3">
                                    <span className="text-xs font-bold text-stone-300 w-4 flex-shrink-0">{i + 1}</span>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex justify-between mb-1">
                                            <span className="text-xs font-semibold text-stone-700 truncate">{p.name}</span>
                                            <span className="text-xs font-bold text-green-800 ml-2 flex-shrink-0">{fmtCurrency(p.revenue)}</span>
                                        </div>
                                        <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                                            <div className="h-full bg-green-600 rounded-full"
                                                style={{ width: `${(p.revenue / maxRev) * 100}%` }} />
                                        </div>
                                    </div>
                                    <span className="text-[10px] text-stone-400 flex-shrink-0 w-10 text-right">×{p.qty}</span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}