package ke.co.bethanyhouse.neema.testing

import ke.co.bethanyhouse.neema.core.perm.Perms

/**
 * Who is signed in, for permission tests (round 6's matrix). Every persona is
 * the same person — Moses, [Fixtures.ME_ID] — so feature fixtures that key on
 * the signed-in agent keep working; only his role columns change:
 *
 * - the session (what the token response said: `role`, `is_superuser`);
 * - GET /admin/me (the ORM row: `role`, `is_superuser`, no custom-role columns);
 * - his row in GET /admin/agents (`role`, `is_superuser`, `custom_role_id`,
 *   `role_name`/`role_color`/`role_permissions` joined from custom_roles, and
 *   the per-agent `custom_permissions` override);
 * - GET /admin/roles serves [Personas.roles]: main.py's three seeds plus Sales.
 *
 * [expected] is what lib/permissions.ts `getAgentPermissions` resolves for
 * that row — the oracle the matrix tests compare against.
 */
enum class Persona(
    val role: String,
    val superuser: Boolean,
    val customRoleId: String? = null,
    val roleName: String? = null,
    val roleColor: String? = null,
    val rolePermissions: List<String>? = null,
    val customPermissions: List<String>? = null,
    val expected: List<String>,
) {
    /** is_superuser: everything, whatever the role says. */
    Superuser("admin", true, expected = Perms.ALL),

    /** Legacy `admin` role, no custom role: the admin fallback (everything). */
    Admin("admin", false, expected = Perms.ALL),

    /** Legacy `agent`, no custom role: main.py's Agent seed. */
    Agent(
        "agent", false,
        expected = listOf(
            Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.INTERCEPT_RELEASE, Perms.CLOSE_CONVERSATIONS,
            Perms.TRANSFER_CONVERSATIONS, Perms.ADD_NOTES, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS, Perms.VIEW_CATALOG,
            Perms.VIEW_CRM, Perms.VIEW_LEADS,
        ),
    ),

    /** Legacy `readonly`, no custom role. */
    Readonly(
        "readonly", false,
        expected = listOf(Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS),
    ),

    /** A custom "Sales" role: conversations and orders only. */
    Sales(
        "agent", false, customRoleId = "sales", roleName = "Sales", roleColor = "#3b82f6",
        rolePermissions = SALES, expected = SALES,
    ),

    /** Sales, with a per-agent override that replaces the role's list outright. */
    Override(
        "agent", false, customRoleId = "sales", roleName = "Sales", roleColor = "#3b82f6",
        rolePermissions = SALES, customPermissions = OVERRIDE, expected = OVERRIDE,
    ),

    /**
     * Sales, with an empty override `[]`: mapAgent keeps `[]` (it is not
     * null), getAgentPermissions skips an empty list — so the LEGACY role's
     * defaults apply, not Sales'. (Here the legacy role is readonly.)
     */
    EmptyOverride(
        "readonly", false, customRoleId = "sales", roleName = "Sales", roleColor = "#3b82f6",
        rolePermissions = SALES, customPermissions = emptyList(),
        expected = listOf(Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS),
    ),
    ;

    /** GET /admin/me for this persona — routers/admin.py `get_me` (the ORM row). */
    val meOrm: String
        get() = Fixtures.meOrm
            .replace("\"role\":\"admin\"", "\"role\":\"$role\"")
            .replace("\"is_superuser\":true", "\"is_superuser\":$superuser")

    /** This persona's row in GET /admin/agents — routers/admin.py `list_agents`. */
    val row: String
        get() = Fixtures.agentRow(
            Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", role, true, superuser, 4, 60 * 24 * 200, 1,
            customRole = customRoleId, roleName = roleName, roleColor = roleColor,
            rolePermissions = rolePermissions.json(), customPermissions = customPermissions.json(),
        )

    /** The whole team list with this persona in Moses's place. */
    val agents: String
        get() {
            // By id, not by text: the rows' timestamps are "now"-relative to the microsecond.
            val mine = kotlinx.serialization.json.Json.parseToJsonElement(row)
            return kotlinx.serialization.json.JsonArray(
                kotlinx.serialization.json.Json.parseToJsonElement(Fixtures.agents).let { it as kotlinx.serialization.json.JsonArray }.map { a ->
                    val id = ((a as kotlinx.serialization.json.JsonObject)["id"] as? kotlinx.serialization.json.JsonPrimitive)?.content
                    if (id == Fixtures.ME_ID) mine else a
                },
            ).toString()
        }

    /** The token response a sign-in as this persona gets (routers/auth.py). */
    fun tokenResponse() = Fixtures.tokenResponse(role = role, superuser = superuser)
}

private val SALES = listOf(Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS)
private val OVERRIDE = listOf(Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_REPORTS, Perms.EXPORT_REPORTS)

private fun List<String>?.json(): String = this?.joinToString(",", "[", "]") { "\"$it\"" } ?: "null"

object Personas {
    /**
     * GET /admin/roles — routers/roles.py `list_roles` (ORDER BY protected
     * DESC, name) over main.py's seeds (super_admin, agent, viewer; note the
     * seeded Super Admin lacks clear_chat_history) plus the custom Sales role.
     */
    val roles: String
        get() = """[
      {"id":"super_admin","name":"Super Admin","description":"Full platform access — cannot be modified","color":"#7c3aed","permissions":${(Perms.ALL - Perms.CLEAR_CHAT_HISTORY).json()},"protected":true,"created_at":"${Fixtures.pyIso(60 * 24 * 400)}"},
      {"id":"agent","name":"Agent","description":"Handle conversations and orders","color":"#589b31","permissions":${Persona.Agent.expected.json()},"protected":false,"created_at":"${Fixtures.pyIso(60 * 24 * 400)}"},
      {"id":"sales","name":"Sales","description":"Handles conversations and orders","color":"#3b82f6","permissions":${SALES.json()},"protected":false,"created_at":"${Fixtures.pyIso(60 * 24 * 90)}"},
      {"id":"viewer","name":"Viewer","description":"Read-only access","color":"#699a32","permissions":${Persona.Readonly.expected.json()},"protected":false,"created_at":"${Fixtures.pyIso(60 * 24 * 400)}"}
    ]"""

    /** Serve [p]'s /admin/me, team list, roles and sign-in answers on [f]. */
    fun install(f: FakeNeema, p: Persona) {
        f.on("GET", "/admin/me", body = p.meOrm)
        f.on("GET", "/admin/agents", body = p.agents)
        f.on("GET", "/admin/roles", body = roles)
        f.on("PATCH", "/admin/me") { _, _ -> 200 to p.meOrm }
        f.on("POST", "/(agent-auth|auth)/(login|refresh)") { _, _ -> 200 to p.tokenResponse() }
    }

    /**
     * An admin edits this agent while the app is open: from now on the
     * server answers /admin/me and the team list as [p]. Nothing on screen
     * changes until the app rereads them (the 180 s poll, or a 403).
     */
    fun become(f: FakeNeema, p: Persona) = install(f, p)
}
