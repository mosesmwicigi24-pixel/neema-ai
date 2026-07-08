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

// ── Click-outside hook ─────────────────────────────────────────────────────────
function useClickOutside(
    refs: Array<React.RefObject<HTMLElement | null>>,
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
    });
}

// ── Dropdown menu item ─────────────────────────────────────────────────────────
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
            style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 12px",
                border: "none",
                borderRadius: 8,
                backgroundColor: "transparent",
                color: danger ? "#ef4444" : "#4a5568",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 500,
                fontFamily: "inherit",
                textAlign: "left",
                transition: "background-color 0.12s",
            }}
            onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.backgroundColor = danger ? "#fef2f2" : "#f8fafc";
            }}
            onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
            }}
        >
            <span style={{ flexShrink: 0, opacity: 0.65, color: danger ? "#ef4444" : "#718096", lineHeight: 0 }}>
                {icon}
            </span>
            {label}
        </button>
    );
}

// ── Tooltip — only renders when label is non-empty ────────────────────────────
function NavTooltip({ label, children }: { label: string; children: React.ReactNode }) {
    const [show, setShow] = useState(false);
    if (!label) return <>{children}</>;
    return (
        <div
            style={{ position: "relative" }}
            onMouseEnter={() => setShow(true)}
            onMouseLeave={() => setShow(false)}
        >
            {children}
            {show && (
                <div
                    style={{
                        position: "absolute",
                        left: "calc(100% + 10px)",
                        top: "50%",
                        transform: "translateY(-50%)",
                        zIndex: 9999,
                        backgroundColor: "#1c2917",
                        color: "#f0f9ec",
                        fontSize: 11,
                        fontWeight: 500,
                        padding: "5px 10px",
                        borderRadius: 8,
                        whiteSpace: "nowrap",
                        pointerEvents: "none",
                        boxShadow: "0 4px 12px rgba(0,0,0,0.18)",
                        animation: "fadeIn 0.1s ease",
                    }}
                >
                    {label}
                    {/* Arrow */}
                    <div style={{
                        position: "absolute",
                        right: "100%",
                        top: "50%",
                        transform: "translateY(-50%)",
                        borderWidth: 4,
                        borderStyle: "solid",
                        borderColor: "transparent #1c2917 transparent transparent",
                    }} />
                </div>
            )}
        </div>
    );
}

