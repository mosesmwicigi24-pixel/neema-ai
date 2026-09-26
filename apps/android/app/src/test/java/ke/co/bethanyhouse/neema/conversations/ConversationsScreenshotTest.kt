package ke.co.bethanyhouse.neema.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.graphics.drawable.BitmapDrawable
import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import coil.Coil
import coil.ImageLoader
import com.android.resources.ScreenOrientation
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.feature.conversations.*
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
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
 * The inbox and the thread in every state the web draws: tabs and filters,
 * empty / loading, bulk select, every bubble and media type, system pills,
 * notes, quotes, comment cards, translations, the composer in each window
 * state, AI drafts, attachments, the lock banner, dialogs, dark mode and the
 * tablet two-pane layout.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ConversationsScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false, maxPercentDifference = 0.1)

    private val sched = TestCoroutineScheduler()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        // Photos have no network here: every image paints as a soft "photo" gradient.
        val img = photo()
        Coil.setImageLoader(
            ImageLoader.Builder(paparazzi.context)
                .components { add(coil.intercept.Interceptor { chain -> coil.request.SuccessResult(img, chain.request, coil.decode.DataSource.MEMORY) }) }
                .placeholder(img).build(),
        )
    }

    @After fun tearDown() = Dispatchers.resetMain()

    private fun photo(): BitmapDrawable {
        val b = Bitmap.createBitmap(800, 600, Bitmap.Config.ARGB_8888)
        Canvas(b).drawRect(0f, 0f, 800f, 600f, Paint().apply {
            shader = LinearGradient(0f, 0f, 800f, 600f, 0xFFB9C7AE.toInt(), 0xFF6F8566.toInt(), Shader.TileMode.CLAMP)
        })
        return BitmapDrawable(paparazzi.context.resources, b)
    }

    private class Owner : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }

    private class Screen(val fake: FakeNeema, val dash: DashboardViewModel, val vm: ConversationsViewModel, val owner: ViewModelStoreOwner)

    private fun screen(role: String = "admin", superuser: Boolean = true, setup: FakeNeema.() -> Unit = {}): Screen {
        val fake = FakeNeema.withFixtures().also(InboxFixtures::install).apply(setup)
        val dash = dashboard(paparazzi.context, fake, role, superuser)
        val owner = Owner()
        // The same instance the screen's viewModel { } call will find in this store.
        val vm = ViewModelProvider.create(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class]
        return Screen(fake, dash, vm, owner)
    }

    /**
     * The rows are computed in place when I/O is synchronous (as here), so the
     * list is ready the moment the ViewModel is — no polling. Asserting it (not
     * waiting for it) is what keeps these screenshots from ever being flaky.
     */
    private fun Screen.settle(rowCount: Int? = null): Screen {
        val n = vm.rows.value.size
        check(if (rowCount != null) n == rowCount else n > 0) { "rows not ready on the first frame: $n" }
        return this
    }

    private fun Screen.snap(dark: Boolean = false, extra: @Composable () -> Unit = {}) = paparazzi.snapshot {
        AppFrame(dark) {
            CompositionLocalProvider(LocalViewModelStoreOwner provides owner) {
                ConversationsScreen(dash)
                extra()
            }
        }
    }

    private val tabletPortrait = DeviceConfig.NEXUS_10.copy(orientation = ScreenOrientation.PORTRAIT, screenWidth = 1600, screenHeight = 2560)

    // ═══════════════ The list ═══════════════

    @Test fun inbox_all() = screen().settle(6).snap()

    @Test fun inbox_all_dark() = screen().settle(6).snap(dark = true)

    @Test fun inbox_unreadTab_filtersOpen() = screen {
        on("GET", "/admin/conversations", body = """{"items":[${InboxFixtures.conversations.filter { it.contains("\"unread\":0").not() }.joinToString(",")}],"next_cursor":null}""")
    }.apply { vm.setTab("unread"); vm.toggleFilters(); vm.setTag("vip") }.settle().snap()

    @Test fun inbox_channelTab_whatsapp() = screen {
        on("GET", "/admin/conversations", body = """{"items":[${InboxFixtures.conversations.filter { it.contains("\"channel\":\"whatsapp\"") }.joinToString(",")}],"next_cursor":null}""")
    }.apply { vm.setChannel("whatsapp") }.settle().snap()

    @Test fun inbox_empty() = screen {
        on("GET", "/admin/conversations", body = """{"items":[],"next_cursor":null}""")
        on("GET", "/admin/conversations/summary", body = """{"unread":0,"human":0,"yours":0,"unread_messages":{},"tags":[]}""")
    }.snap()

    /** The list could not load: never a false "none", and never "Loading…" forever — a quiet Retry. */
    @Test fun inbox_error() = screen {
        on("GET", "/admin/conversations", code = 500, body = """{"detail":"down"}""")
    }.snap()

    @Test fun inbox_error_dark() = screen {
        on("GET", "/admin/conversations", code = 500, body = """{"detail":"down"}""")
    }.snap(dark = true)
    @Test fun inbox_bulkSelect() = screen().settle(6).apply {
        vm.enterSelect("p1"); vm.toggleRow("c6"); vm.toggleRow("c2")
    }.snap()

    @Test fun inbox_bulkSelect_dark() = screen().settle(6).apply { vm.enterSelect("p1") }.snap(dark = true)

    // ═══════════════ The thread ═══════════════

    /** Human-held by me, reply window open: the composer with the AI draft button. */
    @Test fun thread_humanMine_windowOpen() = screen().settle().apply { vm.select("c1") }.snap()

    @Test fun thread_humanMine_windowOpen_dark() = screen().settle().apply { vm.select("c1") }.snap(dark = true)

    /** The rich thread in screen-sized slices (a 7000px image is unreadable once scaled). */
    private fun richSlice(from: String, to: String): String {
        val all = kotlinx.serialization.json.Json.parseToJsonElement(InboxFixtures.richThread) as kotlinx.serialization.json.JsonArray
        val ids = all.map { (it as kotlinx.serialization.json.JsonObject)["id"].toString().trim('"') }
        return kotlinx.serialization.json.JsonArray(all.subList(ids.indexOf(from), ids.indexOf(to) + 1)).toString()
    }

    private fun bubbles(from: String, to: String, dark: Boolean) =
        screen { on("GET", "/admin/conversations/[^/]+/messages", body = richSlice(from, to)) }
            .settle().apply { vm.select("c2") }.snap(dark = dark)

    /** Formatting, translations both ways, the escalation card, flag and generic pills. */
    @Test fun bubbles_textPillsTranslations() = bubbles("r1", "e4", false)
    @Test fun bubbles_textPillsTranslations_dark() = bubbles("r1", "e4", true)

    /** A three-photo album, a text, and our photo with its AI analysis. */
    @Test fun bubbles_photos() = bubbles("i1", "i4", false)
    @Test fun bubbles_photos_dark() = bubbles("i1", "i4", true)

    /** Video, voice notes (transcript toggle, the AI's cart line), a document. */
    @Test fun bubbles_videoAudioDocument() = bubbles("v1", "d1", false)
    @Test fun bubbles_videoAudioDocument_dark() = bubbles("v1", "d1", true)

    /** Lost media, an unsupported row, a comment run under its post card, our threaded public reply. */
    @Test fun bubbles_fallbacksAndComments() = bubbles("x1", "k3", false)
    @Test fun bubbles_fallbacksAndComments_dark() = bubbles("x1", "k3", true)

    /** A note, reply quotes (text and photo). */
    @Test fun bubbles_noteAndQuotes() = bubbles("n1", "m7", false)
    @Test fun bubbles_noteAndQuotes_dark() = bubbles("n1", "m7", true)

    @Test fun thread_windowHumanAgent() = screen {
        on("GET", "/admin/conversations/[^/]+/window", body = InboxFixtures.windowHumanAgent())
    }.settle().apply { vm.select("c1") }.snap()

    @Test fun thread_windowClosed() = screen {
        on("GET", "/admin/conversations/[^/]+/window", body = InboxFixtures.windowClosed())
    }.settle().apply { vm.select("c1"); vm.setReplyText("Are you still there?") }.snap()

    /** An AI thread (no composer — the web shows none until someone takes it). */
    @Test fun thread_aiMode() = screen().settle().apply { vm.select("c2") }.snap()

    @Test fun thread_loadError() = screen {
        on("GET", "/admin/conversations/[^/]+/messages", code = 500, body = """{"detail":"boom"}""")
    }.settle().apply { vm.select("c2") }.snap()

    @Test fun thread_empty() = screen {
        on("GET", "/admin/conversations/[^/]+/messages", body = "[]")
    }.settle().apply { vm.select("c3") }.snap()

    @Test fun thread_webVisitor() = screen {
        on("GET", "/admin/conversations/[^/]+/messages", body = """[{"id":"w1","type":"message","direction":"inbound","sender":"user","text":"Do you ship to Kampala?","created_at":"${Fixtures.ago(20)}"},
          {"id":"w2","type":"message","direction":"outbound","sender":"ai","text":"Yes! We ship across East Africa — Kampala takes 3–5 days.","created_at":"${Fixtures.ago(19)}"}]""")
    }.settle().apply { vm.select("c7") }.snap()

    /** Inviting a web-chat visitor: the phone field starts EMPTY — never the hash's digits. */
    @Test fun dialog_invite_webVisitor() = screen().settle().apply { vm.select("c7") }.let { s ->
        s.snap { InviteDialog(s.dash, s.vm, s.vm.activeConv()!!, inviteTarget(s.vm.thread.value.reach, "c7")) {} }
    }

    /**
     * Round 3: a Messenger thread exactly as the server sends it — a null
     * wa_id (the PSID is the key), "+00:00" microsecond timestamps, a French
     * customer with the gray English line under a dashed rule, a human reply
     * quoting them, a note and a comment.
     */
    @Test fun thread_messenger_realContract() = screen {
        on("GET", "/admin/conversations", body = InboxFixtures.Contract.page(InboxFixtures.Contract.peterWa, InboxFixtures.Contract.maryMsgr.replace("\"intercept_mode\":\"ai\"", "\"intercept_mode\":\"human\"").replace("\"assigned_agent_id\":null", "\"assigned_agent_id\":\"${Fixtures.ME_ID}\""), InboxFixtures.Contract.peterFb))
        on("GET", "/admin/conversations/[^/]+/messages", body = InboxFixtures.Contract.thread())
        on("GET", "/admin/conversations/[^/]+/window", body = InboxFixtures.windowHumanAgent())
    }.settle().apply { vm.select("k2") }.snap()

    @Test fun thread_messenger_realContract_dark() = screen {
        on("GET", "/admin/conversations", body = InboxFixtures.Contract.page(InboxFixtures.Contract.peterWa, InboxFixtures.Contract.maryMsgr, InboxFixtures.Contract.peterFb))
        on("GET", "/admin/conversations/[^/]+/messages", body = InboxFixtures.Contract.thread())
    }.settle().apply { vm.select("k2") }.snap(dark = true)

    /** The invite, from the thread menu, to the phone captured on a Messenger customer's profile. */
    @Test fun dialog_invite_profilePhone() = screen().settle().apply { vm.select("c2") }.let { s ->
        s.snap { InviteDialog(s.dash, s.vm, s.vm.activeConv()!!, "+250 788 123 456") {} }
    }

    @Test fun dialog_note_dark() = screen().settle().apply { vm.select("c1") }.snap(dark = true) {
        NoteDialog("Repeat buyer — offer free delivery to Nyeri", {}, {}) {}
    }

    /** An admin on a paused thread: Resume (amber primary), Transfer, Note, Clear as the web's Btn variants. */
    @Test fun thread_paused_tablet() {
        paparazzi.unsafeUpdateConfig(deviceConfig = tabletPortrait)
        screen().settle(6).apply { vm.select("c3") }.snap()
    }

    /** A regular agent on a thread Grace holds: the lock badge and banner, no composer. */
    @Test fun thread_lockedByAnotherAgent() = screen(role = "agent", superuser = false) {
        on("GET", "/admin/me", body = Fixtures.me.replace("\"role\":\"admin\"", "\"role\":\"agent\"").replace("\"is_superuser\":true", "\"is_superuser\":false"))
    }.settle().apply { vm.select("c6") }.snap()

    // ═══════════════ The composer ═══════════════

    @Test fun composer_draftPill() = screen {
        on("GET", "/admin/conversations/[^/]+/latest-draft", body = """{"draft":"Hello Father 🙏 Yes — Nyeri by Friday works."}""")
    }.settle().apply { vm.select("c1") }.snap()

    @Test fun composer_draftExpanded() = screen().settle().apply { vm.select("c1"); vm.generateDraft() }.snap()

    @Test fun composer_draftEditing() = screen().settle().apply { vm.select("c1"); vm.generateDraft(); vm.toggleDraftEditing() }.snap()

    @Test fun composer_quoteAndTranslation() = screen {
        on("GET", "/admin/conversations/[^/]+/messages", body = """[{"id":"t1","type":"message","direction":"inbound","sender":"user","text":"Mnaweza kufikisha Nyeri Ijumaa?","created_at":"${Fixtures.ago(3)}","translation":"Can you deliver to Nyeri on Friday?","translated_from":"sw"}]""")
    }.settle().apply {
        vm.select("c1")
        vm.beginReplyTo(vm.thread.value.messages["c1"]!!.first())
        vm.setReplyText("Yes, we will deliver on Friday.")
        sched.advanceTimeBy(701); sched.runCurrent()
    }.snap()

    @Test fun composer_attachments() = screen().settle().apply {
        vm.select("c1")
        // What the pickers hand back: names and types come from the URIs here.
        vm.addMedia(listOf("photo1.jpg", "Measurements.pdf", "fit.mp4").map { Uri.parse("content://media/$it") })
        val end = AppClock.now() + 3000
        while (vm.composer.value.media.size < 3 && AppClock.now() < end) Thread.sleep(5)
        vm.setMediaCaption(vm.composer.value.media.first().id, "The black one, 16 inch")
    }.snap()

    // ═══════════════ Dialogs ═══════════════

    @Test fun dialog_transfer() = screen().settle().apply { vm.select("c1") }.let { s ->
        s.snap { TransferDialog(s.dash, s.vm.activeConv(), false, { _, _ -> }) {} }
    }

    @Test fun dialog_note() = screen().settle().apply { vm.select("c1") }.snap {
        NoteDialog("Repeat buyer — offer free delivery to Nyeri", {}, {}) {}
    }

    @Test fun dialog_clearHistory() = screen().settle().apply { vm.select("c1"); vm.showClear(true) }.snap()

    @Test fun dialog_askNeema() = screen().settle().apply { vm.select("c1") }.let { s ->
        s.snap { AskNeemaDialog(s.vm, "What were his sizes?", "Collar 16 inch, chest 42 — from his order BH-1042 in March.") {} }
    }

    @Test fun dialog_answerViaNeema() = screen().settle().apply { vm.select("c2") }.let { s ->
        s.snap { AnswerViaNeemaDialog(s.vm, "", "Neema sent: “Yes, Reverend — the purple cassock is KES 12,500 and ready in 5 days 🙏”") {} }
    }

    @Test fun dialog_answerViaNeema_dark() = screen().settle().apply { vm.select("c2") }.let { s ->
        s.snap(dark = true) { AnswerViaNeemaDialog(s.vm, "", "Outside the messaging window — reply yourself when they next write.") {} }
    }

    // ═══════════════ Tablet ═══════════════

    @Test fun tablet_twoPane() {
        paparazzi.unsafeUpdateConfig(deviceConfig = tabletPortrait)
        screen().settle(6).apply { vm.select("c1") }.snap()
    }

    @Test fun tablet_landscape_sidePanes() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        screen().settle(6).apply { vm.select("c1"); vm.setActivityOpen(true) }.snap()
    }

    @Test fun tablet_twoPane_dark_bulkSelect() {
        paparazzi.unsafeUpdateConfig(deviceConfig = tabletPortrait)
        screen().settle(6).apply { vm.select("c2"); vm.enterSelect("p1"); vm.toggleRow("c6") }.snap(dark = true)
    }
}
