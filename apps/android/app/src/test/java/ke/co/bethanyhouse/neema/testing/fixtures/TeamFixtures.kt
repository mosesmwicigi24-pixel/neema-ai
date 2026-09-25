package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * Team / Profile / Settings data, built from what the API handlers actually
 * return (apps/api/app/routers/admin.py, roles.py, crm.py and
 * services/promotions.py, app_settings.py). Each value cites its handler.
 *
 * Serialisation facts these follow:
 *  - Raw-SQL rows (`dict(zip(keys, row))`) and ORM objects both go through
 *    FastAPI's jsonable_encoder: UUIDs become strings, TIMESTAMPTZ columns
 *    become Python isoformat — microseconds and "+00:00", never "Z".
 *  - JSONB columns (custom_permissions, permissions) arrive decoded (the
 *    asyncpg dialect registers a json codec), so they are arrays or null.
 *  - An ORM `Agent` returned bare (get_me, update_me, create_agent) carries
 *    every mapped column — including password_hash — and none of the
 *    custom-role columns, which only exist in SQL (main.py migrations).
 *  - A write the database refuses (duplicate email: agents.email is UNIQUE)
 *    is an unhandled IntegrityError: a 500 with a plain-text body.
 *
 * The write routes below re-implement each handler's validation, so tests
 * exercise the server's real answers — errors included.
 */
object TeamFixtures {
    const val AGENT4_ID = "a1000000-0000-0000-0000-000000000004"
    const val NEW_AGENT_ID = "a1000000-0000-0000-0000-000000000009"

    /** Python's `datetime.isoformat()` of an aware UTC timestamp. */
    private val py = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSSxxx")
    fun pyTs(minutesAgo: Long): String = OffsetDateTime.now(ZoneOffset.UTC).minusMinutes(minutesAgo).format(py)

    val allPerms = listOf(
        "view_conversations", "reply_conversations", "intercept_release", "close_conversations", "transfer_conversations",
        "add_notes", "view_orders", "manage_orders", "view_catalog", "manage_catalog", "view_leads", "manage_leads",
        "view_crm", "edit_crm", "view_analytics", "view_reports", "export_reports", "manage_agents", "manage_roles", "manage_settings",
    )

    private fun arr(l: List<String>) = l.joinToString(",", "[", "]") { "\"$it\"" }

    // ── Roles ────────────────────────────────────────────────────────────────

    private val supportPerms = allPerms.take(14)
    private val salesPerms = listOf("view_conversations", "reply_conversations", "view_orders", "manage_orders")

    private fun role(id: String, name: String, desc: String, color: String, perms: List<String>, protected: Boolean, minutesAgo: Long) =
        """{"id":"$id","name":"$name","description":"$desc","color":"$color","permissions":${arr(perms)},"protected":$protected,"created_at":"${pyTs(minutesAgo)}"}"""

    /**
     * roles.py list_roles: `SELECT id, name, description, color, permissions,
     * protected, created_at FROM custom_roles ORDER BY protected DESC, name`.
     * super_admin / agent / viewer are main.py's seeds (super_admin is the only
     * protected one); the rest were made in the role editor.
     */
    val roles get() = listOf(
        role("super_admin", "Super Admin", "Full platform access — cannot be modified", "#7c3aed", allPerms, true, 60L * 24 * 400),
        role("agent", "Agent", "Handle conversations and orders", "#589b31",
            listOf("view_conversations", "reply_conversations", "intercept_release", "close_conversations", "transfer_conversations",
                "add_notes", "view_orders", "manage_orders", "view_catalog", "view_crm", "view_leads"), false, 60L * 24 * 400),
        role("sales", "Sales", "Handles conversations and orders", "#3b82f6", salesPerms, false, 60L * 24 * 90),
        role("support", "Support Lead", "Owns escalations, closes threads and keeps customer records tidy", "#0f766e", supportPerms, false, 60L * 24 * 40),
        role("trainee", "Trainee", "", "#7c3aed", emptyList(), false, 60L * 24 * 5),
        role("viewer", "Viewer", "Read-only access", "#699a32",
            listOf("view_conversations", "view_orders", "view_catalog", "view_crm", "view_leads", "view_analytics"), false, 60L * 24 * 400),
    ).joinToString(",", "[", "]")

