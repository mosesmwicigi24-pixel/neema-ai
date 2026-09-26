package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The round-6 personas for the inbox's permission matrix: who is signed in, as
 * the server tells it — the session's role, GET /admin/me (the bare ORM row,
 * no custom-role columns) and this agent's GET /admin/agents row (the SQL join
 * with role_permissions / custom_permissions).
 *
 * Only `role` (the stored enum) and `is_superuser` decide the inbox's controls
 * on the web (ConversationsView.tsx); the permission lists are served so a
 * test can prove they change nothing there.
 */
object InboxPersonaFixtures {
    enum class Persona(
        val role: String,
        val superuser: Boolean,
        val customRole: String? = null,
        val roleName: String? = null,
        val rolePermissions: String = "null",
        val customPermissions: String = "null",
    ) {
        /** Superuser on a plain agent role: is_superuser alone makes them an admin. */
        Superuser("agent", true),
        Admin("admin", false),
        /** Legacy agent — no custom role: the LEGACY_FALLBACK agent set. */
        Agent("agent", false),
        /** Legacy readonly — views everything, handles nothing. */
        Readonly("readonly", false),
        /** A custom Sales role on the agent enum. */
        Sales("agent", false, "sales", "Sales", """["view_conversations","reply_conversations","view_orders","manage_orders"]"""),
        /** A custom role WITHOUT reply_conversations / intercept_release — still the agent enum. */
        Viewer("agent", false, "viewer", "Viewer", """["view_conversations","view_orders"]"""),
        /** A custom role that grants replying — on the readonly enum. */
        ReadonlyReplier("readonly", false, "replier", "Replier", """["view_conversations","reply_conversations","intercept_release"]"""),
        /** A per-agent override naming only view_conversations. */
        Override("agent", false, customPermissions = """["view_conversations"]"""),
        /** An empty override: the web reads it as "no override" (length check) and falls back. */
        EmptyOverride("agent", false, customPermissions = "[]"),
        /** A role the inbox doesn't recognise as a handler. */
        Supervisor("supervisor", false),
    }

    /** GET /admin/me for [p]: the base admin ORM row with the persona's role and flag. */
    fun me(p: Persona): String = Fixtures.meOrm
        .replace("\"role\":\"admin\"", "\"role\":\"${p.role}\"")
        .replace("\"is_superuser\":true", "\"is_superuser\":${p.superuser}")

    /** The signed-in agent's GET /admin/agents row for [p]. */
    fun row(p: Persona): String = Fixtures.agentRow(
        Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", p.role, true, p.superuser, 4, 60 * 24 * 200, 1,
        customRole = p.customRole, roleName = p.roleName, roleColor = p.customRole?.let { "#3b82f6" },
        rolePermissions = p.rolePermissions, customPermissions = p.customPermissions,
    )

    /**
     * The whole team list with the signed-in agent as [p]. (Rebuilt, not a text
     * replace: the rows carry microsecond timestamps, so two renders of the same
     * row can differ.)
     */
    fun agents(p: Persona): String {
        val base = Json.parseToJsonElement(Fixtures.agents).jsonArray
        val rest = base.filter { it.jsonObject["id"]?.jsonPrimitive?.content != Fixtures.ME_ID }
        return JsonArray(listOf(Json.parseToJsonElement(row(p))) + rest).toString()
    }

    val roles = """[{"id":"admin","name":"Admin","description":"Full system access","color":"#f59e0b","permissions":["view_conversations","manage_agents","manage_roles","manage_settings"],"protected":true},
      {"id":"sales","name":"Sales","description":"Handles conversations and orders","color":"#3b82f6","permissions":["view_conversations","reply_conversations","view_orders","manage_orders"],"protected":false},
      {"id":"viewer","name":"Viewer","description":"Reads conversations","color":"#3b82f6","permissions":["view_conversations","view_orders"],"protected":false},
      {"id":"replier","name":"Replier","description":"Replies on a readonly seat","color":"#3b82f6","permissions":["view_conversations","reply_conversations","intercept_release"],"protected":false}]"""

    /** Serve [p] as the signed-in agent (call after the base and inbox installs). */
    fun install(f: FakeNeema, p: Persona) {
        f.on("GET", "/admin/me", body = me(p))
        f.on("GET", "/admin/agents", body = agents(p))
        f.on("GET", "/admin/roles", body = roles)
    }
}
