import React, { useState, useRef, useEffect, useCallback } from "react";
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
    refs: React.RefObject<HTMLElement>[],
    handler: () => void,
) {
    useEffect(() => {
        const listener = (e: MouseEvent | TouchEvent) => {
            if (refs.some((r) => r.current?.contains(e.target as Node))) return;
            handler();
        };
        document.addEventListener("mousedown", listener);
        document.addEventListener("touchstart", listener);
        return () => {
            document.removeEventListener("mousedown", listener);
            document.removeEventListener("touchstart", listener);
        };
    }, [refs, handler]);
}

// ── Dropdown menu item ────────────────────────────────────────────────────────
function MenuItem({
    icon,
    label,
    onClick,
    danger = false,
}: {
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    danger?: boolean;
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
                danger ? "text-red-400" : "text-stone-400",
            )}>
                {icon}
            </span>
            <span className="flex-1 text-left">{label}</span>
        </button>
    );
}

// ── Simple tooltip — only renders when label is non-empty ─────────────────────
function NavTooltip({ label, children }: { label: string; children: React.ReactNode }) {
    const [show, setShow] = useState(false);

    // Don't wrap if no label — avoids empty black box
    if (!label) return <>{children}</>;

    return (
        <div
            className="relative"
            onMouseEnter={() => setShow(true)}
            onMouseLeave={() => setShow(false)}
        >
            {children}
            {show && (
                <div
                    className="absolute left-full ml-3 top-1/2 -translate-y-1/2 z-[9999] px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap pointer-events-none"
                    style={{
                        backgroundColor: "#1c2917",
                        color: "#f0f9ec",
                        boxShadow: "0 4px 12px rgba(0,0,0,0.18)",
                        animation: "fadeIn 0.1s ease",
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

// ── Account popup — uses position:fixed to escape overflow:hidden on aside ────
function AccountPopup({
    open,
    anchorRef,
    collapsed,
    session,
    theme,
    onThemeToggle,
    onProfile,
    onSettings,
    onLogout,
    loggingOut,
    popupRef,
}: {
    open: boolean;
    anchorRef: React.RefObject<HTMLElement>;
    collapsed: boolean;
    session: Session;
    theme: ThemeMode;
    onThemeToggle: () => void;
    onProfile: () => void;
    onSettings: () => void;
    onLogout: () => void;
    loggingOut: boolean;
    popupRef: React.RefObject<HTMLDivElement>;
}) {
    const [pos, setPos] = useState({ top: 0, left: 0, width: 0 });

    useEffect(() => {
        if (!open || !anchorRef.current) return;
        const r = anchorRef.current.getBoundingClientRect();
        if (collapsed) {
            // Popup to the RIGHT of the sidebar
            setPos({ top: r.top, left: r.right + 8, width: 248 });
        } else {
            // Popup above the footer, aligned to sidebar width
            setPos({
                top: r.top - 8,        // will be adjusted by translateY(-100%)
                left: r.left,
                width: r.width,
            });
        }
    }, [open, anchorRef, collapsed]);

    if (!open) return null;

    return (
        <div
            ref={popupRef}
            style={{
                position: "fixed",
                zIndex: 9999,
                backgroundColor: "#ffffff",
                border: "1px solid #e8ebe3",
                borderRadius: 14,
                boxShadow: "0 8px 32px rgba(0,0,0,0.13), 0 2px 8px rgba(0,0,0,0.06)",
                overflow: "hidden",
                animation: "accountPopIn 0.15s ease",
                ...(collapsed
                    ? { top: pos.top, left: pos.left, width: pos.width }
                    : { bottom: `calc(100vh - ${pos.top}px)`, left: pos.left, width: pos.width }),
            }}
        >
            <style>{`
                @keyframes accountPopIn {
                    from { opacity: 0; transform: translateY(4px); }
                    to   { opacity: 1; transform: translateY(0); }
                }
            `}</style>

            {/* ── User identity ──────────────────────────────────────────── */}
            <div className="px-4 py-4" style={{ borderBottom: "1px solid #edf0ea" }}>
                <div className="flex items-center gap-3">
                    <div className="flex-shrink-0">
                        <Avatar name={session.user.name || "U"} size="md" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div
                            className="text-sm font-semibold truncate leading-snug"
                            style={{ color: "#1c2917" }}
                        >
                            {session.user.name || "Unknown"}
                        </div>
                        <div
                            className="text-[11px] truncate mt-0.5"
                            style={{ color: "#8a9e80" }}
                        >
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

            {/* ── Actions ────────────────────────────────────────────────── */}
            <div className="p-1.5 space-y-0.5">
                <MenuItem
                    icon={
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                        </svg>
                    }
                    label="View Profile"
                    onClick={onProfile}
                />
                <MenuItem
                    icon={
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                    }
                    label="Settings"
                    onClick={onSettings}
                />
            </div>

            {/* ── Theme toggle ───────────────────────────────────────────── */}
            <div className="px-3 py-2.5" style={{ borderTop: "1px solid #edf0ea" }}>
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <span style={{ color: "#a0aec0" }}>
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
                        onClick={onThemeToggle}
                        style={{
                            position: "relative",
                            height: 18,
                            width: 32,
                            borderRadius: 9999,
                            backgroundColor: theme === "dark" ? "#589b31" : "#dde4d6",
                            transition: "background-color 0.2s",
                            flexShrink: 0,
                            border: "none",
                            cursor: "pointer",
                        }}
                    >
                        <span
                            style={{
                                position: "absolute",
                                top: 2,
                                width: 14,
                                height: 14,
                                backgroundColor: "#ffffff",
                                borderRadius: 9999,
                                boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                                transition: "transform 0.2s",
                                transform: theme === "dark" ? "translateX(16px)" : "translateX(2px)",
                            }}
                        />
                    </button>
                </div>
            </div>

            {/* ── Sign out ───────────────────────────────────────────────── */}
            <div className="p-1.5" style={{ borderTop: "1px solid #edf0ea" }}>
                <MenuItem
                    icon={
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                        </svg>
                    }
                    label={loggingOut ? "Signing out…" : "Sign out"}
                    onClick={onLogout}
                    danger
                />
            </div>
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

    // Refs for the footer trigger button and the popup panel
    const footerBtnRef = useRef<HTMLButtonElement>(null);
    const popupRef     = useRef<HTMLDivElement>(null);

    // Close popup when clicking outside both the trigger and the popup
    useClickOutside(
        [footerBtnRef as React.RefObject<HTMLElement>, popupRef as React.RefObject<HTMLElement>],
        () => setMenuOpen(false),
    );

    const handleLogout = async () => {
        setLoggingOut(true);
        setMenuOpen(false);
        try {
            if (onLogout) onLogout();
            else {
                const { signOut: so } = await import("next-auth/react");
                await so({ callbackUrl: "/login" });
            }
        } catch {
            setLoggingOut(false);
        }
    };

    const handleProfile = useCallback(() => {
        setView("profile" as ViewId);
        setMenuOpen(false);
    }, [setView]);

    const handleSettings = useCallback(() => {
        setView("settings" as ViewId);
        setMenuOpen(false);
    }, [setView]);

    const handleThemeToggle = useCallback(() => {
        setTheme((t) => (t === "light" ? "dark" : "light"));
    }, [setTheme]);

    return (
        <aside
            className={cn(
                "flex flex-col h-full flex-shrink-0 transition-all duration-300 relative",
                collapsed ? "w-[60px]" : "w-52",
            )}
            style={{
                backgroundColor: "#ffffff",
                borderRight: "1px solid #edf0ea",
                // NOTE: no overflow:hidden — lets fixed popups escape freely
            }}
        >
            {/* ── Header: logo + bell [+ brand + collapse when expanded] ───── */}
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    height: collapsed ? "auto" : 56,
                    flexDirection: collapsed ? "column" : "row",
                    padding: collapsed ? "12px 0 8px" : "0 12px",
                    gap: collapsed ? 8 : 4,
                    borderBottom: "1px solid #edf0ea",
                    flexShrink: 0,
                }}
            >
                {/* Logo mark */}
                <div
                    style={{
                        width: 32,
                        height: 32,
                        borderRadius: 10,
                        backgroundColor: "#589b31",
                        boxShadow: "0 2px 8px rgba(88,155,49,0.28)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                    }}
                >
                    <svg width="16" height="16" fill="none" stroke="white" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                </div>

                {/* Brand — expanded only */}
                {!collapsed && (
                    <div style={{ flex: 1, minWidth: 0, marginLeft: 6 }}>
                        <div style={{ fontWeight: 600, fontSize: 13, color: "#16270c", lineHeight: 1 }}>
                            Neema
                        </div>
                        <div style={{ fontSize: 10, fontWeight: 500, color: "#699a32", letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 2 }}>
                            Admin
                        </div>
                    </div>
                )}

                {/* Bell — always visible; compact=collapsed so popup goes right */}
                <Notifications compact={collapsed} />

                {/* Collapse button — expanded only */}
                {!collapsed && (
                    <button
                        onClick={() => setCollapsed(true)}
                        title="Collapse sidebar"
                        style={{
                            width: 28,
                            height: 28,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            borderRadius: 8,
                            border: "none",
                            backgroundColor: "transparent",
                            color: "#c5d5bc",
                            cursor: "pointer",
                            flexShrink: 0,
                            transition: "background-color 0.15s, color 0.15s",
                        }}
                        onMouseEnter={(e) => {
                            (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                            (e.currentTarget as HTMLElement).style.color = "#427425";
                        }}
                        onMouseLeave={(e) => {
                            (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                            (e.currentTarget as HTMLElement).style.color = "#c5d5bc";
                        }}
                    >
                        <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                        </svg>
                    </button>
                )}
            </div>

            {/* ── Nav items ────────────────────────────────────────────────── */}
            <nav style={{ flex: 1, overflowY: "auto", padding: "8px", scrollbarWidth: "none" }}>
                {/* Expand button — collapsed only */}
                {collapsed && (
                    <NavTooltip label="Expand sidebar">
                        <button
                            onClick={() => setCollapsed(false)}
                            style={{
                                width: "100%",
                                height: 36,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                borderRadius: 10,
                                border: "none",
                                backgroundColor: "transparent",
                                color: "#c5d5bc",
                                cursor: "pointer",
                                marginBottom: 6,
                                transition: "background-color 0.15s, color 0.15s",
                            }}
                            onMouseEnter={(e) => {
                                (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                                (e.currentTarget as HTMLElement).style.color = "#427425";
                            }}
                            onMouseLeave={(e) => {
                                (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                                (e.currentTarget as HTMLElement).style.color = "#c5d5bc";
                            }}
                        >
                            <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                            </svg>
                        </button>
                    </NavTooltip>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {navItems.map((item) => {
                        const isActive = view === item.id;
                        const btn = (
                            <button
                                key={item.id}
                                onClick={() => setView(item.id as ViewId)}
                                style={{
                                    width: "100%",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: collapsed ? "center" : "flex-start",
                                    gap: 10,
                                    padding: collapsed ? "0" : "0 12px",
                                    height: 40,
                                    borderRadius: 12,
                                    border: "none",
                                    backgroundColor: isActive ? "#589b31" : "transparent",
                                    color: isActive ? "#ffffff" : "#6b7e64",
                                    cursor: "pointer",
                                    position: "relative",
                                    transition: "background-color 0.15s",
                                    fontFamily: "inherit",
                                    fontSize: 13,
                                    fontWeight: 500,
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec";
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                                }}
                            >
                                <span style={{ color: isActive ? "#ffffff" : "#8a9e80", flexShrink: 0, lineHeight: 0 }}>
                                    {item.icon}
                                </span>
                                {!collapsed && (
                                    <>
                                        <span style={{ flex: 1, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                            {item.label}
                                        </span>
                                        {item.badge != null && (
                                            <span style={{
                                                marginLeft: "auto",
                                                flexShrink: 0,
                                                backgroundColor: isActive ? "rgba(255,255,255,0.3)" : "#589b31",
                                                color: "#ffffff",
                                                fontSize: 10,
                                                fontWeight: 700,
                                                borderRadius: 9999,
                                                minWidth: 18,
                                                height: 18,
                                                display: "flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                padding: "0 4px",
                                            }}>
                                                {item.badge}
                                            </span>
                                        )}
                                    </>
                                )}
                                {collapsed && item.badge != null && (
                                    <span style={{
                                        position: "absolute",
                                        top: 4,
                                        right: 4,
                                        width: 14,
                                        height: 14,
                                        backgroundColor: "#589b31",
                                        color: "#ffffff",
                                        fontSize: 8,
                                        fontWeight: 700,
                                        borderRadius: 9999,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}>
                                        {item.badge}
                                    </span>
                                )}
                            </button>
                        );

                        return collapsed ? (
                            <NavTooltip key={item.id} label={item.label}>{btn}</NavTooltip>
                        ) : (
                            <React.Fragment key={item.id}>{btn}</React.Fragment>
                        );
                    })}
                </div>
            </nav>

            {/* ── User footer ───────────────────────────────────────────────── */}
            <div style={{ flexShrink: 0, padding: 8, borderTop: "1px solid #edf0ea" }}>
                {/* Account popup — position:fixed, not clipped by aside */}
                <AccountPopup
                    open={menuOpen}
                    anchorRef={footerBtnRef as React.RefObject<HTMLElement>}
                    collapsed={collapsed}
                    session={session}
                    theme={theme}
                    onThemeToggle={handleThemeToggle}
                    onProfile={handleProfile}
                    onSettings={handleSettings}
                    onLogout={handleLogout}
                    loggingOut={loggingOut}
                    popupRef={popupRef}
                />

                {/* Collapsed: centered avatar */}
                {collapsed ? (
                    <button
                        ref={footerBtnRef}
                        onClick={() => setMenuOpen((o) => !o)}
                        title="Account menu"
                        style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            padding: "4px 0",
                            border: "none",
                            borderRadius: 12,
                            backgroundColor: menuOpen ? "#f0f4ec" : "transparent",
                            cursor: "pointer",
                            position: "relative",
                            transition: "background-color 0.15s",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec"; }}
                        onMouseLeave={(e) => { if (!menuOpen) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                        <div style={{ position: "relative", display: "inline-flex" }}>
                            <Avatar name={session.user.name || "U"} size="sm" />
                            {/* Online dot */}
                            <span style={{
                                position: "absolute",
                                bottom: 0,
                                right: 0,
                                width: 9,
                                height: 9,
                                backgroundColor: "#22c55e",
                                borderRadius: "50%",
                                border: "2px solid #ffffff",
                            }} />
                        </div>
                        {loggingOut && (
                            <div style={{
                                position: "absolute",
                                inset: 0,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                backgroundColor: "rgba(255,255,255,0.8)",
                                borderRadius: 12,
                            }}>
                                <div style={{
                                    width: 12,
                                    height: 12,
                                    border: "2px solid #589b31",
                                    borderTopColor: "transparent",
                                    borderRadius: "50%",
                                    animation: "spin 0.7s linear infinite",
                                }} />
                            </div>
                        )}
                    </button>
                ) : (
                    /* Expanded: avatar + name + email row */
                    <button
                        ref={footerBtnRef}
                        onClick={() => setMenuOpen((o) => !o)}
                        style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            padding: "6px 8px",
                            border: "none",
                            borderRadius: 12,
                            backgroundColor: menuOpen ? "#f0f4ec" : "transparent",
                            cursor: "pointer",
                            transition: "background-color 0.15s",
                            fontFamily: "inherit",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#f0f4ec"; }}
                        onMouseLeave={(e) => { if (!menuOpen) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                        {/* Avatar + online dot */}
                        <div style={{ position: "relative", flexShrink: 0 }}>
                            <Avatar name={session.user.name || "U"} size="sm" />
                            <span style={{
                                position: "absolute",
                                bottom: 0,
                                right: 0,
                                width: 9,
                                height: 9,
                                backgroundColor: "#22c55e",
                                borderRadius: "50%",
                                border: "2px solid #ffffff",
                            }} />
                        </div>

                        {/* Name + email */}
                        <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                            <div style={{
                                fontSize: 12,
                                fontWeight: 600,
                                color: "#1c2917",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                lineHeight: 1.3,
                            }}>
                                {session.user.name || "—"}
                            </div>
                            <div style={{
                                fontSize: 10,
                                color: "#8a9e80",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                lineHeight: 1.3,
                                marginTop: 1,
                            }}>
                                {session.user.email || "—"}
                            </div>
                        </div>

                        {/* Chevron */}
                        <svg
                            width="14" height="14"
                            fill="none" stroke="#c5d5bc"
                            viewBox="0 0 24 24"
                            style={{
                                flexShrink: 0,
                                transition: "transform 0.2s",
                                transform: menuOpen ? "rotate(180deg)" : "none",
                            }}
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                        </svg>
                    </button>
                )}
            </div>
        </aside>
    );
}