    // ── Agents ───────────────────────────────────────────────────────────────

    /**
     * admin.py list_agents: the agents row LEFT JOIN custom_roles —
     * id, name, email, role, is_available, is_superuser, avatar_url,
     * created_at, last_seen_at, active_convs (COALESCEd), custom_role_id,
     * custom_permissions, role_name, role_color, role_permissions; ORDER BY name.
     */
    val agents get() = agentsWithMe()

    /**
     * The same list with the signed-in agent's own row changed — a plain agent
     * whose power comes from [customPermissions] (limited-permission states).
     */
    fun agentsWithMe(
        role: String = "admin", superuser: Boolean = true, customPermissions: List<String>? = null,
    ) = """[
      {"id":"${Fixtures.AGENT3_ID}","name":"Brian Otieno","email":"brian@bethanyhouse.co.ke","role":"readonly","is_available":false,
       "is_superuser":false,"avatar_url":null,"created_at":"${pyTs(60L * 24 * 30)}","last_seen_at":"${pyTs(60L * 26)}","active_convs":0,
       "custom_role_id":null,"custom_permissions":null,"role_name":null,"role_color":null,"role_permissions":null},
      {"id":"${Fixtures.AGENT2_ID}","name":"Grace Wanjiru","email":"grace@bethanyhouse.co.ke","role":"agent","is_available":true,
       "is_superuser":false,"avatar_url":null,"created_at":"${pyTs(60L * 24 * 120)}","last_seen_at":"${pyTs(3)}","active_convs":7,
       "custom_role_id":"sales","custom_permissions":null,"role_name":"Sales","role_color":"#3b82f6","role_permissions":${arr(salesPerms)}},
      {"id":"${Fixtures.ME_ID}","name":"Moses Mwicigi","email":"moses@bethanyhouse.co.ke","role":"$role","is_available":true,
       "is_superuser":$superuser,"avatar_url":null,"created_at":"${pyTs(60L * 24 * 200)}","last_seen_at":"${pyTs(1)}","active_convs":4,
       "custom_role_id":null,"custom_permissions":${customPermissions?.let { arr(it) } ?: "null"},"role_name":null,"role_color":null,"role_permissions":null},
      {"id":"$AGENT4_ID","name":"Wanjiku Kamau-Ochieng Nyambura","email":"wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke","role":"agent",
       "is_available":false,"is_superuser":false,"avatar_url":null,"created_at":"${pyTs(60L * 24 * 10)}","last_seen_at":null,"active_convs":2,
       "custom_role_id":"support","custom_permissions":["view_conversations","reply_conversations","add_notes"],
       "role_name":"Support Lead","role_color":"#0f766e","role_permissions":${arr(supportPerms)}}
    ]"""

    /**
     * admin.py get_me / update_me / create_agent return the ORM `Agent`:
     * every mapped column (password_hash included — see the report), and no
     * custom_role_id / custom_permissions / role_* keys.
     */
    fun ormAgent(
        id: String = Fixtures.ME_ID, name: String = "Moses Mwicigi", email: String = "moses@bethanyhouse.co.ke",
        role: String = "admin", available: Boolean = true, superuser: Boolean = true, activeConvs: Int = 4,
        createdMinutesAgo: Long = 60L * 24 * 200, lastSeenMinutesAgo: Long? = 1,
    ) = """{"id":"$id","name":${JsonPrimitive(name)},"email":${JsonPrimitive(email)},
        "password_hash":"${'$'}2b${'$'}12${'$'}Qm9ndXNIYXNoRm9yVGVzdHMuLi4uLi4uLi4uLi4uLi4uLi4uLi4u","role":"$role",
        "is_available":$available,"is_superuser":$superuser,"active_convs":$activeConvs,"avatar_url":null,
        "created_at":"${pyTs(createdMinutesAgo)}","last_seen_at":${lastSeenMinutesAgo?.let { "\"${pyTs(it)}\"" } ?: "null"}}"""

