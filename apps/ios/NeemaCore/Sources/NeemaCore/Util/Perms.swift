import Foundation

/// Port of lib/permissions.ts — keys must match custom_roles.permissions in the DB.
public enum Perms {
    public static let VIEW_CONVERSATIONS = "view_conversations"
    public static let REPLY_CONVERSATIONS = "reply_conversations"
    public static let INTERCEPT_RELEASE = "intercept_release"
    public static let CLOSE_CONVERSATIONS = "close_conversations"
    public static let TRANSFER_CONVERSATIONS = "transfer_conversations"
    public static let ADD_NOTES = "add_notes"
    public static let VIEW_ORDERS = "view_orders"
    public static let MANAGE_ORDERS = "manage_orders"
    public static let VIEW_CATALOG = "view_catalog"
    public static let MANAGE_CATALOG = "manage_catalog"
    public static let VIEW_LEADS = "view_leads"
    public static let MANAGE_LEADS = "manage_leads"
    public static let VIEW_CRM = "view_crm"
    public static let EDIT_CRM = "edit_crm"
    public static let VIEW_ANALYTICS = "view_analytics"
    public static let VIEW_REPORTS = "view_reports"
    public static let EXPORT_REPORTS = "export_reports"
    public static let MANAGE_AGENTS = "manage_agents"
    public static let MANAGE_ROLES = "manage_roles"
    public static let MANAGE_SETTINGS = "manage_settings"
    public static let CLEAR_CHAT_HISTORY = "clear_chat_history"

    public static let ALL: [String] = [
        VIEW_CONVERSATIONS, REPLY_CONVERSATIONS, INTERCEPT_RELEASE, CLOSE_CONVERSATIONS,
        TRANSFER_CONVERSATIONS, ADD_NOTES, VIEW_ORDERS, MANAGE_ORDERS, VIEW_CATALOG,
        MANAGE_CATALOG, VIEW_LEADS, MANAGE_LEADS, VIEW_CRM, EDIT_CRM, VIEW_ANALYTICS,
        VIEW_REPORTS, EXPORT_REPORTS, MANAGE_AGENTS, MANAGE_ROLES, MANAGE_SETTINGS,
        CLEAR_CHAT_HISTORY,
    ]

    /// Fallback for agents that predate the custom-role system (mirrors main.py seeds).
    private static let LEGACY_FALLBACK: [String: [String]] = [
        "admin": ALL,
        "agent": [
            VIEW_CONVERSATIONS, REPLY_CONVERSATIONS, INTERCEPT_RELEASE, CLOSE_CONVERSATIONS,
            TRANSFER_CONVERSATIONS, ADD_NOTES, VIEW_ORDERS, MANAGE_ORDERS, VIEW_CATALOG,
            VIEW_CRM, VIEW_LEADS,
        ],
        "readonly": [VIEW_CONVERSATIONS, VIEW_ORDERS, VIEW_CATALOG, VIEW_CRM, VIEW_LEADS, VIEW_ANALYTICS],
    ]

    /// getAgentPermissions(): a superuser has everything; otherwise the
    /// resolved list (`Agent.permissions` = custom_permissions ?? role_permissions)
    /// when it is non-empty; otherwise the legacy role's defaults. An empty
    /// per-agent override `[]` therefore falls back to the legacy role, exactly
    /// as on the web; an unknown role with nothing resolved has no permissions.
    public static func effective(role: String, isSuperuser: Bool, permissions: [String]?) -> [String] {
        if isSuperuser { return ALL }
        if let p = permissions, !p.isEmpty { return p }
        return LEGACY_FALLBACK[role] ?? []
    }

    public static func of(_ agent: Agent) -> [String] { effective(role: agent.role, isSuperuser: agent.isSuperuser, permissions: agent.permissions) }

    /// hasPermission()
    public static func has(_ agent: Agent, _ perm: String) -> Bool { of(agent).contains(perm) }
    /// hasAllPermissions()
    public static func hasAll(_ agent: Agent, _ perms: [String]) -> Bool { let e = of(agent); return perms.allSatisfy { e.contains($0) } }
    /// hasAnyPermission()
    public static func hasAny(_ agent: Agent, _ perms: [String]) -> Bool { let e = of(agent); return perms.contains { e.contains($0) } }
}
