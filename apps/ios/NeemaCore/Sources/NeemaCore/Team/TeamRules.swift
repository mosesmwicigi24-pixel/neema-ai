import Foundation

/// One grantable permission, as the role editor and the profile list show it.
public struct PermissionDef: Equatable, Sendable, Identifiable {
    public let key: String
    public let label: String
    public let group: String
    public var id: String { key }
    public init(_ key: String, _ label: String, _ group: String) { self.key = key; self.label = label; self.group = group }
}

/// The web's ALL_PERMISSIONS (AgentsView.tsx / ProfileView.tsx) — same keys,
/// labels, order and groups. Keys match custom_roles.permissions in the DB.
public enum PermissionCatalog {
    public static let ALL: [PermissionDef] = [
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
    ]

    public static let GROUPS: [String] = {
        var seen = Set<String>()
        return ALL.map { $0.group }.filter { seen.insert($0).inserted }
    }()

    public static func inGroup(_ group: String) -> [PermissionDef] { ALL.filter { $0.group == group } }

    public static func label(_ key: String) -> String? { ALL.first { $0.key == key }?.label }
}

/// The role editor's swatches (ROLE_COLORS).
public let ROLE_COLORS = [
    "#589b31", "#427425", "#699a32", "#2a48a2", "#1f367a", "#3d528f",
    "#717425", "#979a32", "#7c3aed", "#0891b2", "#0f766e", "#b45309",
]

/// The users table only knows admin / agent / readonly (toDbRole in the web).
public func toDbRole(_ roleId: String) -> String {
    switch roleId {
    case "admin", "agent", "readonly": return roleId
    case "super_admin": return "admin"
    case "viewer": return "readonly"
    default: return "agent"
    }
}

/// What reads on a fill: white, or the brand's deep ink.
public enum ContentTone: Equatable, Sendable { case white, ink }

/// Colour maths the Team / Profile screens use to stay legible (WCAG relative luminance).
public enum TeamColors {
    /// The brand ink the pale fills take (#1c2917).
    public static let INK: UInt32 = 0x1C2917

    /// "#589b31" → 0x589b31; nil for anything unparseable.
    public static func rgb(_ hex: String?) -> UInt32? {
        guard let h = hex?.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
        let digits = h.hasPrefix("#") ? String(h.dropFirst()) : h
        guard digits.count == 6, let v = UInt32(digits, radix: 16) else { return nil }
        return v
    }

