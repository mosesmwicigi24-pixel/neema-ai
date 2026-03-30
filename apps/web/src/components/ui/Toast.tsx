import React from "react";
import type { ToastState } from "@/types";

interface ToastProps {
    toast: ToastState | null;
    isMobile: boolean;
}

export function Toast({
    toast,
    isMobile,
}: ToastProps): React.ReactElement | null {
    if (!toast) return null;
    const isError = toast.type === "error";
    const isWarning = toast.type === "warning";
    const colorCls = isError
        ? "bg-red-50 dark:bg-red-950/80 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300"
        : isWarning
          ? "bg-amber-50 dark:bg-amber-950/80 border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300"
          : "bg-emerald-50 dark:bg-emerald-950/80 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300";
    const dotCls = isError
        ? "bg-red-500"
        : isWarning
          ? "bg-amber-500"
          : "bg-emerald-500";
    const icon = isError ? "✕" : isWarning ? "!" : "✓";
    return (
        <div
            className={`fixed z-[999] flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium ${colorCls} ${isMobile ? "bottom-24 left-4 right-4" : "top-5 right-5 min-w-72 max-w-sm"}`}
            style={{ animation: "slideInDown 0.25s ease" }}
        >
            <span
                className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold text-white ${dotCls}`}
            >
                {icon}
            </span>
            {toast.msg}
        </div>
    );
}