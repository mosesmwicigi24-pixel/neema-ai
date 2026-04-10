import React, { useState, useRef, useEffect } from "react";
import { signOut } from "next-auth/react";
import { Avatar } from "@/components/ui/Avatar";
import { Notifications } from "@/components/ui/Notifications";
import { cn } from "@/lib/utils";
import type { NavItem, Session, ThemeMode, ViewId } from "@/types";

interface SidebarProps {
    navItems: NavItem[];
    view: ViewId;
    setView: (id: ViewId) => void;
    collapsed: boolean;
    setCollapsed: React.Dispatch<React.SetStateAction<boolean>>;
    session: Session;
    theme: ThemeMode;
    setTheme: React.Dispatch<React.SetStateAction<ThemeMode>>;
    onLogout?: () => void;
    notificationCount?: number;
    notifications?: any[];
    onClearNotifications?: () => void;
}

// ── Click-outside hook ────────────────────────────────────────────────────────
function useClickOutside(
    ref: React.RefObject<HTMLElement>,
    handler: () => void,
) {
    useEffect(() => {
        const listener = (e: MouseEvent | TouchEvent) => {
            if (!ref.current || ref.current.contains(e.target as Node)) return;
            handler();
        };
        document.addEventListener("mousedown", listener);
        document.addEventListener("touchstart", listener);
        return () => {
            document.removeEventListener("mousedown", listener);
            document.removeEventListener("touchstart", listener);
        };
    }, [ref, handler]);
}

// ── Dropdown menu item ────────────────────────────────────────────────────────
function MenuItem({
    icon,
    label,
    onClick,
    danger = false,
    shortcut,
}: {
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    danger?: boolean;
    shortcut?: string;
}) {
    return (
        <button
            onClick={onClick}
            className={cn(
                "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-100 group",
                danger
                    ? "text-red-500 hover:bg-red-50 hover:text-red-600"
                    : "text-stone-600 hover:bg-stone-50 hover:text-stone-900",
            )}
        >
            <span className={cn(
                "flex-shrink-0 opacity-70 group-hover:opacity-100 transition-opacity",
                danger ? "text-red-500" : "text-stone-400",
            )}>
                {icon}
            </span>
            <span className="flex-1 text-left">{label}</span>
            {shortcut && (
                <kbd className="text-[9px] text-stone-400 bg-stone-100 border border-stone-200 px-1 py-0.5 rounded font-mono">
                    {shortcut}
                </kbd>
            )}
        </button>
    );
}

// ── Tooltip for collapsed nav items ──────────────────────────────────────────
function NavTooltip({ label, children }: { label: string; children: React.ReactNode }) {
    const [show, setShow] = useState(false);
    return (
        <div
            className="relative"
            onMouseEnter={() => setShow(true)}
            onMouseLeave={() => setShow(false)}
        >
            {children}
            {show && (
                <div
                    className="absolute left-full ml-3 top-1/2 -translate-y-1/2 z-[60] px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap pointer-events-none"
                    style={{
                        backgroundColor: "#1c2917",
                        color: "#f0f9ec",
                        boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                        animation: "fadeIn 0.12s ease",
                    }}
                >
                    {label}
                    <div
                        className="absolute right-full top-1/2 -translate-y-1/2 border-4 border-transparent"
                        style={{ borderRightColor: "#1c2917" }}
                    />
                </div>
            )}
        </div>
    );
}

