import React from "react";
import { cn } from "@/lib/utils";

// ── Card ──────────────────────────────────────────────────────────────────────
interface CardProps {
    children: React.ReactNode;
    className?: string;
    padding?: boolean;
}

export function Card({
    children,
    className = "",
    padding = true,
}: CardProps): React.ReactElement {
    return (
        <div
            className={cn(
                "bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm",
                padding && "p-5",
                className,
            )}
        >
            {children}
        </div>
    );
}

// ── SectionHeader ─────────────────────────────────────────────────────────────
interface SectionHeaderProps {
    title: string;
    subtitle?: string;
    action?: React.ReactNode;
}

export function SectionHeader({
    title,
    subtitle,
    action,
}: SectionHeaderProps): React.ReactElement {
    return (
        <div className="flex items-start justify-between gap-4 mb-6 flex-wrap">
            <div className="min-w-0">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white tracking-tight">
                    {title}
                </h2>
                {subtitle && (
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                        {subtitle}
                    </p>
                )}
            </div>
            {action && <div className="flex-shrink-0">{action}</div>}
        </div>
    );
}

// ── StatCard ──────────────────────────────────────────────────────────────────
interface StatCardProps {
    label: string;
    value: string | number;
    sub?: string;
    icon: React.ReactNode;
    trend?: { value: number; positive: boolean };
    accentColor?: string;
}

export function StatCard({
    label,
    value,
    sub,
    icon,
    trend,
    accentColor = "amber",
}: StatCardProps): React.ReactElement {
    const accentBg = `bg-${accentColor}-50 dark:bg-${accentColor}-950/30`;
    const accentText = `text-${accentColor}-600 dark:text-${accentColor}-400`;

    return (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-start justify-between mb-3">
                <div
                    className={`w-10 h-10 rounded-xl ${accentBg} flex items-center justify-center`}
                >
                    <span className={`text-lg ${accentText}`}>{icon}</span>
                </div>
                {trend && (
                    <span
                        className={`text-xs font-medium ${trend.positive ? "text-emerald-600" : "text-red-500"}`}
                    >
                        {trend.positive ? "↑" : "↓"} {Math.abs(trend.value)}%
                    </span>
                )}
            </div>
            <div className="text-2xl font-bold text-gray-900 dark:text-white leading-none mb-1">
                {value}
            </div>
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                {label}
            </div>
            {sub && <div className={`text-xs mt-1 ${accentText}`}>{sub}</div>}
        </div>
    );
}

// ── Divider ───────────────────────────────────────────────────────────────────
export function Divider({ label }: { label?: string }): React.ReactElement {
    return (
        <div className="flex items-center gap-3 my-5">
            <div className="flex-1 h-px bg-gray-100 dark:bg-gray-800" />
            {label && (
                <span className="text-xs text-gray-400 dark:text-gray-500 font-medium uppercase tracking-wider">
                    {label}
                </span>
            )}
            <div className="flex-1 h-px bg-gray-100 dark:bg-gray-800" />
        </div>
    );
}

// ── Toggle ────────────────────────────────────────────────────────────────────
interface ToggleProps {
    checked: boolean;
    onChange: () => void;
}

export function Toggle({ checked, onChange }: ToggleProps): React.ReactElement {
    return (
        <button
            onClick={onChange}
            className={`relative w-11 h-6 rounded-full transition-colors duration-200 flex-shrink-0 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 touch-manipulation
        ${checked ? "bg-emerald-500" : "bg-gray-200 dark:bg-gray-700"}`}
        >
            <div
                className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${checked ? "translate-x-5" : "translate-x-0.5"}`}
            />
        </button>
    );
}
