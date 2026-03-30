// Notifications.tsx
// Agent notification bell with dropdown panel.
// Notifications arrive via WebSocket events and are stored locally.

import React, { useState, useEffect, useRef, useCallback } from "react";
import { timeAgo } from "@/lib/utils";

export interface AppNotification {
    id:        string;
    type:      "intercept" | "new_message" | "order" | "transfer" | "system";
    title:     string;
    body:      string;
    at:        string;          // ISO timestamp
    read:      boolean;
    convId?:   string;
    href?:     string;
}

interface NotificationsProps {
    onNavigate?: (convId: string) => void;
}

// ── Icon helpers ──────────────────────────────────────────────────────────────

const NOTIF_ICON: Record<AppNotification["type"], { emoji: string; bg: string; text: string }> = {
    intercept:   { emoji: "⚡", bg: "bg-amber-50 dark:bg-amber-900/30",  text: "text-amber-600" },
    new_message: { emoji: "💬", bg: "bg-blue-50 dark:bg-blue-900/30",    text: "text-blue-600"  },
    order:       { emoji: "📦", bg: "bg-emerald-50",                     text: "text-emerald-600" },
    transfer:    { emoji: "⇄",  bg: "bg-purple-50",                     text: "text-purple-600" },
    system:      { emoji: "ℹ️", bg: "bg-stone-50",                       text: "text-stone-500"  },
};

// ── Local storage key ─────────────────────────────────────────────────────────
const STORAGE_KEY = "neema_notifications";

function loadStored(): AppNotification[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch { return []; }
}
function saveStored(notifs: AppNotification[]) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(notifs.slice(0, 50))); } catch {}
}

// ── Main component ────────────────────────────────────────────────────────────

export function Notifications({ onNavigate }: NotificationsProps) {
    const [open, setOpen]   = useState(false);
    const [notifs, setNotifs] = useState<AppNotification[]>(loadStored);
    const ref = useRef<HTMLDivElement>(null);

    // Persist whenever notifs change
    useEffect(() => { saveStored(notifs); }, [notifs]);

    // Close on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener("mousedown", handler);
        return () => document.removeEventListener("mousedown", handler);
    }, []);

    // Public API — other components push notifications via this event
    useEffect(() => {
        const handler = (e: CustomEvent<AppNotification>) => {
            setNotifs((prev) => {
                if (prev.find((n) => n.id === e.detail.id)) return prev;
                return [e.detail, ...prev];
            });
        };
        window.addEventListener("neema:notification" as any, handler);
        return () => window.removeEventListener("neema:notification" as any, handler);
    }, []);

    const unread = notifs.filter((n) => !n.read).length;

    const markRead = (id: string) =>
        setNotifs((p) => p.map((n) => n.id === id ? { ...n, read: true } : n));

    const markAllRead = () =>
        setNotifs((p) => p.map((n) => ({ ...n, read: true })));

    const dismiss = (id: string) =>
        setNotifs((p) => p.filter((n) => n.id !== id));

    const handleClick = (notif: AppNotification) => {
        markRead(notif.id);
        if (notif.convId && onNavigate) {
            onNavigate(notif.convId);
            setOpen(false);
        }
    };

    return (
        <div ref={ref} className="relative">
            {/* Bell button */}
            <button
                onClick={() => setOpen((o) => !o)}
                className={`relative w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${
                    open ? "bg-[#2c4e18] text-[#9ccd65]" : "text-[#699a32] hover:bg-[#2c4e18] hover:text-[#9ccd65]"
                }`}
                title="Notifications"
            >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                {unread > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center">
                        {unread > 9 ? "9+" : unread}
                    </span>
                )}
            </button>

            {/* Dropdown panel */}
            {open && (
                <div className="absolute right-0 top-10 w-80 bg-white dark:bg-[#16270c] border border-[#b5da8b] dark:border-[#2c4e18] rounded-2xl shadow-xl shadow-black/10 z-50 overflow-hidden">
                    {/* Header */}
                    <div className="flex items-center justify-between px-4 py-3 border-b border-[#e6f3d8] dark:border-[#2c4e18]">
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-[#16270c] dark:text-[#f3f9ec]">Notifications</span>
                            {unread > 0 && (
                                <span className="text-[10px] font-bold bg-red-500 text-white px-1.5 py-0.5 rounded-full">
                                    {unread}
                                </span>
                            )}
                        </div>
                        {unread > 0 && (
                            <button
                                onClick={markAllRead}
                                className="text-[10px] text-[#589b31] font-semibold hover:text-[#427425] transition-colors"
                            >
                                Mark all read
                            </button>
                        )}
                    </div>

                    {/* List */}
                    <div className="max-h-[360px] overflow-y-auto">
                        {notifs.length === 0 ? (
                            <div className="py-10 text-center">
                                <div className="text-2xl mb-2">🔔</div>
                                <p className="text-xs text-stone-400">No notifications yet</p>
                            </div>
                        ) : (
                            notifs.map((n) => {
                                const meta = NOTIF_ICON[n.type];
                                return (
                                    <div
                                        key={n.id}
                                        onClick={() => handleClick(n)}
                                        className={`flex items-start gap-3 px-4 py-3 border-b border-[#e6f3d8] dark:border-[#2c4e18] cursor-pointer hover:bg-[#f3f9ec] dark:hover:bg-[#2c4e18] transition-colors ${!n.read ? "bg-[#f0f9ec] dark:bg-[#1a270c]" : ""}`}
                                    >
                                        <div className={`w-8 h-8 rounded-lg ${meta.bg} flex items-center justify-center text-sm flex-shrink-0 mt-0.5`}>
                                            {meta.emoji}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center justify-between gap-2">
                                                <span className={`text-xs font-semibold truncate ${!n.read ? "text-[#16270c] dark:text-[#f3f9ec]" : "text-stone-600"}`}>
                                                    {n.title}
                                                </span>
                                                <span className="text-[10px] text-stone-400 flex-shrink-0">{timeAgo(n.at)}</span>
                                            </div>
                                            <p className="text-[11px] text-stone-500 mt-0.5 leading-relaxed line-clamp-2">
                                                {n.body}
                                            </p>
                                        </div>
                                        <button
                                            onClick={(e) => { e.stopPropagation(); dismiss(n.id); }}
                                            className="text-stone-300 hover:text-stone-500 flex-shrink-0 mt-0.5 text-xs"
                                        >✕</button>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    {notifs.length > 0 && (
                        <div className="px-4 py-2.5 border-t border-[#e6f3d8] dark:border-[#2c4e18]">
                            <button
                                onClick={() => setNotifs([])}
                                className="text-[10px] text-stone-400 hover:text-red-500 transition-colors"
                            >
                                Clear all
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ── Helper to push notifications from anywhere ───────────────────────────────
export function pushNotification(notif: Omit<AppNotification, "id" | "read" | "at">) {
    const event = new CustomEvent("neema:notification", {
        detail: {
            ...notif,
            id:   `${Date.now()}-${Math.random().toString(36).slice(2)}`,
            read: false,
            at:   new Date().toISOString(),
        } as AppNotification,
    });
    window.dispatchEvent(event);
}