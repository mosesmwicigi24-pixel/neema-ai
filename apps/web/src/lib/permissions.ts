export const PERMS = {
    HANDLE_CONVERSATIONS: "handle_conversations",
    MANAGE_ORDERS: "manage_orders",
    MANAGE_AGENTS: "manage_agents",
    MANAGE_CATALOG: "manage_catalog",
    VIEW_ANALYTICS: "view_analytics",
    MANAGE_USERS: "manage_users",
    MANAGE_ROLES: "manage_roles",
    VIEW_AUDIT: "view_audit",
} as const;

export type Permission = (typeof PERMS)[keyof typeof PERMS];

export const ROLE_PERMS: Record<string, Permission[]> = {
    admin: [
        PERMS.HANDLE_CONVERSATIONS,
        PERMS.MANAGE_ORDERS,
        PERMS.MANAGE_AGENTS,
        PERMS.MANAGE_CATALOG,
        PERMS.VIEW_ANALYTICS,
        PERMS.MANAGE_USERS,
        PERMS.MANAGE_ROLES,
        PERMS.VIEW_AUDIT,
    ],
    agent: [PERMS.HANDLE_CONVERSATIONS, PERMS.MANAGE_ORDERS],
    readonly: [PERMS.VIEW_ANALYTICS],
};
