import React from "react";
import type {
    InterceptMode,
    OrderStatus,
    AgentRole,
    Channel,
} from "@/types";
import { ROLE_DEFINITIONS } from "@/lib/mockData";
import { CHANNEL_CONFIG } from "@/lib/channels";

export function InterceptBadge({
    mode,
}: {
    mode: InterceptMode;
}): React.ReactElement {
    const map: Record<InterceptMode, { cls: string; label: string }> = {
        ai: {
            cls: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800",
            label: "AI",
        },
        human: {
            cls: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800",
            label: "Human",
        },
        paused: {
            cls: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400 border border-gray-200 dark:border-gray-700",
            label: "Paused",
        },
    };
    const { cls, label } = map[mode];
    return (
        <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${cls}`}
        >
            {label}
        </span>
    );
}

export function StatusBadge({
    status,
}: {
    status: OrderStatus;
}): React.ReactElement {
    const map: Record<OrderStatus, string> = {
        pending:
            "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800",
        confirmed:
            "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800",
        delivered:
            "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800",
        cancelled:
            "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400 border border-red-200 dark:border-red-800",
    };
    return (
        <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium capitalize ${map[status]}`}
        >
            {status}
        </span>
    );
}

export function RoleBadge({ role }: { role: AgentRole }): React.ReactElement {
    const def = ROLE_DEFINITIONS[role];
    const colorMap: Record<AgentRole, string> = {
        admin: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800",
        agent: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800",
        readonly:
            "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800",
        supervisor:
            "bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-400 border border-orange-200 dark:border-orange-800",
    };
    return (
        <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colorMap[role]}`}
        >
            {def?.label ?? role}
        </span>
    );
}

export function ChannelBadge({
    channel,
}: {
    channel: Channel;
}): React.ReactElement {
    const cfg = CHANNEL_CONFIG[channel];
    return (
        <span
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium text-white"
            style={{ backgroundColor: cfg.color }}
        >
            {cfg.icon}
        </span>
    );
}
