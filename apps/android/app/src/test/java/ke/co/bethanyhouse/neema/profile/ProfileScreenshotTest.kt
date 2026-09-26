package ke.co.bethanyhouse.neema.profile

import androidx.compose.runtime.CompositionLocalProvider
import app.cash.paparazzi.DeviceConfig
import ke.co.bethanyhouse.neema.feature.profile.LocalProfilePreview
import ke.co.bethanyhouse.neema.feature.profile.ProfilePreview
import ke.co.bethanyhouse.neema.feature.profile.ProfileScreen
import ke.co.bethanyhouse.neema.team.AreaShots
import ke.co.bethanyhouse.neema.team.Devices
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Test

/** Profile (ProfileView.tsx + the account menu and Android device settings) in every state, a screen at a time. */
class ProfileScreenshotTest : AreaShots() {
    private fun profile(
        preview: ProfilePreview = ProfilePreview(),
        dark: Boolean = false,
        device: DeviceConfig = Devices.PHONE,
        f: FakeNeema = FakeNeema.withFixtures().also(TeamFixtures::install),
        role: String = "admin",
        superuser: Boolean = true,
    ) {
        val d = dash(f, role, superuser)
        d.setDark(dark)
        shot(device, dark) { CompositionLocalProvider(LocalProfilePreview provides preview) { ProfileScreen(d) } }
    }

    @Test fun view_0() = profile()
    @Test fun view_1() = profile(ProfilePreview(scroll = 2100))
    @Test fun view_2() = profile(ProfilePreview(scroll = 4200))
    @Test fun viewDark_0() = profile(dark = true)
    @Test fun viewDark_1() = profile(ProfilePreview(scroll = 2100), dark = true)
    @Test fun viewDark_2() = profile(ProfilePreview(scroll = 4200), dark = true)
    @Test fun viewTablet_0() = profile(device = Devices.TABLET)
    @Test fun viewTablet_1() = profile(ProfilePreview(scroll = 1600), device = Devices.TABLET)
    @Test fun editing() = profile(ProfilePreview(editMode = true))
    @Test fun editingDark() = profile(ProfilePreview(editMode = true), dark = true)
    @Test fun changingPassword() = profile(ProfilePreview(changingPassword = true, scroll = 900,
        typed = mapOf("password" to "newpassword", "confirm" to "newpassword")))
    @Test fun signOutConfirm() = profile(ProfilePreview(confirmSignOut = true))
    @Test fun signOutConfirmDark() = profile(ProfilePreview(confirmSignOut = true), dark = true)

    /** A plain agent on a custom role, away: fewer permissions; the Settings link stays (Sidebar.tsx shows it to all). */
    private val limited get() = FakeNeema.withFixtures().also(TeamFixtures::install).also {
        // /admin/me is the bare agent row (no role join), exactly as admin.py get_me returns it.
        it.on("GET", "/admin/me", body = """{"id":"${Fixtures.AGENT2_ID}","name":"Grace Wanjiru","email":"grace@bethanyhouse.co.ke",
            "role":"agent","is_available":false,"is_superuser":false,"active_convs":7,"avatar_url":null,
            "created_at":"${Fixtures.ago(60 * 24 * 120)}","last_seen_at":"${Fixtures.ago(3)}","custom_role_id":"sales","custom_permissions":null}""")
        it.on("GET", "/admin/agents", body = TeamFixtures.agents.replace(
            "\"email\":\"grace@bethanyhouse.co.ke\",\"role\":\"agent\",\"is_available\":true",
            "\"email\":\"grace@bethanyhouse.co.ke\",\"role\":\"agent\",\"is_available\":false"))
    }
    @Test fun limitedAgent_0() = profile(f = limited, role = "agent", superuser = false)
    @Test fun limitedAgent_2() = profile(ProfilePreview(scroll = 4200), f = limited, role = "agent", superuser = false)

    /** Legacy readonly, no custom role: the legacy readonly permissions ticked (getAgentPermissions' fallback). */
    private val readonly get() = FakeNeema.withFixtures().also(TeamFixtures::install).also {
        it.on("GET", "/admin/me", body = TeamFixtures.ormAgent(role = "readonly", superuser = false))
        it.on("GET", "/admin/agents", body = TeamFixtures.agentsWithMe("readonly", false))
    }
    @Test fun personaReadonly_0() = profile(f = readonly, role = "readonly", superuser = false)
    @Test fun personaReadonly_2() = profile(ProfilePreview(scroll = 4200), f = readonly, role = "readonly", superuser = false)

    /** /me and the team both failed: the reason and a Retry, never "Loading profile…" forever. */
    @Test fun loading() = profile(
        f = FakeNeema.withFixtures().also {
            it.on("GET", "/admin/me", code = 500, body = "{}")
            it.on("GET", "/admin/agents", code = 500, body = "{}")
        },
    )
}
