import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { StatusBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { timeAgo, fmtCurrency } from "@/lib/utils";
import type { Order, OrderStatus, SharedViewProps } from "@/types";

interface OrdersViewProps extends SharedViewProps {
    orders: Order[];
    setOrders: React.Dispatch<React.SetStateAction<Order[]>>;
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
}: OrdersViewProps): React.ReactElement {
    const [filter, setFilter] = useState<FilterStatus>("all");
    const [search, setSearch] = useState<string>("");
    const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);

    const filtered = orders.filter(
        (o) =>
            (filter === "all" || o.status === filter) &&
            (!search ||
                o.customer_name.toLowerCase().includes(search.toLowerCase()) ||
                o.id.includes(search)),
    );

    const updateStatus = (id: string, status: OrderStatus) => {
        setOrders((os) => os.map((o) => (o.id === id ? { ...o, status } : o)));
        onToast(`Order marked as ${status}`);
        setSelectedOrder(null);
    };

    const filters: FilterStatus[] = [
        "all",
        "pending",
        "confirmed",
        "delivered",
        "cancelled",
    ];
    const totalRevenue = orders
        .filter((o) => o.status !== "cancelled")
        .reduce((s, o) => s + o.subtotal, 0);

    const statuses: OrderStatus[] = [
        "pending",
        "confirmed",
        "delivered",
        "cancelled",
    ];

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Page header */}
            <div className="mb-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                            Orders
                        </h1>
                        <p className="text-sm text-stone-400 mt-0.5">
                            {orders.length} total · {fmtCurrency(totalRevenue)}{" "}
                            revenue
                        </p>
                    </div>
                </div>
            </div>

            {/* Stat cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
                {statuses.map((s) => {
                    const count = orders.filter((o) => o.status === s).length;
                    const meta = STATUS_META[s];
                    return (
                        <button
                            key={s}
                            onClick={() => setFilter(s === filter ? "all" : s)}
                            className={`bg-white rounded-xl border p-4 text-left transition-all hover:shadow-sm ${filter === s ? "border-green-500 shadow-sm ring-1 ring-green-200" : "border-stone-100 hover:border-stone-200"}`}
                        >
                            <div className="flex items-center gap-2 mb-2">
                                <div
                                    className={`w-2 h-2 rounded-full ${meta.dot}`}
                                />
                                <span className="text-xs font-medium text-stone-400 capitalize">
                                    {s}
                                </span>
                            </div>
                            <div className="text-2xl font-bold text-stone-800">
                                {count}
                            </div>
                        </button>
                    );
                })}
            </div>

            {/* Search + filters */}
            <div className="flex flex-col sm:flex-row gap-2 mb-5">
                <div className="relative flex-1">
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
                        placeholder="Search by name or order ID…"
                        className="w-full h-10 pl-9 pr-3 text-sm bg-white border border-stone-200 rounded-xl text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent transition-all"
                        style={{ fontSize: 16 }}
                    />
                </div>
                <div className="flex gap-1.5 flex-wrap">
                    {filters.map((f) => (
                        <button
                            key={f}
                            onClick={() => setFilter(f)}
                            className={`px-3 h-10 rounded-xl border text-xs font-medium capitalize transition-all ${filter === f ? "bg-stone-800 text-white border-stone-800" : "bg-white text-stone-500 border-stone-200 hover:border-stone-400"}`}
                        >
                            {f}
                        </button>
                    ))}
                </div>
            </div>

            {/* Mobile cards */}
            {isMobile ? (
                <div className="space-y-3">
                    {filtered.map((order) => {
                        const meta = STATUS_META[order.status];
                        return (
                            <div
                                key={order.id}
                                className="bg-white rounded-xl border border-stone-100 p-4 shadow-sm"
                            >
                                <div className="flex items-start justify-between mb-3">
                                    <div className="flex items-center gap-2.5">
                                        <Avatar
                                            name={order.customer_name}
                                            size="sm"
                                        />
                                        <div>
                                            <div className="text-sm font-semibold text-stone-800">
                                                {order.customer_name}
                                            </div>
                                            <div className="text-xs text-stone-400 font-mono">
                                                #{order.id} ·{" "}
                                                {timeAgo(order.created_at)}
                                            </div>
                                        </div>
                                    </div>
                                    <span
                                        className={`text-xs font-medium px-2 py-0.5 rounded-md border ${meta.text} ${meta.bg} ${meta.border}`}
                                    >
                                        {meta.label}
                                    </span>
                                </div>
                                <div className="text-xs text-stone-400 mb-3 leading-relaxed">
                                    {order.items
                                        .map((i) => `${i.qty}× ${i.name}`)
                                        .join(" · ")}
                                </div>
                                <div className="flex items-center justify-between">
                                    <span className="text-base font-bold text-stone-800">
                                        {fmtCurrency(order.subtotal)}
                                    </span>
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs bg-stone-100 text-stone-500 px-2 py-1 rounded-md font-medium uppercase">
                                            {order.payment}
                                        </span>
                                        <Btn
                                            size="xs"
                                            onClick={() =>
                                                setSelectedOrder(order)
                                            }
                                            variant="outline"
                                        >
                                            Manage
                                        </Btn>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            ) : (
                /* Desktop table */
                <div className="bg-white rounded-xl border border-stone-100 overflow-hidden shadow-sm">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-stone-100">
                                    {[
                                        "Order",
                                        "Customer",
                                        "Items",
                                        "Total",
                                        "Payment",
                                        "Status",
                                        "Time",
                                        "",
                                    ].map((h) => (
                                        <th
                                            key={h}
                                            className="px-4 py-3 text-left text-xs font-semibold text-stone-400 uppercase tracking-wider whitespace-nowrap"
                                        >
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-stone-50">
                                {filtered.map((order) => {
                                    const meta = STATUS_META[order.status];
                                    return (
                                        <tr
                                            key={order.id}
                                            className="hover:bg-stone-50 transition-colors group"
                                        >
                                            <td className="px-4 py-3 text-xs font-mono text-green-800 font-semibold">
                                                #{order.id}
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-2.5">
                                                    <Avatar
                                                        name={
                                                            order.customer_name
                                                        }
                                                        size="xs"
                                                    />
                                                    <span className="text-sm font-medium text-stone-800 whitespace-nowrap">
                                                        {order.customer_name}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-xs text-stone-400 max-w-[180px]">
                                                <span className="truncate block">
                                                    {order.items
                                                        .map(
                                                            (i) =>
                                                                `${i.qty}x ${i.name}`,
                                                        )
                                                        .join(", ")}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-sm font-semibold text-stone-800 whitespace-nowrap">
                                                {fmtCurrency(order.subtotal)}
                                            </td>
                                            <td className="px-4 py-3">
                                                <span className="text-xs bg-stone-100 text-stone-500 px-2 py-1 rounded-md font-medium uppercase">
                                                    {order.payment}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                <span
                                                    className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-md border ${meta.text} ${meta.bg} ${meta.border}`}
                                                >
                                                    <span
                                                        className={`w-1.5 h-1.5 rounded-full ${meta.dot}`}
                                                    />
                                                    {meta.label}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-xs text-stone-400 whitespace-nowrap">
                                                {timeAgo(order.created_at)}
                                            </td>
                                            <td className="px-4 py-3">
                                                <button
                                                    onClick={() =>
                                                        setSelectedOrder(order)
                                                    }
                                                    className="text-xs text-green-800 font-medium opacity-0 group-hover:opacity-100 hover:underline transition-opacity whitespace-nowrap"
                                                >
                                                    Manage →
                                                </button>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                        {filtered.length === 0 && (
                            <div className="py-14 text-center">
                                <p className="text-sm text-stone-400">
                                    No orders match your filters
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Order detail modal */}
            <Modal
                show={!!selectedOrder}
                onClose={() => setSelectedOrder(null)}
                title={`Order #${selectedOrder?.id ?? ""}`}
            >
                {selectedOrder && (
                    <>
                        <div className="grid grid-cols-2 gap-3 mb-5 p-4 bg-stone-50 rounded-xl">
                            {(
                                [
                                    ["Customer", selectedOrder.customer_name],
                                    ["Status", selectedOrder.status],
                                    [
                                        "Payment",
                                        selectedOrder.payment.toUpperCase(),
                                    ],
                                    [
                                        "Placed",
                                        timeAgo(selectedOrder.created_at),
                                    ],
                                ] as [string, string][]
                            ).map(([k, v]) => (
                                <div key={k}>
                                    <div className="text-xs text-stone-400 uppercase tracking-wider mb-0.5">
                                        {k}
                                    </div>
                                    <div className="text-sm font-semibold text-stone-800 capitalize">
                                        {v}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="mb-5">
                            <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-3">
                                Items
                            </div>
                            <div className="space-y-2">
                                {selectedOrder.items.map((item, i) => (
                                    <div
                                        key={i}
                                        className="flex justify-between py-2 border-b border-stone-100"
                                    >
                                        <span className="text-sm text-stone-600">
                                            {item.qty}× {item.name}
                                        </span>
                                        <span className="text-sm font-semibold text-stone-800">
                                            {fmtCurrency(item.total)}
                                        </span>
                                    </div>
                                ))}
                                <div className="flex justify-between pt-2">
                                    <span className="text-sm font-semibold text-stone-800">
                                        Total
                                    </span>
                                    <span className="text-sm font-bold text-green-800">
                                        {fmtCurrency(selectedOrder.subtotal)}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {STATUS_ACTIONS[selectedOrder.status].next.length >
                            0 && (
                            <>
                                <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-3">
                                    Update Status
                                </div>
                                <div className="flex gap-2 flex-wrap">
                                    {STATUS_ACTIONS[
                                        selectedOrder.status
                                    ].next.map((s) => (
                                        <Btn
                                            key={s}
                                            size="sm"
                                            onClick={() =>
                                                updateStatus(
                                                    selectedOrder.id,
                                                    s,
                                                )
                                            }
                                            variant={
                                                s === "cancelled"
                                                    ? "danger"
                                                    : s === "delivered"
                                                      ? "success"
                                                      : "blue"
                                            }
                                            className="capitalize"
                                        >
                                            {s}
                                        </Btn>
                                    ))}
                                    <Btn
                                        size="sm"
                                        onClick={() => setSelectedOrder(null)}
                                        variant="ghost"
                                    >
                                        Close
                                    </Btn>
                                </div>
                            </>
                        )}
                    </>
                )}
            </Modal>
        </div>
    );
}