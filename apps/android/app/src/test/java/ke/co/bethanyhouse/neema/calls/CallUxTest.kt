package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.AudioRoute
import ke.co.bethanyhouse.neema.feature.calls.AudioRouteKind
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallOutcome
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallUiState
import ke.co.bethanyhouse.neema.feature.calls.CallbackSave
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.PermissionGrant
import ke.co.bethanyhouse.neema.feature.calls.WaitingCall
import ke.co.bethanyhouse.neema.feature.calls.WrapAction
import ke.co.bethanyhouse.neema.feature.calls.firstNameOf
import ke.co.bethanyhouse.neema.feature.calls.statusText
import ke.co.bethanyhouse.neema.feature.calls.wrapActions
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * docs/CALLING_UX.md on the JVM: the phases and their words, every outcome
 * of the wrap-up and whether it closes by itself, several agents on one call
 * (a colleague's answer by frame, by 409, by a re-read after the phone was
 * offline), the call-permission flow (never sent by itself), cancelling,
 * no answer, the second caller, audio routes that follow headsets, and the
 * live row updates that tell the card where the customer's chat is.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallUxTest {
    private val base = Instant.parse("2026-09-26T10:00:00Z").toEpochMilli()

    private inner class Rig(val scope: TestScope, me: String? = "agent-me") {
        val api = FakeCallApi()
        val media = FakeMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val foreground = MutableStateFlow(true)
        val connected = MutableStateFlow(true)
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = api, events = frames, connected = connected, scope = scope.backgroundScope, foreground = foreground,
            signedInFn = { true }, media = media, ringer = ringer, audio = audio,
            micGranted = { true }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
            myAgentId = { me },
        ).also { it.start() }
        val state get() = calls.state.value

        fun raw(json: String) {
            frames.tryEmit(ke.co.bethanyhouse.neema.core.net.NeemaJson.parseToJsonElement(json) as JsonObject)
            scope.runCurrent()
        }
        fun ring(id: String = "wacid.1", from: String = "254712345678", name: String = "Fr. Peter Kamau") =
            raw("""{"type":"incoming_call","call_id":"$id","from":"$from","name":"$name","at":"1","conversation_id":null}""")
        fun settle() = scope.runCurrent()
        fun at(ago: Long) = Instant.ofEpochMilli(base + scope.testScheduler.currentTime - ago).toString()
        fun live(id: String = "wacid.1"): FakePeer { ring(id); calls.answer(); settle(); media.peer.onEvent(PeerEvent.Connected); settle(); return media.peer }
        suspend fun placeCall(to: String = "254733444555", name: String = "Deacon James Mwangi"): Result<Unit> {
            val r = scope.async { calls.initiateCall(to, name) }
            settle()
            return r.await()
        }
    }

    private fun rig(me: String? = "agent-me", block: suspend TestScope.(Rig) -> Unit) = runTest { val r = Rig(this, me); r.settle(); block(r) }

    // ── The words (§3) ──────────────────────────────────────────────────────
    @Test fun everyPhaseSaysItsOwnWords() {
        val s = CallUiState(name = "Fr. Peter Kamau", from = "254712345678")
        assertEquals("Incoming…", s.copy(phase = CallPhase.Ringing).statusText())
        assertEquals("Calling…", s.copy(phase = CallPhase.Placing).statusText())
        assertEquals("Ringing…", s.copy(phase = CallPhase.RingingOut).statusText())
        assertEquals("Connecting…", s.copy(phase = CallPhase.Connecting).statusText())
        assertEquals("04:12", s.copy(phase = CallPhase.InCall, seconds = 252).statusText())
        assertEquals("the timer never shows while nothing flows", "Reconnecting…", s.copy(phase = CallPhase.InCall, seconds = 252, reconnecting = true).statusText())
        fun ended(o: CallOutcome, secs: Int = 0) = s.copy(phase = CallPhase.Ended, outcome = o, seconds = secs).statusText()
        assertEquals("Call ended · 4:12", ended(CallOutcome.Completed, 252))
        assertEquals("Answered by Ann", ended(CallOutcome.AnsweredElsewhere("Ann Wanjiru")))
        assertEquals("Call declined", ended(CallOutcome.Declined()))
        assertEquals("Missed call", ended(CallOutcome.Missed()))
        assertEquals("Saved to call back — find it under Calls", ended(CallOutcome.Callback(CallbackSave.Saved)))
        assertEquals("No answer", ended(CallOutcome.NoAnswer))
        assertEquals("Call cancelled", ended(CallOutcome.Cancelled))
        assertEquals("Call dropped · 2:13 — the connection was lost", ended(CallOutcome.ConnectionLost, 133))
        assertEquals("The customer's phone is off", ended(CallOutcome.Failed("The customer's phone is off")))
        assertEquals("Peter hasn't allowed WhatsApp calls yet", ended(CallOutcome.PermissionNeeded))
        assertEquals("Call request sent — you'll be told when Peter taps Allow", ended(CallOutcome.PermissionRequested))
        assertEquals("Microphone blocked — allow it in settings", ended(CallOutcome.MicBlocked))
        assertEquals("This customer hasn't allowed WhatsApp calls yet",
            CallUiState(phase = CallPhase.Ended, from = "254700000000", outcome = CallOutcome.PermissionNeeded).statusText())
    }

    @Test fun firstNamesSkipTitles() {
        assertEquals("Peter", firstNameOf("Fr. Peter Kamau"))
        assertEquals("Grace", firstNameOf("Grace"))
        assertEquals("Mary", firstNameOf("  Rev.  Mary Achieng "))
        assertNull(firstNameOf(null)); assertNull(firstNameOf("  ")); assertNull(firstNameOf("+254712345678"))
    }

    @Test fun neutralWrapUpsCloseByThemselvesActionableOnesWait() {
        assertEquals(6_000L, CallOutcome.Completed.autoCloseMs)
        assertEquals(4_000L, CallOutcome.AnsweredElsewhere(null).autoCloseMs)
        assertEquals(2_000L, CallOutcome.Cancelled.autoCloseMs)
        for (o in listOf(CallOutcome.Missed(), CallOutcome.NoAnswer, CallOutcome.ConnectionLost, CallOutcome.Failed("x"),
            CallOutcome.PermissionNeeded, CallOutcome.PermissionRequested, CallOutcome.MicBlocked, CallOutcome.Callback(CallbackSave.NotSaved))) {
            assertNull("$o stays until the agent acts", o.autoCloseMs)
        }
    }

    @Test fun wrapUpActionsFollowTheTable() {
        val s = CallUiState(phase = CallPhase.Ended, from = "254712345678", name = "Fr. Peter Kamau")
        fun acts(o: CallOutcome, outbound: Boolean = false) = s.copy(outcome = o, outbound = outbound).wrapActions()
        assertEquals(listOf(WrapAction.OpenChat, WrapAction.CallAgain, WrapAction.Done), acts(CallOutcome.Completed))
        assertEquals(listOf(WrapAction.Done), acts(CallOutcome.AnsweredElsewhere("Ann")))
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), acts(CallOutcome.Declined()))
        assertEquals(listOf(WrapAction.CallBack, WrapAction.Message, WrapAction.Done), acts(CallOutcome.Missed()))
        assertEquals(listOf(WrapAction.CallAgain, WrapAction.Message, WrapAction.Done), acts(CallOutcome.NoAnswer, true))
        assertEquals(listOf(WrapAction.CallAgain, WrapAction.OpenChat, WrapAction.Done), acts(CallOutcome.ConnectionLost))
        assertEquals(listOf(WrapAction.TryAgain, WrapAction.Message, WrapAction.Done), acts(CallOutcome.Failed("x"), true))
        assertEquals(listOf(WrapAction.SendCallRequest, WrapAction.Message, WrapAction.Cancel), acts(CallOutcome.PermissionNeeded, true))
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), acts(CallOutcome.PermissionRequested, true))
        assertEquals(listOf(WrapAction.OpenSettings, WrapAction.Done), acts(CallOutcome.MicBlocked))
        assertEquals("nobody to call or write to", listOf(WrapAction.Done), CallUiState(phase = CallPhase.Ended, outcome = CallOutcome.Missed()).wrapActions())
    }

    // ── Several agents, one call (§4) ───────────────────────────────────────
    @Test fun aColleaguesAnswerStopsThisPhoneAtOnce() = rig { r ->
        r.foreground.value = false; r.settle()
        r.ring()
        assertTrue(r.ringer.ringing && r.ringer.showing)
        r.raw("""{"type":"call_answered","call_id":"wacid.1","agent_id":"agent-ann","agent_name":"Ann Wanjiru","direction":"inbound"}""")
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallOutcome.AnsweredElsewhere("Ann Wanjiru"), r.state.outcome)
        assertEquals("Answered by Ann", r.state.statusText())
        assertFalse(r.ringer.ringing); assertFalse(r.ringer.showing)
        assertFalse("Ann keeps her call", r.api.log.any { it.startsWith("terminate") })
        advanceTimeBy(3_999); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
        advanceTimeBy(2); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun aColleaguesAnswerWhileThisPhoneIsAnsweringEndsItHereOnly() = rig { r ->
        r.media.gatherAtOnce = false
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallPhase.Connecting, r.state.phase)
        // This agent's own answer echoed back changes nothing.
        r.raw("""{"type":"call_answered","call_id":"wacid.1","agent_id":"agent-me","agent_name":"Moses","direction":"inbound"}""")
        assertEquals(CallPhase.Connecting, r.state.phase)
        r.raw("""{"type":"call_answered","call_id":"wacid.1","agent_id":"agent-ann","agent_name":"Ann","direction":"inbound"}""")
        assertEquals(CallOutcome.AnsweredElsewhere("Ann"), r.state.outcome)
        assertTrue(r.media.peer.closed)
        assertFalse(r.api.log.any { it.startsWith("terminate") })
    }

    @Test fun a409NamesTheWinner() = rig { r ->
        r.api.answerError = ApiException(409, "POST", "/admin/calls/wacid.1/answer", """{"detail":"call already answered by Ann Wanjiru"}""")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallOutcome.AnsweredElsewhere("Ann Wanjiru"), r.state.outcome)
        assertEquals("Answered by Ann", r.state.statusText())
        assertFalse(r.api.log.any { it.startsWith("terminate") })
    }

    @Test fun a410SaysTheCallAlreadyEnded() = rig { r ->
        r.api.answerError = ApiException(410, "POST", "/admin/calls/wacid.1/answer", """{"detail":"This call has already ended."}""")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallOutcome.Missed(CallManager.CALL_GONE), r.state.outcome)
        assertEquals("This call has already ended", r.state.statusText())
        assertEquals(WrapAction.CallBack, r.state.wrapActions().first())
        assertFalse(r.api.log.any { it.startsWith("terminate") })
    }

    @Test fun callEndedOutcomesMapToTheWrapUp() = rig { r ->
        fun endWith(outcome: String, setup: () -> Unit): CallOutcome? {
            setup()
            r.raw("""{"type":"call_ended","call_id":"${r.state.callId}","outcome":"$outcome","status":"COMPLETED","duration":42,"agent_name":"Ann Wanjiru"}""")
            val o = r.state.outcome
            r.calls.dismiss(); r.settle()
            advanceTimeBy(13_000); runCurrent()
            return o
        }
        var n = 0
        fun ringFresh() = r.ring("wacid.r${n++}")
        assertEquals(CallOutcome.Missed(), endWith("missed", ::ringFresh))
        assertEquals(CallOutcome.Declined("Ann Wanjiru"), endWith("declined", ::ringFresh))
        assertEquals(CallOutcome.Callback(CallbackSave.Saved), endWith("callback", ::ringFresh))
        assertEquals("completed while it rang here: someone else took it", CallOutcome.AnsweredElsewhere("Ann Wanjiru"), endWith("completed", ::ringFresh))
        assertEquals(CallOutcome.Completed, endWith("completed") { r.live("wacid.r${n++}") })
        assertEquals(CallOutcome.NoAnswer, endWith("no_answer") { r.api.connectId = "wacid.o${n++}"; r.scope.async { r.calls.initiateCall("254733444555") }; r.settle() })
        assertEquals(CallOutcome.Failed(CallManager.CALL_NOT_CONNECTED), endWith("failed") { r.api.connectId = "wacid.o${n++}"; r.scope.async { r.calls.initiateCall("254733444555") }; r.settle() })
    }

    @Test fun aCallThatEndedWhileOfflineShowsItsRealOutcomeOnReconnect() = rig { r ->
        r.ring()
        r.connected.value = false; r.settle()
        // Offline: Ann answered; no frame reached this phone.
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", waId = "254712345678", status = "answered", agentName = "Ann Wanjiru", startedAt = r.at(5_000)))
        // The log read fails on the way back (a flaky network): the call's own row still tells.
        r.api.listError = ApiException(502, "GET", "/admin/calls", "<html>502</html>")
        r.connected.value = true; r.settle()
        assertTrue("re-read its own row", "get wacid.1" in r.api.log)
        assertEquals(CallOutcome.AnsweredElsewhere("Ann Wanjiru"), r.state.outcome)
        assertFalse(r.ringer.ringing)
    }

    @Test fun anOutboundCallThatRangOutWhileOfflineSaysNoAnswer() = rig { r ->
        assertTrue(r.placeCall().isSuccess)
        r.foreground.value = false; r.settle()
        r.api.listError = ApiException(0, "GET", "/admin/calls", "Failed to connect")
        r.api.calls = listOf(Call(id = "k9", callId = "wacid.out1", direction = "outbound", status = "no_answer", startedAt = r.at(60_000)))
        r.foreground.value = true; r.settle()
        assertEquals(CallOutcome.NoAnswer, r.state.outcome)
        assertTrue(r.media.peer.closed)
    }

    @Test fun aLiveCallThatEndedWhileTheAppWasAwayIsCorrectedOnReturn() = rig { r ->
        r.live()
        advanceTimeBy(30_000); runCurrent()
        r.foreground.value = false; r.settle()
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", waId = "254712345678", status = "completed", duration = 31, startedAt = r.at(40_000)))
        r.foreground.value = true; r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallOutcome.Completed, r.state.outcome)
        assertTrue(r.media.peer.closed)
        assertFalse("the server already ended it", r.api.log.any { it.startsWith("terminate") })
    }

    @Test fun aReSyncOfACallStillGoingChangesNothing() = rig { r ->
        r.live()
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", status = "answered", agentId = "agent-me", startedAt = r.at(5_000)))
        r.connected.value = false; r.settle(); r.connected.value = true; r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        // A row the server lost (404) changes nothing either.
        r.api.calls = emptyList()
        r.foreground.value = false; r.settle(); r.foreground.value = true; r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    // ── Outbound: placing, ringing, cancel, no answer, failures ─────────────
    @Test fun placingThenRingingThenConnectingThenLive() = rig { r ->
        r.api.connectGate = kotlinx.coroutines.CompletableDeferred()
        val placed = async { r.calls.initiateCall("254733444555", "Deacon James Mwangi") }
        r.settle()
        assertEquals(CallPhase.Placing, r.state.phase)
        assertEquals("Calling…", r.state.statusText())
        assertTrue("call audio from the start (the ringback)", r.audio.inCall)
        r.api.connectGate!!.complete(Unit); r.settle()
        assertTrue(placed.await().isSuccess)
        assertEquals(CallPhase.RingingOut, r.state.phase)
        // The customer picked up: call_answered for our own call.
        r.raw("""{"type":"call_answered","call_id":"wacid.out1","agent_id":"agent-me","agent_name":"Moses","direction":"outbound"}""")
        assertEquals(CallPhase.Connecting, r.state.phase)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    @Test fun cancellingWhilePlacingOrRingingSaysCancelled() = rig { r ->
        r.media.gatherAtOnce = false
        val a = async { r.calls.initiateCall("254733444555") }
        r.settle()
        r.calls.hangup(); r.settle()
        assertEquals(CallOutcome.Cancelled, r.state.outcome)
        advanceTimeBy(2_600); runCurrent()
        assertTrue(a.await().isSuccess)
        assertEquals("closes by itself", CallPhase.Idle, r.state.phase)
        assertFalse(r.api.log.any { it.startsWith("connect") || it.startsWith("terminate") })

        r.media.gatherAtOnce = true
        assertTrue(r.placeCall().isSuccess)
        assertEquals(CallPhase.RingingOut, r.state.phase)
        r.calls.hangup(); r.settle()
        assertEquals(CallOutcome.Cancelled, r.state.outcome)
        assertTrue("their phone stops ringing", "terminate wacid.out1" in r.api.log)
    }

    @Test fun noAnswerStaysWithCallAgain() = rig { r ->
        assertTrue(r.placeCall().isSuccess)
        r.raw("""{"type":"call_ended","call_id":"wacid.out1","outcome":"no_answer","status":"REJECTED","duration":null,"direction":"outbound"}""")
        assertEquals(CallOutcome.NoAnswer, r.state.outcome)
        advanceTimeBy(60_000); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
        r.api.connectId = "wacid.out2"
        r.calls.redial(); r.settle()
        assertEquals("Call again places it again", CallPhase.RingingOut, r.state.phase)
        assertEquals("wacid.out2", r.state.callId)
        assertEquals("Deacon James Mwangi", r.state.name)
        assertEquals(2, r.api.log.count { it.startsWith("connect") })
    }

    @Test fun aConnectRefusalSaysTheServersReason() = rig { r ->
        r.api.connectError = ApiException(502, "POST", "/admin/calls/connect", """{"detail":"call failed: the customer's phone is switched off"}""")
        val res = r.placeCall()
        assertEquals("Couldn't place the call", res.exceptionOrNull()!!.message)
        assertEquals(CallOutcome.Failed("The customer's phone is switched off"), r.state.outcome)
        // An HTML error page is never shown as a reason.
        r.api.connectError = ApiException(502, "POST", "/admin/calls/connect", "<html><body>502 Bad Gateway</body></html>")
        r.placeCall()
        assertEquals(CallOutcome.Failed("Couldn't place the call"), r.state.outcome)
    }

    // ── Call permission: asked only on the agent's tap ──────────────────────
    @Test fun permissionAlreadyRequestedSaysSo() = rig { r ->
        r.api.connectError = ApiException(409, "POST", "/admin/calls/connect", """{"detail":"This customer hasn't allowed calls yet."}""")
        r.api.permissionStatus = "requested"
        r.placeCall()
        assertTrue("permission 254733444555" in r.api.log)
        assertEquals(CallOutcome.PermissionRequested, r.state.outcome)
        assertEquals("Call request sent — you'll be told when James taps Allow", r.state.statusText())
        assertFalse(r.api.log.any { it.startsWith("request-permission") })
    }

    @Test fun sendCallRequestThenTheCustomerAllowsCalls() = rig { r ->
        r.api.connectError = ApiException(409, "POST", "/admin/calls/connect", """{"detail":"no permission"}""")
        r.placeCall()
        assertEquals(CallOutcome.PermissionNeeded, r.state.outcome)
        // Offline the first time: said on the card, still offered.
        r.api.permissionError = ApiException(0, "POST", "/admin/calls/request-permission", "Failed to connect to neema")
        r.calls.sendCallRequest(); r.settle()
        assertEquals(CallOutcome.PermissionNeeded, r.state.outcome)
        assertEquals("No connection — the call request wasn't sent", r.state.error)
        assertFalse(r.state.busy)
        r.api.permissionError = null
        r.calls.sendCallRequest(); r.settle()
        assertEquals(2, r.api.log.count { it == "request-permission 254733444555" })
        assertEquals(CallOutcome.PermissionRequested, r.state.outcome)
        assertNull(r.state.error)
        // Another customer allowing calls isn't news for this phone.
        r.raw("""{"type":"call_permission","wa_id":"254700000001","status":"granted","expires_at":null,"permanent":false}""")
        assertNull(r.calls.permissionGranted.value)
        r.raw("""{"type":"call_permission","wa_id":"254733444555","status":"granted","expires_at":"2026-10-03T10:00:00+00:00","permanent":false}""")
        assertEquals(PermissionGrant("254733444555", "Deacon James Mwangi"), r.calls.permissionGranted.value)
        assertEquals("the banner replaces the stale wrap-up", CallPhase.Idle, r.state.phase)
        // "Call now".
        r.api.connectError = null
        r.calls.callGranted(); r.settle()
        assertNull(r.calls.permissionGranted.value)
        assertEquals(CallPhase.RingingOut, r.state.phase)
        assertEquals("254733444555", r.state.from)
    }

    // ── The second caller ──────────────────────────────────────────────────
    @Test fun aSecondCallerIsABannerThatCanBeDeclinedOrKeptForLater() = rig { r ->
        r.live()
        r.ring("wacid.2", "254799999999", "Sr. Agnes Wairimu")
        assertEquals(WaitingCall("wacid.2", "254799999999", "Sr. Agnes Wairimu"), r.state.waiting)
        assertEquals("wacid.1", r.state.callId)
        r.calls.declineWaiting(); r.settle()
        assertNull(r.state.waiting)
        assertTrue("terminate wacid.2" in r.api.log)
        assertEquals(CallPhase.InCall, r.state.phase)

        r.ring("wacid.3", "254788888888", "Bro. Kevin Ouma")
        r.calls.callbackWaiting(); r.settle()
        assertTrue("callback wacid.3" in r.api.log)
        assertNull(r.state.waiting)

        r.ring("wacid.4", "254777777777", "Mrs. Faith Chebet")
        // They gave up: the banner goes with them.
        r.raw("""{"type":"call_ended","call_id":"wacid.4","outcome":"missed"}""")
        assertNull(r.state.waiting)
        r.calls.hangup(); r.settle()
        assertEquals("nobody waits: the wrap-up of this call stays", CallOutcome.Completed, r.state.outcome)
    }

    @Test fun endAndAnswerTakesTheSecondCaller() = rig { r ->
        r.live()
        r.ring("wacid.2", "254799999999", "Sr. Agnes Wairimu")
        r.calls.endAndAnswer(); r.settle()
        assertTrue("terminate wacid.1" in r.api.log)
        assertTrue("answer wacid.2" in r.api.log)
        assertEquals("wacid.2", r.state.callId)
        assertEquals(CallPhase.Connecting, r.state.phase)
    }

    @Test fun aNewRingReplacesTheWrapUpAtOnce() = rig { r ->
        r.ring(); r.frame("missed")
        assertEquals(CallOutcome.Missed(), r.state.outcome)
        r.ring("wacid.2", "254799999999", "Sr. Agnes Wairimu")
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("Sr. Agnes Wairimu", r.state.name)
        assertNull(r.state.outcome)
    }

    private fun Rig.frame(outcome: String) = raw("""{"type":"call_ended","call_id":"${state.callId}","outcome":"$outcome"}""")

    // ── Audio routes follow headsets (§ build brief 3) ──────────────────────
    private val buds = AudioRoute(AudioRouteKind.Bluetooth, "Jabra Talk 25")
    private val wired = AudioRoute(AudioRouteKind.Wired)

    @Test fun aConnectedHeadsetTakesTheCallFromTheStart() = rig { r ->
        r.audio.plug(buds); r.settle()
        r.live()
        assertEquals(buds, r.state.route)
        assertEquals(buds, r.audio.route)
        assertTrue(r.state.routeChoice)
    }

    @Test fun headsetsComeAndGoMidCallWithoutEverBlastingTheSpeaker() = rig { r ->
        r.live()
        assertEquals(AudioRoute.Earpiece, r.audio.route)
        r.audio.plug(wired); r.settle()
        assertEquals("plugged in: the call follows it", wired, r.audio.route)
        r.audio.unplug(wired); r.settle()
        assertEquals("unplugged: back to the earpiece, never the speaker", AudioRoute.Earpiece, r.audio.route)
        r.audio.plug(buds); r.settle()
        assertEquals(buds, r.state.route)
        r.audio.plug(wired); r.settle()
        assertEquals(wired, r.state.route)
        r.audio.unplug(wired); r.settle()
        assertEquals("the other headset is still there", buds, r.state.route)
        // The agent chose the speaker; a headset that goes (not in use) changes nothing.
        r.calls.selectRoute(AudioRoute.Speaker)
        r.audio.unplug(buds); r.settle()
        assertEquals(AudioRoute.Speaker, r.audio.route)
        r.calls.toggleSpeaker()
        assertEquals(AudioRoute.Earpiece, r.audio.route)
    }

    @Test fun aTabletWithoutAnEarpieceUsesItsSpeaker() = rig { r ->
        r.audio.routes.value = listOf(AudioRoute.Speaker); r.settle()
        r.live()
        assertEquals(AudioRoute.Speaker, r.audio.route)
        r.audio.plug(wired); r.settle()
        assertEquals(wired, r.audio.route)
        r.audio.unplug(wired); r.settle()
        assertEquals(AudioRoute.Speaker, r.audio.route)
    }

    @Test fun theSpeakerToggleReturnsToTheHeadset() = rig { r ->
        r.audio.plug(buds); r.settle()
        r.live()
        r.calls.toggleSpeaker()
        assertEquals(AudioRoute.Speaker, r.audio.route)
        r.calls.toggleSpeaker()
        assertEquals(buds, r.audio.route)
        r.calls.selectRoute(AudioRoute(AudioRouteKind.Wired))
        assertEquals("not plugged in: ignored", buds, r.audio.route)
    }

    // ── The call card's other actions ───────────────────────────────────────
    @Test fun aRowUpdateTellsTheCardWhereTheChatIs() = rig { r ->
        r.ring(name = "")
        r.raw("""{"type":"call_update","call":{"call_id":"wacid.1","wa_id":"254712345678","name":"Fr. Peter Kamau","person_id":"p1","conversation_id":"c1","status":"ringing","unknown_key":[1,2]}}""")
        assertEquals("c1", r.state.conversationId)
        assertEquals("p1", r.state.personId)
        assertEquals("Fr. Peter Kamau", r.state.name)
        assertEquals(CallPhase.Ringing, r.state.phase)
        // A broken row is ignored.
        r.raw("""{"type":"call_update","call":"nope"}""")
        assertEquals(CallPhase.Ringing, r.state.phase)
    }

    @Test fun openChatMinimisesALiveCallAndClosesAWrapUp() = rig { r ->
        r.live()
        assertEquals("254712345678", r.calls.openChat())
        assertTrue(r.state.minimised)
        assertEquals("still on the call", CallPhase.InCall, r.state.phase)
        r.calls.expand()
        assertFalse(r.state.minimised)
        r.calls.hangup(); r.settle()
        assertEquals("254712345678", r.calls.openChat())
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun theOngoingNotificationsEndHangsUp() = rig { r ->
        r.live()
        r.calls.minimise()
        r.calls.handleAction("end", null); r.settle()
        assertEquals(CallOutcome.Completed, r.state.outcome)
        assertTrue("terminate wacid.1" in r.api.log)
        assertTrue("the minimised bar shows the wrap-up", r.state.minimised)
    }

    @Test fun recordingShowsOnlyWhileItRunsThenSaysWhatHappensNext() = rig { r ->
        r.api.ice = r.api.ice.copy(transcribe = true, autoTranscribe = true)
        r.ring(); r.calls.answer(); r.settle()
        assertFalse("not yet connected", r.state.recording)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertTrue(r.state.recording)
        r.calls.hangup(); r.settle()
        assertFalse(r.state.recording)
        assertEquals(CallManager.RECORDING_SAVED_AUTO, r.state.recordingNote)
        // Recording switched off on the server: nothing is said.
        advanceTimeBy(13_000); runCurrent()
        r.api.ice = r.api.ice.copy(record = false)
        r.live("wacid.2")
        assertFalse(r.state.recording)
        r.calls.hangup(); r.settle()
        assertNull(r.state.recordingNote)
    }
}
