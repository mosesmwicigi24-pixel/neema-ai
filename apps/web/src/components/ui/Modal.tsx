import React, { useEffect } from "react";
import { cn } from "@/lib/utils";

interface ModalProps {
    show: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    size?: "sm" | "md" | "lg";
}

export function Modal({
    show,
    onClose,
    title,
    children,
    size = "md",
}: ModalProps): React.ReactElement | null {
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
        };
        if (show) document.addEventListener("keydown", handler);
        return () => document.removeEventListener("keydown", handler);
    }, [show, onClose]);

    if (!show) return null;

    const widthCls = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];

    return (
        <div
            className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
            onClick={onClose}
        >
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
            {/* Sheet */}
            <div
                className={cn(
                    "relative w-full bg-white dark:bg-gray-900 shadow-2xl",
                    "rounded-t-2xl sm:rounded-2xl",
                    "max-h-[90vh] overflow-y-auto",
                    "animate-in slide-in-from-bottom-4 sm:fade-in sm:zoom-in-95 duration-200",
                    widthCls,
                )}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Drag handle (mobile only) */}
                <div className="flex justify-center pt-3 sm:hidden">
                    <div className="w-10 h-1 bg-gray-200 dark:bg-gray-700 rounded-full" />
                </div>
                {/* Header */}
                <div className="flex items-center justify-between px-5 pt-4 pb-4 border-b border-gray-100 dark:border-gray-800">
                    <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                        {title}
                    </h3>
                    <button
                        onClick={onClose}
                        className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                    >
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
                                d="M6 18L18 6M6 6l12 12"
                            />
                        </svg>
                    </button>
                </div>
                <div className="px-5 pb-6 pt-4">{children}</div>
            </div>
        </div>
    );}
