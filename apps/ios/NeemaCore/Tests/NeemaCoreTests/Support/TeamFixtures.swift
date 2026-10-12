import Foundation
@testable import NeemaCore

/// Team / Profile data, built from what the API handlers actually return
/// (apps/api/app/routers/admin.py, roles.py). Each value cites its handler
/// (Android `TeamFixtures`).
///
/// Serialisation facts these follow: raw-SQL rows and ORM objects both go
/// through FastAPI's jsonable_encoder (UUIDs as strings, TIMESTAMPTZ as Python
/// isoformat with microseconds and "+00:00"); JSONB columns arrive decoded
/// (arrays or null); an ORM `Agent` returned bare (get_me, update_me,
/// create_agent) carries every mapped column — password_hash included — and
/// none of the custom-role columns; a write the database refuses (duplicate
/// email) is an unhandled IntegrityError: a 500 with a plain-text body.
///
/// The write routes re-implement each handler's validation, so tests exercise
/// the server's real answers — errors included.
enum TeamFixtures {
    static let AGENT4_ID = "a1000000-0000-0000-0000-000000000004"
    static let NEW_AGENT_ID = "a1000000-0000-0000-0000-000000000009"

    /// Python's `datetime.isoformat()` of an aware UTC timestamp, `minutesAgo` before the (pinned) clock.
    static func pyTs(_ minutesAgo: Int64) -> String { SalesFixtures.pyIso(AppClock.date().addingTimeInterval(-Double(minutesAgo) * 60)) }

    static let allPerms = [
        "view_conversations", "reply_conversations", "intercept_release", "close_conversations", "transfer_conversations",
        "add_notes", "view_orders", "manage_orders", "view_catalog", "manage_catalog", "view_leads", "manage_leads",
        "view_crm", "edit_crm", "view_analytics", "view_reports", "export_reports", "manage_agents", "manage_roles", "manage_settings",
    ]

    private static func arr(_ l: [String]) -> String { "[" + l.map { "\"\($0)\"" }.joined(separator: ",") + "]" }
    private static func q(_ s: String) -> String { JSONValue.string(s).text }

    // ── Roles ────────────────────────────────────────────────────────────────

    private static let supportPerms = Array(allPerms.prefix(14))
    private static let salesPerms = ["view_conversations", "reply_conversations", "view_orders", "manage_orders"]

    private static func role(_ id: String, _ name: String, _ desc: String, _ color: String, _ perms: [String], _ protected: Bool, _ minutesAgo: Int64) -> String {
        "{\"id\":\"\(id)\",\"name\":\"\(name)\",\"description\":\"\(desc)\",\"color\":\"\(color)\",\"permissions\":\(arr(perms)),\"protected\":\(protected),\"created_at\":\"\(pyTs(minutesAgo))\"}"
    }

    /// roles.py list_roles: `SELECT id, name, description, color, permissions,
    /// protected, created_at FROM custom_roles ORDER BY protected DESC, name`.
    /// super_admin / agent / viewer are main.py's seeds (super_admin is the only
    /// protected one); the rest were made in the role editor.
    static var roles: String {
        "[" + [
            role("super_admin", "Super Admin", "Full platform access — cannot be modified", "#7c3aed", allPerms, true, 60 * 24 * 400),
            role("agent", "Agent", "Handle conversations and orders", "#589b31",
                 ["view_conversations", "reply_conversations", "intercept_release", "close_conversations", "transfer_conversations",
                  "add_notes", "view_orders", "manage_orders", "view_catalog", "view_crm", "view_leads"], false, 60 * 24 * 400),
            role("sales", "Sales", "Handles conversations and orders", "#3b82f6", salesPerms, false, 60 * 24 * 90),
            role("support", "Support Lead", "Owns escalations, closes threads and keeps customer records tidy", "#0f766e", supportPerms, false, 60 * 24 * 40),
            role("trainee", "Trainee", "", "#7c3aed", [], false, 60 * 24 * 5),
            role("viewer", "Viewer", "Read-only access", "#699a32",
                 ["view_conversations", "view_orders", "view_catalog", "view_crm", "view_leads", "view_analytics"], false, 60 * 24 * 400),
        ].joined(separator: ",") + "]"
    }