// ── Account popup — position:fixed escapes overflow:hidden on the aside ────────
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
    anchorRef: React.RefObject<HTMLButtonElement | null>;
    collapsed: boolean;
    session: Session;
    theme: ThemeMode;
    onThemeToggle: () => void;
    onProfile: () => void;
    onSettings: () => void;
    onLogout: () => void;
    loggingOut: boolean;
    popupRef: React.RefObject<HTMLDivElement | null>;
}) {
    const [style, setStyle] = useState<React.CSSProperties>({});

    useEffect(() => {
        if (!open || !anchorRef.current) return;
        const r = anchorRef.current.getBoundingClientRect();
        const POPUP_WIDTH = 252;
        const POPUP_GAP = 8;

        if (collapsed) {
            // ── Collapsed: open to the RIGHT, bottom-anchored to avatar top ──
            // "bottom" in fixed coords = viewport height minus the top of the button
            setStyle({
                position: "fixed",
                bottom: window.innerHeight - r.top - r.height, // align bottom of popup with bottom of button
                left: r.right + POPUP_GAP,
                width: POPUP_WIDTH,
            });
        } else {
            // ── Expanded: open ABOVE the footer row ──────────────────────────
            // "bottom" in fixed coords = viewport height minus top of footer button
            setStyle({
                position: "fixed",
                bottom: window.innerHeight - r.top + POPUP_GAP,
                left: r.left,
                width: r.width,
            });
        }
    }, [open, collapsed, anchorRef]);

    if (!open) return null;

    const divider = { borderTop: "1px solid #edf0ea" };

    return (
        <div
            ref={popupRef}
            style={{
                ...style,
                zIndex: 9999,
                backgroundColor: "#ffffff",
                border: "1px solid #e8ebe3",
                borderRadius: 14,
                boxShadow: "0 -4px 24px rgba(0,0,0,0.10), 0 8px 32px rgba(0,0,0,0.10)",
                overflow: "hidden",
                animation: "popupIn 0.14s ease",
                fontFamily: "inherit",
            }}
        >
            <style>{`
                @keyframes popupIn {
                    from { opacity: 0; transform: translateY(6px); }
                    to   { opacity: 1; transform: translateY(0); }
                }
            `}</style>

            {/* ── Identity header ──────────────────────────────────────────── */}
            <div style={{ padding: "14px 16px", ...divider, borderTop: "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    {/* Avatar — always visible and correctly colored */}
                    <div style={{ flexShrink: 0 }}>
                        <Avatar name={session.user.name || "User"} size="md" />
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{
                            fontSize: 13,
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
                            fontSize: 11,
                            color: "#8a9e80",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            lineHeight: 1.4,
                            marginTop: 2,
                        }}>
                            {session.user.email || "—"}
                        </div>
                        <span style={{
                            display: "inline-block",
                            marginTop: 6,
                            fontSize: 9,
                            fontWeight: 700,
                            textTransform: "uppercase",
                            letterSpacing: "0.08em",
                            padding: "2px 8px",
                            borderRadius: 999,
                            backgroundColor: "#f0f9ec",
                            color: "#589b31",
                            border: "1px solid #c5e7b1",
                        }}>
                            {session.user.role}
                        </span>
                    </div>
                </div>
            </div>

            {/* ── Actions ──────────────────────────────────────────────────── */}
            <div style={{ padding: "6px", ...divider }}>
                <MenuItem
                    icon={
                        <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                        </svg>
                    }
                    label="View Profile"
                    onClick={onProfile}
                />
                <MenuItem
                    icon={
                        <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                    }
                    label="Settings"
                    onClick={onSettings}
                />
            </div>

            {/* ── Theme toggle ─────────────────────────────────────────────── */}
            <div style={{ padding: "10px 14px", ...divider }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color: "#a0aec0", lineHeight: 0 }}>
                            {theme === "light" ? (
                                <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                                </svg>
                            ) : (
                                <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                                </svg>
                            )}
                        </span>
                        <span style={{ fontSize: 12, fontWeight: 500, color: "#4a5568" }}>
                            {theme === "light" ? "Dark mode" : "Light mode"}
                        </span>
                    </div>
                    {/* Toggle pill */}
                    <button
                        onClick={onThemeToggle}
                        style={{
                            position: "relative",
                            width: 32,
                            height: 18,
                            borderRadius: 9999,
                            border: "none",
                            backgroundColor: theme === "dark" ? "#589b31" : "#dde4d6",
                            cursor: "pointer",
                            flexShrink: 0,
                            transition: "background-color 0.2s",
                        }}
                    >
                        <span style={{
                            position: "absolute",
                            top: 2,
                            left: theme === "dark" ? 14 : 2,
                            width: 14,
                            height: 14,
                            borderRadius: "50%",
                            backgroundColor: "#ffffff",
                            boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                            transition: "left 0.2s",
                        }} />
                    </button>
                </div>
            </div>

            {/* ── Sign out ─────────────────────────────────────────────────── */}
            <div style={{ padding: "6px", ...divider }}>
                <MenuItem
                    icon={
                        <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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

// ── Main Sidebar ───────────────────────────────────────────────────────────────
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
    const [menuOpen, setMenuOpen]   = useState(false);
    const [loggingOut, setLoggingOut] = useState(false);

    const footerBtnRef = useRef<HTMLButtonElement>(null);
    const popupRef     = useRef<HTMLDivElement>(null);

    useClickOutside(
        [footerBtnRef as React.RefObject<HTMLElement>, popupRef as React.RefObject<HTMLElement>],
        () => setMenuOpen(false),
    );

    const handleLogout = async () => {
        setLoggingOut(true);
        setMenuOpen(false);
        try {
            if (onLogout) onLogout();
            else await signOut({ callbackUrl: "/login" });
        } catch {
            setLoggingOut(false);
        }
    };

    const handleProfile  = useCallback(() => { setView("profile" as ViewId);  setMenuOpen(false); }, [setView]);
    const handleSettings = useCallback(() => { setView("settings" as ViewId); setMenuOpen(false); }, [setView]);
    const handleTheme    = useCallback(() => { setTheme((t) => t === "light" ? "dark" : "light"); }, [setTheme]);

    // ── Shared inline styles ──────────────────────────────────────────────────
    // ── Figma dark-navy palette ───────────────────────────────────────────────
    const NAVY = "#0e1729";        // sidebar background
    const NAVY_BORDER = "#1e2a44"; // dividers / borders
    const NAVY_HOVER = "#1b2740";  // hover fill
    const GOLD = "#f59e0b";        // active / accent
    const TEXT_MUTED = "#94a3b8";  // inactive labels + icons
    const TEXT_LIGHT = "#f8fafc";  // primary text on navy

    const sidebarStyle: React.CSSProperties = {
        display: "flex",
        flexDirection: "column",
        height: "100%",
        width: collapsed ? 60 : 208,
        flexShrink: 0,
        backgroundColor: NAVY,
        borderRight: `1px solid ${NAVY_BORDER}`,
        transition: "width 0.3s ease",
        position: "relative",
        // NO overflow:hidden — lets fixed popups escape freely
    };

    const headerStyle: React.CSSProperties = {
        display: "flex",
        alignItems: "center",
        flexDirection: collapsed ? "column" : "row",
        height: collapsed ? "auto" : 56,
        padding: collapsed ? "12px 0 8px" : "0 10px",
        gap: collapsed ? 6 : 4,
        borderBottom: `1px solid ${NAVY_BORDER}`,
        flexShrink: 0,
    };

    const footerStyle: React.CSSProperties = {
        flexShrink: 0,
        padding: 8,
        borderTop: `1px solid ${NAVY_BORDER}`,
    };

    return (
        <aside style={sidebarStyle}>
            {/* ── Header: logo + bell [+ brand + collapse btn] ─────────────── */}
            <div style={headerStyle}>
                {/* Logo */}
                <div style={{
                    width: 32, height: 32,
                    borderRadius: 10,
                    backgroundColor: GOLD,
                    boxShadow: "0 2px 8px rgba(245,158,11,0.35)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    flexShrink: 0,
                }}>
                    <svg width="16" height="16" fill="none" stroke="white" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                </div>

                {/* Brand — expanded only */}
                {!collapsed && (
                    <div style={{ flex: 1, minWidth: 0, marginLeft: 6 }}>
                        <div style={{ fontWeight: 600, fontSize: 13, color: TEXT_LIGHT, lineHeight: 1 }}>Neema AI</div>
                        <div style={{ fontSize: 10, fontWeight: 500, color: TEXT_MUTED, letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 2 }}>Admin Portal</div>
                    </div>
                )}

                {/* Bell — always visible; compact=true when collapsed opens popup to the right */}
                <Notifications compact={collapsed} />

                {/* Collapse toggle — expanded only */}
                {!collapsed && (
                    <button
                        onClick={() => setCollapsed(true)}
                        title="Collapse sidebar"
                        style={{
                            width: 28, height: 28,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            borderRadius: 8, border: "none",
                            backgroundColor: "transparent", color: TEXT_MUTED,
                            cursor: "pointer", flexShrink: 0,
                            transition: "background-color 0.15s, color 0.15s",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = NAVY_HOVER; (e.currentTarget as HTMLElement).style.color = GOLD; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; (e.currentTarget as HTMLElement).style.color = TEXT_MUTED; }}
                    >
                        <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                        </svg>
                    </button>
                )}
            </div>

            {/* ── Nav ──────────────────────────────────────────────────────── */}
            <nav style={{ flex: 1, overflowY: "auto", padding: 8, scrollbarWidth: "none" }}>
                {/* Expand button — collapsed only */}
                {collapsed && (
                    <NavTooltip label="Expand sidebar">
                        <button
                            onClick={() => setCollapsed(false)}
                            style={{
                                width: "100%", height: 36, marginBottom: 6,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                borderRadius: 10, border: "none",
                                backgroundColor: "transparent", color: TEXT_MUTED,
                                cursor: "pointer",
                                transition: "background-color 0.15s, color 0.15s",
                            }}
                            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = NAVY_HOVER; (e.currentTarget as HTMLElement).style.color = GOLD; }}
                            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; (e.currentTarget as HTMLElement).style.color = TEXT_MUTED; }}
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
                                    padding: collapsed ? 0 : "0 12px",
                                    height: 40,
                                    borderRadius: 12,
                                    border: "none",
                                    backgroundColor: isActive ? GOLD : "transparent",
                                    color: isActive ? "#ffffff" : TEXT_MUTED,
                                    cursor: "pointer",
                                    position: "relative",
                                    transition: "background-color 0.15s",
                                    fontFamily: "inherit",
                                    fontSize: 13,
                                    fontWeight: isActive ? 600 : 500,
                                }}
                                onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = NAVY_HOVER; }}
                                onMouseLeave={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                            >
                                <span style={{ color: isActive ? "#ffffff" : TEXT_MUTED, flexShrink: 0, lineHeight: 0 }}>
                                    {item.icon}
                                </span>
                                {!collapsed && (
                                    <>
                                        <span style={{ flex: 1, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                            {item.label}
                                        </span>
                                        {item.badge != null && (
                                            <span style={{
                                                marginLeft: "auto", flexShrink: 0,
                                                backgroundColor: isActive ? "rgba(255,255,255,0.3)" : GOLD,
                                                color: "#fff", fontSize: 10, fontWeight: 700,
                                                borderRadius: 999, minWidth: 18, height: 18,
                                                display: "flex", alignItems: "center", justifyContent: "center",
                                                padding: "0 4px",
                                            }}>
                                                {item.badge}
                                            </span>
                                        )}
                                    </>
                                )}
                                {collapsed && item.badge != null && (
                                    <span style={{
                                        position: "absolute", top: 4, right: 4,
                                        width: 14, height: 14,
                                        backgroundColor: GOLD, color: "#fff",
                                        fontSize: 8, fontWeight: 700,
                                        borderRadius: 999,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                    }}>
                                        {item.badge}
                                    </span>
                                )}
                            </button>
                        );

                        return collapsed
                            ? <NavTooltip key={item.id} label={item.label}>{btn}</NavTooltip>
                            : <React.Fragment key={item.id}>{btn}</React.Fragment>;
                    })}
                </div>
            </nav>

            {/* ── Footer: user account ─────────────────────────────────────── */}
            <div style={footerStyle}>
                {/* Popup — position:fixed, escapes overflow:hidden */}
                <AccountPopup
                    open={menuOpen}
                    anchorRef={footerBtnRef}
                    collapsed={collapsed}
                    session={session}
                    theme={theme}
                    onThemeToggle={handleTheme}
                    onProfile={handleProfile}
                    onSettings={handleSettings}
                    onLogout={handleLogout}
                    loggingOut={loggingOut}
                    popupRef={popupRef}
                />

                {/* ── Collapsed: centered avatar ────────────────────────────── */}
                {collapsed ? (
                    <button
                        ref={footerBtnRef}
                        onClick={() => setMenuOpen((o) => !o)}
                        title="Account menu"
                        style={{
                            width: "100%",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            padding: "4px 0",
                            border: "none", borderRadius: 12,
                            backgroundColor: menuOpen ? NAVY_HOVER : "transparent",
                            cursor: "pointer", position: "relative",
                            transition: "background-color 0.15s",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = NAVY_HOVER; }}
                        onMouseLeave={(e) => { if (!menuOpen) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                        <div style={{ position: "relative", display: "inline-flex" }}>
                            <Avatar name={session.user.name || "User"} size="sm" />
                            <span style={{
                                position: "absolute", bottom: 0, right: 0,
                                width: 9, height: 9,
                                backgroundColor: "#22c55e",
                                borderRadius: "50%",
                                border: `2px solid ${NAVY}`,
                            }} />
                        </div>
                        {loggingOut && (
                            <div style={{
                                position: "absolute", inset: 0,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                backgroundColor: "rgba(14,23,41,0.85)",
                                borderRadius: 12,
                            }}>
                                <div style={{
                                    width: 14, height: 14,
                                    border: `2px solid ${GOLD}`,
                                    borderTopColor: "transparent",
                                    borderRadius: "50%",
                                    animation: "spin 0.7s linear infinite",
                                }} />
                            </div>
                        )}
                    </button>
                ) : (
                    /* ── Expanded: avatar + name + email ──────────────────────── */
                    <button
                        ref={footerBtnRef}
                        onClick={() => setMenuOpen((o) => !o)}
                        style={{
                            width: "100%",
                            display: "flex", alignItems: "center", gap: 10,
                            padding: "6px 8px",
                            border: "none", borderRadius: 12,
                            backgroundColor: menuOpen ? NAVY_HOVER : "transparent",
                            cursor: "pointer",
                            transition: "background-color 0.15s",
                            fontFamily: "inherit",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = NAVY_HOVER; }}
                        onMouseLeave={(e) => { if (!menuOpen) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                        {/* Avatar + online dot */}
                        <div style={{ position: "relative", flexShrink: 0 }}>
                            <Avatar name={session.user.name || "User"} size="sm" />
                            <span style={{
                                position: "absolute", bottom: 0, right: 0,
                                width: 9, height: 9,
                                backgroundColor: "#22c55e",
                                borderRadius: "50%",
                                border: `2px solid ${NAVY}`,
                            }} />
                        </div>

                        {/* Name + role */}
                        <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                            <div style={{
                                fontSize: 12, fontWeight: 600, color: TEXT_LIGHT,
                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                lineHeight: 1.3,
                            }}>
                                {session.user.name || "—"}
                            </div>
                            <div style={{
                                fontSize: 10, color: TEXT_MUTED,
                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                lineHeight: 1.3, marginTop: 1, textTransform: "capitalize",
                            }}>
                                {session.user.role || session.user.email || "—"}
                            </div>
                        </div>

                        {/* Chevron */}
                        <svg
                            width="14" height="14" fill="none" stroke={TEXT_MUTED} viewBox="0 0 24 24"
                            style={{ flexShrink: 0, transition: "transform 0.2s", transform: menuOpen ? "rotate(180deg)" : "none" }}
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                        </svg>
                    </button>
                )}
            </div>
        </aside>
    );
}