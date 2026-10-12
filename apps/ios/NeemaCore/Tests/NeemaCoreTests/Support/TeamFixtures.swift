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
}
