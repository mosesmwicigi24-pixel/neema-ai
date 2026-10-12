import Foundation

/// The team calls whose replies the core API types too tightly:
/// `PATCH /admin/agents/{id}` answers `{"ok": true}`, and role assignment
/// takes an optional `custom_permissions` override.
public final class TeamApi {
    public let http: NeemaHTTP
    public init(http: NeemaHTTP) { self.http = http }

    /// Name / email / password / role / is_available — whichever keys `body` carries.
    public func updateAgent(id: String, body: JSONValue) async throws -> OkResponse { try await http.patch("/admin/agents/\(id)", body) }

    public func setAvailable(id: String, available: Bool) async throws -> OkResponse {
        try await updateAgent(id: id, body: .object(["is_available": .bool(available)]))
    }

    /// Give `agentId` a custom role. `customPermissions` = nil clears any per-agent override; a list (even empty) replaces the role's set.
    /// The server answers the agent's joined row; nothing in it is read (the list is refetched), so any JSON object counts as success.
    public func assignRole(agentId: String, roleId: String, customPermissions: [String]?) async throws -> JSONValue {
        var o: [String: JSONValue] = ["custom_role_id": .string(roleId)]
        if let p = customPermissions { o["custom_permissions"] = .array(p.map { .string($0) }) }
        return try await http.patch("/admin/agents/\(agentId)/role", JSONValue.object(o))
    }
}
