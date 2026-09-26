package ke.co.bethanyhouse.neema.feature.agents

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CustomRole
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.AppClock
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * What is typed and ticked in the Team screen's dialogs — AgentsView.tsx's
 * createForm, editForm, pwForm, assignRoleId and roleForm.
 *
 * Held by [AgentsViewModel], not by the dialogs, so it outlives a rotation
 * (and a save that is still on the wire when the phone turns), and is written
 * to the saved state by [save] so it comes back after Android restarts the
 * app — except the passwords, which are never written anywhere: after a
 * restart the password boxes are empty and the agent types them again.
 *
 * Opening a dialog resets its form exactly where the web does: Edit, Reset
 * Password, Assign Role and the role editor start from the row they open;
 * Add Agent keeps what was typed until an agent is created (the web never
 * clears createForm on Cancel).
 */
class TeamForms {
    // Add Agent
    var createName by mutableStateOf("")
    var createEmail by mutableStateOf("")
    /** Never saved. */
    var createPassword by mutableStateOf("")
    var createRole by mutableStateOf("agent")

    // Edit agent
    var editName by mutableStateOf("")
    var editEmail by mutableStateOf("")

    // Reset password — never saved.
    var password by mutableStateOf("")
    var confirm by mutableStateOf("")

    // Assign role
    var assignRole by mutableStateOf("")
    /** Per-agent override (agents.custom_permissions): off = exactly the role's permissions. */
    var assignOverride by mutableStateOf(false)
    var assignPerms by mutableStateOf<List<String>>(emptyList())

    // Role editor
    var roleName by mutableStateOf("")
    var roleDescription by mutableStateOf("")
    var roleColor by mutableStateOf(ROLE_COLORS[0])
    var rolePerms by mutableStateOf<List<String>>(emptyList())
    /**
     * One id per opened "New Role" editor: a retry after a timeout updates
     * the role the first attempt may have created instead of adding a twin.
     */
    var roleDraftId by mutableStateOf("role_${AppClock.now()}")

    fun resetCreate() {
        createName = ""; createEmail = ""; createPassword = ""; createRole = "agent"
    }

    fun openEdit(agent: Agent) { editName = agent.name; editEmail = agent.email }

    fun openPassword() { password = ""; confirm = "" }

    fun openAssign(agent: Agent, roles: List<CustomRole>) {
        assignRole = agent.customRoleId ?: ""
        assignOverride = agent.customPermissions != null
        assignPerms = agent.customPermissions ?: roles.find { it.id == agent.customRoleId }?.permissions ?: emptyList()
    }

    /** [editing] null = a new role. */
    fun openRole(editing: CustomRole?) {
        roleName = editing?.name ?: ""
        roleDescription = editing?.description ?: ""
        roleColor = editing?.color ?: ROLE_COLORS[0]
        rolePerms = editing?.permissions ?: emptyList()
        if (editing == null) roleDraftId = "role_${AppClock.now()}"
    }

    /** Everything but the passwords, as JSON. */
    fun save(): String = buildJsonObject {
        put("createName", createName); put("createEmail", createEmail); put("createRole", createRole)
        put("editName", editName); put("editEmail", editEmail)
        put("assignRole", assignRole); put("assignOverride", assignOverride)
        putJsonArray("assignPerms") { assignPerms.forEach { add(JsonPrimitive(it)) } }
        put("roleName", roleName); put("roleDescription", roleDescription); put("roleColor", roleColor)
        putJsonArray("rolePerms") { rolePerms.forEach { add(JsonPrimitive(it)) } }
        put("roleDraftId", roleDraftId)
    }.toString()

    fun restore(saved: String) {
        val o = runCatching { NeemaJson.parseToJsonElement(saved) as JsonObject }.getOrNull() ?: return
        fun s(k: String) = (o[k] as? JsonPrimitive)?.takeIf { it.isString }?.content
        fun list(k: String) = (o[k] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }
        s("createName")?.let { createName = it }
        s("createEmail")?.let { createEmail = it }
        s("createRole")?.let { createRole = it }
        s("editName")?.let { editName = it }
        s("editEmail")?.let { editEmail = it }
        s("assignRole")?.let { assignRole = it }
        (o["assignOverride"] as? JsonPrimitive)?.let { assignOverride = it.content == "true" }
        list("assignPerms")?.let { assignPerms = it }
        s("roleName")?.let { roleName = it }
        s("roleDescription")?.let { roleDescription = it }
        s("roleColor")?.let { roleColor = it }
        list("rolePerms")?.let { rolePerms = it }
        s("roleDraftId")?.let { roleDraftId = it }
    }
}
