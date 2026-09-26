package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures

/**
 * The round-6 permission personas, as the server describes them: the signed-in
 * agent's /admin/agents row (routers/admin.py `list_agents`, where the custom
 * role's and the per-agent permissions are joined in) and the bare ORM row
 * /admin/me returns (no permission columns at all).
 */
enum class SalesPersona(
    val role: String,
    val superuser: Boolean,
    /** The joined custom role's permissions (`role_permissions`), JSON or "null". */
    val rolePermissions: String = "null",
    /** The per-agent override (`custom_permissions`), JSON or "null". */
    val customPermissions: String = "null",
    val roleName: String? = null,
) {
    Superuser("admin", true),
    Admin("admin", false),
    LegacyAgent("agent", false),
    LegacyReadonly("readonly", false),
    /** A custom "Sales" role: conversations and orders, no leads. */
    SalesRole(
        "agent", false,
        rolePermissions = """["view_conversations","reply_conversations","view_orders","manage_orders"]""",
        roleName = "Sales",
    ),
    /** The Sales role, overridden per agent to view-only leads and conversations. */
    Override(
        "agent", false,
        rolePermissions = """["view_conversations","reply_conversations","view_orders","manage_orders"]""",
        customPermissions = """["view_conversations","view_leads"]""",
        roleName = "Sales",
    ),
    /** An empty override on a readonly agent: `[]` falls back to the legacy readonly set. */
    EmptyOverride("readonly", false, customPermissions = "[]"),
    ;

    /** The persona's own row in GET /admin/agents. */
    fun agentRow(): String = Fixtures.agentRow(
        Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", role, true, superuser, 4, 60 * 24 * 200, 1,
        customRole = roleName?.lowercase(), roleName = roleName, roleColor = roleName?.let { "#3b82f6" },
        rolePermissions = rolePermissions, customPermissions = customPermissions,
    )

    /** GET /admin/me: the ORM row — role and superuser flag only. */
    fun meOrm(): String = Fixtures.meOrm
        .replace("\"role\":\"admin\"", "\"role\":\"$role\"")
        .replace("\"is_superuser\":true", "\"is_superuser\":$superuser")
}

object SalesPersonaFixtures {
    /** Serve [p] as the signed-in agent (on top of [SalesFixtures.install]). */
    fun install(f: FakeNeema, p: SalesPersona) {
        f.on("GET", "/admin/agents", body = "[${p.agentRow()}]")
        f.on("GET", "/admin/me", body = p.meOrm())
    }

    /**
     * The server refusing everything a Sales screen writes, with FastAPI's
     * `{"detail": …}` — what a future role check would send. None of these
     * routes checks a permission today (crm.py / admin.py only depend on
     * `get_current_agent`), so this exists to prove the 403 path.
     */
    fun refuseWrites(f: FakeNeema, detail: String? = "Not allowed for your role") {
        val body = if (detail == null) "{}" else """{"detail":"$detail"}"""
        f.on("PATCH", "/admin/orders/[^/]+", code = 403, body = body)
        f.on("PATCH", "/admin/deals/[^/]+", code = 403, body = body)
        f.on("POST", "/admin/actions/[^/]+/approve", code = 403, body = body)
        f.on("POST", "/admin/actions/[^/]+/veto", code = 403, body = body)
        f.on("PATCH", "/admin/leads/[^/]+", code = 403, body = body)
    }
}
