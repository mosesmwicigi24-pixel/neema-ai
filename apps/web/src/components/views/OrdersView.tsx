import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { timeAgo, fmtCurrency, fmtDate } from "@/lib/utils";
import { ordersApi } from "@/lib/api";
import type { Order, OrderStatus, SharedViewProps } from "@/types";

interface OrdersViewProps extends SharedViewProps {
    orders: Order[];
    setOrders: React.Dispatch<React.SetStateAction<Order[]>>;
    refetchOrders?: () => void;
}

type FilterStatus = "all" | OrderStatus;

const STATUS_ACTIONS: Record<OrderStatus, { next: OrderStatus[] }> = {
    pending:   { next: ["confirmed", "cancelled"] },
    confirmed: { next: ["delivered", "cancelled"] },
    delivered: { next: [] },
    cancelled: { next: [] },
};

const STATUS_META: Record<OrderStatus, {
    label: string; dot: string; text: string; bg: string; border: string;
}> = {
    pending:   { label: "Pending",   dot: "bg-amber-400",   text: "text-amber-700",   bg: "bg-amber-50",   border: "border-amber-200"   },
    confirmed: { label: "Confirmed", dot: "bg-blue-400",    text: "text-blue-700",    bg: "bg-blue-50",    border: "border-blue-200"    },
    delivered: { label: "Delivered", dot: "bg-emerald-400", text: "text-emerald-700", bg: "bg-emerald-50", border: "border-emerald-200" },
    cancelled: { label: "Cancelled", dot: "bg-red-400",     text: "text-red-700",     bg: "bg-red-50",     border: "border-red-200"     },
};

