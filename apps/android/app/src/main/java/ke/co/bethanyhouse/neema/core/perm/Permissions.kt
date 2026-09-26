package ke.co.bethanyhouse.neema.core.perm

import ke.co.bethanyhouse.neema.core.model.Agent

/** Port of lib/permissions.ts — keys must match custom_roles.permissions in the DB. */
object Perms {
    const val VIEW_CONVERSATIONS = "view_conversations"
    const val REPLY_CONVERSATIONS = "reply_conversations"
    const val INTERCEPT_RELEASE = "intercept_release"
    const val CLOSE_CONVERSATIONS = "close_conversations"
    const val TRANSFER_CONVERSATIONS = "transfer_conversations"
    const val ADD_NOTES = "add_notes"
    const val VIEW_ORDERS = "view_orders"
    const val MANAGE_ORDERS = "manage_orders"
    const val VIEW_CATALOG = "view_catalog"
    const val MANAGE_CATALOG = "manage_catalog"
    const val VIEW_LEADS = "view_leads"
    const val MANAGE_LEADS = "manage_leads"
    const val VIEW_CRM = "view_crm"
    const val EDIT_CRM = "edit_crm"
    const val VIEW_ANALYTICS = "view_analytics"
    const val VIEW_REPORTS = "view_reports"
    const val EXPORT_REPORTS = "export_reports"
    const val MANAGE_AGENTS = "manage_agents"
    const val MANAGE_ROLES = "manage_roles"
    const val MANAGE_SETTINGS = "manage_settings"
    const val CLEAR_CHAT_HISTORY = "clear_chat_history"

    val ALL = listOf(
        VIEW_CONVERSATIONS, REPLY_CONVERSATIONS, INTERCEPT_RELEASE, CLOSE_CONVERSATIONS,
        TRANSFER_CONVERSATIONS, ADD_NOTES, VIEW_ORDERS, MANAGE_ORDERS, VIEW_CATALOG,
        MANAGE_CATALOG, VIEW_LEADS, MANAGE_LEADS, VIEW_CRM, EDIT_CRM, VIEW_ANALYTICS,
        VIEW_REPORTS, EXPORT_REPORTS, MANAGE_AGENTS, MANAGE_ROLES, MANAGE_SETTINGS,
        CLEAR_CHAT_HISTORY,
    )

    /** Fallback for agents that predate the custom-role system (mirrors main.py seeds). */
    private val LEGACY_FALLBACK: Map<String, List<String>> = mapOf(
        "admin" to ALL,
        "agent" to listOf(
            VIEW_CONVERSATIONS, REPLY_CONVERSATIONS, INTERCEPT_RELEASE, CLOSE_CONVERSATIONS,
            TRANSFER_CONVERSATIONS, ADD_NOTES, VIEW_ORDERS, MANAGE_ORDERS, VIEW_CATALOG,
            VIEW_CRM, VIEW_LEADS,
        ),
        "readonly" to listOf(VIEW_CONVERSATIONS, VIEW_ORDERS, VIEW_CATALOG, VIEW_CRM, VIEW_LEADS, VIEW_ANALYTICS),
    )

    /**
     * getAgentPermissions(): a superuser has everything; otherwise the
     * resolved list ([Agent.permissions] = custom_permissions ?? role_permissions)
     * when it is non-empty; otherwise the legacy role's defaults. An empty
     * per-agent override `[]` therefore falls back to the legacy role, exactly
     * as on the web; an unknown role with nothing resolved has no permissions.
     */
    fun effective(role: String, isSuperuser: Boolean, permissions: List<String>?): List<String> = when {
        isSuperuser -> ALL
        !permissions.isNullOrEmpty() -> permissions
        else -> LEGACY_FALLBACK[role] ?: emptyList()
    }

    fun of(agent: Agent): List<String> = effective(agent.role, agent.isSuperuser, agent.permissions)

    /** hasPermission() */
    fun has(agent: Agent, perm: String): Boolean = perm in of(agent)
    /** hasAllPermissions() */
    fun hasAll(agent: Agent, perms: List<String>): Boolean = of(agent).let { e -> perms.all { it in e } }
    /** hasAnyPermission() */
    fun hasAny(agent: Agent, perms: List<String>): Boolean = of(agent).let { e -> perms.any { it in e } }
}
