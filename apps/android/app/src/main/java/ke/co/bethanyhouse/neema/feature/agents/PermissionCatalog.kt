package ke.co.bethanyhouse.neema.feature.agents

import androidx.compose.ui.graphics.Color
import ke.co.bethanyhouse.neema.core.perm.Perms

/** One grantable permission, as the role editor and the profile list show it. */
data class PermissionDef(val key: String, val label: String, val group: String)

/**
 * The web's ALL_PERMISSIONS (AgentsView.tsx / ProfileView.tsx) — same keys,
 * labels, order and groups. Keys match custom_roles.permissions in the DB.
 */
object PermissionCatalog {
    val ALL: List<PermissionDef> = listOf(
        PermissionDef(Perms.VIEW_CONVERSATIONS, "View conversations", "Conversations"),
        PermissionDef(Perms.REPLY_CONVERSATIONS, "Send replies", "Conversations"),
        PermissionDef(Perms.INTERCEPT_RELEASE, "Intercept / Release AI", "Conversations"),
        PermissionDef(Perms.CLOSE_CONVERSATIONS, "Close conversations", "Conversations"),
        PermissionDef(Perms.TRANSFER_CONVERSATIONS, "Transfer conversations", "Conversations"),
        PermissionDef(Perms.ADD_NOTES, "Add internal notes", "Conversations"),
        PermissionDef(Perms.VIEW_ORDERS, "View orders", "Orders"),
        PermissionDef(Perms.MANAGE_ORDERS, "Update order status", "Orders"),
        PermissionDef(Perms.VIEW_CATALOG, "View catalog", "Catalog"),
        PermissionDef(Perms.MANAGE_CATALOG, "Edit catalog", "Catalog"),
        PermissionDef(Perms.VIEW_LEADS, "View leads", "CRM"),
        PermissionDef(Perms.MANAGE_LEADS, "Manage leads", "CRM"),
        PermissionDef(Perms.VIEW_CRM, "View CRM profile", "CRM"),
        PermissionDef(Perms.EDIT_CRM, "Edit CRM profile", "CRM"),
        PermissionDef(Perms.VIEW_ANALYTICS, "View analytics", "Reports"),
        PermissionDef(Perms.VIEW_REPORTS, "View reports", "Reports"),
        PermissionDef(Perms.EXPORT_REPORTS, "Export reports", "Reports"),
        PermissionDef(Perms.MANAGE_AGENTS, "Manage agents", "Admin"),
        PermissionDef(Perms.MANAGE_ROLES, "Manage roles", "Admin"),
        PermissionDef(Perms.MANAGE_SETTINGS, "Manage settings", "Admin"),
    )

    val GROUPS: List<String> = ALL.map { it.group }.distinct()

    fun inGroup(group: String): List<PermissionDef> = ALL.filter { it.group == group }

    fun label(key: String): String? = ALL.find { it.key == key }?.label
}

/** The role editor's swatches (ROLE_COLORS). */
val ROLE_COLORS = listOf(
    "#589b31", "#427425", "#699a32", "#2a48a2", "#1f367a", "#3d528f",
    "#717425", "#979a32", "#7c3aed", "#0891b2", "#0f766e", "#b45309",
)

/** "#589b31" → Color; anything unparseable falls back to the brand green. */
fun hexColor(hex: String?): Color =
    runCatching { Color(android.graphics.Color.parseColor(hex?.trim())) }.getOrDefault(ke.co.bethanyhouse.neema.core.ui.theme.Palette.Moss600)

/** The users table only knows admin / agent / readonly (toDbRole in the web). */
fun toDbRole(roleId: String): String = when (roleId) {
    "admin", "agent", "readonly" -> roleId
    "super_admin" -> "admin"
    "viewer" -> "readonly"
    else -> "agent"
}
