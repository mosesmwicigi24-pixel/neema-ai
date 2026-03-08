import React from "react";
import { cn } from "@/lib/utils";
import type { NavItem, ThemeMode, ViewId } from "@/types";

interface MobileHeaderProps {
    navItems: NavItem[];
    view: ViewId;
    theme: ThemeMode;
    setTheme: React.Dispatch<React.SetStateAction<ThemeMode>>;
}

export function MobileHeader({
    navItems,
    view,
    theme,
    setTheme,
}: MobileHeaderProps): React.ReactElement {
    const current = navItems.find((n) => n.id === view);
    return (
        <header className="fixed top-0 left-0 right-0 z-50 h-14 bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 flex items-center px-4 gap-3">
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
            <span className="font-semibold text-gray-900 dark:text-white text-sm">
                Neema
            </span>
            <span className="text-gray-300 dark:text-gray-600">·</span>
            <span className="text-sm text-gray-500 dark:text-gray-400 font-medium">
                {current?.label}
            </span>
            <div className="ml-auto">
                <button
                    onClick={() =>
                        setTheme((t) => (t === "light" ? "dark" : "light"))
                    }
                    className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-all"
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
        </header>
    );
}

interface MobileBottomNavProps {
    navItems: NavItem[];
    view: ViewId;
    setView: (id: ViewId) => void;
}

export function MobileBottomNav({
    navItems,
    view,
    setView,
}: MobileBottomNavProps): React.ReactElement {
    return (
        <nav className="fixed bottom-0 left-0 right-0 z-50 bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-800 flex pb-safe">
            {navItems.slice(0, 5).map((item) => {
                const isActive = view === item.id;
                return (
                    <button
                        key={item.id}
                        onClick={() => setView(item.id as ViewId)}
                        className={cn(
                            "flex-1 flex flex-col items-center justify-center gap-1 py-2 min-h-[56px] relative touch-manipulation transition-colors",
                            isActive ? "text-amber-500" : "text-gray-400",
                        )}
                    >
                        {isActive && (
                            <div className="absolute top-0 left-1/4 right-1/4 h-0.5 bg-amber-500 rounded-b-full" />
                        )}
                        <span className="text-xl leading-none">
                            {item.icon}
                        </span>
                        <span
                            className={cn(
                                "text-[10px] font-medium",
                                isActive ? "text-amber-500" : "text-gray-400",
                            )}
                        >
                            {item.label}
                        </span>
                        {item.badge != null && (
                            <span className="absolute top-2 left-1/2 ml-2 bg-amber-500 text-white text-[9px] font-bold rounded-full min-w-[14px] h-[14px] flex items-center justify-center px-0.5">
                                {item.badge}
                            </span>
                        )}
                    </button>
                );
            })}
        </nav>
    );
}
