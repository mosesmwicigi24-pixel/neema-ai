import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { StatusBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { timeAgo, fmtCurrency } from "@/lib/utils";
import { ordersApi } from "@/lib/api";
import type { Order, OrderStatus, SharedViewProps } from "@/types";

interface OrdersViewProps extends SharedViewProps {
    orders: Order[];
    setOrders: React.Dispatch<React.SetStateAction<Order[]>>;
    refetchOrders?: () => void;
}

type FilterStatus = "all" | OrderStatus;

const STATUS_ACTIONS: Record<OrderStatus, { next: OrderStatus[] }> = {
    pending: { next: ["confirmed", "cancelled"] },
    confirmed: { next: ["delivered", "cancelled"] },
    delivered: { next: [] },
    cancelled: { next: [] },
};

const STATUS_META: Record<
    OrderStatus,
    { label: string; dot: string; text: string; bg: string; border: string }
> = {
    pending: {
        label: "Pending",
        dot: "bg-amber-400",
        text: "text-amber-700",
        bg: "bg-amber-50",
        border: "border-amber-200",
    },
    confirmed: {
        label: "Confirmed",
        dot: "bg-blue-400",
        text: "text-blue-700",
        bg: "bg-blue-50",
        border: "border-blue-200",
    },
    delivered: {
        label: "Delivered",
        dot: "bg-emerald-400",
        text: "text-emerald-700",
        bg: "bg-emerald-50",
        border: "border-emerald-200",
    },
    cancelled: {
        label: "Cancelled",
        dot: "bg-red-400",
        text: "text-red-700",
        bg: "bg-red-50",
        border: "border-red-200",
    },
};

export function OrdersView({
    orders,
    setOrders,
    onToast,
    isMobile,
    refetchOrders,
}: OrdersViewProps): React.ReactElement {
    const [filter, setFilter] = useState<FilterStatus>("all");
    const [search, setSearch] = useState("");
    const [selected, setSelected] = useState<Order | null>(null);
    const [updating, setUpdating] = useState<string | null>(null);

    const filtered = orders.filter((o) => {
        if (filter !== "all" && o.status !== filter) return false;
        if (
            search &&
            !o.contact_name.toLowerCase().includes(search.toLowerCase()) &&
            !o.contact_phone.includes(search)
        )
            return false;
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

    const statusCounts = Object.keys(STATUS_META).reduce<
        Record<string, number>
    >((acc, s) => {
        acc[s] = orders.filter((o) => o.status === s).length;
        return acc;
    }, {});

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                        Orders
                    </h1>
                    <p className="text-sm text-stone-400 mt-0.5">
                        {orders.length} total
                        {statusCounts.pending > 0 && (
                            <span className="ml-1.5 text-amber-600 font-medium">
                                · {statusCounts.pending} pending
                            </span>
                        )}
                    </p>
                </div>
            </div>

            {/* Status filter pills */}
            <div className="flex gap-2 mb-4 overflow-x-auto scrollbar-none pb-1">
                {(
                    [
                        "all",
                        "pending",
                        "confirmed",
                        "delivered",
                        "cancelled",
                    ] as const
                ).map((s) => {
                    const meta = s !== "all" ? STATUS_META[s] : null;
                    const count =
                        s === "all" ? orders.length : (statusCounts[s] ?? 0);
                    return (
                        <button
                            key={s}
                            onClick={() => setFilter(s)}
                            className={`flex-shrink-0 flex items-center gap-1.5 h-8 px-3 rounded-lg border text-xs font-medium transition-all ${
                                filter === s
                                    ? "bg-stone-800 text-white border-stone-800"
                                    : "bg-white text-stone-500 border-stone-200 hover:border-stone-400"
                            }`}
                        >
                            {meta && (
                                <div
                                    className={`w-1.5 h-1.5 rounded-full ${meta.dot}`}
                                />
                            )}
                            <span className="capitalize">
                                {s === "all" ? "All Orders" : meta?.label}
                            </span>
                            <span
                                className={`text-[10px] font-bold ${filter === s ? "text-stone-300" : "text-stone-400"}`}
                            >
                                {count}
                            </span>
                        </button>
                    );
                })}
            </div>

            {/* Search */}
            <div className="relative mb-4">
                <svg
                    className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-300"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                </svg>
                <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search by name or phone…"
                    className="w-full h-10 pl-9 pr-3 text-sm bg-white border border-stone-200 rounded-xl text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent"
                    style={{ fontSize: 16 }}
                />
            </div>

            {/* Orders table */}
            <div className="bg-white rounded-xl border border-stone-100 shadow-sm overflow-hidden">
                {filtered.length === 0 ? (
                    <div className="py-16 text-center">
                        <span className="text-3xl mb-3 block">📦</span>
                        <p className="text-sm text-stone-400">
                            No orders found
                        </p>
                    </div>
                ) : (
                    <div className="divide-y divide-stone-50">
                        {filtered.map((order) => {
                            const meta =
                                STATUS_META[order.status] ??
                                STATUS_META.pending;
                            const isUpdating = updating === order.id;
                            return (
                                <div
                                    key={order.id}
                                    className="flex items-center gap-3 px-4 py-3.5 hover:bg-stone-50 transition-colors cursor-pointer"
                                    onClick={() => setSelected(order)}
                                >
                                    <Avatar
                                        name={order.contact_name}
                                        size={36}
                                    />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5">
                                            <span className="text-sm font-semibold text-stone-800 truncate">
                                                {order.contact_name}
                                            </span>
                                            <span
                                                className={`text-[10px] px-1.5 py-0.5 rounded font-semibold border ${meta.bg} ${meta.text} ${meta.border}`}
                                            >
                                                {meta.label}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs text-stone-400 font-mono">
                                                +{order.contact_phone}
                                            </span>
                                            <span className="text-stone-200">
                                                ·
                                            </span>
                                            <span className="text-xs text-stone-400">
                                                {order.items?.length ?? 0} item
                                                {(order.items?.length ?? 0) !==
                                                1
                                                    ? "s"
                                                    : ""}
                                            </span>
                                            <span className="text-stone-200">
                                                ·
                                            </span>
                                            <span className="text-xs text-stone-400">
                                                {timeAgo(order.created_at)}
                                            </span>
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0">
                                        <div className="text-sm font-bold text-stone-800">
                                            {fmtCurrency(order.total)}
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
                title={`Order · ${selected?.contact_name}`}
            >
                {selected &&
                    (() => {
                        const meta =
                            STATUS_META[selected.status] ?? STATUS_META.pending;
                        const actions =
                            STATUS_ACTIONS[selected.status]?.next ?? [];
                        return (
                            <>
                                <div className="flex items-center gap-2 mb-4">
                                    <span
                                        className={`text-xs px-2 py-1 rounded font-semibold border ${meta.bg} ${meta.text} ${meta.border}`}
                                    >
                                        {meta.label}
                                    </span>
                                    <span className="text-xs text-stone-400 font-mono">
                                        +{selected.contact_phone}
                                    </span>
                                </div>

                                {/* Items */}
                                <div className="bg-stone-50 rounded-xl p-3 mb-4 space-y-2">
                                    {(selected.items ?? []).map((item, i) => (
                                        <div
                                            key={i}
                                            className="flex justify-between text-sm"
                                        >
                                            <span className="text-stone-700">
                                                {item.name} × {item.quantity}
                                            </span>
                                            <span className="font-semibold text-stone-800">
                                                {fmtCurrency(
                                                    item.unit_price *
                                                        item.quantity,
                                                )}
                                            </span>
                                        </div>
                                    ))}
                                    {(selected.items ?? []).length === 0 && (
                                        <p className="text-xs text-stone-400 text-center py-2">
                                            No items recorded
                                        </p>
                                    )}
                                    <div className="border-t border-stone-200 pt-2 flex justify-between">
                                        <span className="text-sm font-semibold text-stone-800">
                                            Total
                                        </span>
                                        <span className="text-sm font-bold text-green-800">
                                            {fmtCurrency(selected.total)}
                                        </span>
                                    </div>
                                </div>

                                {selected.notes && (
                                    <p className="text-xs text-stone-500 bg-amber-50 border border-amber-200 rounded-lg p-2.5 mb-4">
                                        📝 {selected.notes}
                                    </p>
                                )}

                                {/* Status actions */}
                                {actions.length > 0 && (
                                    <div className="flex gap-2 flex-wrap">
                                        {actions.map((next) => {
                                            const nextMeta = STATUS_META[next];
                                            return (
                                                <Btn
                                                    key={next}
                                                    onClick={() =>
                                                        updateStatus(
                                                            selected.id,
                                                            next,
                                                        )
                                                    }
                                                    variant={
                                                        next === "cancelled"
                                                            ? "danger"
                                                            : "primary"
                                                    }
                                                    disabled={
                                                        updating === selected.id
                                                    }
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