    // ── Agents ───────────────────────────────────────────────────────────────

    /// admin.py list_agents: the agents row LEFT JOIN custom_roles —
    /// id, name, email, role, is_available, is_superuser, avatar_url,
    /// created_at, last_seen_at, active_convs (COALESCEd), custom_role_id,
    /// custom_permissions, role_name, role_color, role_permissions; ORDER BY name.
    static var agents: String { agentsWithMe() }

    /// The same list with the signed-in agent's own row changed — a plain agent
    /// whose power comes from `customPermissions` (limited-permission states).
    static func agentsWithMe(role: String = "admin", superuser: Bool = true, customPermissions: [String]? = nil,
                             customRole: (String, String, String)? = nil, rolePermissions: [String]? = nil) -> String {
        func opt(_ s: String?) -> String { s.map { "\"\($0)\"" } ?? "null" }
        return """
        [
          {"id":"\(Fixtures.AGENT3_ID)","name":"Brian Otieno","email":"brian@bethanyhouse.co.ke","role":"readonly","is_available":false,
           "is_superuser":false,"avatar_url":null,"created_at":"\(pyTs(60 * 24 * 30))","last_seen_at":"\(pyTs(60 * 26))","active_convs":0,
           "custom_role_id":null,"custom_permissions":null,"role_name":null,"role_color":null,"role_permissions":null},
          {"id":"\(Fixtures.AGENT2_ID)","name":"Grace Wanjiru","email":"grace@bethanyhouse.co.ke","role":"agent","is_available":true,
           "is_superuser":false,"avatar_url":null,"created_at":"\(pyTs(60 * 24 * 120))","last_seen_at":"\(pyTs(3))","active_convs":7,
           "custom_role_id":"sales","custom_permissions":null,"role_name":"Sales","role_color":"#3b82f6","role_permissions":\(arr(salesPerms))},
          {"id":"\(Fixtures.ME_ID)","name":"Moses Mwicigi","email":"moses@bethanyhouse.co.ke","role":"\(role)","is_available":true,
           "is_superuser":\(superuser),"avatar_url":null,"created_at":"\(pyTs(60 * 24 * 200))","last_seen_at":"\(pyTs(1))","active_convs":4,
           "custom_role_id":\(opt(customRole?.0)),"custom_permissions":\(customPermissions.map(arr) ?? "null"),
           "role_name":\(opt(customRole?.1)),"role_color":\(opt(customRole?.2)),
           "role_permissions":\(rolePermissions.map(arr) ?? "null")},
          {"id":"\(AGENT4_ID)","name":"Wanjiku Kamau-Ochieng Nyambura","email":"wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke","role":"agent",
           "is_available":false,"is_superuser":false,"avatar_url":null,"created_at":"\(pyTs(60 * 24 * 10))","last_seen_at":null,"active_convs":2,
           "custom_role_id":"support","custom_permissions":["view_conversations","reply_conversations","add_notes"],
           "role_name":"Support Lead","role_color":"#0f766e","role_permissions":\(arr(supportPerms))}
        ]
        """
    }

    /// admin.py get_me / update_me / create_agent return the ORM `Agent`:
    /// every mapped column (password_hash included — see the report), and no
    /// custom_role_id / custom_permissions / role_* keys.
    static func ormAgent(id: String = Fixtures.ME_ID, name: String = "Moses Mwicigi", email: String = "moses@bethanyhouse.co.ke",
                         role: String = "admin", available: Bool = true, superuser: Bool = true, activeConvs: Int = 4,
                         createdMinutesAgo: Int64 = 60 * 24 * 200, lastSeenMinutesAgo: Int64? = 1) -> String {
        let seen = lastSeenMinutesAgo.map { "\"\(pyTs($0))\"" } ?? "null"
        return "{\"id\":\"\(id)\",\"name\":\(q(name)),\"email\":\(q(email)),"
            + "\"password_hash\":\"$2b$12$Qm9ndXNIYXNoRm9yVGVzdHMuLi4uLi4uLi4uLi4uLi4uLi4uLi4u\",\"role\":\"\(role)\","
            + "\"is_available\":\(available),\"is_superuser\":\(superuser),\"active_convs\":\(activeConvs),\"avatar_url\":null,"
            + "\"created_at\":\"\(pyTs(createdMinutesAgo))\",\"last_seen_at\":\(seen)}"
    }

