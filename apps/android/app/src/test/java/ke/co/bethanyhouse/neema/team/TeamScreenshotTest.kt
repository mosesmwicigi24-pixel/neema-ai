package ke.co.bethanyhouse.neema.team

import androidx.compose.runtime.CompositionLocalProvider
import ke.co.bethanyhouse.neema.feature.agents.AgentsScreen
import ke.co.bethanyhouse.neema.feature.agents.LocalTeamPreview
import ke.co.bethanyhouse.neema.feature.agents.TeamPreview
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Test

/** The Team screen (AgentsView.tsx) in every state: list, roles, each dialog, dark, tablet, limited. */
class TeamScreenshotTest : AreaShots() {
    private fun fake() = FakeNeema.withFixtures().also(TeamFixtures::install)

    private fun team(
        preview: TeamPreview = TeamPreview(),
        dark: Boolean = false,
        device: app.cash.paparazzi.DeviceConfig = Devices.PHONE,
        f: FakeNeema = fake(),
        role: String = "admin",
        superuser: Boolean = true,
    ) {
        val d = dash(f, role, superuser)
        shot(device, dark) { CompositionLocalProvider(LocalTeamPreview provides preview) { AgentsScreen(d) } }
    }

    // ── Lists ────────────────────────────────────────────────────────────────
    @Test fun agents() = team()
    @Test fun agentsScrolled() = team(TeamPreview(scrollItem = 4))
    @Test fun agentsDark() = team(dark = true)
    @Test fun agentsDarkScrolled() = team(TeamPreview(scrollItem = 4), dark = true)
    @Test fun agentsTablet() = team(device = Devices.TABLET)
    @Test fun agentsTabletDark() = team(device = Devices.TABLET, dark = true)
    /** Two columns (a tablet held upright): each row's cards share one height and their footers line up. */
    @Test fun agentsTabletPortrait() = team(device = Devices.TABLET_PORTRAIT)
    @Test fun agentsTabletPortraitDark() = team(device = Devices.TABLET_PORTRAIT, dark = true)
    @Test fun agentsEmpty() =team(f = fake().also { it.on("GET", "/admin/agents", body = "[]") })
    @Test fun roles() = team(TeamPreview(tab = "roles"))
    @Test fun rolesScrolled() = team(TeamPreview(tab = "roles", scrollItem = 4))
    @Test fun rolesDark() = team(TeamPreview(tab = "roles"), dark = true)
    @Test fun rolesTablet() = team(TeamPreview(tab = "roles"), device = Devices.TABLET)
    @Test fun rolesFailedToLoad() = team(TeamPreview(tab = "roles"), f = fake().also { it.on("GET", "/admin/roles", code = 500, body = "{}") })

    // ── Limited permissions ──────────────────────────────────────────────────
    /** manage_agents without manage_roles: agents only, no Roles tab. */
    @Test fun agentsWithoutManageRoles() = team(
        f = fake().also {
            it.on("GET", "/admin/agents", body = TeamFixtures.agents.replace(
                "\"is_superuser\":true", "\"is_superuser\":false").replaceFirst(
                "\"custom_permissions\":null", "\"custom_permissions\":[\"view_conversations\",\"manage_agents\"]"))
        },
        role = "agent", superuser = false,
    )

    @Test fun noAccess() = team(
        f = fake().also {
            it.on("GET", "/admin/agents", body = TeamFixtures.agents.replace(
                "\"is_superuser\":true", "\"is_superuser\":false").replaceFirst(
                "\"custom_permissions\":null", "\"custom_permissions\":[\"view_conversations\"]"))
        },
        role = "agent", superuser = false,
    )

    // ── Dialogs ──────────────────────────────────────────────────────────────
    @Test fun addAgent() = team(TeamPreview(dialog = "create",
        typed = mapOf("name" to "Jane Doe", "email" to "jane@bethanyhouse.co.ke", "password" to "s3cretpass")))
    @Test fun addAgentDark() = team(TeamPreview(dialog = "create"), dark = true)
    @Test fun editAgent() = team(TeamPreview(dialog = "edit:${Fixtures.AGENT2_ID}"))
    @Test fun resetPasswordMismatch() = team(TeamPreview(dialog = "pw:${Fixtures.AGENT3_ID}",
        typed = mapOf("password" to "newpassword", "confirm" to "newpasswrd")))
    @Test fun resetPasswordDark() = team(TeamPreview(dialog = "pw:${Fixtures.AGENT3_ID}"), dark = true)
    @Test fun assignRole() = team(TeamPreview(dialog = "assign:${Fixtures.AGENT2_ID}"))
    @Test fun assignRoleWithOverride() = team(TeamPreview(dialog = "assign:${TeamFixtures.AGENT4_ID}"), device = Devices.PHONE)
    @Test fun assignRoleWithOverrideDark() = team(TeamPreview(dialog = "assign:${TeamFixtures.AGENT4_ID}"), dark = true)
    @Test fun assignRoleTablet() = team(TeamPreview(dialog = "assign:${TeamFixtures.AGENT4_ID}"), device = Devices.TABLET)
    @Test fun removeAgent() = team(TeamPreview(dialog = "del:${Fixtures.AGENT3_ID}"))
    @Test fun newRole() = team(TeamPreview(tab = "roles", dialog = "role:create"))
    @Test fun editRole() = team(TeamPreview(tab = "roles", dialog = "role:support"), device = Devices.tallPhone(3400))
    @Test fun editRoleDark() = team(TeamPreview(tab = "roles", dialog = "role:support"), dark = true)
    @Test fun editRoleTablet() = team(TeamPreview(tab = "roles", dialog = "role:support"), device = Devices.TABLET)
    @Test fun deleteRole() = team(TeamPreview(tab = "roles", dialog = "delrole:sales"))
}
