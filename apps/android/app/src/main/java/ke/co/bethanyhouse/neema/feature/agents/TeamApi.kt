package ke.co.bethanyhouse.neema.feature.agents

import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.model.RoleAssignResponse
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * The team calls whose replies the core API types too tightly.
 *
 * `PATCH /admin/agents/{id}` answers `{"ok": true}` (admin.py update_agent),
 * not an agent row, so decoding it as `Agent` (as `NeemaApi.agents.update` /
 * `setAvailable` do) would throw on every successful save. And role
 * assignment accepts an optional `custom_permissions` override that the core
 * call doesn't expose. Both live here, on the shared HTTP client.
 */
class TeamApi(private val http: NeemaHttp) {

    /** Name / email / password / role / is_available — whichever keys [body] carries. */
    suspend fun updateAgent(id: String, body: JsonObject): OkResponse = http.patch("/admin/agents/$id", body)

    suspend fun setAvailable(id: String, available: Boolean): OkResponse =
        updateAgent(id, buildJsonObject { put("is_available", available) })

    /**
     * Give [agentId] a custom role. [customPermissions] = null clears any
     * per-agent override (the server writes NULL), so the agent gets exactly
     * the role's permissions — which is what the web's Assign button does.
     */
    suspend fun assignRole(agentId: String, roleId: String, customPermissions: List<String>?): RoleAssignResponse =
        http.patch("/admin/agents/$agentId/role", buildJsonObject {
            put("custom_role_id", roleId)
            if (customPermissions != null) {
                putJsonArray("custom_permissions") { customPermissions.forEach { add(JsonPrimitive(it)) } }
            }
        })
}