    static var me: String { ormAgent() }

    private static let agentIds = [Fixtures.ME_ID, Fixtures.AGENT2_ID, Fixtures.AGENT3_ID, AGENT4_ID]
    private static func rows(_ json: String) -> [[String: JSONValue]] { JSONValue.parse(json)?.arrayValue?.compactMap { $0.objectValue } ?? [] }
    private static func emails() -> [String] { rows(agents).compactMap { $0["email"]?.stringValue } }
    private static func emailOf(_ id: String) -> String? { rows(agents).first { $0["id"]?.stringValue == id }?["email"]?.stringValue }
    private static func roleIds() -> [String] { rows(roles).compactMap { $0["id"]?.stringValue } }
    private static func protectedRole(_ id: String) -> Bool? { rows(roles).first { $0["id"]?.stringValue == id }?["protected"]?.boolValue }
    private static func body(_ b: String?) -> [String: JSONValue] { JSONValue.parse(b ?? "{}")?.objectValue ?? [:] }
    private static func detail(_ s: String) -> String { "{\"detail\":\(q(s))}" }
    private static func lastSegment(_ path: String, back: Int = 0) -> String {
        let parts = path.split(separator: "/").map(String.init)
        return parts.count > back ? parts[parts.count - 1 - back] : ""
    }
    /// Starlette's answer to an unhandled exception (IntegrityError on agents.email).
    static let SERVER_ERROR = "Internal Server Error"

    static func install(_ f: FakeNeema) {
        f.on("GET", "/admin/roles", body: roles)
        f.on("GET", "/admin/agents", body: agents)
        f.on("GET", "/admin/me", body: me)
        writes(f)
    }

