package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.Fixtures.ago

/**
 * Team / Profile / Settings data beyond the base set: a fuller role list
 * (protected, many permissions, none), an agent with a per-agent permission
 * override, and a long name to test truncation. Shapes follow admin.py
 * list_agents and roles.py list_roles.
 */
object TeamFixtures {
    const val AGENT4_ID = "a1000000-0000-0000-0000-000000000004"

    val allPerms = listOf(
        "view_conversations", "reply_conversations", "intercept_release", "close_conversations", "transfer_conversations",
        "add_notes", "view_orders", "manage_orders", "view_catalog", "manage_catalog", "view_leads", "manage_leads",
        "view_crm", "edit_crm", "view_analytics", "view_reports", "export_reports", "manage_agents", "manage_roles", "manage_settings",
    )

    private fun arr(l: List<String>) = l.joinToString(",", "[", "]") { "\"$it\"" }

    val roles = """[
      {"id":"admin","name":"Admin","description":"Full system access","color":"#f59e0b","permissions":${arr(allPerms)},"protected":true},
      {"id":"sales","name":"Sales","description":"Handles conversations and orders","color":"#3b82f6",
       "permissions":["view_conversations","reply_conversations","view_orders","manage_orders"],"protected":false},
      {"id":"support","name":"Support Lead","description":"Owns escalations, closes threads and keeps customer records tidy","color":"#0f766e",
       "permissions":${arr(allPerms.take(14))},"protected":false},
      {"id":"trainee","name":"Trainee","description":"","color":"#7c3aed","permissions":[],"protected":false}
    ]"""

    val agents get() = """[
      ${Fixtures.me},
      {"id":"${Fixtures.AGENT2_ID}","name":"Grace Wanjiru","email":"grace@bethanyhouse.co.ke","role":"agent","is_available":true,
       "is_superuser":false,"active_convs":7,"avatar_url":null,"created_at":"${ago(60 * 24 * 120)}","last_seen_at":"${ago(3)}",
       "custom_role_id":"sales","custom_permissions":null,"role_name":"Sales","role_color":"#3b82f6",
       "role_permissions":["view_conversations","reply_conversations","view_orders","manage_orders"]},
      {"id":"${Fixtures.AGENT3_ID}","name":"Brian Otieno","email":"brian@bethanyhouse.co.ke","role":"readonly","is_available":false,
       "is_superuser":false,"active_convs":0,"avatar_url":null,"created_at":"${ago(60 * 24 * 30)}","last_seen_at":"${ago(60 * 26)}",
       "custom_role_id":null,"custom_permissions":null,"role_name":null,"role_color":null,"role_permissions":null},
      {"id":"$AGENT4_ID","name":"Wanjiku Kamau-Ochieng Nyambura","email":"wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke","role":"agent",
       "is_available":false,"is_superuser":false,"active_convs":2,"avatar_url":null,"created_at":"${ago(60 * 24 * 10)}","last_seen_at":null,
       "custom_role_id":"support","custom_permissions":["view_conversations","reply_conversations","add_notes"],
       "role_name":"Support Lead","role_color":"#0f766e","role_permissions":${arr(allPerms.take(14))}}
    ]"""

    fun install(f: FakeNeema) {
        f.on("GET", "/admin/roles", body = roles)
        f.on("GET", "/admin/agents", body = agents)
        writes(f)
    }

    /** What the write routes really answer (admin.py create_agent / update_me return the agent row). */
    fun writes(f: FakeNeema) {
        f.on("POST", "/admin/agents") { _, _ ->
            200 to """{"id":"a1000000-0000-0000-0000-000000000009","name":"Jane Doe","email":"jane@bethanyhouse.co.ke","role":"admin","is_available":true}"""
        }
        f.on("PATCH", "/admin/me", body = Fixtures.me)
    }

    /** No offer declared yet (GET /admin/settings/offer before anyone starts one). */
    fun noOffer(f: FakeNeema) =
        f.on("GET", "/admin/settings/offer", body = """{"campaign":null,"running":false,"says":"","max_percent":30}""")

    /** A stored offer whose end date has passed — saved, not running. */
    fun expiredOffer(f: FakeNeema) = f.on(
        "GET", "/admin/settings/offer",
        body = """{"campaign":{"name":"Lent Offer","percent":15,"scope":"products","categories":[],"skus":["CS-BLK-16","STL-GRN","ZZ-UNKNOWN"],
          "starts_on":null,"ends_on":"2026-03-01"},"running":false,"says":"","max_percent":30}""",
    )
}
