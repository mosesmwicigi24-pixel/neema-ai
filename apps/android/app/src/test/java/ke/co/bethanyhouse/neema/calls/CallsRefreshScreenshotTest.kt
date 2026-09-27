package ke.co.bethanyhouse.neema.calls

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.CallHoliday
import ke.co.bethanyhouse.neema.core.model.CallHours
import ke.co.bethanyhouse.neema.core.model.CallHoursSlot
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.model.CallVoicemail
import ke.co.bethanyhouse.neema.core.model.CallingSettings
import ke.co.bethanyhouse.neema.core.model.CallingSettingsSaved
import ke.co.bethanyhouse.neema.core.model.PermissionTemplate
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.calls.CallActions
import ke.co.bethanyhouse.neema.feature.calls.CallCard
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallOutcome
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallReadiness
import ke.co.bethanyhouse.neema.feature.calls.CallRefusal
import ke.co.bethanyhouse.neema.feature.calls.CallUiState
import ke.co.bethanyhouse.neema.feature.calls.CallsScreen
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.feature.conversations.ThreadCallEvent
import ke.co.bethanyhouse.neema.feature.conversations.ThreadMsg
import ke.co.bethanyhouse.neema.feature.conversations.customer.CallPermissionBlock
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerViewModel
import ke.co.bethanyhouse.neema.feature.settings.CallingSettingsApi
import ke.co.bethanyhouse.neema.feature.settings.CallingSettingsModel
import ke.co.bethanyhouse.neema.feature.settings.WhatsAppCallingCard
import ke.co.bethanyhouse.neema.orders.Devices
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.serialization.json.JsonObject
import org.junit.Rule
import org.junit.Test

/**
 * The 2026-09-27 platform refresh (CALLING_UX.md §2.1) on screen: permission
 * truth on the wrap-up (declined, the request limit, template required,
 * already allowed), a server action that isn't a retry, the unanswered-calls
 * caution, "Recorded by WhatsApp", the customer declining our call,
 * voicemail on the log, details and thread pill, the restriction banner,
 * WhatsApp's two-speaker transcript, the customer panel's permission lines,
 * and Settings → WhatsApp calling.
 *   ./gradlew :app:recordPaparazziDebug --tests '*CallsRefreshScreenshotTest'
 */
class CallsRefreshScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)
    @get:Rule val clock = ke.co.bethanyhouse.neema.testing.PinnedClock()

    private val wa = "254733444555"
    private val james = CallUiState(
        phase = CallPhase.Ended, callId = "wacid.out", from = wa, name = "Deacon James Mwangi", outbound = true,
    )
    private fun inHours(h: Int) = java.time.Instant.ofEpochMilli(AppClock.now() + h * 3_600_000L - 1_000L).toString()
    private fun perm(status: String, canCall: Boolean?, canRequest: Boolean? = true, at: String? = null, streak: Int = 0) =
        CallPermission(wa, status, metaStatus = if (canCall == false) "no_permission" else "permanent", canCall = canCall,
            canRequest = canRequest, requestAvailableAt = at, unansweredStreak = streak, source = "meta")

    private fun card(s: CallUiState, device: DeviceConfig = DeviceConfig.PIXEL_6, dark: Boolean = false) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot { AppFrame(dark) { CallCard(s, CallActions()) } }
    }

    // ── The wrap-up and the card ─────────────────────────────────────────────
    @Test fun wrapRejected() = card(james.copy(outcome = CallOutcome.Rejected))
    @Test fun wrapRequestLimit() = card(
        james.copy(outcome = CallOutcome.PermissionNeeded, permission = perm("denied", canCall = false, canRequest = false, at = inHours(5))),
    )
    @Test fun wrapTemplateRequiredAdmin() = card(
        james.copy(
            outcome = CallOutcome.PermissionNeeded, conversationId = "c3",
            error = "James hasn't messaged in 24 hours — WhatsApp only allows a call request by template then. An admin can create it in Settings → WhatsApp calling.",
            refusal = CallRefusal("template_required", "admin", "…", adminCanFix = true),
        ),
    )
    @Test fun wrapAlreadyAllowed() = card(james.copy(outcome = CallOutcome.AlreadyAllowed, conversationId = "c3"))
    @Test fun wrapTokenExpiredHugeText() = card(
        james.copy(outcome = CallOutcome.Failed("WhatsApp access token expired — an admin must renew it", "admin"), conversationId = "c3"),
        device = Devices.HugeText,
    )
    @Test fun cardPlacingUnansweredCaution() = card(
        james.copy(phase = CallPhase.Placing, callId = "pending", outcome = null, permission = perm("granted", canCall = true, streak = 3)),
    )
    @Test fun cardPlacingUnansweredCautionSmallDark() = card(
        james.copy(phase = CallPhase.RingingOut, outcome = null, permission = perm("granted", canCall = true, streak = 2)),
        device = DeviceConfig.NEXUS_5, dark = true,
    )
    @Test fun cardInCallRecordedByWhatsApp() = card(
        CallUiState(phase = CallPhase.InCall, callId = CallsFixtures.C1, from = "254712345678", name = "Fr. Peter Kamau", seconds = 95, metaTranscription = true),
    )

    // ── The Calls view ───────────────────────────────────────────────────────
    private val voicemailLog get() = CallsFixtures.calls.replaceFirst(
        "\"status\":\"missed\",\"duration\":null", "\"status\":\"missed\",\"has_voicemail\":true,\"duration\":null",
    )
    private val twoSpeaker = CallsFixtures.transcript(
        CallsFixtures.C1, "done",
        summary = "Fr. Peter wants two black clergy shirts (16\") delivered to Nyeri by Friday.",
        transcript = "Agent: Bethany House, good afternoon.\nCustomer: Hello, this is Father Peter from Nyeri. I need two black clergy shirts, size sixteen.\nAgent: Certainly Father — we can deliver by Friday.",
        language = "en",
    )

    @Composable
    private fun Console(dash: ke.co.bethanyhouse.neema.app.DashboardViewModel, dark: Boolean, setup: (CallsViewModel) -> Unit) = AppFrame(dark) {
        val vm: CallsViewModel = viewModel { CallsViewModel(dash) }
        remember { setup(vm) }
        CallsScreen(dash, readinessOverride = CallReadiness())
    }

    private fun console(dark: Boolean = false, device: DeviceConfig = DeviceConfig.PIXEL_6, restricted: Boolean = false, setup: (CallsViewModel) -> Unit = {}) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install).also {
            it.on("GET", "/admin/calls", body = voicemailLog)
            it.on("GET", CallsFixtures.route(CallsFixtures.C1, "transcript"), body = twoSpeaker)
        }
        val dash = dashboard(paparazzi.context, fake)
        if (restricted) dash.container.calls.onFrame(
            NeemaJson.parseToJsonElement("""{"type":"calling_restricted","event":"restricted","reasons":["LOW_PICKUP_RATE"],"at":"2026-09-27T09:00:00Z"}""") as JsonObject,
        )
        paparazzi.snapshot { Console(dash, dark, setup) }
    }

    @Test fun logVoicemailAndRestriction() = console(restricted = true)
    @Test fun logVoicemailAndRestrictionDark() = console(dark = true, restricted = true)
    @Test fun detailsVoicemail() = console { vm -> vm.calls.value?.find { it.callId == CallsFixtures.C2 }?.let(vm::select) }
    @Test fun transcriptTwoSpeakers() = console { it.toggleTranscript(CallsFixtures.C1); it.toggleFull() }

    // ── The thread pill ──────────────────────────────────────────────────────
    @Test fun threadVoicemailPill() {
        val row = CallsFixtures.row("k2", CallsFixtures.C2, "254712345678", "Fr. Peter Kamau", "inbound", "missed", null, null,
            CallsFixtures.pyIso(130), null, "none", false).replace("\"has_recording\":false", "\"has_recording\":false,\"has_voicemail\":true")
        val pill = ThreadMsg(
            id = "call-k2", type = "system_event", direction = "inbound", sender = "human_agent", text = "Missed call",
            createdAt = Fixtures.ago(130), eventKind = "call", callRaw = NeemaJson.parseToJsonElement(row),
        )
        paparazzi.snapshot {
            AppFrame(false) {
                Column(Modifier.fillMaxSize().background(Palette.Mist).padding(12.dp)) { ThreadCallEvent(pill, onUseAsReply = {}) }
            }
        }
    }

    // ── The customer panel's Calls section ──────────────────────────────────
    @Test fun customerPermissionStates() = customerPermission(false)
    @Test fun customerPermissionStatesDark() = customerPermission(true)

    private fun customerPermission(dark: Boolean) {
        val ui = CustomerViewModel.CallRequestUi()
        paparazzi.snapshot {
            AppFrame(dark) {
                Column(
                    Modifier.fillMaxSize().background(Neema.colors.bg2).padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    val now = AppClock.now()
                    CallPermissionBlock(perm("granted", true).copy(permanent = true, callsLeftToday = 4), ui, "James", {}, {}, {})
                    CallPermissionBlock(perm("granted", true).copy(metaStatus = "temporary", expiresAt = "2026-10-03T10:00:00+00:00"), ui, "James", {}, {}, {})
                    CallPermissionBlock(perm("requested", false, canRequest = false).copy(at = java.time.Instant.ofEpochMilli(now - 2 * 3_600_000L).toString()), ui, "James", {}, {}, {})
                    CallPermissionBlock(perm("denied", false, canRequest = false, at = inHours(5)), ui, "James", {}, {}, {})
                    CallPermissionBlock(perm("denied", false).copy(revoked = true), ui, "James", {}, {}, {})
                    CallPermissionBlock(
                        perm("unknown", false),
                        ui.copy(error = "James hasn't messaged in 24 hours — WhatsApp only allows a call request by template then. An admin can create it in Settings → WhatsApp calling.", adminCanFix = true, templateRequired = true),
                        "James", {}, {}, {},
                    )
                }
            }
        }
    }

    // ── Settings → WhatsApp calling ──────────────────────────────────────────
    private val settings = CallingSettings(
        status = "ENABLED", callIconVisibility = "DEFAULT", callbackPermissionStatus = "ENABLED",
        callHours = CallHours(
            "ENABLED", "Africa/Nairobi",
            listOf("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY").map { CallHoursSlot(it, "0800", "1700") } + CallHoursSlot("SATURDAY", "0900", "1300"),
            listOf(CallHoliday("2026-12-25", "0000", "2359")),
        ),
        voicemail = CallVoicemail("ENABLED", listOf("TIMEOUT"), 20),
        restrictions = listOf(NeemaJson.parseToJsonElement("""{"type":"LOW_PICKUP_RATE","expiration":"2026-10-02"}""")),
    )

    private class StillApi(val s: CallingSettings, val t: PermissionTemplate, val saveError: Exception? = null) : CallingSettingsApi {
        override suspend fun settings() = s
        override suspend fun save(change: JsonObject): CallingSettingsSaved { saveError?.let { throw it }; return CallingSettingsSaved(true, s) }
        override suspend fun template() = t
        override suspend fun createTemplate() {}
    }

    private fun settingsCard(api: CallingSettingsApi, dark: Boolean = false, edit: (CallingSettingsModel) -> Unit = {}) {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 4200))
        val m = CallingSettingsModel(api, CoroutineScope(Dispatchers.Unconfined))
        m.start()
        edit(m)
        paparazzi.snapshot {
            AppFrame(dark) {
                Column(Modifier.fillMaxSize().background(Neema.colors.bg).padding(16.dp)) { WhatsAppCallingCard(m) }
            }
        }
    }

    @Test fun settingsCallingCard() = settingsCard(
        StillApi(settings, PermissionTemplate(true, "neema_call_permission", "en", "app", true, true, "pending", "UTILITY")),
    )
    @Test fun settingsCallingCardDark() = settingsCard(
        StillApi(settings, PermissionTemplate(true, "neema_call_permission", "en", "app", true, true, "approved", "UTILITY")), dark = true,
    )
    @Test fun settingsCallingCardErrors() = settingsCard(
        StillApi(
            settings.copy(restrictions = emptyList()), PermissionTemplate(false, wabaConfigured = true, exists = false),
            saveError = ApiException(503, "POST", "/admin/calls/settings",
                """{"detail":"Couldn't read the current calling settings from WhatsApp, so nothing was changed (the holiday schedule would be lost) — try again.","code":"meta_unavailable","action":"retry"}"""),
        ),
    ) { m ->
        m.edit { it.copy(voicemail = it.voicemail!!.copy(timeoutSeconds = 45)) }
        m.edit { it.copy(callHours = it.callHours!!.copy(holidays = it.callHours!!.holidays + CallHoliday("2026-13-40", "0900", "0800"))) }
        m.save()
    }
    @Test fun settingsCallingCardSaveRefused() = settingsCard(
        StillApi(
            settings.copy(restrictions = emptyList(), callHours = settings.callHours!!.copy(status = "DISABLED")),
            PermissionTemplate(false, wabaConfigured = true, exists = false),
            saveError = ApiException(503, "POST", "/admin/calls/settings",
                """{"detail":"Couldn't read the current calling settings from WhatsApp, so nothing was changed (the holiday schedule would be lost) — try again.","code":"meta_unavailable","action":"retry"}"""),
        ),
    ) { m -> m.edit { it.copy(callbackPermissionStatus = "DISABLED") }; m.save() }
}
