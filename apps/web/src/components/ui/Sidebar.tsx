import React from "react";
import { Avatar } from "@/components/ui/Avatar";
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
}

export function Sidebar({
    navItems,
    view,
    setView,
    collapsed,
    setCollapsed,
    session,
    theme,
    setTheme,
}: SidebarProps): React.ReactElement {
    return (
        <aside
            className={cn(
                "flex flex-col h-full bg-gray-950 border-r border-gray-800 flex-shrink-0 transition-all duration-300 overflow-hidden",
                collapsed ? "w-16" : "w-56",
            )}
        >
            {/* Logo */}
            <div
                className={cn(
                    "flex items-center border-b border-gray-800 h-14 flex-shrink-0",
                    collapsed ? "justify-center px-3" : "px-4 gap-3",
                )}
            >
                {!collapsed && (
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <div className="w-7 h-7 rounded-lg bg-amber-500 flex items-center justify-center flex-shrink-0">
                            <svg
                                className="w-4 h-4 text-white"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2.5}
                                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                                />
                            </svg>
                        </div>
                        <span className="text-white font-semibold text-base leading-none tracking-tight">
                            Neema
                        </span>
                    </div>
                )}
                <button
                    onClick={() => setCollapsed((c) => !c)}
                    className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-all flex-shrink-0"
                >
                    <svg
                        className="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        {collapsed ? (
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M13 5l7 7-7 7M5 5l7 7-7 7"
                            />
                        ) : (
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
                            />
                        )}
                    </svg>
                </button>
            </div>

            {/* Nav */}
            <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
                {navItems.map((item) => {
                    const isActive = view === item.id;
                    return (
                        <button
                            key={item.id}
                            onClick={() => setView(item.id as ViewId)}
                            title={collapsed ? item.label : undefined}
                            className={cn(
                                "w-full flex items-center rounded-lg text-sm font-medium transition-all duration-150 touch-manipulation group relative",
                                collapsed
                                    ? "justify-center h-10 px-0"
                                    : "gap-2.5 px-3 h-10",
                                isActive
                                    ? "bg-amber-500 text-white shadow-sm"
                                    : "text-gray-400 hover:text-white hover:bg-gray-800",
                            )}
                        >
                            <span className="flex-shrink-0 text-base leading-none">
                                {item.icon}
                            </span>
                            {!collapsed && (
                                <>
                                    <span className="flex-1 text-left truncate">
                                        {item.label}
                                    </span>
                                    {item.badge != null && (
                                        <span className="ml-auto flex-shrink-0 bg-amber-400 text-gray-900 text-xs font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
                                            {item.badge}
                                        </span>
                                    )}
                                </>
                            )}
                            {collapsed && item.badge != null && (
                                <span className="absolute top-1 right-1 w-4 h-4 bg-amber-400 text-gray-900 text-[9px] font-bold rounded-full flex items-center justify-center">
                                    {item.badge}
                                </span>
                            )}
                        </button>
                    );
                })}
            </nav>

            {/* Footer */}
            <div
                className={cn(
                    "border-t border-gray-800 p-2 flex-shrink-0",
                    collapsed ? "flex justify-center" : "",
                )}
            >
                {collapsed ? (
                    <div className="py-1">
                        <Avatar
                            name={session.user.name}
                            size="sm"
                            className="ring-2 ring-gray-700"
                        />
                    </div>
                ) : (
                    <div className="flex items-center gap-2 p-2 rounded-lg hover:bg-gray-800 transition-colors">
                        <Avatar name={session.user.name} size="sm" />
                        <div className="flex-1 min-w-0">
                            <div className="text-xs font-semibold text-white truncate">
                                {session.user.name}
                            </div>
                            <div className="text-[10px] text-amber-400 uppercase tracking-wider font-medium">
                                {session.user.role}
                            </div>
                        </div>
                        <button
                            onClick={() =>
                                setTheme((t) =>
                                    t === "light" ? "dark" : "light",
                                )
                            }
                            className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-white hover:bg-gray-700 transition-all flex-shrink-0"
                            title="Toggle theme"
                        >
                            {theme === "light" ? (
                                <svg
                                    className="w-4 h-4"
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
                                    className="w-4 h-4"
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
                        </button>
                    </div>
                )}
            </div>
        </aside>
    );
}