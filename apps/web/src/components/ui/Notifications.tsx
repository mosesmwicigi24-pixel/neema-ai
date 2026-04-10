// Notifications.tsx
// Uses position:fixed so the popup always renders in the viewport,
// never clipped by the sidebar's overflow:hidden.

import React, { useState, useEffect, useRef, useCallback } from "react";
import { timeAgo } from "@/lib/utils";

export interface AppNotification {
    id: string;
    type: "intercept" | "new_message" | "order" | "transfer" | "system";
    title: string;
    body: string;
    at: string;
    read: boolean;
    convId?: string;
}

const META: Record<AppNotification["type"], { emoji: string; bg: string; color: string }> = {
    intercept:   { emoji: "⚡", bg: "#fef9ec", color: "#d97706" },
    new_message: { emoji: "💬", bg: "#eff6ff", color: "#2563eb" },
    order:       { emoji: "📦", bg: "#f0fdf4", color: "#16a34a" },
    transfer:    { emoji: "⇄",  bg: "#f5f3ff", color: "#7c3aed" },
    system:      { emoji: "ℹ️", bg: "#f8fafc", color: "#64748b" },
};

const KEY = "neema_notifs_v3";

const load = (): AppNotification[] => {
    try {
        return JSON.parse(localStorage.getItem(KEY) || "[]");
    } catch {
        return [];
    }
};

const save = (n: AppNotification[]) => {
    try {
        localStorage.setItem(KEY, JSON.stringify(n.slice(0, 60)));
    } catch {}
};

interface NotificationsProps {
    onNavigate?: (id: string) => void;
    /** Collapsed sidebar — render as icon-only with no label */
    compact?: boolean;
}

