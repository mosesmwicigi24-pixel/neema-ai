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
}

// ── Keyboard trap for dropdown ────────────────────────────────────────────────
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

// ── Menu item ─────────────────────────────────────────────────────────────────
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
                    ? "text-red-400 hover:bg-red-500/10 hover:text-red-300"
                    : "text-gray-300 hover:bg-gray-700/60 hover:text-white",
            )}
        >
            <span
                className={cn(
                    "flex-shrink-0 opacity-60 group-hover:opacity-100 transition-opacity",
                    danger ? "text-red-400" : "",
                )}
            >
                {icon}
            </span>
            <span className="flex-1 text-left">{label}</span>
            {shortcut && (
                <kbd className="text-[9px] text-gray-600 bg-gray-800 border border-gray-700 px-1 py-0.5 rounded font-mono">
                    {shortcut}
                </kbd>
            )}
        </button>
    );
}

// ── Main component ────────────────────────────────────────────────────────────
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
    const menuRef = useRef<HTMLDivElement>(null);

    useClickOutside(menuRef as React.RefObject<HTMLElement>, () =>
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
                "flex flex-col h-full border-r border-[#152451]/60 flex-shrink-0 transition-all duration-300 overflow-hidden relative",
                collapsed ? "w-16" : "w-56",
            )}
            style={{ backgroundColor: "#070d1c" }}
        >
            {/* Logo */}
            <div
                className={cn(
                    "flex items-center border-b border-[#152451]/60 h-14 flex-shrink-0",
                    collapsed ? "justify-center px-3" : "px-4 gap-3",
                )}
            >
                {!collapsed && (
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 shadow-lg"
                            style={{ backgroundColor: "#589b31", boxShadow: "0 2px 12px rgba(88,155,49,0.4)" }}>
                            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                            </svg>
                        </div>
                        <div className="min-w-0">
                            <div className="text-white font-semibold text-sm leading-none tracking-tight">Neema</div>
                            <div className="text-[9px] uppercase tracking-widest font-medium mt-0.5" style={{ color: "#699a32" }}>
                                Admin
                            </div>
                        </div>
                    </div>
                )}
                <div className="flex items-center gap-1">
                    {!collapsed && <Notifications />}
                    <button
                        onClick={() => setCollapsed((c) => !c)}
                        className="w-7 h-7 flex items-center justify-center rounded-lg transition-all flex-shrink-0"
                        style={{ color: "#699a32" }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#152451"; (e.currentTarget as HTMLElement).style.color = "#f3f9ec"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = ""; (e.currentTarget as HTMLElement).style.color = "#699a32"; }}
                    >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            {collapsed ? (
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                            ) : (
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                            )}
                        </svg>
                    </button>
                </div>
            </div>

            {/* Nav */}
            <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto scrollbar-none">
                {navItems.map((item) => {
                    const isActive = view === item.id;
                    return (
                        <button
                            key={item.id}
                            onClick={() => setView(item.id as ViewId)}
                            title={collapsed ? item.label : undefined}
                            className={cn(
                                "w-full flex items-center rounded-lg text-sm font-medium transition-all duration-150 touch-manipulation group relative",
                                collapsed ? "justify-center h-10 px-0" : "gap-2.5 px-3 h-10",
                            )}
                            style={{
                                backgroundColor: isActive ? "#589b31" : "",
                                color: isActive ? "#ffffff" : "#699a32",
                            }}
                            onMouseEnter={(e) => {
                                if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "#2c4e18";
                                if (!isActive) (e.currentTarget as HTMLElement).style.color = "#f3f9ec";
                            }}
                            onMouseLeave={(e) => {
                                if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "";
                                if (!isActive) (e.currentTarget as HTMLElement).style.color = "#699a32";
                            }}
                        >
                            <span className="flex-shrink-0 text-base leading-none">{item.icon}</span>
                            {!collapsed && (
                                <>
                                    <span className="flex-1 text-left truncate">{item.label}</span>
                                    {item.badge != null && (
                                        <span className="ml-auto flex-shrink-0 bg-[#589b31] text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
                                            {item.badge}
                                        </span>
                                    )}
                                </>
                            )}
                            {collapsed && item.badge != null && (
                                <span className="absolute top-1 right-1 w-3.5 h-3.5 bg-[#589b31] text-white text-[8px] font-bold rounded-full flex items-center justify-center">
                                    {item.badge}
                                </span>
                            )}
                        </button>
                    );
                })}
            </nav>

            {/* Footer with user menu */}
            <div
                className={cn(
                    "border-t border-[#152451]/60 p-2 flex-shrink-0 relative",
                    collapsed ? "flex justify-center" : "",
                )}
                ref={menuRef}
            >
                {/* Dropdown menu — renders above the footer */}
                {menuOpen && (
                    <div
                        className={cn(
                            "absolute bottom-full mb-2 z-50 border rounded-xl shadow-2xl shadow-black/60 overflow-hidden",
                            collapsed ? "left-full ml-2 w-52" : "left-2 right-2",
                        )}
                        style={{ backgroundColor: "#0a1229", borderColor: "#152451", animation: "menuSlideUp 0.15s ease" }}
                    >
                        <style>{`
                            @keyframes menuSlideUp {
                                from { opacity: 0; transform: translateY(6px); }
                                to   { opacity: 1; transform: translateY(0); }
                            }
                        `}</style>

                        {/* User info header */}
                        <div className="px-3 py-3 border-b" style={{ borderColor: "#152451" }}>
                            <div className="flex items-center gap-2.5">
                                <Avatar name={session.user.name} size="sm" />
                                <div className="min-w-0 flex-1">
                                    <div className="text-xs font-semibold text-white truncate">
                                        {session.user.name}
                                    </div>
                                    <div className="text-[10px] truncate" style={{ color: "#699a32" }}>
                                        {session.user.email}
                                    </div>
                                </div>
                                <span className="flex-shrink-0 text-[9px] border px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide"
                                    style={{ backgroundColor: "rgba(88,155,49,0.2)", color: "#9ccd65", borderColor: "rgba(88,155,49,0.3)" }}>
                                    {session.user.role}
                                </span>
                            </div>
                        </div>

                        {/* Menu items */}
                        <div className="p-1.5 space-y-0.5">
                            <MenuItem
                                icon={
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
                                            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                                        />
                                    </svg>
                                }
                                label="View Profile"
                                onClick={handleProfileClick}
                            />
                            <MenuItem
                                icon={
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
                                            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                                        />
                                    </svg>
                                }
                                label="Settings"
                                onClick={handleSettingsClick}
                            />
                        </div>

                        {/* Preferences */}
                        <div className="px-1.5 pb-1.5">
                            <div className="text-[9px] text-gray-600 uppercase tracking-widest font-semibold px-2 pb-1 pt-0.5">
                                Preferences
                            </div>
                            {/* Theme toggle */}
                            <div className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-800/60 transition-colors">
                                <div className="flex items-center gap-2.5">
                                    <span className="text-gray-500">
                                        {theme === "light" ? (
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
                                                    d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
                                                />
                                            </svg>
                                        ) : (
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
                                                    d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
                                                />
                                            </svg>
                                        )}
                                    </span>
                                    <span className="text-xs text-gray-300 font-medium">
                                        {theme === "light"
                                            ? "Dark mode"
                                            : "Light mode"}
                                    </span>
                                </div>
                                <button
                                    onClick={handleThemeToggle}
                                    className={cn(
                                        "relative w-8 h-4.5 rounded-full transition-colors duration-200 flex-shrink-0",
                                        theme === "dark"
                                            ? "bg-green-600"
                                            : "bg-gray-700",
                                    )}
                                    style={{ height: 18, width: 32 }}
                                >
                                    <span
                                        className={cn(
                                            "absolute top-0.5 w-3.5 h-3.5 bg-white rounded-full shadow-sm transition-transform duration-200",
                                            theme === "dark"
                                                ? "translate-x-4"
                                                : "translate-x-0.5",
                                        )}
                                    />
                                </button>
                            </div>
                        </div>

                        {/* Divider + logout */}
                        <div className="px-1.5 pb-1.5 border-t border-gray-800/60 pt-1.5">
                            <MenuItem
                                icon={
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
                                            d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                                        />
                                    </svg>
                                }
                                label={loggingOut ? "Signing out…" : "Sign out"}
                                onClick={handleLogout}
                                danger
                            />
                        </div>
                    </div>
                )}

                {/* Collapsed state — just avatar button */}
                {collapsed ? (
                    <button
                        onClick={() => setMenuOpen((o) => !o)}
                        className="py-1 rounded-lg hover:bg-gray-800 transition-colors relative"
                        title="Account menu"
                    >
                        <Avatar
                            name={session.user.name}
                            size="sm"
                            className="ring-2 ring-gray-700 hover:ring-green-700 transition-all"
                        />
                        {loggingOut && (
                            <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 rounded-lg">
                                <div className="w-3 h-3 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
                            </div>
                        )}
                    </button>
                ) : (
                    /* Expanded state — full user row */
                    <button
                        onClick={() => setMenuOpen((o) => !o)}
                        className={cn(
                            "w-full flex items-center gap-2 p-2 rounded-lg transition-all duration-150 group",
                            menuOpen
                                ? "bg-gray-800 text-white"
                                : "hover:bg-gray-800/70 text-gray-300 hover:text-white",
                        )}
                    >
                        <Avatar name={session.user.name} size="sm" />
                        <div className="flex-1 min-w-0 text-left">
                            <div className="text-xs font-semibold text-white truncate leading-tight">
                                {session.user.name}
                            </div>
                            <div className="text-[10px] text-green-500/70 uppercase tracking-wider font-medium leading-tight">
                                {session.user.role}
                            </div>
                        </div>
                        <svg
                            className={cn(
                                "w-3.5 h-3.5 text-gray-500 flex-shrink-0 transition-transform duration-200",
                                menuOpen
                                    ? "rotate-180 text-gray-300"
                                    : "group-hover:text-gray-300",
                            )}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M5 15l7-7 7 7"
                            />
                        </svg>
                    </button>
                )}
            </div>
        </aside>
    );
}