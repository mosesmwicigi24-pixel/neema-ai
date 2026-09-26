package ke.co.bethanyhouse.neema.conversations

import androidx.compose.runtime.CompositionLocalProvider
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.android.resources.ScreenOrientation
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsScreen
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.feature.conversations.InboxMemory
import ke.co.bethanyhouse.neema.feature.conversations.MEMORY_KEY
import ke.co.bethanyhouse.neema.feature.conversations.SavedComposer
import ke.co.bethanyhouse.neema.feature.conversations.SavedMedia
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 9: the inbox as it comes back after Android killed the app — the
 * thread that was open, the half-typed reply, a reply that was still on its
 * way ("Saving…" while the server is asked), one held for sign-in, a file
 * whose read grant lapsed, and the list's search and filters.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxLifecycleScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false, maxPercentDifference = 0.1)

    private val sched = TestCoroutineScheduler()

    @Before fun setUp() { Dispatchers.setMain(UnconfinedTestDispatcher(sched)) }
    @After fun tearDown() = Dispatchers.resetMain()

    private class Owner : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }

    private fun vmIn(owner: Owner, dash: DashboardViewModel) =
        ViewModelProvider.create(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class]

    /** Work done in [before], the process killed (only what reached disk survives), and the app back. */
    private fun restored(fake: FakeNeema, before: (DashboardViewModel, ConversationsViewModel) -> Unit, edit: (InboxMemory) -> InboxMemory = { it }): Pair<DashboardViewModel, Owner> {
        val dash = dashboard(paparazzi.context, fake)
        val owner = Owner()
        before(dash, vmIn(owner, dash))
        dash.container.foreground.value = false
        val snaps = dash.container.snapshots
        val saved = snaps.read(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer())!!
        owner.viewModelStore.clear()
        snaps.write(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer(), edit(saved))
        val dash2 = DashboardViewModel(dash.container)
        val owner2 = Owner()
        vmIn(owner2, dash2)
        return dash2 to owner2
    }

    private fun snap(p: Pair<DashboardViewModel, Owner>, dark: Boolean = false) = paparazzi.snapshot {
        AppFrame(dark) { CompositionLocalProvider(LocalViewModelStoreOwner provides p.second) { ConversationsScreen(p.first) } }
    }

    private fun fake() = FakeNeema.withFixtures().also(InboxFixtures::install).also { InboxNetFixtures.Server(it) }

    private val lostFile: (InboxMemory) -> InboxMemory = { m ->
        m.copy(composers = m.composers + ("p:p1" to (m.composers["p:p1"] ?: SavedComposer()).copy(
            media = listOf(SavedMedia("content://com.android.providers.media.photopicker/gone/1", "purple-cassock.jpg", "image/jpeg", 120_000)),
        )))
    }

    /** The thread comes back with the reply still being checked, the next one half-typed, and a file to re-attach. */
    private fun midSend() = restored(fake().apply {
        on("POST", "/admin/conversations/c1/reply") { _, _ -> InboxNetFixtures.timeout() }
    }, { _, vm ->
        vm.select("c1")
        vm.setReplyText("Yes — Friday works. I'll confirm the courier"); vm.sendReply()
        vm.setReplyText("And the invoice is on its way")
    }, lostFile)

    @Test fun restored_phone_midSend_draftAndLostFile() = snap(midSend())

    @Test fun restored_phone_midSend_draftAndLostFile_dark() = snap(midSend(), dark = true)

    /** A reply the expired session refused, back after the kill: "Not sent" with Retry, never sent on its own. */
    @Test fun restored_phone_heldForSignIn() = snap(restored(fake().apply {
        on("POST", "/admin/conversations/c1/reply", code = 401, body = """{"detail":"Token expired"}""")
        on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
    }, { _, vm -> vm.select("c1"); vm.setReplyText("Delivery to Nyeri is KES 400"); vm.sendReply() }))

    /** The open note dialog and its text come back with its thread. */
    @Test fun restored_phone_noteDialog() = snap(restored(fake(), { _, vm ->
        vm.select("c1"); vm.showNote(true); vm.setNoteText("Repeat buyer — offer free delivery to Nyeri. Call after 5pm.")
    }))

    /** The list: the tab, the filter panel and the search as typed. */
    @Test fun restored_phone_listSearchAndFilters() = snap(restored(fake(), { _, vm ->
        vm.setTab("human"); vm.toggleFilters(); vm.setSearch("Kamau")
    }))

    private val tablet = DeviceConfig.NEXUS_10.copy(orientation = ScreenOrientation.LANDSCAPE)

    @Test fun restored_tablet_midSend() {
        paparazzi.unsafeUpdateConfig(deviceConfig = tablet)
        snap(midSend())
    }
}
