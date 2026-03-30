import React from "react";
import { initials } from "@/lib/utils";

const COLORS = [
    "bg-amber-500",
    "bg-blue-500",
    "bg-emerald-500",
    "bg-rose-500",
    "bg-violet-500",
    "bg-orange-500",
    "bg-cyan-500",
    "bg-pink-500",
];

const SIZE_CLS: Record<string, string> = {
    xs: "w-6 h-6 text-xs",
    sm: "w-8 h-8 text-xs",
    md: "w-10 h-10 text-sm",
    lg: "w-12 h-12 text-base",
    xl: "w-16 h-16 text-xl",
};

interface AvatarProps {
    name?: string;
    size?: "xs" | "sm" | "md" | "lg" | "xl" | number;
    className?: string;
}

export function Avatar({
    name,
    size = "md",
    className = "",
}: AvatarProps): React.ReactElement {
    const color = COLORS[(name?.charCodeAt(0) ?? 0) % COLORS.length];

    // Numeric size: render with inline style
    if (typeof size === "number") {
        return (
            <div
                style={{ width: size, height: size, fontSize: size * 0.36 }}
                className={`${color} rounded-full flex items-center justify-center font-semibold text-white flex-shrink-0 ${className}`}
            >
                {initials(name)}
            </div>
        );
    }

    return (
        <div
            className={`${SIZE_CLS[size] ?? SIZE_CLS.md} ${color} rounded-full flex items-center justify-center font-semibold text-white flex-shrink-0 ${className}`}
        >
            {initials(name)}
        </div>
    );
}