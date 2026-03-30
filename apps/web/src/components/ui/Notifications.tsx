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
const META: Record<AppNotification["type"], { emoji: string; bg: string }> = {
    intercept: { emoji: "⚡", bg: "#fef3c7" },
    new_message: { emoji: "💬", bg: "#dbeafe" },
    order: { emoji: "📦", bg: "#d1fae5" },
    transfer: { emoji: "⇄", bg: "#ede9fe" },
    system: { emoji: "ℹ️", bg: "#f1f5f9" },
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

export function Notifications({
    onNavigate,
}: {
    onNavigate?: (id: string) => void;
}) {
    const [open, setOpen] = useState(false);
    const [notifs, setNotifs] = useState<AppNotification[]>(load);
    const [pos, setPos] = useState({ top: 0, left: 0 });
    const btnRef = useRef<HTMLButtonElement>(null);
    const panelRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        save(notifs);
    }, [notifs]);

    const toggle = useCallback(() => {
        if (btnRef.current) {
            const r = btnRef.current.getBoundingClientRect();
            // place popup left edge at button left, below the button
            setPos({ top: r.bottom + 6, left: r.left });
        }
        setOpen((o) => !o);
    }, []);

    useEffect(() => {
        if (!open) return;
        const h = (e: MouseEvent) => {
            if (
                !panelRef.current?.contains(e.target as Node) &&
                !btnRef.current?.contains(e.target as Node)
            )
                setOpen(false);
        };
        document.addEventListener("mousedown", h);
        return () => document.removeEventListener("mousedown", h);
    }, [open]);

    useEffect(() => {
        const h = (e: Event) => {
            const n = (e as CustomEvent<AppNotification>).detail;
            setNotifs((p) => (p.find((x) => x.id === n.id) ? p : [n, ...p]));
        };
        window.addEventListener("neema:notification", h);
        return () => window.removeEventListener("neema:notification", h);
    }, []);

    const unread = notifs.filter((n) => !n.read).length;
    const markRead = (id: string) =>
        setNotifs((p) =>
            p.map((n) => (n.id === id ? { ...n, read: true } : n)),
        );
    const markAllRead = () =>
        setNotifs((p) => p.map((n) => ({ ...n, read: true })));
    const dismiss = (id: string) =>
        setNotifs((p) => p.filter((n) => n.id !== id));
    const handleClick = (n: AppNotification) => {
        markRead(n.id);
        if (n.convId && onNavigate) {
            onNavigate(n.convId);
            setOpen(false);
        }
    };

    return (
        <>
            <button
                ref={btnRef}
                onClick={toggle}
                className="relative w-7 h-7 rounded-lg flex items-center justify-center transition-colors flex-shrink-0"
                style={{
                    color: open ? "#f3f9ec" : "#699a32",
                    backgroundColor: open ? "#1f367a" : "transparent",
                }}
                onMouseEnter={(e) => {
                    if (!open) {
                        (e.currentTarget as HTMLElement).style.backgroundColor =
                            "#152451";
                        (e.currentTarget as HTMLElement).style.color =
                            "#f3f9ec";
                    }
                }}
                onMouseLeave={(e) => {
                    if (!open) {
                        (e.currentTarget as HTMLElement).style.backgroundColor =
                            "transparent";
                        (e.currentTarget as HTMLElement).style.color =
                            "#699a32";
                    }
                }}
                title="Notifications"
            >
                <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                    />
                </svg>
                {unread > 0 && (
                    <span
                        className="absolute -top-1 -right-1 min-w-[16px] h-4 px-0.5 rounded-full flex items-center justify-center text-white font-bold"
                        style={{ fontSize: 9, backgroundColor: "#ef4444" }}
                    >
                        {unread > 9 ? "9+" : unread}
                    </span>
                )}
            </button>

            {open && (
                <div
                    ref={panelRef}
                    style={{
                        position: "fixed",
                        top: pos.top,
                        left: pos.left,
                        width: 316,
                        zIndex: 9999,
                        backgroundColor: "#070d1c",
                        border: "1px solid #152451",
                        borderRadius: 14,
                        boxShadow: "0 8px 40px rgba(0,0,0,0.55)",
                        animation: "notifDrop 0.13s ease",
                    }}
                >
                    <style>{`@keyframes notifDrop{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}`}</style>

                    {/* Header */}
                    <div
                        className="flex items-center justify-between px-4 py-3"
                        style={{ borderBottom: "1px solid #0a1229" }}
                    >
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-bold text-white">
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
                                className="text-[10px] font-semibold"
                                style={{ color: "#84c13e" }}
                            >
                                Mark all read
                            </button>
                        )}
                    </div>

                    {/* List */}
                    <div
                        style={{
                            maxHeight: 340,
                            overflowY: "auto",
                            scrollbarWidth: "none",
                        }}
                    >
                        {notifs.length === 0 ? (
                            <div className="py-10 text-center">
                                <div className="text-3xl mb-2">🔔</div>
                                <p
                                    className="text-xs"
                                    style={{ color: "#699a32" }}
                                >
                                    No notifications yet
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
                                            borderBottom: "1px solid #0a1229",
                                            backgroundColor: !n.read
                                                ? "rgba(88,155,49,0.09)"
                                                : "transparent",
                                        }}
                                        onMouseEnter={(e) => {
                                            (
                                                e.currentTarget as HTMLElement
                                            ).style.backgroundColor = "#0a1229";
                                        }}
                                        onMouseLeave={(e) => {
                                            (
                                                e.currentTarget as HTMLElement
                                            ).style.backgroundColor = !n.read
                                                ? "rgba(88,155,49,0.09)"
                                                : "transparent";
                                        }}
                                    >
                                        <div
                                            className="w-8 h-8 rounded-xl flex items-center justify-center text-sm flex-shrink-0 mt-0.5"
                                            style={{ backgroundColor: m.bg }}
                                        >
                                            {m.emoji}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-start justify-between gap-2">
                                                <span
                                                    className="text-xs font-semibold leading-tight"
                                                    style={{
                                                        color: !n.read
                                                            ? "#f3f9ec"
                                                            : "#9ccd65",
                                                    }}
                                                >
                                                    {n.title}
                                                </span>
                                                <span
                                                    className="text-[10px] flex-shrink-0 mt-0.5"
                                                    style={{ color: "#4f7425" }}
                                                >
                                                    {timeAgo(n.at)}
                                                </span>
                                            </div>
                                            <p
                                                className="text-[11px] mt-0.5 leading-relaxed line-clamp-2"
                                                style={{ color: "#699a32" }}
                                            >
                                                {n.body}
                                            </p>
                                        </div>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                dismiss(n.id);
                                            }}
                                            className="text-[10px] flex-shrink-0 mt-0.5 hover:text-red-400 transition-colors"
                                            style={{ color: "#1f367a" }}
                                        >
                                            ✕
                                        </button>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    {notifs.length > 0 && (
                        <div
                            className="px-4 py-2.5 flex justify-between items-center"
                            style={{ borderTop: "1px solid #0a1229" }}
                        >
                            <span
                                className="text-[10px]"
                                style={{ color: "#4f7425" }}
                            >
                                {notifs.length} notification
                                {notifs.length !== 1 ? "s" : ""}
                            </span>
                            <button
                                onClick={() => setNotifs([])}
                                className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
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