    val me get() = ormAgent()

    private val agentIds = listOf(Fixtures.ME_ID, Fixtures.AGENT2_ID, Fixtures.AGENT3_ID, AGENT4_ID)
    private fun emails(): List<String> = Json.parseToJsonElement(agents).let { it as JsonArray }
        .map { it.jsonObject["email"]!!.jsonPrimitive.content }
    private fun roleIds(): List<String> = Json.parseToJsonElement(roles).let { it as JsonArray }
        .map { it.jsonObject["id"]!!.jsonPrimitive.content }
    private fun protectedRole(id: String) = Json.parseToJsonElement(roles).let { it as JsonArray }
        .firstOrNull { it.jsonObject["id"]!!.jsonPrimitive.content == id }?.jsonObject?.get("protected")?.jsonPrimitive?.booleanOrNull

    private fun body(b: String?): JsonObject = runCatching { Json.parseToJsonElement(b ?: "{}").jsonObject }.getOrDefault(JsonObject(emptyMap()))
    private fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
    private fun detail(s: String) = """{"detail":${JsonPrimitive(s)}}"""
    /** Starlette's answer to an unhandled exception (IntegrityError on agents.email). */
    const val SERVER_ERROR = "Internal Server Error"

    fun install(f: FakeNeema) {
        f.on("GET", "/admin/roles", body = roles)
        f.on("GET", "/admin/agents", body = agents)
        f.on("GET", "/admin/me", body = me)
        writes(f)
    }

