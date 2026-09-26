package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures

/**
 * The round-6 permission personas for the Reports / Analytics / Catalog area:
 * the signed-in agent (Fixtures.ME_ID, moses@…) as each kind of account the
 * web's `getAgentPermissions` distinguishes. [install] serves them as
 * routers/admin.py does — `/admin/agents` (the SQL join carrying
 * `role_permissions` / `custom_permissions`) and the bare ORM `/admin/me`.
 */
object AreaPersonaFixtures {

    enum class Persona(
        val label: String,
        val role: String,
        val superuser: Boolean,
        val customRole: String? = null,
        val rolePermissions: String = "null",
        val customPermissions: String = "null",
        /** What page.tsx's nav shows for this persona: Reports, Analytics, Catalog. */
        val reports: Boolean,
        val analytics: Boolean,
        val catalog: Boolean,
    ) {
        Superuser("superuser", "agent", true, reports = true, analytics = true, catalog = true),
        Admin("admin role", "admin", false, reports = true, analytics = true, catalog = true),
        LegacyAgent("legacy agent", "agent", false, reports = false, analytics = false, catalog = true),
        LegacyReadonly("legacy readonly", "readonly", false, reports = false, analytics = true, catalog = true),
        Sales(
            "custom Sales role", "agent", false, customRole = "sales",
            rolePermissions = """["view_conversations","reply_conversations","view_orders","manage_orders"]""",
            reports = false, analytics = false, catalog = false,
        ),
        /** Per-agent override: wins over the Sales role; reports + catalogue management, no export, no analytics. */
        Override(
            "custom_permissions override", "agent", false, customRole = "sales",
            rolePermissions = """["view_conversations","reply_conversations","view_orders","manage_orders"]""",
            customPermissions = """["view_conversations","view_reports","view_catalog","manage_catalog"]""",
            reports = true, analytics = false, catalog = true,
        ),
        /**
         * `custom_permissions: []` — mapAgent's `[] ?? role_permissions` keeps
         * the empty list, and getAgentPermissions reads an empty list as "no
         * custom permissions": the legacy fallback for the base role.
         */
        EmptyOverride(
            "empty override []", "agent", false, customRole = "sales",
            rolePermissions = """["view_conversations","reply_conversations","view_orders","manage_orders"]""",
            customPermissions = "[]",
            reports = false, analytics = false, catalog = true,
        ),
    }

    /** The signed-in agent's /admin/agents row as [p]. */
    fun meRow(p: Persona): String = Fixtures.agentRow(
        Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", p.role, true, p.superuser, 4, 60 * 24 * 200, 1,
        customRole = p.customRole, roleName = p.customRole?.replaceFirstChar { it.uppercaseChar() },
        roleColor = p.customRole?.let { "#3b82f6" },
        rolePermissions = p.rolePermissions, customPermissions = p.customPermissions,
    )

    /** GET /admin/me: the bare ORM row, no role columns. */
    fun meOrm(p: Persona): String = Fixtures.meOrm
        .replace("\"role\":\"admin\"", "\"role\":\"${p.role}\"")
        .replace("\"is_superuser\":true", "\"is_superuser\":${p.superuser}")

    /** The team as the base fixtures serve it, with the signed-in agent as [p]. */
    fun agents(p: Persona): String {
        // The base team opens with the signed-in admin's row (it ends at its
        // null role_permissions); swap that row, keep Grace and Brian.
        val all = Fixtures.agents
        val end = "\"role_permissions\":null}"
        val cut = all.indexOf(end)
        check(cut > 0) { "Fixtures.agents no longer starts with the signed-in agent's row" }
        return "[" + meRow(p) + all.substring(cut + end.length)
    }

    fun install(f: FakeNeema, p: Persona) {
        f.on("GET", "/admin/me", body = meOrm(p))
        f.on("GET", "/admin/agents", body = agents(p))
    }
}
