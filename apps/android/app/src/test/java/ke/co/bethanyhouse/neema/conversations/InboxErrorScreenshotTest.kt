package ke.co.bethanyhouse.neema.conversations

import android.net.Uri
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
import ke.co.bethanyhouse.neema.feature.conversations.*
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.offline
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.timeout
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 5: what the inbox looks like when the network lets the agent down —
 * a reply still being confirmed, one that didn't go (Retry / Edit), a note
 * that didn't save, a file left in the tray with its reason, the list and the
 * thread failing with a plain reason, and an older page that needs a tap.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxErrorScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false, maxPercentDifference = 0.1)

    private val sched = TestCoroutineScheduler()

    @Before fun setUp() { Dispatchers.setMain(UnconfinedTestDispatcher(sched)) }
    @After fun tearDown() = Dispatchers.resetMain()

    private class Owner : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }
    private class Screen(val fake: FakeNeema, val server: InboxNetFixtures.Server, val dash: DashboardViewModel, val vm: ConversationsViewModel, val owner: ViewModelStoreOwner)

    private fun screen(setup: FakeNeema.(InboxNetFixtures.Server) -> Unit = {}): Screen {
        val fake = FakeNeema.withFixtures().also(InboxFixtures::install)
        val server = InboxNetFixtures.Server(fake)
        fake.setup(server)
        val dash = dashboard(paparazzi.context, fake)
        val owner = Owner()
        val vm = ViewModelProvider.create(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class]
        return Screen(fake, server, dash, vm, owner)
    }

    private fun Screen.snap(dark: Boolean = false) = paparazzi.snapshot {
        AppFrame(dark) { CompositionLocalProvider(LocalViewModelStoreOwner provides owner) { ConversationsScreen(dash) } }
    }

    private fun idle(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }

    /**
     * Peter's thread after a bad minute: one reply still being confirmed
     * ("Sending…"), one the server never got ("Not sent" + Retry / Edit), and
     * a note that didn't save.
     */
    private fun sendTrouble(): Screen = screen {
        on("POST", "/admin/conversations/c1/note") { _, _ -> timeout() }
    }.apply {
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> timeout() }
        vm.select("c1")
        vm.setReplyText("Yes Father — two black shirts, 16 inch. Delivery to Nyeri by Friday."); vm.sendReply()
        vm.showNote(true); vm.setNoteText("Wants delivery before the ordination on Saturday"); vm.saveNote()
        idle(31_000)
        vm.setReplyText("Shall I send the M-Pesa details?"); vm.sendReply()
    }

    @Test fun send_sendingAndNotSent() = sendTrouble().snap()
    @Test fun send_sendingAndNotSent_dark() = sendTrouble().snap(dark = true)

    @Test fun send_sendingAndNotSent_tablet() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        sendTrouble().snap()
    }

    /** A 150 MB video that timed out stays in the tray, captioned, with the reason and Retry. */
    private fun trayTrouble(): Screen = screen {
        on("POST", "/admin/conversations/c1/upload-media") { _, _ -> timeout() }
    }.apply {
        vm.select("c1")
        @Suppress("UNCHECKED_CAST")
        val comp = ConversationsViewModel::class.java.getDeclaredField("_composer").apply { isAccessible = true }.get(vm) as MutableStateFlow<ComposerUi>
        comp.value = comp.value.copy(media = listOf(
            PickedMedia("v1", Uri.parse("content://m/fitting.mp4"), "fitting.mp4", "video/mp4", 140L * 1024 * 1024, bytes = byteArrayOf(1), caption = "The fitting — sleeves too long?"),
        ))
        vm.sendMedia()
    }

    @Test fun tray_videoTimedOut() = trayTrouble().snap()
    @Test fun tray_videoTimedOut_dark() = trayTrouble().snap(dark = true)

    /** The thread couldn't load at all: what happened, in plain words, and Try again. */
    @Test fun thread_offline() = screen { it.threadDown = { offline() } }.apply { vm.select("c1") }.snap()
    @Test fun thread_offline_dark() = screen { it.threadDown = { offline() } }.apply { vm.select("c1") }.snap(dark = true)

    /** The older page failed: a tap retries (scrolling at the top can't ask again). */
    @Test fun thread_olderPageFailed() = screen {
        val short = "[" + listOf(
            InboxNetFixtures.row("s1", "Habari! Do you make clergy shirts?", sender = "user", direction = "inbound"),
            InboxNetFixtures.row("s2", "Habari Father! Yes 🙏 KES 3,500 in black.", sender = "ai"),
            InboxNetFixtures.row("s3", "16 inch, two black ones please", sender = "user", direction = "inbound"),
        ).joinToString(",") + "]"
        on("GET", "/admin/conversations/c1/messages") { r, _ -> if (r.url.queryParameter("before") != null) timeout() else 200 to short }
    }.apply {
        vm.select("c1")
        // A short thread that says there is more above, so the top of it is on screen.
        @Suppress("UNCHECKED_CAST")
        val t = ConversationsViewModel::class.java.getDeclaredField("_thread").apply { isAccessible = true }.get(vm) as MutableStateFlow<ThreadUi>
        t.value = t.value.copy(hasMore = t.value.hasMore + ("c1" to true))
        vm.loadOlder()
        check(vm.thread.value.olderError == "c1")
    }.snap()

    /** Saved rows on screen, the refresh failed: they stay, and a slim line says why with Retry. */
    private fun listStale(): Screen = screen().apply {
        fake.on("GET", "/admin/conversations") { _, _ -> offline() }
        vm.refresh()
    }

    @Test fun list_refreshFailed_rowsKept() = listStale().snap()
    @Test fun list_refreshFailed_rowsKept_dark() = listStale().snap(dark = true)

    /** Nothing to show and the server is down: the reason under Retry — never raw HTML. */
    @Test fun list_emptyServerDown() = screen {
        on("GET", "/admin/conversations", code = 503, body = "<html><body><h1>503 Service Unavailable</h1></body></html>")
    }.snap()

    /** The next page failed: the footer offers Retry instead of paging in a loop. */
    @Test fun list_moreFailed() = screen().apply {
        fake.on("GET", "/admin/conversations") { r, _ -> if (r.url.queryParameter("cursor") != null) offline() else 200 to InboxFixtures.page }
        vm.loadMore()
    }.snap()
}
