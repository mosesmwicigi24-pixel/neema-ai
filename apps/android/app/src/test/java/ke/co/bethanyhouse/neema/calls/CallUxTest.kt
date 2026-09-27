package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.model.PermissionRequestResponse
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.feature.calls.CallingRestriction
import ke.co.bethanyhouse.neema.feature.calls.callCaution
import ke.co.bethanyhouse.neema.feature.calls.callRowWords
import ke.co.bethanyhouse.neema.feature.calls.permissionLines
import ke.co.bethanyhouse.neema.feature.calls.sendRequestBlocked
import ke.co.bethanyhouse.neema.feature.calls.threadCallLabel
import ke.co.bethanyhouse.neema.feature.calls.transcriptTurns
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
import ke.co.bethanyhouse.neema.feature.calls.outcomeNote
import ke.co.bethanyhouse.neema.feature.calls.wrapActions
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
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
        assertEquals("no name: their number, as the web", "+254700000000 hasn't allowed WhatsApp calls yet",
            CallUiState(phase = CallPhase.Ended, from = "254700000000", outcome = CallOutcome.PermissionNeeded).statusText())
    }

    @Test fun firstNamesSkipTitles() {
        assertEquals("Peter", firstNameOf("Fr. Peter Kamau"))
        assertEquals("Grace", firstNameOf("Grace"))
        assertEquals("Mary", firstNameOf("  Rev.  Mary Achieng "))
        assertNull(firstNameOf(null)); assertNull(firstNameOf("  ")); assertNull(firstNameOf("+254712345678"))
    }

    @Test fun neutralWrapUpsCloseByThemselvesActionableOnesWait() {
        assertEquals(8_000L, CallOutcome.Completed.autoCloseMs)
        assertEquals(5_000L, CallOutcome.Declined().autoCloseMs)
        assertEquals(6_000L, CallOutcome.PermissionRequested.autoCloseMs)
        assertEquals(4_000L, CallOutcome.AnsweredElsewhere(null).autoCloseMs)
        assertEquals(2_000L, CallOutcome.Cancelled.autoCloseMs)
        for (o in listOf(CallOutcome.Missed(), CallOutcome.NoAnswer, CallOutcome.ConnectionLost, CallOutcome.Failed("x"),
            CallOutcome.PermissionNeeded, CallOutcome.MicBlocked, CallOutcome.Callback(CallbackSave.NotSaved))) {
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
        assertEquals("Missed call", r.state.statusText())
        assertEquals("the reason, under it (as the web)", "This call has already ended", r.state.outcomeNote())
        assertEquals(WrapAction.CallBack, r.state.wrapActions().first())
        assertFalse(r.api.log.any { it.startsWith("terminate") })
    }

    @Test fun callEndedOutcomesMapToTheWrapUp() = rig { r ->
        fun endWith(outcome: String, setup: () -> Unit): CallOutcome? {
            setup()
            r.raw("""{"type":"call_ended","call_id":"${r.state.callId}","outcome":"$outcome","status":"COMPLETED","duration":42,"agent_id":"agent-ann","agent_name":"Ann Wanjiru"}""")
            val o = r.state.outcome
            r.calls.dismiss(); r.settle()
            advanceTimeBy(13_000); runCurrent()
            return o
        }
        var n = 0
        fun ringFresh() = r.ring("wacid.r${n++}")
        assertEquals(CallOutcome.Missed(), endWith("missed", ::ringFresh))
        assertEquals(CallOutcome.Declined("Ann Wanjiru"), endWith("declined", ::ringFresh))
        assertEquals(CallOutcome.Callback(CallbackSave.Saved, "Ann Wanjiru"), endWith("callback", ::ringFresh))
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
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
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
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
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
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
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
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
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

    // ── 2026-09-27 platform refresh (CALLING_UX.md §2.1) ─────────────────────
    private val james = "254733444555"
    private fun meta(status: String = "unknown", canCall: Boolean? = null, canRequest: Boolean? = true, streak: Int = 0,
                     at: String? = null, permanent: Boolean = false, expires: String? = null, revoked: Boolean = false, left: Int? = null) =
        CallPermission(james, status, expires, permanent, metaStatus = if (canCall == false) "no_permission" else "temporary",
            canCall = canCall, canRequest = canRequest, requestAvailableAt = at, callsLeftToday = left, revoked = revoked,
            unansweredStreak = streak, source = "meta")
    private fun refusal(status: Int, path: String, detail: String, code: String, action: String, extra: String = "") =
        ApiException(status, "POST", path, """{"detail":${kotlinx.serialization.json.JsonPrimitive(detail)},"code":"$code","action":"$action"$extra}""")
    private fun inHours(h: Int) = Instant.ofEpochMilli(AppClock.now() + h * 3_600_000L - 1_000L).toString()

    @Test fun permissionTruthSkipsTheDoomedConnect() = rig { r ->
        r.api.permission = meta(canCall = false)
        val res = r.placeCall()
        assertTrue("permission $james" in r.api.log)
        assertFalse("no connect Meta would refuse", r.api.log.any { it.startsWith("connect") })
        assertTrue("no peer, no microphone", r.media.peers.isEmpty())
        assertEquals(CallOutcome.PermissionNeeded, r.state.outcome)
        assertEquals((res.exceptionOrNull() as CallManager.CallError).shown, true)
        assertEquals(listOf(WrapAction.SendCallRequest, WrapAction.Message, WrapAction.Cancel), r.state.wrapActions())
        // Asked already (and still waiting): the card says that instead.
        advanceTimeBy(10_000); runCurrent()
        r.calls.dismiss()
        r.api.permission = meta(status = "requested", canCall = false, canRequest = false)
        r.placeCall()
        assertEquals(CallOutcome.PermissionRequested, r.state.outcome)
        assertFalse(r.api.log.any { it.startsWith("connect") })
    }

    @Test fun aSlowOrFailedPermissionReadNeverHoldsTheCallUp() = rig { r ->
        r.api.permissionGate = kotlinx.coroutines.CompletableDeferred()
        val placed = async { r.calls.initiateCall(james, "Deacon James Mwangi") }
        runCurrent()
        assertEquals("Calling… at once", CallPhase.Placing, r.state.phase)
        assertFalse(r.api.log.any { it.startsWith("connect") })
        advanceTimeBy(CallManager.PERMISSION_READ_MS + 1); runCurrent()
        assertTrue(placed.await().isSuccess)
        assertTrue("placed as before", "connect $james" in r.api.log)
        assertNull(r.state.permission)
        // A read that fails outright: placed as before too.
        r.calls.hangup(); r.settle(); advanceTimeBy(3_000); runCurrent()
        r.api.permissionGate = null
        r.api.permissionReadError = ApiException(502, "GET", "/admin/calls/permission", "{}")
        r.api.connectId = "wacid.out2"
        assertTrue(r.placeCall().isSuccess)
        assertEquals(2, r.api.log.count { it == "connect $james" })
    }

    @Test fun callingSaysRingingOnlyWhenMetaSaysItRings() = rig { r ->
        assertTrue(r.placeCall().isSuccess)
        assertEquals("Calling…", r.state.statusText())
        r.raw("""{"type":"call_status","call_id":"wacid.other","status":"ringing"}""")
        assertEquals("someone else's call", CallPhase.Placing, r.state.phase)
        r.raw("""{"type":"call_status","call_id":"wacid.out1","status":"accepted"}""")
        assertEquals(CallPhase.Placing, r.state.phase)
        r.raw("""{"type":"call_status","call_id":"wacid.out1","status":"ringing"}""")
        assertEquals("Ringing…", r.state.statusText())
        // The customer picks up straight from "Calling…" too (no ringing frame ever came).
        r.calls.hangup(); r.settle(); advanceTimeBy(3_000); runCurrent()
        r.api.connectId = "wacid.out2"
        r.placeCall()
        r.raw("""{"type":"call_answered","call_id":"wacid.out2","agent_id":"agent-me","agent_name":"Moses","direction":"outbound"}""")
        assertEquals(CallPhase.Connecting, r.state.phase)
        // A ringing frame that beat connect's reply is applied once the id is known.
        r.calls.hangup(); r.settle(); advanceTimeBy(3_000); runCurrent()
        r.api.connectId = "wacid.out3"
        r.api.connectGate = kotlinx.coroutines.CompletableDeferred()
        val placed = async { r.calls.initiateCall(james, "Deacon James Mwangi") }
        r.settle()
        r.raw("""{"type":"call_status","call_id":"wacid.out3","status":"ringing"}""")
        assertEquals(CallPhase.Placing, r.state.phase)
        r.api.connectGate!!.complete(Unit); r.settle()
        assertTrue(placed.await().isSuccess)
        assertEquals(CallPhase.RingingOut, r.state.phase)
    }

    @Test fun aDeclinedCallSaysSoWithMessageAndDone() = rig { r ->
        r.placeCall()
        r.raw("""{"type":"call_ended","call_id":"wacid.out1","outcome":"rejected","status":"REJECTED","direction":"outbound"}""")
        assertEquals(CallOutcome.Rejected, r.state.outcome)
        assertEquals("James declined the call", r.state.statusText())
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertNull("the agent decides: it stays", CallOutcome.Rejected.autoCloseMs)
        assertEquals("Declined by customer", callRowWords(Call(callId = "x", direction = "outbound", status = "rejected")).label)
        // A no_answer corrected to rejected a moment later: the latest word wins.
        r.calls.dismiss()
        r.api.connectId = "wacid.out2"
        r.placeCall()
        r.raw("""{"type":"call_ended","call_id":"wacid.out2","outcome":"no_answer","direction":"outbound"}""")
        assertEquals(CallOutcome.NoAnswer, r.state.outcome)
        r.raw("""{"type":"call_ended","call_id":"wacid.out2","outcome":"rejected","direction":"outbound"}""")
        assertEquals(CallOutcome.Rejected, r.state.outcome)
    }

    @Test fun unansweredStreakCautionsButNeverBlocks() = rig { r ->
        r.api.permission = meta(status = "granted", canCall = true, streak = 3)
        assertTrue(r.placeCall().isSuccess)
        assertTrue("never blocking", "connect $james" in r.api.log)
        assertEquals(
            "James missed your last 3 calls — WhatsApp removes call permission after 4 in a row. Consider a message first.",
            r.state.callCaution(),
        )
        r.raw("""{"type":"call_status","call_id":"wacid.out1","status":"ringing"}""")
        assertTrue(r.state.callCaution() != null)
        r.raw("""{"type":"call_answered","call_id":"wacid.out1","agent_id":"agent-me","direction":"outbound"}""")
        assertNull("only before it goes through", r.state.callCaution())
        assertNull(CallUiState(phase = CallPhase.Placing, outbound = true, permission = meta(streak = 1)).callCaution())
        // WhatsApp's revoke-after-4 rule: never warned about on a Messenger call.
        assertNull(CallUiState(phase = CallPhase.Placing, outbound = true, channel = "messenger",
            permission = meta(streak = 3)).callCaution())
    }

    @Test fun templateRequiredOffersSettingsToAdminsOnly() = rig { r ->
        r.calls.canManageSettings = { true }
        r.api.permission = meta(canCall = false)
        r.placeCall()
        val detail = "James hasn't messaged in 24 hours — WhatsApp only allows a call request by template then. " +
            "An admin can create it in Settings → WhatsApp calling."
        r.api.permissionError = refusal(409, "/admin/calls/request-permission", detail, "template_required", "admin", ""","route":"template"""")
        r.calls.sendCallRequest(); r.settle()
        assertEquals(detail, r.state.error)
        assertEquals(CallOutcome.PermissionNeeded, r.state.outcome)
        assertEquals(listOf(WrapAction.CallingSettings, WrapAction.Message, WrapAction.Cancel), r.state.wrapActions())
        // Asking again can't work: a second tap sends nothing.
        r.calls.sendCallRequest(); r.settle()
        assertEquals(1, r.api.log.count { it.startsWith("request-permission") })
        // Not an admin: no Settings button.
        val agent = r.state.copy(refusal = r.state.refusal!!.copy(adminCanFix = false))
        assertEquals(listOf(WrapAction.Message, WrapAction.Cancel), agent.wrapActions())
    }

    @Test fun theRequestLimitSaysWhenTheyCanAskAgain() = rig { r ->
        r.api.permission = meta(canCall = false)
        r.placeCall()
        r.api.permissionError = refusal(409, "/admin/calls/request-permission",
            "You've asked this customer recently — WhatsApp allows 1 request a day and 2 a week.", "138009", "wait",
            ""","request_available_at":"${inHours(5)}"""")
        r.calls.sendCallRequest(); r.settle()
        assertNull(r.state.error)
        assertEquals("You can ask again in 5 h", r.state.sendRequestBlocked())
        assertTrue(r.state.outcomeNote()!!.contains("You can ask again in 5 h"))
        r.calls.sendCallRequest(); r.settle()
        assertEquals("the button waits", 1, r.api.log.count { it.startsWith("request-permission") })
        // Known before anyone taps: Meta's can_request=false.
        val known = CallUiState(phase = CallPhase.Ended, outcome = CallOutcome.PermissionNeeded, from = james,
            permission = meta(canCall = false, canRequest = false, at = inHours(3)))
        assertEquals("You can ask again in 3 h", known.sendRequestBlocked())
    }

    @Test fun alreadyPermittedOffersCallNow() = rig { r ->
        r.api.permission = meta(canCall = false)
        r.placeCall()
        r.api.requestResponse = PermissionRequestResponse(permission = CallPermission(james, "granted", permanent = true), alreadyPermitted = true)
        r.calls.sendCallRequest(); r.settle()
        assertEquals(CallOutcome.AlreadyAllowed, r.state.outcome)
        assertEquals("James already allows calls — call now", r.state.statusText())
        assertEquals(listOf(WrapAction.CallNow, WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        r.api.permission = null
        r.calls.callNow(); r.settle()
        assertTrue("connect $james" in r.api.log)
    }

    @Test fun everyServerActionMapsToTheWrapUp() = rig { r ->
        fun fail(code: String, action: String, detail: String) {
            r.calls.dismiss()
            r.api.connectError = refusal(502, "/admin/calls/connect", "call failed: $detail", code, action)
            r.scope.launch { r.calls.initiateCall(james, "Deacon James Mwangi") }
            r.settle()
        }
        fail("190", "admin", "WhatsApp access token expired — an admin must renew it")
        assertEquals(CallOutcome.Failed("WhatsApp access token expired — an admin must renew it", "admin"), r.state.outcome)
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertEquals(CallManager.ADMIN_MUST_ACT, r.state.outcomeNote())
        fail("meta_unavailable", "retry", "WhatsApp isn't answering right now — try again.")
        assertEquals(listOf(WrapAction.TryAgain, WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertNull(r.state.outcomeNote())
        fail("rate_limited", "wait", "WhatsApp is rate-limiting us — try again in a minute.")
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertEquals(CallManager.WAIT_A_MOMENT, r.state.outcomeNote())
        fail("138000", "none", "This customer can't take WhatsApp calls.")
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertEquals(CallManager.MESSAGE_INSTEAD, r.state.outcomeNote())
        fail("138006", "request_permission", "This customer hasn't allowed calls yet.")
        assertEquals(CallOutcome.PermissionNeeded, r.state.outcome)
        assertEquals(WrapAction.SendCallRequest, r.state.wrapActions().first())
    }

    @Test fun structuredRefusalsReadTheirCodeActionAndFields() {
        val e = refusal(409, "/admin/calls/request-permission", "x", "138009", "wait", ""","request_available_at":"2026-09-28T10:00:00+00:00"""")
        assertEquals("138009", e.code); assertEquals("wait", e.action); assertEquals("x", e.detail)
        assertEquals("2026-09-28T10:00:00+00:00", e.field("request_available_at"))
        // The header alone (a body without `code`), and an older body with neither.
        assertEquals("190", ApiException(502, "POST", "/p", """{"detail":"call failed: x"}""", reasonHeader = "190").code)
        val old = ApiException(409, "POST", "/p", """{"detail":"no permission"}""")
        assertNull(old.code); assertNull(old.action); assertEquals("no permission", old.detail)
        assertNull(ApiException(502, "POST", "/p", "<html>bad gateway</html>").code)
    }

    @Test fun thePermissionIsSaidHonestly() {
        val now = AppClock.now()
        fun lines(p: CallPermission) = permissionLines(p, "James", now)
        assertEquals(listOf("Allowed permanently"), lines(meta(status = "granted", canCall = true, permanent = true)))
        assertEquals(listOf("Allowed until 3 Oct 2026"), lines(meta(status = "granted", canCall = true, expires = "2026-10-03T10:00:00+00:00")))
        assertEquals(listOf("Request sent 2h ago — waiting for James"),
            lines(meta(status = "requested", canCall = false, canRequest = false).copy(at = Instant.ofEpochMilli(now - 2 * 3_600_000L).toString())))
        assertEquals(listOf("James declined calls"), lines(meta(status = "denied", canCall = false)))
        assertEquals(listOf("Permission revoked after unanswered calls"), lines(meta(status = "denied", canCall = false, revoked = true)))
        assertEquals(listOf("James declined calls", "You can ask again in 5 h"),
            lines(meta(status = "denied", canCall = false, canRequest = false, at = inHours(5))))
        assertEquals("only when Meta gave it", listOf("Allowed permanently", "Calls left today: 3"),
            lines(meta(status = "granted", canCall = true, permanent = true, left = 3)))
        assertTrue(lines(meta()).isEmpty())
    }

    @Test fun aPermissionFrameUpdatesTheCardHonestly() = rig { r ->
        r.api.permission = meta(canCall = false)
        r.placeCall()
        r.raw("""{"type":"call_permission","wa_id":"$james","status":"denied","revoked":true,"reason":"automatic"}""")
        assertTrue(r.state.permission!!.revoked)
        assertTrue(r.state.outcomeNote()!!.startsWith("Permission revoked after unanswered calls"))
    }

    @Test fun voicemailShowsOnTheRowAndThePill() {
        val row = NeemaJson.decodeFromString(Call.serializer(),
            """{"call_id":"wacid.9","wa_id":"$james","direction":"inbound","status":"missed","has_voicemail":true}""")
        assertTrue(row.hasVoicemail)
        assertEquals("Missed call · voicemail", threadCallLabel("Missed call", row))
        assertEquals("Missed · voicemail", threadCallLabel("", row))
        assertEquals("Missed call", threadCallLabel("Missed call", row.copy(hasVoicemail = false)))
        assertFalse("an older row", NeemaJson.decodeFromString(Call.serializer(), """{"call_id":"x","status":"missed"}""").hasVoicemail)
    }

    @Test fun whatsAppsOwnTranscriptionIsSaidHonestly() = rig { r ->
        r.api.ice = r.api.ice.copy(record = false, metaTranscription = true)
        r.live()
        assertTrue("the card says WhatsApp records it", r.state.metaTranscription)
        advanceTimeBy(5_000); runCurrent()
        r.calls.hangup(); r.settle()
        assertEquals(CallManager.META_SUMMARY, r.state.recordingNote)
        // Recorded here as well: the usual note, with the summary promised.
        advanceTimeBy(13_000); runCurrent()
        r.api.ice = r.api.ice.copy(record = true, metaTranscription = true)
        r.live("wacid.2")
        r.calls.hangup(); r.settle()
        assertEquals(CallManager.RECORDING_SAVED_AUTO, r.state.recordingNote)
    }

    @Test fun twoSpeakerTranscriptsSplitIntoTurns() {
        assertEquals(
            listOf("Agent" to "Hello, Bethany House.", "Customer" to "Hi, I need a cassock size 54 please."),
            transcriptTurns("Agent: Hello, Bethany House.\n\ncustomer:  Hi, I need a cassock size 54 please."),
        )
        assertNull("plain text stays plain", transcriptTurns("Hello there, this is a transcript."))
        assertNull("another labelling stays plain", transcriptTurns("Agent: Good afternoon.\nCaller: Hello, Father Peter here."))
    }

    @Test fun aCallingRestrictionRaisesTheBanner() = rig { r ->
        assertNull(r.calls.restriction.value)
        r.raw("""{"type":"calling_restricted","event":"restricted","reasons":["LOW_PICKUP_RATE"],"at":"2026-09-27T09:00:00Z"}""")
        assertEquals(CallingRestriction(listOf("LOW_PICKUP_RATE"), "2026-09-27T09:00:00Z"), r.calls.restriction.value)
        assertEquals("Low pickup rate. Calls you place may fail until it lifts (up to 7 days).",
            ke.co.bethanyhouse.neema.feature.calls.restrictionText(r.calls.restriction.value!!))
        r.calls.dismissRestriction()
        assertNull(r.calls.restriction.value)
    }

    // ── The contract's words (§2.1) and a Messenger call's (§2.0) ───────────
    @Test fun theWordsMatchTheContractAndTheWeb() {
        val james = CallUiState(name = "Deacon James Mwangi", from = "254733444555", outbound = true)
        assertEquals("Declined by customer", callRowWords(Call(callId = "x", direction = "outbound", status = "rejected")).label)
        val declined = james.copy(phase = CallPhase.Ended, outcome = CallOutcome.Rejected, conversationId = "conv-james")
        assertEquals("James declined the call", declined.statusText())
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), declined.wrapActions())
        assertEquals(
            "James missed your last 3 calls — WhatsApp removes call permission after 4 in a row. Consider a message first.",
            james.copy(phase = CallPhase.RingingOut, permission = CallPermission(status = "granted", unansweredStreak = 3)).callCaution(),
        )
        assertEquals("Recorded by WhatsApp — summary in a minute", CallManager.META_SUMMARY)
        // Messenger: never a PSID, the app named, the permission words its own.
        val m = CallUiState(from = "7788990011", channel = "messenger")
        assertEquals("Messenger caller", m.who)
        assertEquals("Messenger", m.app)
        assertNull(m.number)
        assertEquals("This customer hasn't allowed Messenger calls yet", m.copy(phase = CallPhase.Ended, outcome = CallOutcome.PermissionNeeded).statusText())
        assertEquals("The customer declined the call", m.copy(phase = CallPhase.Ended, outcome = CallOutcome.Rejected, outbound = true).statusText())
        assertEquals("Grace hasn't allowed Messenger calls yet",
            m.copy(name = "Grace Wanjiku", phase = CallPhase.Ended, outcome = CallOutcome.PermissionNeeded).statusText())
        assertEquals("Messenger caller", WaitingCall("c_1", "7788990011", null, "messenger").who)
        assertEquals("+254712345678", WaitingCall("w_1", "254712345678", null).who)
        assertEquals("Allowed calls", permissionLines(CallPermission(status = "granted"), "James", AppClock.now()).first())
        assertEquals("James hasn't allowed calls yet",
            permissionLines(CallPermission(status = "unknown", metaStatus = "no_permission"), "James", AppClock.now()).first())
    }
}
