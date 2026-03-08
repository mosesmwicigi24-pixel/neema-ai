import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { StatusBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Card, SectionHeader } from "@/components/ui/Layout";
import { Modal } from "@/components/ui/Modal";
import { timeAgo, fmtCurrency } from "@/lib/utils";
import type { Order, OrderStatus, SharedViewProps } from "@/types";

interface OrdersViewProps extends SharedViewProps {
    orders: Order[];
    setOrders: React.Dispatch<React.SetStateAction<Order[]>>;
}

type FilterStatus = "all" | OrderStatus;

const STATUS_ACTIONS: Record<
    OrderStatus,
    { next: OrderStatus[]; colors: { [k: string]: string } }
> = {
    pending: { next: ["confirmed", "cancelled"], colors: {} },
    confirmed: { next: ["delivered", "cancelled"], colors: {} },
    delivered: { next: [], colors: {} },
    cancelled: { next: [], colors: {} },
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

    return (
        <div
            className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header with quick stats */}
            <SectionHeader
                title="Orders"
                subtitle={`${orders.length} total · KES ${totalRevenue.toLocaleString()} revenue`}
            />

            {/* Quick stats bar */}
            <div className="grid grid-cols-4 gap-3 mb-5">
                {(
                    [
                        "pending",
                        "confirmed",
                        "delivered",
                        "cancelled",
                    ] as OrderStatus[]
                ).map((s) => {
                    const count = orders.filter((o) => o.status === s).length;
                    const colorMap: Record<OrderStatus, string> = {
                        pending:
                            "border-t-amber-400 text-amber-600 dark:text-amber-400",
                        confirmed:
                            "border-t-blue-400 text-blue-600 dark:text-blue-400",
                        delivered:
                            "border-t-emerald-400 text-emerald-600 dark:text-emerald-400",
                        cancelled:
                            "border-t-red-400 text-red-600 dark:text-red-400",
                    };
                    return (
                        <div
                            key={s}
                            className={`bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 border-t-4 p-3 text-center ${colorMap[s]}`}
                        >
                            <div className="text-xl font-bold text-gray-900 dark:text-white">
                                {count}
                            </div>
                            <div className="text-[11px] font-medium capitalize opacity-70">
                                {s}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Search + filters */}
            <div className="flex flex-col sm:flex-row gap-2 mb-4">
                <div className="relative flex-1">
                    <svg
                        className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
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
                        className="w-full h-10 pl-9 pr-3 text-sm bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500"
                        style={{ fontSize: 16 }}
                    />
                </div>
                <div className="flex gap-1.5 flex-wrap">
                    {filters.map((f) => (
                        <button
                            key={f}
                            onClick={() => setFilter(f)}
                            className={`px-3 h-10 rounded-xl border text-xs font-medium capitalize transition-all ${
                                filter === f
                                    ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900 border-gray-900 dark:border-white"
                                    : "bg-white dark:bg-gray-900 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-800 hover:border-gray-400"
                            }`}
                        >
                            {f}
                        </button>
                    ))}
                </div>
            </div>

            {isMobile ? (
                <div className="space-y-3">
                    {filtered.map((order) => (
                        <div
                            key={order.id}
                            className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 shadow-sm"
                        >
                            <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2.5">
                                    <Avatar
                                        name={order.customer_name}
                                        size="sm"
                                    />
                                    <div>
                                        <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                            {order.customer_name}
                                        </div>
                                        <div className="text-xs text-gray-400 font-mono">
                                            #{order.id} ·{" "}
                                            {timeAgo(order.created_at)}
                                        </div>
                                    </div>
                                </div>
                                <StatusBadge status={order.status} />
                            </div>
                            <div className="text-xs text-gray-500 dark:text-gray-400 mb-3 leading-relaxed">
                                {order.items
                                    .map((i) => `${i.qty}× ${i.name}`)
                                    .join(" · ")}
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-base font-bold text-gray-900 dark:text-white">
                                    {fmtCurrency(order.subtotal)}
                                </span>
                                <div className="flex items-center gap-2">
                                    <span className="text-xs bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 px-2 py-1 rounded-lg font-medium uppercase">
                                        {order.payment}
                                    </span>
                                    <Btn
                                        size="xs"
                                        onClick={() => setSelectedOrder(order)}
                                        variant="outline"
                                    >
                                        Manage
                                    </Btn>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <Card padding={false}>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-gray-100 dark:border-gray-800">
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
                                            className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider whitespace-nowrap"
                                        >
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                                {filtered.map((order) => (
                                    <tr
                                        key={order.id}
                                        className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group"
                                    >
                                        <td className="px-4 py-3 text-xs font-mono text-amber-600 dark:text-amber-400 font-medium">
                                            #{order.id}
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-2.5">
                                                <Avatar
                                                    name={order.customer_name}
                                                    size="xs"
                                                />
                                                <span className="text-sm font-medium text-gray-900 dark:text-white whitespace-nowrap">
                                                    {order.customer_name}
                                                </span>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 text-xs text-gray-500 dark:text-gray-400 max-w-[180px]">
                                            <span className="truncate block">
                                                {order.items
                                                    .map(
                                                        (i) =>
                                                            `${i.qty}x ${i.name}`,
                                                    )
                                                    .join(", ")}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-white whitespace-nowrap">
                                            {fmtCurrency(order.subtotal)}
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-xs bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 px-2 py-1 rounded-lg font-medium uppercase">
                                                {order.payment}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <StatusBadge
                                                status={order.status}
                                            />
                                        </td>
                                        <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                                            {timeAgo(order.created_at)}
                                        </td>
                                        <td className="px-4 py-3">
                                            <button
                                                onClick={() =>
                                                    setSelectedOrder(order)
                                                }
                                                className="text-xs text-amber-600 dark:text-amber-400 font-medium opacity-0 group-hover:opacity-100 hover:underline transition-opacity whitespace-nowrap"
                                            >
                                                Manage →
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {filtered.length === 0 && (
                            <div className="py-12 text-center text-sm text-gray-400">
                                No orders match your filters
                            </div>
                        )}
                    </div>
                </Card>
            )}

            <Modal
                show={!!selectedOrder}
                onClose={() => setSelectedOrder(null)}
                title={`Order #${selectedOrder?.id ?? ""}`}
            >
                {selectedOrder && (
                    <>
                        <div className="grid grid-cols-2 gap-3 mb-4 p-4 bg-gray-50 dark:bg-gray-800 rounded-xl">
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
                                    <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">
                                        {k}
                                    </div>
                                    <div className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                                        {v}
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="mb-5">
                            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                                Items
                            </div>
                            <div className="space-y-2">
                                {selectedOrder.items.map((item, i) => (
                                    <div
                                        key={i}
                                        className="flex justify-between py-2 border-b border-gray-100 dark:border-gray-800"
                                    >
                                        <span className="text-sm text-gray-700 dark:text-gray-300">
                                            {item.qty}× {item.name}
                                        </span>
                                        <span className="text-sm font-medium text-gray-900 dark:text-white">
                                            {fmtCurrency(item.total)}
                                        </span>
                                    </div>
                                ))}
                                <div className="flex justify-between pt-2 font-semibold">
                                    <span className="text-sm text-gray-900 dark:text-white">
                                        Total
                                    </span>
                                    <span className="text-sm text-amber-600 dark:text-amber-400">
                                        {fmtCurrency(selectedOrder.subtotal)}
                                    </span>
                                </div>
                            </div>
                        </div>
                        {STATUS_ACTIONS[selectedOrder.status].next.length >
                            0 && (
                            <>
                                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
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