// ── Main Sidebar component ────────────────────────────────────────────────────
export function Sidebar({
    navItems,
    view,
    setView,
    collapsed,
    setCollapsed,
    session,
    theme,
    setTheme,
    onLogout,
}: SidebarProps): React.ReactElement {
    const [menuOpen, setMenuOpen] = useState(false);
    const [loggingOut, setLoggingOut] = useState(false);
    const footerRef = useRef<HTMLDivElement>(null);

    useClickOutside(footerRef as React.RefObject<HTMLElement>, () =>
        setMenuOpen(false),
    );

    const handleLogout = async () => {
        setLoggingOut(true);
        setMenuOpen(false);
        try {
            if (onLogout) {
                onLogout();
            } else {
                await signOut({ callbackUrl: "/login" });
            }
        } catch {
            setLoggingOut(false);
        }
    };

    const handleProfileClick = () => {
        setView("profile" as ViewId);
        setMenuOpen(false);
    };

    const handleSettingsClick = () => {
        setView("settings" as ViewId);
        setMenuOpen(false);
    };

    const handleThemeToggle = () => {
        setTheme((t) => (t === "light" ? "dark" : "light"));
    };

    return (
        <aside
            className={cn(
                "flex flex-col h-full flex-shrink-0 transition-all duration-300 overflow-hidden relative",
                collapsed ? "w-[60px]" : "w-52",
            )}
            style={{
                backgroundColor: "#ffffff",
                borderRight: "1px solid #edf0ea",
            }}
        >
            {/* ── Header bar: logo + bell (+ collapse button when expanded) ─ */}
            <div
                className={cn(
                    "flex items-center h-14 flex-shrink-0 gap-1",
                    collapsed ? "flex-col justify-center py-2 px-0 h-auto gap-2" : "px-3",
                )}
                style={{ borderBottom: "1px solid #edf0ea" }}
            >
                {/* Logo mark — always visible */}
                <div
                    className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
                    style={{
                        backgroundColor: "#589b31",
                        boxShadow: "0 2px 8px rgba(88,155,49,0.3)",
                    }}
                >
                    <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                </div>

                {/* Brand name — expanded only */}
                {!collapsed && (
                    <div className="flex-1 min-w-0 ml-1">
                        <div className="font-semibold text-sm leading-none" style={{ color: "#16270c" }}>
                            Neema
                        </div>
                        <div className="text-[10px] font-medium mt-0.5 uppercase tracking-widest" style={{ color: "#699a32" }}>
                            Admin
                        </div>
                    </div>
                )}

                {/* Bell — always visible; compact=true when collapsed so popup opens to the right */}
                <NavTooltip label={collapsed ? "Notifications" : ""}>
                    <Notifications compact={collapsed} />
                </NavTooltip>

                {/* Collapse toggle — expanded only */}
                {!collapsed && (
                    <button
                        onClick={() => setCollapsed(true)}
                        className="w-7 h-7 flex items-center justify-center rounded-lg transition-colors flex-shrink-0"
                        style={{ color: "#c5d5bc" }}
                        title="Collapse sidebar"
                        onMouseEnter={(e) => {
                            (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                            (e.currentTarget as HTMLElement).style.color = "#427425";
                        }}
                        onMouseLeave={(e) => {
                            (e.currentTarget as HTMLElement).style.backgroundColor = "";
                            (e.currentTarget as HTMLElement).style.color = "#c5d5bc";
                        }}
                    >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                        </svg>
                    </button>
                )}
            </div>

            {/* ── Nav items ────────────────────────────────────────────────── */}
            <nav className="flex-1 overflow-y-auto scrollbar-none py-2 px-2">
                {/* Expand button — collapsed only, at top of nav */}
                {collapsed && (
                    <NavTooltip label="Expand sidebar">
                        <button
                            onClick={() => setCollapsed(false)}
                            className="w-full flex items-center justify-center h-9 mb-2 rounded-lg transition-colors"
                            style={{ color: "#c5d5bc" }}
                            onMouseEnter={(e) => {
                                (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                                (e.currentTarget as HTMLElement).style.color = "#427425";
                            }}
                            onMouseLeave={(e) => {
                                (e.currentTarget as HTMLElement).style.backgroundColor = "";
                                (e.currentTarget as HTMLElement).style.color = "#c5d5bc";
                            }}
                        >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                            </svg>
                        </button>
                    </NavTooltip>
                )}

                <div className="space-y-0.5">
                    {navItems.map((item) => {
                        const isActive = view === item.id;
                        const navBtn = (
                            <button
                                key={item.id}
                                onClick={() => setView(item.id as ViewId)}
                                className={cn(
                                    "w-full flex items-center rounded-xl text-sm font-medium transition-all duration-150 relative",
                                    collapsed ? "justify-center h-10 px-0" : "gap-2.5 px-3 h-10",
                                )}
                                style={{
                                    backgroundColor: isActive ? "#589b31" : "transparent",
                                    color: isActive ? "#ffffff" : "#6b7e64",
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                                }}
                            >
                                <span
                                    className="flex-shrink-0 leading-none"
                                    style={{ color: isActive ? "#ffffff" : "#8a9e80" }}
                                >
                                    {item.icon}
                                </span>
                                {!collapsed && (
                                    <>
                                        <span className="flex-1 text-left truncate font-medium" style={{ fontSize: 13 }}>
                                            {item.label}
                                        </span>
                                        {item.badge != null && (
                                            <span
                                                className="ml-auto flex-shrink-0 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1"
                                                style={{ backgroundColor: isActive ? "rgba(255,255,255,0.3)" : "#589b31" }}
                                            >
                                                {item.badge}
                                            </span>
                                        )}
                                    </>
                                )}
                                {collapsed && item.badge != null && (
                                    <span
                                        className="absolute top-1 right-1 w-3.5 h-3.5 text-white text-[8px] font-bold rounded-full flex items-center justify-center"
                                        style={{ backgroundColor: "#589b31" }}
                                    >
                                        {item.badge}
                                    </span>
                                )}
                            </button>
                        );

                        return collapsed ? (
                            <NavTooltip key={item.id} label={item.label}>
                                {navBtn}
                            </NavTooltip>
                        ) : (
                            <React.Fragment key={item.id}>{navBtn}</React.Fragment>
                        );
                    })}
                </div>
            </nav>

            {/* ── User footer — always visible ──────────────────────────────── */}
            <div
                className="flex-shrink-0 p-2 relative"
                style={{ borderTop: "1px solid #edf0ea" }}
                ref={footerRef}
            >
                {/* Account popup — anchored above footer, works in both states */}
                {menuOpen && (
                    <div
                        className={cn(
                            "absolute bottom-full mb-2 z-50 rounded-xl overflow-hidden",
                            collapsed ? "left-full ml-2 w-60" : "left-2 right-2",
                        )}
                        style={{
                            backgroundColor: "#ffffff",
                            border: "1px solid #e8ebe3",
                            boxShadow: "0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)",
                            animation: "menuSlideUp 0.15s ease",
                        }}
                    >
                        <style>{`
                            @keyframes menuSlideUp {
                                from { opacity: 0; transform: translateY(6px); }
                                to   { opacity: 1; transform: translateY(0); }
                            }
                        `}</style>

                        {/* User identity */}
                        <div className="px-4 py-4" style={{ borderBottom: "1px solid #edf0ea" }}>
                            <div className="flex items-center gap-3">
                                <div className="flex-shrink-0">
                                    <Avatar name={session.user.name} size="md" />
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="text-sm font-semibold truncate leading-tight" style={{ color: "#1c2917" }}>
                                        {session.user.name || "—"}
                                    </div>
                                    <div className="text-[11px] truncate mt-0.5" style={{ color: "#8a9e80" }}>
                                        {session.user.email || "—"}
                                    </div>
                                    <span
                                        className="inline-block mt-1.5 text-[9px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide"
                                        style={{
                                            backgroundColor: "#f0f9ec",
                                            color: "#589b31",
                                            border: "1px solid #c5e7b1",
                                        }}
                                    >
                                        {session.user.role}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Actions */}
                        <div className="p-1.5 space-y-0.5">
                            <MenuItem
                                icon={
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                                    </svg>
                                }
                                label="View Profile"
                                onClick={handleProfileClick}
                            />
                            <MenuItem
                                icon={
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                    </svg>
                                }
                                label="Settings"
                                onClick={handleSettingsClick}
                            />
                        </div>

                        {/* Theme toggle */}
                        <div className="px-3 py-2.5" style={{ borderTop: "1px solid #edf0ea" }}>
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="text-stone-400">
                                        {theme === "light" ? (
                                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                    d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                                            </svg>
                                        ) : (
                                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                    d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                                            </svg>
                                        )}
                                    </span>
                                    <span className="text-xs font-medium" style={{ color: "#4a5568" }}>
                                        {theme === "light" ? "Dark mode" : "Light mode"}
                                    </span>
                                </div>
                                <button
                                    onClick={handleThemeToggle}
                                    className="relative rounded-full transition-colors duration-200 flex-shrink-0"
                                    style={{
                                        height: 18,
                                        width: 32,
                                        backgroundColor: theme === "dark" ? "#589b31" : "#dde4d6",
                                    }}
                                >
                                    <span
                                        className="absolute top-0.5 w-3.5 h-3.5 bg-white rounded-full shadow-sm transition-transform duration-200"
                                        style={{ transform: theme === "dark" ? "translateX(16px)" : "translateX(2px)" }}
                                    />
                                </button>
                            </div>
                        </div>

                        {/* Sign out */}
                        <div className="p-1.5" style={{ borderTop: "1px solid #edf0ea" }}>
                            <MenuItem
                                icon={
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                                    </svg>
                                }
                                label={loggingOut ? "Signing out…" : "Sign out"}
                                onClick={handleLogout}
                                danger
                            />
                        </div>
                    </div>
                )}

                {/* Collapsed: centered avatar button */}
                {collapsed ? (
                    <button
                        onClick={() => setMenuOpen((o) => !o)}
                        className="relative mx-auto flex items-center justify-center w-10 h-10 rounded-xl transition-colors"
                        title="Account menu"
                        style={{ backgroundColor: menuOpen ? "#f0f4ec" : "transparent" }}
                        onMouseEnter={(e) => {
                            (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                        }}
                        onMouseLeave={(e) => {
                            if (!menuOpen) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                        }}
                    >
                        <Avatar name={session.user.name} size="sm" />
                        <span
                            className="absolute bottom-1.5 right-1.5 w-2 h-2 rounded-full border-2 border-white"
                            style={{ backgroundColor: "#22c55e" }}
                        />
                        {loggingOut && (
                            <div className="absolute inset-0 flex items-center justify-center bg-white/80 rounded-xl">
                                <div
                                    className="w-3 h-3 border-2 border-t-transparent rounded-full animate-spin"
                                    style={{ borderColor: "#589b31", borderTopColor: "transparent" }}
                                />
                            </div>
                        )}
                    </button>
                ) : (
                    /* Expanded: full user row — avatar + name + email */
                    <button
                        onClick={() => setMenuOpen((o) => !o)}
                        className="w-full flex items-center gap-2.5 p-2 rounded-xl transition-all duration-150"
                        style={{ backgroundColor: menuOpen ? "#f0f4ec" : "transparent" }}
                        onMouseEnter={(e) => {
                            (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                        }}
                        onMouseLeave={(e) => {
                            if (!menuOpen) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                        }}
                    >
                        <div className="relative flex-shrink-0">
                            <Avatar name={session.user.name} size="sm" />
                            <span
                                className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full border-2 border-white"
                                style={{ backgroundColor: "#22c55e" }}
                            />
                        </div>
                        <div className="flex-1 min-w-0 text-left">
                            <div className="text-xs font-semibold truncate leading-tight" style={{ color: "#1c2917" }}>
                                {session.user.name || "—"}
                            </div>
                            <div className="text-[10px] truncate leading-tight mt-0.5" style={{ color: "#8a9e80" }}>
                                {session.user.email || "—"}
                            </div>
                        </div>
                        <svg
                            className="w-3.5 h-3.5 flex-shrink-0 transition-transform duration-200"
                            style={{ color: "#c5d5bc", transform: menuOpen ? "rotate(180deg)" : "none" }}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                        </svg>
                    </button>
                )}
            </div>
        </aside>
    );
}