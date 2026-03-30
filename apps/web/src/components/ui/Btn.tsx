import React from "react";
import { cn } from "@/lib/utils";

export type BtnVariant =
    | "primary"
    | "secondary"
    | "danger"
    | "success"
    | "blue"
    | "ghost"
    | "outline";

const VARIANTS: Record<BtnVariant, string> = {
    primary:
        "bg-amber-500 hover:bg-amber-600 text-white border border-amber-500 shadow-sm",
    secondary:
        "bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 border border-gray-200 dark:border-gray-700",
    danger: "bg-red-50 hover:bg-red-100 dark:bg-red-950/30 dark:hover:bg-red-950/50 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800",
    success:
        "bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800",
    blue: "bg-blue-50 hover:bg-blue-100 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800",
    ghost: "bg-transparent hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 border border-transparent",
    outline:
        "bg-transparent hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200 border border-gray-300 dark:border-gray-600",
};

interface BtnProps {
    onClick?: () => void;
    children: React.ReactNode;
    variant?: BtnVariant;
    size?: "xs" | "sm" | "md";
    small?: boolean;
    disabled?: boolean;
    full?: boolean;
    className?: string;
    type?: "button" | "submit";
}

export function Btn({
    onClick,
    children,
    variant = "primary",
    size = "md",
    small,
    disabled = false,
    full = false,
    className = "",
    type = "button",
}: BtnProps): React.ReactElement {
    const resolvedSize = small ? "sm" : size;
    const sizeCls = {
        xs: "px-2 py-1 text-xs rounded-md h-7",
        sm: "px-3 py-1.5 text-xs rounded-lg h-8",
        md: "px-4 py-2 text-sm rounded-lg h-9",
    }[resolvedSize];

    return (
        <button
            type={type}
            onClick={onClick}
            disabled={disabled}
            className={cn(
                "inline-flex items-center justify-center gap-1.5 font-medium transition-all duration-150 whitespace-nowrap touch-manipulation",
                VARIANTS[variant],
                sizeCls,
                disabled && "opacity-40 cursor-not-allowed pointer-events-none",
                full && "w-full",
                className,
            )}
        >
            {children}
        </button>
    );
}