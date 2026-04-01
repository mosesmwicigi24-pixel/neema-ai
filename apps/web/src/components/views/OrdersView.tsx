import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { timeAgo, fmtCurrency, fmtDate, formatPhone } from "@/lib/utils";
import { ordersApi } from "@/lib/api";
import type { Order, OrderStatus, SharedViewProps } from "@/types";

interface OrdersViewProps extends SharedViewProps {
    orders: Order[];
    setOrders: React.Dispatch<React.SetStateAction<Order[]>>;
    refetchOrders?: () => void;
}

type FilterStatus = "all" | OrderStatus;

const PAGE_SIZE = 15;

// Flat channel icon badges matching the design system
const CH_BG: Record<string, string> = {
    whatsapp: "#25D366", messenger: "#0099FF", instagram: "#E1306C",
    facebook: "#1877F2", email: "#4d66b3", sms: "#589b31",
};
const CH_ICON: Record<string, string> = {
    whatsapp:  'M12 2C6.48 2 2 6.48 2 12c0 1.82.48 3.54 1.32 5.04L2 22l5.08-1.3A9.94 9.94 0 0012 22c5.52 0 10-4.48 10-10S17.52 2 12 2zm0 18c-1.56 0-3.02-.44-4.26-1.2l-.3-.18-3.14.72.7-3.06-.2-.32A7.96 7.96 0 014 12c0-4.42 3.58-8 8-8s8 3.58 8 8-3.58 8-8 8zm4.24-5.78c-.24-.12-1.42-.7-1.64-.78-.22-.08-.38-.12-.54.12-.16.24-.62.78-.76.94-.14.16-.28.18-.52.06-.24-.12-1.02-.38-1.94-1.18a7.2 7.2 0 01-1.34-1.64c-.14-.24 0-.36.1-.5.1-.1.24-.28.36-.42.12-.16.16-.26.24-.44.08-.16.04-.3 0-.42-.06-.14-.54-1.32-.74-1.8-.2-.48-.4-.42-.54-.44h-.46c-.16 0-.42.06-.64.3-.22.24-.84.82-.84 2s.86 2.32.98 2.48c.12.16 1.7 2.6 4.12 3.64.58.26 1.02.4 1.38.52.58.18 1.1.16 1.52.1.46-.08 1.42-.58 1.62-1.14.2-.56.2-1.04.14-1.14-.08-.1-.22-.16-.46-.28z',
    messenger: 'M12 2C6.48 2 2 6.15 2 11.26c0 2.91 1.4 5.5 3.58 7.22V22l3.25-1.84c.87.24 1.79.37 2.74.37 5.52 0 10-4.14 10-9.26S17.52 2 12 2zm1.07 12.51l-2.17-2.24-4.24 2.24 4.72-5.01 2.25 2.25 4.14-2.25-4.7 5.01z',
    email:     'M3 8l9 6 9-6M5 6h14a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2z',
    sms:       'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
};
function ChannelPill({ channel }: { channel?: string }) {
    const ch = (channel || "whatsapp").toLowerCase();
    const bg = CH_BG[ch] || "#699a32";
    const icon = CH_ICON[ch];
    return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium text-white flex-shrink-0"
            style={{ backgroundColor: bg }}>
            {icon ? (
                <svg viewBox="0 0 24 24" className="w-2.5 h-2.5" fill={ch==="email"||ch==="sms"?"none":"currentColor"}
                    stroke={ch==="email"||ch==="sms"?"white":"none"} strokeWidth={1.5}>
                    <path d={icon} />
                </svg>
            ) : null}
            <span className="capitalize">{ch}</span>
        </span>
    );
}

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
    const [page,     setPage]     = useState(1);

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

    // Reset to page 1 when filters or search changes
    React.useEffect(() => { setPage(1); }, [filter, search]);
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    const paginated  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

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
        <div className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`} style={{backgroundColor:"#f3f9ec"}}>

            {/* Header */}
            <div className="flex items-start justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold tracking-tight" style={{color:"#16270c"}}>Orders</h1>
                    <p className="text-sm mt-0.5" style={{color:"#699a32"}}>
                        {orders.length} total
                        {statusCounts.pending > 0 && (
                            <span className="ml-1.5 font-medium" style={{color:"#bcc13e"}}>
                                · {statusCounts.pending} pending
                            </span>
                        )}
                    </p>
                </div>
                {/* Revenue summary pill */}
                <div className="rounded-xl px-4 py-2.5 shadow-sm text-right flex-shrink-0" style={{backgroundColor:"white",border:"1px solid #cee6b2"}}>
                    <div className="text-xs font-medium mb-0.5" style={{color:"#699a32"}}>Total Revenue</div>
                    <div className="text-base font-bold" style={{color:"#427425"}}>{fmtCurrency(totalRevenue)}</div>
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
                            className={`rounded-xl shadow-sm p-3.5 text-left transition-all hover:shadow-md ${
                                filter === s ? `${meta.border} ring-1 ring-inset ${meta.border}` : ""
                            }`}
                            style={{ backgroundColor: "white", border: "1px solid #e6f3d8" }}
                        >
                            <div className="flex items-center gap-1.5 mb-2">
                                <div className={`w-2 h-2 rounded-full ${meta.dot}`} />
                                <span className={`text-xs font-semibold ${meta.text}`}>{meta.label}</span>
                            </div>
                            <div className="text-xl font-bold" style={{color:"#16270c"}}>{count}</div>
                            {rev > 0 && (
                                <div className="text-xs mt-0.5" style={{color:"#699a32"}}>{fmtCurrency(rev)}</div>
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
                        className="w-full h-9 pl-9 pr-3 text-sm rounded-xl focus:outline-none focus:ring-2" style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#16270c",fontSize:13}}
                        style={{ fontSize: 16 }}
                    />
                </div>
                {filter !== "all" && (
                    <button
                        onClick={() => setFilter("all")}
                        className="h-9 px-3 rounded-xl text-xs font-semibold flex items-center gap-1.5" style={{backgroundColor:"#427425",color:"white",border:"1px solid #427425"}}
                    >
                        {STATUS_META[filter]?.label} ✕
                    </button>
                )}
            </div>

            {/* Orders list */}
            <div className="rounded-xl shadow-sm overflow-hidden" style={{backgroundColor:"white",border:"1px solid #cee6b2"}}>
                {filtered.length === 0 ? (
                    <div className="py-16 text-center">
                        <span className="text-3xl mb-3 block">📦</span>
                        <p className="text-sm" style={{color:"#699a32"}}>No orders found</p>
                    </div>
                ) : (
                    <div className="divide-y" style={{divideColor:"#f0f9ec"}}>
                        {paginated.map((order) => {
                            const meta = STATUS_META[order.status] ?? STATUS_META.pending;
                            const isUpdating = updating === order.id;
                            const itemSummary = (order.items ?? []).slice(0, 2)
                                .map((i) => `${i.name}${(i.qty || i.quantity || 1) > 1 ? ` ×${i.qty || i.quantity}` : ""}`)
                                .join(", ");
                            const extraItems = (order.items?.length ?? 0) - 2;

                            return (
                                <div
                                    key={order.id}
                                    className="flex items-center gap-3 px-4 py-3.5 cursor-pointer transition-colors" style={{borderBottom:"1px solid #f0f9ec"}}
                                    onClick={() => setSelected(order)}
                                >
                                    <Avatar name={order.contact_name} size={38} />
                                    <div className="flex-1 min-w-0">
                                        {/* Row 1: name + status + channel */}
                                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                                            <span className="text-sm font-semibold truncate" style={{color:"#16270c"}}>
                                                {order.contact_name}
                                            </span>
                                            {order.channel && <ChannelPill channel={order.channel} />}
                                            <span className={`flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded font-semibold border ${meta.bg} ${meta.text} ${meta.border}`}>
                                                {meta.label}
                                            </span>
                                        </div>
                                        {/* Row 2: order ID + phone + item summary */}
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                            <span className="text-[10px] font-mono font-bold px-1 py-0.5 rounded" style={{backgroundColor:"#e6f3d8",color:"#427425"}}>
                                                #{(order.id||"").slice(-6).toUpperCase()}
                                            </span>
                                            <span className="text-xs font-mono" style={{color:"#699a32"}}>
                                                {formatPhone(order.contact_phone)}
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
                                        <div className="text-[10px] mt-0.5" style={{color:"#699a32"}}>
                                            {timeAgo(order.created_at)}
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0">
                                        <div className="text-sm font-bold" style={{color:"#16270c"}}>
                                            {fmtCurrency(order.total || order.subtotal)}
                                        </div>
                                        <div className="text-[10px] mt-0.5" style={{color:"#699a32"}}>
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

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between mt-4 px-1">
                    <span className="text-xs" style={{color:"#699a32"}}>
                        Showing {((page-1)*PAGE_SIZE)+1}–{Math.min(page*PAGE_SIZE, filtered.length)} of {filtered.length}
                    </span>
                    <div className="flex items-center gap-1">
                        <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page===1}
                            className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-semibold transition-colors disabled:opacity-30"
                            style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#427425"}}>‹</button>
                        {Array.from({length:Math.min(totalPages,5)}, (_, i) => {
                            const pg = totalPages <= 5 ? i+1 : page <= 3 ? i+1 : page >= totalPages-2 ? totalPages-4+i : page-2+i;
                            return (
                                <button key={pg} onClick={() => setPage(pg)}
                                    className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-semibold transition-colors"
                                    style={ page===pg
                                        ? {backgroundColor:"#589b31",color:"white",border:"1px solid #589b31"}
                                        : {backgroundColor:"white",border:"1px solid #b5da8b",color:"#427425"} }>
                                    {pg}
                                </button>
                            );
                        })}
                        <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page===totalPages}
                            className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-semibold transition-colors disabled:opacity-30"
                            style={{backgroundColor:"white",border:"1px solid #b5da8b",color:"#427425"}}>›</button>
                    </div>
                </div>
            )}

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
                            <div className="flex items-center gap-3 mb-4 p-3 rounded-xl" style={{backgroundColor:"#f3f9ec",border:"1px solid #e6f3d8"}}>
                                <Avatar name={selected.contact_name} size={40} />
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-bold" style={{color:"#16270c"}}>{selected.contact_name}</div>
                                    <div className="text-xs font-mono" style={{color:"#699a32"}}>{formatPhone(selected.contact_phone)}</div>
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
                                    <div key={r.label} className="rounded-lg px-3 py-2" style={{backgroundColor:"#f3f9ec",border:"1px solid #e6f3d8"}}>
                                        <div className="text-[10px] uppercase tracking-wide font-semibold" style={{color:"#699a32"}}>{r.label}</div>
                                        <div className="text-xs font-semibold mt-0.5" style={{color:"#16270c"}}>{r.value}</div>
                                    </div>
                                ))}
                            </div>

                            {/* Items */}
                            <div className="mb-4">
                                <div className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{color:"#699a32"}}>Items</div>
                                <div className="rounded-xl p-3 space-y-2" style={{backgroundColor:"#f3f9ec",border:"1px solid #e6f3d8"}}>
                                    {(selected.items ?? []).length === 0 ? (
                                        <p className="text-xs text-stone-400 text-center py-2">No items recorded</p>
                                    ) : (
                                        (selected.items ?? []).map((item, i) => (
                                            <div key={i} className="flex items-start justify-between gap-2">
                                                <div className="flex-1 min-w-0">
                                                    <span className="text-xs font-medium" style={{color:"#16270c"}}>{item.name}</span>
                                                    {item.sku && (
                                                        <span className="ml-1.5 text-[10px] font-mono" style={{color:"#699a32"}}>{item.sku}</span>
                                                    )}
                                                </div>
                                                <div className="text-right flex-shrink-0">
                                                    <div className="text-xs font-semibold" style={{color:"#16270c"}}>
                                                        {fmtCurrency(item.unit_price * (item.quantity || item.qty || 1))}
                                                    </div>
                                                    <div className="text-[10px]" style={{color:"#699a32"}}>
                                                        {fmtCurrency(item.unit_price)} × {item.quantity || item.qty || 1}
                                                    </div>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                    <div className="pt-2.5 mt-2 flex justify-between items-center" style={{borderTop:"1px solid #cee6b2"}}>
                                        <span className="text-sm font-bold" style={{color:"#16270c"}}>Total</span>
                                        <span className="text-base font-bold" style={{color:"#427425"}}>
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