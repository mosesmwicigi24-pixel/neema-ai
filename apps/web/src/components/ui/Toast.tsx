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
    return (
        <div
            className={`fixed z-[999] flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium
        ${
            isError
                ? "bg-red-50 dark:bg-red-950/80 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300"
                : "bg-emerald-50 dark:bg-emerald-950/80 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
        }
        ${isMobile ? "bottom-24 left-4 right-4" : "top-5 right-5 min-w-72 max-w-sm"}`}
            style={{ animation: "slideInDown 0.25s ease" }}
        >
            <span
                className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold text-white ${isError ? "bg-red-500" : "bg-emerald-500"}`}
            >
                {isError ? "✕" : "✓"}
            </span>
            {toast.msg}
        </div>
    );
}