export function Notifications({ onNavigate, compact = false }: NotificationsProps) {
    const [open, setOpen]   = useState(false);
    const [notifs, setNotifs] = useState<AppNotification[]>(load);
    const [pos, setPos]     = useState({ top: 0, left: 0, width: 0 });
    const btnRef   = useRef<HTMLButtonElement>(null);
    const panelRef = useRef<HTMLDivElement>(null);

    // Persist to localStorage whenever list changes
    useEffect(() => { save(notifs); }, [notifs]);

    // Position popup relative to the bell button
    const toggle = useCallback(() => {
        if (btnRef.current) {
            const r = btnRef.current.getBoundingClientRect();
            // Pop to the right when in collapsed (compact) mode,
            // otherwise drop below the button
            if (compact) {
                setPos({ top: r.top, left: r.right + 8, width: 316 });
            } else {
                // Align left edge with button, drop below
                setPos({ top: r.bottom + 6, left: r.left, width: 316 });
            }
        }
        setOpen((o) => !o);
    }, [compact]);

    // Close on outside click
    useEffect(() => {
        if (!open) return;
        const h = (e: MouseEvent) => {
            if (
                !panelRef.current?.contains(e.target as Node) &&
                !btnRef.current?.contains(e.target as Node)
            ) setOpen(false);
        };
        document.addEventListener("mousedown", h);
        return () => document.removeEventListener("mousedown", h);
    }, [open]);

    // Listen for custom notification events (fired by pushNotification / websocket bridge)
    useEffect(() => {
        const h = (e: Event) => {
            const n = (e as CustomEvent<AppNotification>).detail;
            setNotifs((p) => (p.find((x) => x.id === n.id) ? p : [n, ...p]));
        };
        window.addEventListener("neema:notification", h);
        return () => window.removeEventListener("neema:notification", h);
    }, []);

    const unread = notifs.filter((n) => !n.read).length;

    const markRead    = (id: string) => setNotifs((p) => p.map((n) => n.id === id ? { ...n, read: true } : n));
    const markAllRead = () => setNotifs((p) => p.map((n) => ({ ...n, read: true })));
    const dismiss     = (id: string) => setNotifs((p) => p.filter((n) => n.id !== id));

    const handleClick = (n: AppNotification) => {
        markRead(n.id);
        if (n.convId && onNavigate) {
            onNavigate(n.convId);
            setOpen(false);
        }
    };

    return (
        <>
            {/* ── Bell button ─────────────────────────────────────────────── */}
            <button
                ref={btnRef}
                onClick={toggle}
                className="relative flex items-center justify-center rounded-xl transition-colors flex-shrink-0"
                style={{
                    width: compact ? 40 : 36,
                    height: compact ? 40 : 36,
                    backgroundColor: open ? "#f0f4ec" : "transparent",
                    color: open ? "#427425" : "#8a9e80",
                }}
                onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                    (e.currentTarget as HTMLElement).style.color = "#427425";
                }}
                onMouseLeave={(e) => {
                    if (!open) {
                        (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                        (e.currentTarget as HTMLElement).style.color = "#8a9e80";
                    }
                }}
                title="Notifications"
            >
                <svg
                    className="w-4 h-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.8}
                        d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                    />
                </svg>

                {/* Unread badge */}
                {unread > 0 && (
                    <span
                        className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-0.5 rounded-full flex items-center justify-center text-white font-bold border-2 border-white"
                        style={{ fontSize: 9, backgroundColor: "#ef4444" }}
                    >
                        {unread > 9 ? "9+" : unread}
                    </span>
                )}
            </button>

            {/* ── Notification popup — fixed, never clipped ────────────────── */}
            {open && (
                <div
                    ref={panelRef}
                    style={{
                        position: "fixed",
                        top: pos.top,
                        left: pos.left,
                        width: pos.width,
                        zIndex: 9999,
                        backgroundColor: "#ffffff",
                        border: "1px solid #e8ebe3",
                        borderRadius: 14,
                        boxShadow: "0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)",
                        animation: "notifDrop 0.13s ease",
                        overflow: "hidden",
                    }}
                >
                    <style>{`
                        @keyframes notifDrop {
                            from { opacity: 0; transform: translateY(-4px); }
                            to   { opacity: 1; transform: translateY(0); }
                        }
                    `}</style>

                    {/* Header */}
                    <div
                        className="flex items-center justify-between px-4 py-3"
                        style={{ borderBottom: "1px solid #edf0ea" }}
                    >
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold" style={{ color: "#1c2917" }}>
                                Notifications
                            </span>
                            {unread > 0 && (
                                <span
                                    className="text-[10px] font-bold text-white px-1.5 py-0.5 rounded-full"
                                    style={{ backgroundColor: "#ef4444" }}
                                >
                                    {unread}
                                </span>
                            )}
                        </div>
                        {unread > 0 && (
                            <button
                                onClick={markAllRead}
                                className="text-[10px] font-semibold transition-colors"
                                style={{ color: "#589b31" }}
                                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#427425"; }}
                                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "#589b31"; }}
                            >
                                Mark all read
                            </button>
                        )}
                    </div>

                    {/* List */}
                    <div style={{ maxHeight: 360, overflowY: "auto", scrollbarWidth: "none" }}>
                        {notifs.length === 0 ? (
                            <div className="py-12 text-center">
                                <div
                                    className="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl mx-auto mb-3"
                                    style={{ backgroundColor: "#f5f7f2" }}
                                >
                                    🔔
                                </div>
                                <p className="text-sm font-medium" style={{ color: "#1c2917" }}>
                                    All caught up
                                </p>
                                <p className="text-xs mt-0.5" style={{ color: "#b5c9a8" }}>
                                    No new notifications
                                </p>
                            </div>
                        ) : (
                            notifs.map((n) => {
                                const m = META[n.type];
                                return (
                                    <div
                                        key={n.id}
                                        onClick={() => handleClick(n)}
                                        className="flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors"
                                        style={{
                                            borderBottom: "1px solid #f5f7f2",
                                            backgroundColor: !n.read ? "#fafef7" : "transparent",
                                        }}
                                        onMouseEnter={(e) => {
                                            (e.currentTarget as HTMLElement).style.backgroundColor = "#f5f7f2";
                                        }}
                                        onMouseLeave={(e) => {
                                            (e.currentTarget as HTMLElement).style.backgroundColor = !n.read ? "#fafef7" : "transparent";
                                        }}
                                    >
                                        {/* Icon */}
                                        <div
                                            className="w-8 h-8 rounded-xl flex items-center justify-center text-sm flex-shrink-0 mt-0.5"
                                            style={{ backgroundColor: m.bg }}
                                        >
                                            {m.emoji}
                                        </div>

                                        {/* Content */}
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-start justify-between gap-2">
                                                <span
                                                    className="text-xs font-semibold leading-tight"
                                                    style={{ color: !n.read ? "#1c2917" : "#6b7e64" }}
                                                >
                                                    {n.title}
                                                </span>
                                                <span
                                                    className="text-[10px] flex-shrink-0 mt-0.5"
                                                    style={{ color: "#b5c9a8" }}
                                                >
                                                    {timeAgo(n.at)}
                                                </span>
                                            </div>
                                            <p
                                                className="text-[11px] mt-0.5 leading-relaxed line-clamp-2"
                                                style={{ color: "#8a9e80" }}
                                            >
                                                {n.body}
                                            </p>
                                        </div>

                                        {/* Dismiss */}
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                dismiss(n.id);
                                            }}
                                            className="text-[11px] flex-shrink-0 mt-0.5 transition-colors"
                                            style={{ color: "#dde4d6" }}
                                            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#ef4444"; }}
                                            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "#dde4d6"; }}
                                        >
                                            ✕
                                        </button>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    {/* Footer */}
                    {notifs.length > 0 && (
                        <div
                            className="px-4 py-2.5 flex justify-between items-center"
                            style={{ borderTop: "1px solid #edf0ea" }}
                        >
                            <span className="text-[10px]" style={{ color: "#b5c9a8" }}>
                                {notifs.length} notification{notifs.length !== 1 ? "s" : ""}
                            </span>
                            <button
                                onClick={() => setNotifs([])}
                                className="text-[10px] transition-colors"
                                style={{ color: "#b5c9a8" }}
                                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#ef4444"; }}
                                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "#b5c9a8"; }}
                            >
                                Clear all
                            </button>
                        </div>
                    )}
                </div>
            )}
        </>
    );
}

// ── Push a notification into the bell from anywhere in the app ────────────────
export function pushNotification(
    notif: Omit<AppNotification, "id" | "read" | "at">,
) {
    window.dispatchEvent(
        new CustomEvent("neema:notification", {
            detail: {
                ...notif,
                id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                read: false,
                at: new Date().toISOString(),
            } as AppNotification,
        }),
    );
}