    public static func luminance(_ rgb: UInt32) -> Double {
        func channel(_ c: UInt32) -> Double {
            let s = Double(c) / 255
            return s <= 0.03928 ? s / 12.92 : pow((s + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * channel((rgb >> 16) & 0xFF) + 0.7152 * channel((rgb >> 8) & 0xFF) + 0.0722 * channel(rgb & 0xFF)
    }

    public static func contrast(_ a: UInt32, _ b: UInt32) -> Double {
        let la = luminance(a), lb = luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }

    /// Whichever of white or the brand text colour reads better on `fill` (a role colour, say).
    /// White stays unless it falls under 3:1 — the role chips are the web's white-on-colour.
    public static func contentOn(_ fill: UInt32) -> ContentTone {
        let white = contrast(0xFFFFFF, fill)
        return (white >= 3 || white >= contrast(INK, fill)) ? .white : .ink
    }

    /// `contentOn` for a hex string; an unparseable fill reads as the brand green's white.
    public static func contentOn(hex: String?) -> ContentTone { contentOn(rgb(hex) ?? 0x589B31) }
}

/// The role editor's form (roleForm in the web).
public struct RoleForm: Equatable, Sendable {
    public var name: String
    public var description: String
    public var color: String
    public var permissions: [String]
    /// A new role's id, fixed when its editor opens. roles.py create_role
    /// upserts by id, so re-sending after a timeout updates the role the first
    /// try may have made instead of adding a twin.
    public var id: String?
    public init(name: String = "", description: String = "", color: String = ROLE_COLORS[0], permissions: [String] = [], id: String? = nil) {
        self.name = name; self.description = description; self.color = color; self.permissions = permissions; self.id = id
    }
}

/// What a write that got no answer says when it can't tell whether it landed.
public let UNCERTAIN_SAVE = "No answer from the server, so this may not have saved — what you typed is kept. Check your connection and try again."

/// The availability switch's failure: the web's words, unless the phone is offline or signed out.
public func availabilityFailure(_ e: Error) -> String {
    switch FriendlyErrors.httpStatus(e) {
    case 0, 401, 429: return FriendlyErrors.text(of: e)
    default: return "Failed to update availability"
    }
}

/// What is typed and ticked in the Team screen's dialogs — AgentsView.tsx's
/// createForm, editForm, pwForm, assignRoleId and roleForm.
///
/// Held by the model, not by the dialogs, so it outlives a rotation (and a
/// save that is still on the wire when the phone turns), and is written to
/// the scene state by `save` so it comes back after the system restarts the
/// app — except the passwords, which are never written anywhere.
///
/// Opening a dialog resets its form exactly where the web does: Edit, Reset
/// Password, Assign Role and the role editor start from the row they open;
/// Add Agent keeps what was typed until an agent is created (the web never
/// clears createForm on Cancel).
public struct TeamForms: Equatable, Sendable {
    // Add Agent
    public var createName = ""
    public var createEmail = ""
    /// Never saved.
    public var createPassword = ""
    public var createRole = "agent"

    // Edit agent
    public var editName = ""
    public var editEmail = ""

    // Reset password — never saved.
    public var password = ""
    public var confirm = ""

    // Assign role
    public var assignRole = ""
    /// Per-agent override (agents.custom_permissions): off = exactly the role's permissions.
    public var assignOverride = false
    public var assignPerms: [String] = []

    // Role editor
    public var roleName = ""
    public var roleDescription = ""
    public var roleColor = ROLE_COLORS[0]
    public var rolePerms: [String] = []
    /// One id per opened "New Role" editor: a retry after a timeout updates
    /// the role the first attempt may have created instead of adding a twin.
    public var roleDraftId = "role_\(AppClock.now())"

    public init() {}

    public mutating func resetCreate() {
        createName = ""; createEmail = ""; createPassword = ""; createRole = "agent"
    }

    public mutating func openEdit(_ agent: Agent) { editName = agent.name; editEmail = agent.email }

    public mutating func openPassword() { password = ""; confirm = "" }

    public mutating func openAssign(_ agent: Agent, roles: [CustomRole]) {
        assignRole = agent.customRoleId ?? ""
        assignOverride = agent.customPermissions != nil
        assignPerms = agent.customPermissions ?? roles.first { $0.id == agent.customRoleId }?.permissions ?? []
    }

    /// `editing` nil = a new role.
    public mutating func openRole(_ editing: CustomRole?) {
        roleName = editing?.name ?? ""
        roleDescription = editing?.description ?? ""
        roleColor = editing?.color ?? ROLE_COLORS[0]
        rolePerms = editing?.permissions ?? []
        if editing == nil { roleDraftId = "role_\(AppClock.now())" }
    }

    /// The role editor's form as it is typed.
    public var roleForm: RoleForm { RoleForm(name: roleName, description: roleDescription, color: roleColor, permissions: rolePerms, id: roleDraftId) }

    /// Everything but the passwords, as JSON.
    public func save() -> String {
        JSONValue.object([
            "createName": .string(createName), "createEmail": .string(createEmail), "createRole": .string(createRole),
            "editName": .string(editName), "editEmail": .string(editEmail),
            "assignRole": .string(assignRole), "assignOverride": .bool(assignOverride),
            "assignPerms": .array(assignPerms.map { .string($0) }),
            "roleName": .string(roleName), "roleDescription": .string(roleDescription), "roleColor": .string(roleColor),
            "rolePerms": .array(rolePerms.map { .string($0) }),
            "roleDraftId": .string(roleDraftId),
        ]).text
    }

    public mutating func restore(_ saved: String) {
        guard let o = JSONValue.parse(saved)?.objectValue else { return }
        func s(_ k: String) -> String? { o[k]?.stringValue }
        func list(_ k: String) -> [String]? { o[k]?.arrayValue?.compactMap { $0.stringValue } }
        if let v = s("createName") { createName = v }
        if let v = s("createEmail") { createEmail = v }
        if let v = s("createRole") { createRole = v }
        if let v = s("editName") { editName = v }
        if let v = s("editEmail") { editEmail = v }
        if let v = s("assignRole") { assignRole = v }
        if let v = o["assignOverride"]?.boolValue { assignOverride = v }
        if let v = list("assignPerms") { assignPerms = v }
        if let v = s("roleName") { roleName = v }
        if let v = s("roleDescription") { roleDescription = v }
        if let v = s("roleColor") { roleColor = v }
        if let v = list("rolePerms") { rolePerms = v }
        if let v = s("roleDraftId") { roleDraftId = v }
    }
}