    /** Every Team / Profile write, answering as its handler does. */
    fun writes(f: FakeNeema) {
        // admin.py create_agent: 422 "Missing required fields: …" when name/email/password is falsy;
        // a taken email violates agents.email UNIQUE → 500; else the refreshed ORM row.
        f.on("POST", "/admin/agents") { _, b ->
            val j = body(b)
            val missing = listOf("name", "email", "password").filter { j.str(it).isNullOrEmpty() }
            when {
                missing.isNotEmpty() -> 422 to detail("Missing required fields: ${missing.joinToString(", ")}")
                j.str("email") in emails() -> 500 to SERVER_ERROR
                j.str("role") !in listOf(null, "admin", "agent", "readonly") -> 500 to SERVER_ERROR   // PgEnum(AgentRole)
                else -> 200 to ormAgent(NEW_AGENT_ID, j.str("name")!!, j.str("email")!!, j.str("role") ?: "agent",
                    superuser = false, activeConvs = 0, createdMinutesAgo = 0, lastSeenMinutesAgo = null)
            }
        }
        // admin.py update_agent: 404 "Agent not found"; 422 for a short password; {"ok": true}.
        f.on("PATCH", "/admin/agents/[^/]+") { r, b ->
            val id = r.url.pathSegments.last()
            val pw = body(b).str("password")
            val email = body(b).str("email")
            when {
                id !in agentIds -> 404 to detail("Agent not found")
                !pw.isNullOrEmpty() && pw.length < 8 -> 422 to detail("Password must be at least 8 characters")
                !email.isNullOrEmpty() && email in emails() - emailOf(id) -> 500 to SERVER_ERROR
                else -> 200 to """{"ok":true}"""
            }
        }
        // admin.py assign_agent_role: 422 / 404s, then the joined row (no is_superuser, no role_permissions).
        f.on("PATCH", "/admin/agents/[^/]+/role") { r, b ->
            val id = r.url.pathSegments[r.url.pathSegments.size - 2]
            val j = body(b)
            val roleId = j.str("custom_role_id")
            when {
                roleId.isNullOrEmpty() -> 422 to detail("custom_role_id is required")
                roleId !in roleIds() -> 404 to detail("Role not found")
                id !in agentIds -> 404 to detail("Agent not found")
                else -> 200 to """{"id":"$id","name":"Brian Otieno","email":"${emailOf(id)}","role":"readonly","is_available":false,
                    "custom_role_id":"$roleId","custom_permissions":${j["custom_permissions"] ?: "null"},"role_name":"Sales","role_color":"#3b82f6"}"""
            }
        }
        // admin.py delete_agent: 404 "Agent not found"; {"ok": true}. No guard on self or the last admin.
        f.on("DELETE", "/admin/agents/[^/]+") { r, _ ->
            if (r.url.pathSegments.last() in agentIds) 200 to """{"ok":true}""" else 404 to detail("Agent not found")
        }
        // admin.py update_me: sets whichever of name/email/password is present (no checks), returns the ORM row.
        f.on("PATCH", "/admin/me") { _, b ->
            val j = body(b)
            val email = j.str("email")
            if (email != null && email in emails() - emailOf(Fixtures.ME_ID)) 500 to SERVER_ERROR
            else 200 to ormAgent(name = j.str("name") ?: "Moses Mwicigi", email = email ?: "moses@bethanyhouse.co.ke")
        }
        // roles.py create_role: 422 "name is required"; id = body id or role_<hex8>; upserts; returns the row.
        f.on("POST", "/admin/roles") { _, b ->
            val j = body(b)
            if (j.str("name").isNullOrEmpty()) 422 to detail("name is required")
            else 200 to """{"id":"${j.str("id") ?: "role_1a2b3c4d"}","name":${j["name"]},"description":${j["description"] ?: "\"\""},
                "color":${j["color"] ?: "\"#589b31\""},"permissions":${j["permissions"] ?: "[]"},"protected":false,"created_at":"${pyTs(0)}"}"""
        }
        // roles.py update_role: 404 / 403 "Cannot modify a protected role"; the updated row.
        f.on("PATCH", "/admin/roles/[^/]+") { r, b ->
            val id = r.url.pathSegments.last()
            val j = body(b)
            when (protectedRole(id)) {
                null -> 404 to detail("Role not found")
                true -> 403 to detail("Cannot modify a protected role")
                false -> 200 to """{"id":"$id","name":${j["name"] ?: "\"Sales\""},"description":${j["description"] ?: "\"\""},
                    "color":${j["color"] ?: "\"#3b82f6\""},"permissions":${j["permissions"] ?: "[]"},"protected":false,"created_at":"${pyTs(60L * 24 * 90)}"}"""
            }
        }
        // roles.py delete_role: 404 / 403 "Cannot delete a protected role"; clears agents on it; {"ok": true}.
        f.on("DELETE", "/admin/roles/[^/]+") { r, _ ->
            when (protectedRole(r.url.pathSegments.last())) {
                null -> 404 to detail("Role not found")
                true -> 403 to detail("Cannot delete a protected role")
                false -> 200 to """{"ok":true}"""
            }
        }
    }

    private fun emailOf(id: String) = Json.parseToJsonElement(agents).let { it as JsonArray }
        .first { it.jsonObject["id"]!!.jsonPrimitive.content == id }.jsonObject["email"]!!.jsonPrimitive.content

    // ── Settings (crm.py) ────────────────────────────────────────────────────

    /** app_settings.DIRECTIVES_MAX_CHARS */
    const val DIRECTIVES_MAX = 600
    /** promotions.MAX_PERCENT */
    const val OFFER_MAX_PERCENT = 70
    const val OFFER_422 = "a campaign needs a name, 1-70%, a scope with its categories or SKUs, and an end date (YYYY-MM-DD)"

    /** A running Easter offer, as promotions.parse stores it and describe() words it. */
    val easterCampaign = """{"name":"Easter Sale","percent":10,"scope":"category","categories":["Vestments"],"skus":[],"starts_on":null,"ends_on":"2099-04-30"}"""
    const val EASTER_SAYS = "Easter Sale — 10% off our Vestments, until 30 April 2099"

