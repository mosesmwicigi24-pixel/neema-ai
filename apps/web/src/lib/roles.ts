import type { RoleDefinitions, PermissionDef } from "../types";

// Static role/permission reference data (formerly bundled with mock fixtures,
// which are gone — the app talks to the real API).

export const ROLE_DEFINITIONS: RoleDefinitions = {
    admin: {
        label: "Admin",
        color: "#f59e0b",
        description: "Full system access",
        permissions: [
            "view_conversations",
            "send_messages",
            "intercept",
            "manage_agents",
            "manage_catalog",
            "view_orders",
            "manage_orders",
            "view_analytics",
            "manage_settings",
        ],
    },
    agent: {
        label: "Agent",
        color: "#3b82f6",
        description: "Handle conversations & orders",
        permissions: [
            "view_conversations",
            "send_messages",
            "intercept",
            "view_orders",
        ],
    },
    readonly: {
        label: "Viewer",
        color: "#10b981",
        description: "Read-only access",
        permissions: ["view_conversations", "view_orders"],
    },
    supervisor: {
        label: "Supervisor",
        color: "#f97316",
        description: "Oversee agents & convs",
        permissions: [
            "view_conversations",
            "send_messages",
            "intercept",
            "manage_agents",
            "view_orders",
            "view_analytics",
        ],
    },
};

export const ALL_PERMISSIONS: PermissionDef[] = [
    {
        key: "view_conversations",
        label: "View Conversations",
        group: "Conversations",
    },
    { key: "send_messages", label: "Send Messages", group: "Conversations" },
    {
        key: "intercept",
        label: "Intercept / Release AI",
        group: "Conversations",
    },
    { key: "manage_agents", label: "Manage Agents", group: "Team" },
    { key: "view_orders", label: "View Orders", group: "Orders" },
    { key: "manage_orders", label: "Manage Orders", group: "Orders" },
    { key: "manage_catalog", label: "Manage Catalog", group: "Catalog" },
    { key: "view_analytics", label: "View Analytics", group: "Analytics" },
    { key: "manage_settings", label: "System Settings", group: "Settings" },
];
