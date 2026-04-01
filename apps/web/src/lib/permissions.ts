// permissions.ts
// Permission keys must match exactly what is stored in custom_roles.permissions
// in the database (and defined in AgentsView.tsx ALL_PERMISSIONS).

export const PERMS = {
    // Conversations
    VIEW_CONVERSATIONS:     "view_conversations",
    REPLY_CONVERSATIONS:    "reply_conversations",
    INTERCEPT_RELEASE:      "intercept_release",
    CLOSE_CONVERSATIONS:    "close_conversations",
    TRANSFER_CONVERSATIONS: "transfer_conversations",
    ADD_NOTES:              "add_notes",
    // Orders
    VIEW_ORDERS:            "view_orders",
    MANAGE_ORDERS:          "manage_orders",
    // Catalog
    VIEW_CATALOG:           "view_catalog",
    MANAGE_CATALOG:         "manage_catalog",
    // CRM / Leads
    VIEW_LEADS:             "view_leads",
    MANAGE_LEADS:           "manage_leads",
    VIEW_CRM:               "view_crm",
    EDIT_CRM:               "edit_crm",
    // Reports
    VIEW_ANALYTICS:         "view_analytics",
    VIEW_REPORTS:           "view_reports",
    EXPORT_REPORTS:         "export_reports",
    // Admin
    MANAGE_AGENTS:          "manage_agents",
    MANAGE_ROLES:           "manage_roles",
    MANAGE_SETTINGS:        "manage_settings",
} as const;

export type Permission = (typeof PERMS)[keyof typeof PERMS];

// ── Fallback permissions for agents without a custom role assigned yet ────────
// These mirror the seeds in main.py so behaviour is consistent.

const LEGACY_FALLBACK: Record<string, Permission[]> = {
    admin: Object.values(PERMS) as Permission[],
    agent: [
        PERMS.VIEW_CONVERSATIONS,
        PERMS.REPLY_CONVERSATIONS,
        PERMS.INTERCEPT_RELEASE,
        PERMS.CLOSE_CONVERSATIONS,
        PERMS.TRANSFER_CONVERSATIONS,
        PERMS.ADD_NOTES,
        PERMS.VIEW_ORDERS,
        PERMS.MANAGE_ORDERS,
        PERMS.VIEW_CATALOG,
        PERMS.VIEW_CRM,
        PERMS.VIEW_LEADS,
    ],
    readonly: [
        PERMS.VIEW_CONVERSATIONS,
        PERMS.VIEW_ORDERS,
        PERMS.VIEW_CATALOG,
        PERMS.VIEW_CRM,
        PERMS.VIEW_LEADS,
        PERMS.VIEW_ANALYTICS,
    ],
};

// ── Core helpers ──────────────────────────────────────────────────────────────

/**
 * Returns the effective permission list for an agent.
 *
 * Priority order:
 *  1. agent.permissions  — already resolved by mapAgent():
 *       custom_permissions (per-agent overrides) ?? role_permissions (from DB role)
 *  2. LEGACY_FALLBACK    — for agents that predate the custom-role system
 */
export function getAgentPermissions(agent: {
    role: string;
    is_superuser?: boolean;
    permissions?: string[] | null;
}): string[] {
    // Superusers always get everything regardless of role assignment
    if (agent.is_superuser) return Object.values(PERMS);

    if (agent.permissions && agent.permissions.length > 0) {
        return agent.permissions;
    }

    return LEGACY_FALLBACK[agent.role] ?? [];
}

/**
 * Returns true if the agent has the given permission.
 */
export function hasPermission(
    agent: { role: string; is_superuser?: boolean; permissions?: string[] | null },
    perm: Permission,
): boolean {
    return getAgentPermissions(agent).includes(perm);
}

/**
 * Returns true if the agent has ALL of the given permissions.
 */
export function hasAllPermissions(
    agent: { role: string; is_superuser?: boolean; permissions?: string[] | null },
    perms: Permission[],
): boolean {
    const effective = getAgentPermissions(agent);
    return perms.every(p => effective.includes(p));
}

/**
 * Returns true if the agent has ANY of the given permissions.
 */
export function hasAnyPermission(
    agent: { role: string; is_superuser?: boolean; permissions?: string[] | null },
    perms: Permission[],
): boolean {
    const effective = getAgentPermissions(agent);
    return perms.some(p => effective.includes(p));
}

// ── Legacy export (keeps any existing callers working) ────────────────────────
// Derived from LEGACY_FALLBACK so it stays in sync automatically.
export const ROLE_PERMS: Record<string, Permission[]> = LEGACY_FALLBACK;