    /// Every Team / Profile write, answering as its handler does.
    static func writes(_ f: FakeNeema) {
        // admin.py create_agent: 422 "Missing required fields: …" when name/email/password is falsy;
        // a taken email violates agents.email UNIQUE → 500; else the refreshed ORM row.
        f.on("POST", "/admin/agents") { _, b in
            let j = body(b)
            let missing = ["name", "email", "password"].filter { (j[$0]?.stringValue ?? "").isEmpty }
            if !missing.isEmpty { return (422, detail("Missing required fields: \(missing.joined(separator: ", "))")) }
            if let e = j["email"]?.stringValue, emails().contains(e) { return (500, SERVER_ERROR) }
            if let r = j["role"]?.stringValue, !["admin", "agent", "readonly"].contains(r) { return (500, SERVER_ERROR) } // PgEnum(AgentRole)
            return (200, ormAgent(id: NEW_AGENT_ID, name: j["name"]?.stringValue ?? "", email: j["email"]?.stringValue ?? "",
                                  role: j["role"]?.stringValue ?? "agent", superuser: false, activeConvs: 0, createdMinutesAgo: 0, lastSeenMinutesAgo: nil))
        }
        // admin.py update_agent: 404 "Agent not found"; 422 for a short password; {"ok": true}.
        f.on("PATCH", "/admin/agents/[^/]+") { r, b in
            let id = lastSegment(r.path)
            let j = body(b)
            let pw = j["password"]?.stringValue ?? ""
            let email = j["email"]?.stringValue ?? ""
            if !agentIds.contains(id) { return (404, detail("Agent not found")) }
            if !pw.isEmpty && pw.count < 8 { return (422, detail("Password must be at least 8 characters")) }
            if !email.isEmpty && emails().filter({ $0 != emailOf(id) }).contains(email) { return (500, SERVER_ERROR) }
            return (200, #"{"ok":true}"#)
        }
        // admin.py assign_agent_role: 422 / 404s, then the joined row (no is_superuser, no role_permissions).
        f.on("PATCH", "/admin/agents/[^/]+/role") { r, b in
            let id = lastSegment(r.path, back: 1)
            let j = body(b)
            let roleId = j["custom_role_id"]?.stringValue ?? ""
            if roleId.isEmpty { return (422, detail("custom_role_id is required")) }
            if !roleIds().contains(roleId) { return (404, detail("Role not found")) }
            if !agentIds.contains(id) { return (404, detail("Agent not found")) }
            let perms = j["custom_permissions"]?.text ?? "null"
            return (200, "{\"id\":\"\(id)\",\"name\":\"Brian Otieno\",\"email\":\"\(emailOf(id) ?? "")\",\"role\":\"readonly\",\"is_available\":false,"
                + "\"custom_role_id\":\"\(roleId)\",\"custom_permissions\":\(perms),\"role_name\":\"Sales\",\"role_color\":\"#3b82f6\"}")
        }
        // admin.py delete_agent: 404 "Agent not found"; {"ok": true}. No guard on self or the last admin.
        f.on("DELETE", "/admin/agents/[^/]+") { r, _ in
            agentIds.contains(lastSegment(r.path)) ? (200, #"{"ok":true}"#) : (404, detail("Agent not found"))
        }
        // admin.py update_me: sets whichever of name/email/password is present (no checks), returns the ORM row.
        f.on("PATCH", "/admin/me") { _, b in
            let j = body(b)
            if let e = j["email"]?.stringValue, emails().filter({ $0 != emailOf(Fixtures.ME_ID) }).contains(e) { return (500, SERVER_ERROR) }
            return (200, ormAgent(name: j["name"]?.stringValue ?? "Moses Mwicigi", email: j["email"]?.stringValue ?? "moses@bethanyhouse.co.ke"))
        }
        // roles.py create_role: 422 "name is required"; id = body id or role_<hex8>; upserts; returns the row.
        f.on("POST", "/admin/roles") { _, b in
            let j = body(b)
            if (j["name"]?.stringValue ?? "").isEmpty { return (422, detail("name is required")) }
            return (200, "{\"id\":\"\(j["id"]?.stringValue ?? "role_1a2b3c4d")\",\"name\":\(j["name"]!.text),\"description\":\(j["description"]?.text ?? "\"\""),"
                + "\"color\":\(j["color"]?.text ?? "\"#589b31\""),\"permissions\":\(j["permissions"]?.text ?? "[]"),\"protected\":false,\"created_at\":\"\(pyTs(0))\"}")
        }
        // roles.py update_role: 404 / 403 "Cannot modify a protected role"; the updated row.
        f.on("PATCH", "/admin/roles/[^/]+") { r, b in
            let id = lastSegment(r.path)
            let j = body(b)
            switch protectedRole(id) {
            case nil: return (404, detail("Role not found"))
            case true?: return (403, detail("Cannot modify a protected role"))
            default:
                return (200, "{\"id\":\"\(id)\",\"name\":\(j["name"]?.text ?? "\"Sales\""),\"description\":\(j["description"]?.text ?? "\"\"") ,"
                    + "\"color\":\(j["color"]?.text ?? "\"#3b82f6\""),\"permissions\":\(j["permissions"]?.text ?? "[]"),\"protected\":false,\"created_at\":\"\(pyTs(60 * 24 * 90))\"}")
            }
        }
        // roles.py delete_role: 404 / 403 "Cannot delete a protected role"; clears agents on it; {"ok": true}.
        f.on("DELETE", "/admin/roles/[^/]+") { r, _ in
            switch protectedRole(lastSegment(r.path)) {
            case nil: return (404, detail("Role not found"))
            case true?: return (403, detail("Cannot delete a protected role"))
            default: return (200, #"{"ok":true}"#)
            }
        }
    }

    // ── Settings (crm.py) ────────────────────────────────────────────────────

    /// app_settings.DIRECTIVES_MAX_CHARS
    static let DIRECTIVES_MAX = 600
    /// promotions.MAX_PERCENT
    static let OFFER_MAX_PERCENT = 70
    static let OFFER_422 = "a campaign needs a name, 1-70%, a scope with its categories or SKUs, and an end date (YYYY-MM-DD)"

    /// A running Easter offer, as promotions.parse stores it and describe() words it.
    static let easterCampaign = #"{"name":"Easter Sale","percent":10,"scope":"category","categories":["Vestments"],"skus":[],"starts_on":null,"ends_on":"2099-04-30"}"#
    static let EASTER_SAYS = "Easter Sale — 10% off our Vestments, until 30 April 2099"

    /// The calling settings as WhatsApp has them for the test number (routers/admin.py calls_get_settings).
    static let callingSettings = """
    {"status":"ENABLED","call_icon_visibility":"DEFAULT","callback_permission_status":"DISABLED","call_hours":null,
     "voicemail":{"status":"DISABLED","triggers":["TIMEOUT"],"timeout_seconds":15},"restrictions":[],
     "last_settings_event":null,"last_restriction_event":null}
    """
    /// The call-request template, approved (calls_permission_template).
    static let permissionTemplate = #"{"configured":true,"name":"neema_call_permission","language":"en","source":"app","waba_configured":true,"exists":true,"status":"approved","category":"UTILITY"}"#

    /// Two reports as client_crash_list answers them (newest first; `received_at` is the row's created_at isoformat).
    static var clientCrashes: String {
        """
        [{"id":"crash-7f3a","kind":"crash","at":"\(Fixtures.ago(42))","received_at":"\(pyTs(41))","agent_name":"Grace Wanjiru",
          "summary":"java.lang.IllegalStateException: Composer dropped its draft","trace":"java.lang.IllegalStateException: Composer dropped its draft\\n\\tat ke.co.bethanyhouse.neema.feature.inbox.Composer.send(Composer.kt:214)\\n\\tat android.os.Handler.handleCallback(Handler.java:958)",
          "thread":"main","app_version":"1.4.2","build":"142","device":"samsung SM-S918B","sdk":34},
         {"id":"anr-20c1","kind":"anr","at":"\(Fixtures.ago(60 * 26))","received_at":"\(pyTs(60 * 26 - 1))","agent_name":"Brian Otieno",
          "summary":"Input dispatching timed out (Waiting to send non-key event because the touched window has not finished processing certain input events)",
          "trace":"main (state=Blocked)\\n\\tat ke.co.bethanyhouse.neema.feature.orders.OrdersScreen(OrdersScreen.kt:88)",
          "thread":"main","app_version":"1.4.1","build":"141","device":"Tecno KI5k","sdk":31}]
        """
    }

    /// Every settings route as crm.py answers it. `admin` false makes the four
    /// PUTs refuse with 403 "Admin only", as they do for a non-admin caller.
    static func settings(_ f: FakeNeema, admin: Bool = true) {
        let directives = Ref("Always offer free delivery within Nairobi on orders above KES 10,000.")
        // crm.py get_operator_directives: {"directives", "max_chars"}.
        f.on("GET", "/admin/settings/directives") { _, _ in (200, "{\"directives\":\(q(directives.value)),\"max_chars\":\(DIRECTIVES_MAX)}") }
        // put_operator_directives → set_directives: str(body.directives or "").strip()[:600]; never 413/422.
        f.on("PUT", "/admin/settings/directives") { _, b in
            if !admin { return (403, detail("Admin only")) }
            let v = String((body(b)["directives"]?.stringValue ?? "").trimmingCharacters(in: .whitespacesAndNewlines).prefix(DIRECTIVES_MAX))
            directives.value = v
            return (200, "{\"ok\":true,\"directives\":\(q(v))}")
        }

        let stages = Ref(["measuring"])
        // get_pipeline_stages: {"stages": [...]}
        f.on("GET", "/admin/settings/pipeline-stages") { _, _ in (200, "{\"stages\":\(arr(stages.value))}") }
        // put_pipeline_stages: 403; 422 "stages must be a list"; clean (trim, [:18], drop blanks,
        // built-ins and case-insensitive repeats); 422 "At most 4 custom stages"; {"ok", "stages"}.
        f.on("PUT", "/admin/settings/pipeline-stages") { _, b in
            if !admin { return (403, detail("Admin only")) }
            guard let raw = body(b)["stages"]?.arrayValue else { return (422, detail("stages must be a list")) }
            let canonical: Set<String> = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]
            var cleaned: [String] = []
            for s in raw {
                let label = String((s.content ?? "").trimmingCharacters(in: .whitespacesAndNewlines).prefix(18))
                if !label.isEmpty && !canonical.contains(label.lowercased()) && !cleaned.contains(where: { $0.lowercased() == label.lowercased() }) { cleaned.append(label) }
            }
            if cleaned.count > 4 { return (422, detail("At most 4 custom stages")) }
            stages.value = cleaned
            return (200, "{\"ok\":true,\"stages\":\(arr(cleaned))}")
        }

        let enabled = Ref(true)
        // get_translation_setting: spend is round(float, 4) — a JSON number, never a Decimal string.
        f.on("GET", "/admin/settings/translation") { _, _ in (200, "{\"enabled\":\(enabled.value),\"default\":false,\"spend_30d_usd\":3.4187,\"calls_30d\":812}") }
        // put_translation_setting: 403; 422 unless enabled is a JSON bool; {"ok", "enabled"}.
        f.on("PUT", "/admin/settings/translation") { _, b in
            if !admin { return (403, detail("Admin only")) }
            guard case .bool(let e)? = body(b)["enabled"] else { return (422, detail("enabled must be true or false")) }
            enabled.value = e
            return (200, "{\"ok\":true,\"enabled\":\(e)}")
        }

        let campaign = Ref<String?>(easterCampaign)
        // get_offer: {"campaign": parse(stored) or null, "running", "says": describe(live), "max_percent": 70}.
        f.on("GET", "/admin/settings/offer") { _, _ in (200, offerBody(campaign.value)) }
        // put_offer: 403; set_campaign → parse or 422 (ValueError text); {"ok", "campaign", "running", "says"}.
        f.on("PUT", "/admin/settings/offer") { _, b in
            if !admin { return (403, detail("Admin only")) }
            let c = body(b)["campaign"]
            if c == nil || c?.isNull == true {
                campaign.value = nil
                return (200, #"{"ok":true,"campaign":null,"running":false,"says":""}"#)
            }
            guard let parsed = parseCampaign(c!) else { return (422, detail(OFFER_422)) }
            campaign.value = parsed
            let running = isRunning(parsed)
            return (200, "{\"ok\":true,\"campaign\":\(parsed),\"running\":\(running),\"says\":\(q(running ? describe(parsed) : ""))}")
        }
        // routers/admin.py calls_get_settings / calls_permission_template (manage_settings): WhatsApp's
        // calling settings as the number has them, and the call-request template waiting for review.
        f.on("GET", "/admin/calls/settings", body: callingSettings)
        f.on("GET", "/admin/calls/permission-template", body: permissionTemplate)
        // admin.py client_crash_list (manage_settings): the phones' crash reports, newest first.
        f.on("GET", "/admin/client-crashes", body: clientCrashes)
    }

    private static func offerBody(_ c: String?) -> String {
        let running = c.map(isRunning) ?? false
        return "{\"campaign\":\(c ?? "null"),\"running\":\(running),\"says\":\(q(running ? describe(c!) : "")),\"max_percent\":\(OFFER_MAX_PERCENT)}"
    }

    /// promotions.parse, for the fake: the normalised campaign JSON, or nil when it would 422.
    private static func parseCampaign(_ el: JSONValue) -> String? {
        guard let c = el.objectValue else { return nil }
        let name = String((c["name"]?.stringValue ?? "").trimmingCharacters(in: .whitespacesAndNewlines).prefix(60))
        guard let pct = c["percent"]?.lenientDouble else { return nil }
        let percent = Int(pct)   // int(percent)
        if name.isEmpty || !(1...OFFER_MAX_PERCENT).contains(percent) { return nil }
        let scope = (c["scope"]?.stringValue ?? "all").trimmingCharacters(in: .whitespaces).lowercased()
        if !["all", "category", "products"].contains(scope) { return nil }
        func clean(_ k: String) -> [String] {
            var out: [String] = []
            for v in c[k]?.arrayValue ?? [] {
                let s = (v.stringValue ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                if !s.isEmpty && !out.contains(where: { $0.lowercased() == s.lowercased() }) { out.append(s) }
            }
            return Array(out.prefix(60))
        }
        let cats = clean("categories"), skus = clean("skus")
        if (scope == "category" && cats.isEmpty) || (scope == "products" && skus.isEmpty) { return nil }
        guard let ends = parseIsoDate(c["ends_on"]?.stringValue) else { return nil }
        let starts = parseIsoDate(c["starts_on"]?.stringValue)
        return "{\"name\":\(q(name)),\"percent\":\(percent),\"scope\":\"\(scope)\",\"categories\":\(arr(cats)),\"skus\":\(arr(skus)),"
            + "\"starts_on\":\(starts.map { "\"\($0)\"" } ?? "null"),\"ends_on\":\"\(ends)\"}"
    }

    private static func obj(_ c: String) -> [String: JSONValue] { JSONValue.parse(c)?.objectValue ?? [:] }

    /// promotions.is_running by the SERVER's calendar — the real date in UTC, not the app's pinned clock.
    private static func isRunning(_ c: String) -> Bool {
        let o = obj(c)
        let today = LocalDay.of(millis: Int64(Date().timeIntervalSince1970 * 1000), zone: TimeZone(identifier: "UTC")!)
        if let s = o["starts_on"]?.stringValue, let starts = LocalDay.parse(s), today < starts { return false }
        guard let ends = LocalDay.parse(o["ends_on"]?.stringValue ?? "") else { return false }
        return !(ends < today)
    }

    private static let MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    /// promotions.describe
    private static func describe(_ c: String) -> String {
        let o = obj(c)
        let what: String
        switch o["scope"]?.stringValue {
        case "all": what = "everything in the catalogue"
        case "category": what = "our " + (o["categories"]?.arrayValue ?? []).compactMap { $0.stringValue }.joined(separator: ", ")
        default: what = "selected items"
        }
        let end = LocalDay.parse(o["ends_on"]?.stringValue ?? "") ?? LocalDay(2099, 1, 1)
        let pct = Int(o["percent"]?.lenientDouble ?? 0)
        return "\(o["name"]?.stringValue ?? "") — \(pct)% off \(what), until \(end.day) \(MONTHS[end.month - 1]) \(end.year)"
    }

    /// No offer declared yet (get_offer before anyone starts one).
    static func noOffer(_ f: FakeNeema) {
        f.on("GET", "/admin/settings/offer", body: "{\"campaign\":null,\"running\":false,\"says\":\"\",\"max_percent\":\(OFFER_MAX_PERCENT)}")
    }

    /// A stored offer whose end date has passed — parse() keeps it, it is not running, describe() is "".
    static func expiredOffer(_ f: FakeNeema) {
        f.on("GET", "/admin/settings/offer", body: """
        {"campaign":{"name":"Lent Offer","percent":15,"scope":"products","categories":[],"skus":["CS-BLK-16","STL-GRN","ZZ-UNKNOWN"],
          "starts_on":null,"ends_on":"2026-03-01"},"running":false,"says":"","max_percent":\(OFFER_MAX_PERCENT)}
        """)
    }
}