    /**
     * Every settings route as crm.py answers it. [admin] false makes the four
     * PUTs refuse with 403 "Admin only", as they do for a non-admin caller.
     */
    fun settings(f: FakeNeema, admin: Boolean = true) {
        var directives = "Always offer free delivery within Nairobi on orders above KES 10,000."
        // crm.py get_operator_directives: {"directives", "max_chars"}.
        f.on("GET", "/admin/settings/directives") { _, _ -> 200 to """{"directives":${JsonPrimitive(directives)},"max_chars":$DIRECTIVES_MAX}""" }
        // put_operator_directives → set_directives: str(body.directives or "").strip()[:600]; never 413/422.
        f.on("PUT", "/admin/settings/directives") { _, b ->
            if (!admin) return@on 403 to detail("Admin only")
            directives = (body(b).str("directives") ?: "").trim().take(DIRECTIVES_MAX)
            200 to """{"ok":true,"directives":${JsonPrimitive(directives)}}"""
        }

        var stages = listOf("measuring")
        // get_pipeline_stages: {"stages": [...]}
        f.on("GET", "/admin/settings/pipeline-stages") { _, _ -> 200 to """{"stages":${arr(stages)}}""" }
        // put_pipeline_stages: 403; 422 "stages must be a list"; clean (trim, [:18], drop blanks,
        // built-ins and case-insensitive repeats); 422 "At most 4 custom stages"; {"ok", "stages"}.
        f.on("PUT", "/admin/settings/pipeline-stages") { _, b ->
            if (!admin) return@on 403 to detail("Admin only")
            val raw = body(b)["stages"] as? JsonArray ?: return@on 422 to detail("stages must be a list")
            val canonical = setOf("new", "contacted", "qualified", "proposal", "negotiation", "won", "lost")
            val cleaned = mutableListOf<String>()
            raw.forEach { s ->
                val label = ((s as? JsonPrimitive)?.contentOrNull ?: "").trim().take(18)
                if (label.isNotEmpty() && label.lowercase() !in canonical && cleaned.none { it.lowercase() == label.lowercase() }) cleaned += label
            }
            if (cleaned.size > 4) return@on 422 to detail("At most 4 custom stages")
            stages = cleaned
            200 to """{"ok":true,"stages":${arr(cleaned)}}"""
        }

        var enabled = true
        // get_translation_setting: spend is round(float, 4) — a JSON number, never a Decimal string.
        f.on("GET", "/admin/settings/translation") { _, _ -> 200 to """{"enabled":$enabled,"default":false,"spend_30d_usd":3.4187,"calls_30d":812}""" }
        // put_translation_setting: 403; 422 unless enabled is a JSON bool; {"ok", "enabled"}.
        f.on("PUT", "/admin/settings/translation") { _, b ->
            if (!admin) return@on 403 to detail("Admin only")
            val e = (body(b)["enabled"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
                ?: return@on 422 to detail("enabled must be true or false")
            enabled = e
            200 to """{"ok":true,"enabled":$e}"""
        }

        var campaign: String? = easterCampaign
        // get_offer: {"campaign": parse(stored) or null, "running", "says": describe(live), "max_percent": 70}.
        f.on("GET", "/admin/settings/offer") { _, _ -> 200 to offerBody(campaign) }
        // put_offer: 403; set_campaign → parse or 422 (ValueError text); {"ok", "campaign", "running", "says"}.
        f.on("PUT", "/admin/settings/offer") { _, b ->
            if (!admin) return@on 403 to detail("Admin only")
            val c = body(b)["campaign"]
            if (c == null || c is JsonNull) { campaign = null; return@on 200 to """{"ok":true,"campaign":null,"running":false,"says":""}""" }
            val parsed = parseCampaign(c) ?: return@on 422 to detail(OFFER_422)
            campaign = parsed
            val running = isRunning(parsed)
            200 to """{"ok":true,"campaign":$parsed,"running":$running,"says":${JsonPrimitive(if (running) describe(parsed) else "")}}"""
        }
    }

    private fun offerBody(c: String?): String {
        val running = c != null && isRunning(c)
        return """{"campaign":${c ?: "null"},"running":$running,"says":${JsonPrimitive(if (running) describe(c!!) else "")},"max_percent":$OFFER_MAX_PERCENT}"""
    }

    /** promotions.parse, for the fake: the normalised campaign JSON, or null when it would 422. */
    private fun parseCampaign(el: JsonElement): String? {
        val c = el as? JsonObject ?: return null
        val name = (c.str("name") ?: "").trim().take(60)
        val pctEl = c["percent"] as? JsonPrimitive ?: return null
        val percent = pctEl.intOrNull ?: pctEl.contentOrNull?.toDoubleOrNull()?.toInt() ?: return null   // int(percent)
        if (name.isEmpty() || percent !in 1..OFFER_MAX_PERCENT) return null
        val scope = (c.str("scope") ?: "all").trim().lowercase()
        if (scope !in setOf("all", "category", "products")) return null
        fun clean(k: String) = ((c[k] as? JsonArray) ?: JsonArray(emptyList()))
            .mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.trim()?.takeIf { s -> s.isNotEmpty() } }
            .distinctBy { it.lowercase() }.take(60)
        val cats = clean("categories"); val skus = clean("skus")
        if (scope == "category" && cats.isEmpty() || scope == "products" && skus.isEmpty()) return null
        val ends = runCatching { LocalDate.parse(c.str("ends_on")) }.getOrNull() ?: return null
        val starts = c.str("starts_on")?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
        return """{"name":${JsonPrimitive(name)},"percent":$percent,"scope":"$scope","categories":${arr(cats)},"skus":${arr(skus)},""" +
            """"starts_on":${starts?.let { "\"$it\"" } ?: "null"},"ends_on":"$ends"}"""
    }

    private fun obj(c: String) = Json.parseToJsonElement(c).jsonObject

    private fun isRunning(c: String): Boolean {
        val o = obj(c)
        val today = LocalDate.now(ZoneOffset.UTC)
        val starts = o.str("starts_on")?.let { LocalDate.parse(it) }
        if (starts != null && today < starts) return false
        return today <= LocalDate.parse(o.str("ends_on"))
    }

    /** promotions.describe */
    private fun describe(c: String): String {
        val o = obj(c)
        val what = when (o.str("scope")) {
            "all" -> "everything in the catalogue"
            "category" -> "our " + (o["categories"] as JsonArray).joinToString(", ") { it.jsonPrimitive.content }
            else -> "selected items"
        }
        val end = LocalDate.parse(o.str("ends_on"))
        val month = end.month.getDisplayName(java.time.format.TextStyle.FULL, java.util.Locale.ENGLISH)
        return "${o.str("name")} — ${o["percent"]}% off $what, until ${end.dayOfMonth} $month ${end.year}"
    }

    /** No offer declared yet (get_offer before anyone starts one). */
    fun noOffer(f: FakeNeema) =
        f.on("GET", "/admin/settings/offer", body = """{"campaign":null,"running":false,"says":"","max_percent":$OFFER_MAX_PERCENT}""")

    /** A stored offer whose end date has passed — parse() keeps it, it is not running, describe() is "". */
    fun expiredOffer(f: FakeNeema) = f.on(
        "GET", "/admin/settings/offer",
        body = """{"campaign":{"name":"Lent Offer","percent":15,"scope":"products","categories":[],"skus":["CS-BLK-16","STL-GRN","ZZ-UNKNOWN"],
          "starts_on":null,"ends_on":"2026-03-01"},"running":false,"says":"","max_percent":$OFFER_MAX_PERCENT}""",
    )
}