export function OrdersView({
    orders,
    setOrders,
    onToast,
    isMobile,
    refetchOrders,
}: OrdersViewProps): React.ReactElement {
    const [filter,   setFilter]   = useState<FilterStatus>("all");
    const [search,   setSearch]   = useState("");
    const [selected, setSelected] = useState<Order | null>(null);
    const [updating, setUpdating] = useState<string | null>(null);

    const filtered = orders.filter((o) => {
        if (filter !== "all" && o.status !== filter) return false;
        if (search) {
            const q = search.toLowerCase();
            return (
                o.contact_name.toLowerCase().includes(q) ||
                o.contact_phone.includes(q) ||
                (o.id || "").toLowerCase().includes(q)
            );
        }
        return true;
    });

    const updateStatus = async (id: string, status: OrderStatus) => {
        setUpdating(id);
        try {
            await ordersApi.updateStatus(id, status);
            refetchOrders?.();
            if (selected?.id === id) setSelected(null);
            onToast(`Order marked as ${status}`);
        } catch {
            onToast("Failed to update order", "error");
        } finally {
            setUpdating(null);
        }
    };

    const statusCounts = Object.keys(STATUS_META).reduce<Record<string, number>>((acc, s) => {
        acc[s] = orders.filter((o) => o.status === s).length;
        return acc;
    }, {});

    const totalRevenue = orders
        .filter((o) => o.status !== "cancelled")
        .reduce((s, o) => s + (o.total || o.subtotal || 0), 0);

    return (
        <div className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}>

            {/* Header */}
            <div className="flex items-start justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">Orders</h1>
                    <p className="text-sm text-stone-400 mt-0.5">
                        {orders.length} total
                        {statusCounts.pending > 0 && (
                            <span className="ml-1.5 text-amber-600 font-medium">
                                · {statusCounts.pending} pending
                            </span>
                        )}
                    </p>
                </div>
                {/* Revenue summary pill */}
                <div className="bg-white border border-stone-100 rounded-xl px-4 py-2.5 shadow-sm text-right flex-shrink-0">
                    <div className="text-xs text-stone-400 font-medium mb-0.5">Total Revenue</div>
                    <div className="text-base font-bold text-green-800">{fmtCurrency(totalRevenue)}</div>
                </div>
            </div>

            {/* Status summary cards */}
            <div className={`grid gap-3 mb-5 ${isMobile ? "grid-cols-2" : "grid-cols-4"}`}>
                {(["pending", "confirmed", "delivered", "cancelled"] as OrderStatus[]).map((s) => {
                    const meta  = STATUS_META[s];
                    const count = statusCounts[s] ?? 0;
                    const rev   = orders.filter((o) => o.status === s).reduce((sum, o) => sum + (o.total || o.subtotal || 0), 0);
                    return (
                        <button
                            key={s}
                            onClick={() => setFilter(filter === s ? "all" : s)}
                            className={`bg-white rounded-xl border shadow-sm p-3.5 text-left transition-all hover:shadow-md ${
                                filter === s ? `${meta.border} ring-1 ring-inset ${meta.border}` : "border-stone-100"
                            }`}
                        >
                            <div className="flex items-center gap-1.5 mb-2">
                                <div className={`w-2 h-2 rounded-full ${meta.dot}`} />
                                <span className={`text-xs font-semibold ${meta.text}`}>{meta.label}</span>
                            </div>
                            <div className="text-xl font-bold text-stone-800">{count}</div>
                            {rev > 0 && (
                                <div className="text-xs text-stone-400 mt-0.5">{fmtCurrency(rev)}</div>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Search + filter row */}
            <div className="flex gap-2 mb-4">
                <div className="relative flex-1">
                    <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-300"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search by name or phone…"
                        className="w-full h-9 pl-9 pr-3 text-sm bg-white border border-stone-200 rounded-xl text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent"
                        style={{ fontSize: 16 }}
                    />
                </div>
                {filter !== "all" && (
                    <button
                        onClick={() => setFilter("all")}
                        className="h-9 px-3 rounded-xl text-xs font-semibold bg-stone-800 text-white border border-stone-800 flex items-center gap-1.5"
                    >
                        {STATUS_META[filter]?.label} ✕
                    </button>
                )}
            </div>

            {/* Orders list */}
            <div className="bg-white rounded-xl border border-stone-100 shadow-sm overflow-hidden">
                {filtered.length === 0 ? (
                    <div className="py-16 text-center">
                        <span className="text-3xl mb-3 block">📦</span>
                        <p className="text-sm text-stone-400">No orders found</p>
                    </div>
                ) : (
                    <div className="divide-y divide-stone-50">
                        {filtered.map((order) => {
                            const meta = STATUS_META[order.status] ?? STATUS_META.pending;
                            const isUpdating = updating === order.id;
                            const itemSummary = (order.items ?? []).slice(0, 2)
                                .map((i) => `${i.name}${(i.qty || i.quantity || 1) > 1 ? ` ×${i.qty || i.quantity}` : ""}`)
                                .join(", ");
                            const extraItems = (order.items?.length ?? 0) - 2;

                            return (
                                <div
                                    key={order.id}
                                    className="flex items-center gap-3 px-4 py-3.5 hover:bg-stone-50 transition-colors cursor-pointer"
                                    onClick={() => setSelected(order)}
                                >
                                    <Avatar name={order.contact_name} size={38} />
                                    <div className="flex-1 min-w-0">
                                        {/* Row 1: name + status badge */}
                                        <div className="flex items-center gap-2 mb-0.5">
                                            <span className="text-sm font-semibold text-stone-800 truncate">
                                                {order.contact_name}
                                            </span>
                                            <span className={`flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded font-semibold border ${meta.bg} ${meta.text} ${meta.border}`}>
                                                {meta.label}
                                            </span>
                                        </div>
                                        {/* Row 2: phone + item summary */}
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                            <span className="text-xs text-stone-400 font-mono">
                                                +{order.contact_phone}
                                            </span>
                                            {itemSummary && (
                                                <>
                                                    <span className="text-stone-200">·</span>
                                                    <span className="text-xs text-stone-500 truncate max-w-[220px]">
                                                        {itemSummary}
                                                        {extraItems > 0 && ` +${extraItems} more`}
                                                    </span>
                                                </>
                                            )}
                                        </div>
                                        {/* Row 3: time */}
                                        <div className="text-[10px] text-stone-400 mt-0.5">
                                            {timeAgo(order.created_at)}
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0">
                                        <div className="text-sm font-bold text-stone-800">
                                            {fmtCurrency(order.total || order.subtotal)}
                                        </div>
                                        <div className="text-[10px] text-stone-400 mt-0.5">
                                            {order.currency ?? "KES"}
                                        </div>
                                        {isUpdating && (
                                            <div className="w-4 h-4 border-2 border-green-700 border-t-transparent rounded-full animate-spin mx-auto mt-1" />
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Order detail modal */}
            <Modal
                show={!!selected}
                onClose={() => setSelected(null)}
                title={selected ? `Order — ${selected.contact_name}` : "Order"}
            >
                {selected && (() => {
                    const meta    = STATUS_META[selected.status] ?? STATUS_META.pending;
                    const actions = STATUS_ACTIONS[selected.status]?.next ?? [];
                    return (
                        <>
                            {/* Customer info */}
                            <div className="flex items-center gap-3 mb-4 p-3 bg-stone-50 rounded-xl border border-stone-100">
                                <Avatar name={selected.contact_name} size={40} />
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-bold text-stone-800">{selected.contact_name}</div>
                                    <div className="text-xs text-stone-400 font-mono">+{selected.contact_phone}</div>
                                </div>
                                <span className={`text-xs px-2 py-1 rounded-lg font-semibold border ${meta.bg} ${meta.text} ${meta.border}`}>
                                    {meta.label}
                                </span>
                            </div>

                            {/* Meta row */}
                            <div className="grid grid-cols-2 gap-2 mb-4">
                                {[
                                    { label: "Order ID",  value: selected.id.slice(-8).toUpperCase() },
                                    { label: "Date",      value: fmtDate(selected.created_at) },
                                    { label: "Channel",   value: selected.wa_id ? "WhatsApp" : "—" },
                                    { label: "Currency",  value: selected.currency ?? "KES" },
                                ].map((r) => (
                                    <div key={r.label} className="bg-stone-50 rounded-lg px-3 py-2">
                                        <div className="text-[10px] text-stone-400 uppercase tracking-wide font-semibold">{r.label}</div>
                                        <div className="text-xs font-semibold text-stone-700 mt-0.5">{r.value}</div>
                                    </div>
                                ))}
                            </div>

                            {/* Items */}
                            <div className="mb-4">
                                <div className="text-[10px] font-bold text-stone-400 uppercase tracking-widest mb-2">Items</div>
                                <div className="bg-stone-50 rounded-xl p-3 space-y-2 border border-stone-100">
                                    {(selected.items ?? []).length === 0 ? (
                                        <p className="text-xs text-stone-400 text-center py-2">No items recorded</p>
                                    ) : (
                                        (selected.items ?? []).map((item, i) => (
                                            <div key={i} className="flex items-start justify-between gap-2">
                                                <div className="flex-1 min-w-0">
                                                    <span className="text-xs text-stone-700 font-medium">{item.name}</span>
                                                    {item.sku && (
                                                        <span className="ml-1.5 text-[10px] text-stone-400 font-mono">{item.sku}</span>
                                                    )}
                                                </div>
                                                <div className="text-right flex-shrink-0">
                                                    <div className="text-xs font-semibold text-stone-800">
                                                        {fmtCurrency(item.unit_price * (item.quantity || item.qty || 1))}
                                                    </div>
                                                    <div className="text-[10px] text-stone-400">
                                                        {fmtCurrency(item.unit_price)} × {item.quantity || item.qty || 1}
                                                    </div>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                    <div className="border-t border-stone-200 pt-2.5 mt-2 flex justify-between items-center">
                                        <span className="text-sm font-bold text-stone-800">Total</span>
                                        <span className="text-base font-bold text-green-800">
                                            {fmtCurrency(selected.total || selected.subtotal)}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            {/* Notes */}
                            {selected.notes && (
                                <div className="mb-4 p-2.5 bg-amber-50 border border-amber-200 rounded-lg">
                                    <div className="text-[10px] font-bold text-amber-600 uppercase tracking-wide mb-1">📝 Note</div>
                                    <p className="text-xs text-amber-800">{selected.notes}</p>
                                </div>
                            )}

                            {/* Status actions */}
                            {actions.length > 0 && (
                                <div className="flex gap-2 flex-wrap">
                                    {actions.map((next) => {
                                        const nextMeta = STATUS_META[next];
                                        return (
                                            <Btn
                                                key={next}
                                                onClick={() => updateStatus(selected.id, next)}
                                                variant={next === "cancelled" ? "danger" : "primary"}
                                                disabled={updating === selected.id}
                                            >
                                                Mark as {nextMeta.label}
                                            </Btn>
                                        );
                                    })}
                                </div>
                            )}
                        </>
                    );
                })()}
            </Modal>
        </div>
    );
}