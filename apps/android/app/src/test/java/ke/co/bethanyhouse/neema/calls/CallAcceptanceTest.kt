package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.calls.AudioRoute
import ke.co.bethanyhouse.neema.feature.calls.AudioRouteKind
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallOutcome
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.PermissionGrant
import ke.co.bethanyhouse.neema.feature.calls.WrapAction
import ke.co.bethanyhouse.neema.feature.calls.outcomeNote
import ke.co.bethanyhouse.neema.feature.calls.statusText
import ke.co.bethanyhouse.neema.feature.calls.wrapActions
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.time.Instant

/**
 * The owner's Final Acceptance Test (docs/CALLING_UX.md), scenario by
 * scenario, on the real [CallManager] with the fake API, frames, socket,
 * foreground, peer, ringer, audio and clock: the phase, the outcome, the
 * exact words the agent reads, the actions the card offers, what the ringer
 * and notification did, and every request that went to the server.
 *
 * The web passed the same 20 scenarios; where the web had a bug the run
 * found (a dropped call's length counting the reconnect grace, an answer lost
 * mid-flight ringing again, a decline refused with 409 saying "declined",
 * End while connecting, "your other device"), the Android behaviour is
 * pinned here too.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallAcceptanceTest {
    private val base = Instant.parse("2026-09-26T10:00:00Z").toEpochMilli()

    private val peter = "254712345678"
    private val james = "254733444555"

    private inner class Rig(val scope: TestScope) {
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
            myAgentId = { "agent-me" }, myAgentName = { "Moses Mwicigi" },
        ).also { it.start() }
        val state get() = calls.state.value
        val words get() = state.statusText()

        fun raw(json: String) {
            frames.tryEmit(NeemaJson.parseToJsonElement(json) as JsonObject)
            scope.runCurrent()
        }
        fun settle() = scope.runCurrent()
        fun pass(ms: Long) { scope.advanceTimeBy(ms); scope.runCurrent() }
        fun at(ago: Long) = Instant.ofEpochMilli(base + scope.testScheduler.currentTime - ago).toString()
        fun count(prefix: String) = api.log.count { it.startsWith(prefix) }

        fun ring(id: String = "wacid.1", from: String = peter, name: String = "Fr. Peter Kamau", conv: String? = "conv-peter") =
            raw("""{"type":"incoming_call","call_id":"$id","from":"$from","name":"$name","at":"1","channel":"whatsapp","conversation_id":${conv?.let { "\"$it\"" } ?: "null"}}""")
        fun answered(id: String, agentId: String, agent: String, direction: String = "inbound") =
            raw("""{"type":"call_answered","call_id":"$id","agent_id":"$agentId","agent_name":"$agent","direction":"$direction"}""")
        fun ended(id: String, outcome: String, agentId: String? = null, agent: String? = null, duration: Int? = null) =
            raw("""{"type":"call_ended","call_id":"$id","outcome":"$outcome","status":"COMPLETED","duration":${duration ?: "null"},"direction":"inbound","agent_id":${agentId?.let { "\"$it\"" } ?: "null"},"agent_name":${agent?.let { "\"$it\"" } ?: "null"}}""")
        /** Ring, answer, audio flowing. */
        fun live(id: String = "wacid.1"): FakePeer {
            ring(id); calls.answer(); settle()
            media.peer.onEvent(PeerEvent.Connected); settle()
            return media.peer
        }
        fun place(to: String = james, name: String = "Deacon James Mwangi"): Deferred<Result<Unit>> =
            scope.async { calls.initiateCall(to, name) }.also { settle() }
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest { val r = Rig(this); r.settle(); block(r) }

    private fun err(status: Int, path: String, detail: String) = ApiException(status, "POST", path, """{"detail":"$detail"}""")
    private fun offline(path: String) = ApiException(0, "GET", path, "Failed to connect to neema.bethanyhouse.co.ke")
    private fun timeout(path: String) = ApiException(0, "POST", path, "timed out after 30s")

    // ── 1. An incoming call, one agent ──────────────────────────────────────
    @Test fun s01_incomingCallOneAgent() = rig { r ->
        r.ring()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("Fr. Peter Kamau", r.state.who)
        assertEquals("Incoming…", r.words)
        assertTrue("the phone rings", r.ringer.ringing)
        assertTrue("on screen: the card is the alert, no notification", r.ringer.posted.isEmpty())
        r.calls.answer(); r.settle()
        assertEquals(CallPhase.Connecting, r.state.phase)
        assertEquals("Connecting…", r.words)
        assertFalse("ringing stops the moment Answer is tapped", r.ringer.ringing)
        assertEquals(listOf("ice-config", "offer wacid.1", "answer wacid.1"), r.api.log.filter { !it.startsWith("list") })
        assertEquals("our answer carries the gathered candidates", "setLocal(Answer,v=0 our-answer)+candidates", r.api.lastAnswerSdp)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertEquals("00:00", r.words)
        assertTrue("● Recording only while a recording really runs", r.state.recording)
        r.pass(65_000)
        assertEquals("01:05", r.words)
        r.calls.hangup(); r.settle()
        assertEquals(CallOutcome.Completed, r.state.outcome)
        assertEquals("Call ended · 1:05", r.words)
        assertEquals(listOf(WrapAction.OpenChat, WrapAction.CallAgain, WrapAction.Done), r.state.wrapActions())
        assertEquals(1, r.count("terminate wacid.1"))
        assertFalse(r.audio.inCall)
        r.pass(8_001)
        assertEquals("a neutral wrap-up closes by itself", CallPhase.Idle, r.state.phase)
    }

    // ── 2. Several agents: a colleague answers ──────────────────────────────
    @Test fun s02_colleagueAnswersFirst() = rig { r ->
        r.ring()
        r.answered("wacid.1", "agent-ann", "Ann Wanjiru")
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallOutcome.AnsweredElsewhere("Ann Wanjiru"), r.state.outcome)
        assertEquals("Answered by Ann", r.words)
        assertFalse("ringing stopped", r.ringer.ringing)
        assertFalse(r.ringer.showing)
        assertEquals("no answer POST from this phone", 0, r.count("answer"))
        assertEquals(0, r.count("terminate"))
        assertEquals(listOf(WrapAction.Done), r.state.wrapActions())
        r.pass(4_001)
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun s02_answeredOnMyOtherDeviceSaysSo() = rig { r ->
        r.ring()
        r.answered("wacid.1", "agent-me", "Moses Mwicigi")
        assertEquals(CallOutcome.AnsweredElsewhere("Moses Mwicigi", mine = true), r.state.outcome)
        assertEquals("Answered on your other device", r.words)
        // A colleague's answer never says "your other device".
        r.ring("wacid.2"); r.answered("wacid.2", "agent-ann", "Ann Wanjiru")
        assertEquals("Answered by Ann", r.words)
    }

    // ── 3. Decline ──────────────────────────────────────────────────────────
    @Test fun s03_decline() = rig { r ->
        r.ring()
        r.calls.hangup(); r.settle()   // the Decline button ("Decline call")
        assertEquals(CallOutcome.Declined(), r.state.outcome)
        assertEquals("Call declined", r.words)
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertEquals("declined for the whole team", 1, r.count("terminate wacid.1"))
        assertFalse(r.ringer.ringing)
        r.pass(5_001)
        assertEquals(CallPhase.Idle, r.state.phase)
        // The still-"ringing" row must not ring it again.
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", waId = peter, status = "ringing", startedAt = r.at(8_000)))
        r.calls.pollOnce(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun s03_declineFromAColleagueSaysWho() = rig { r ->
        r.ring()
        r.ended("wacid.1", "declined", agentId = "agent-ann", agent = "Ann Wanjiru")
        assertEquals("Declined by Ann", r.words)
    }

    // ── 4. Missed ───────────────────────────────────────────────────────────
    @Test fun s04_missed() = rig { r ->
        r.ring()
        r.ended("wacid.1", "missed")
        assertEquals(CallOutcome.Missed(), r.state.outcome)
        assertEquals("Missed call", r.words)
        assertEquals(listOf(WrapAction.CallBack, WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        assertFalse(r.ringer.ringing)
        r.pass(60_000)
        assertEquals("a call back is owed: the card waits", CallPhase.Ended, r.state.phase)
        // Call back: straight out to them.
        r.calls.redial(); r.settle()
        assertEquals(1, r.count("connect $peter"))
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
        assertEquals(CallPhase.RingingOut, r.state.phase)
        assertEquals("the same customer, the same name", "Fr. Peter Kamau", r.state.who)
    }

    // ── 5. Outgoing ─────────────────────────────────────────────────────────
    @Test fun s05_outgoing() = rig { r ->
        r.api.connectGate = CompletableDeferred()
        val call = r.place()
        assertEquals(CallPhase.Placing, r.state.phase)
        assertEquals("Calling…", r.words)
        assertTrue(r.audio.inCall)
        assertTrue("never the loudspeaker by itself", !r.audio.speakerOn)
        r.api.connectGate!!.complete(Unit); r.settle()
        assertTrue(call.await().isSuccess)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
        assertEquals(CallPhase.RingingOut, r.state.phase)
        assertEquals("Ringing…", r.words)
        assertEquals(Triple(james, "setLocal(Offer,v=0 our-offer)+candidates", "Deacon James Mwangi"), r.api.lastConnect)
        r.raw("""{"type":"outbound_answer","call_id":"wacid.out1","sdp":"v=0 their-answer"}""")
        assertEquals(CallPhase.Connecting, r.state.phase)
        assertTrue("setRemote(Answer,v=0 their-answer)" in r.media.peer.ops)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertEquals("00:00", r.words)
        assertFalse("an outbound call never rings this phone", r.ringer.ringStarts > 0)
    }

    // ── 6. Permission required → request → granted → Call now ───────────────
    @Test fun s06_permissionRequiredThenGranted() = rig { r ->
        r.api.connectError = err(409, "/admin/calls/connect", "No call permission")
        r.place().await()
        assertEquals(CallOutcome.PermissionNeeded, r.state.outcome)
        assertEquals("James hasn't allowed WhatsApp calls yet", r.words)
        assertEquals(CallManager.PERMISSION_EXPLAINED, r.state.outcomeNote())
        assertEquals(listOf(WrapAction.SendCallRequest, WrapAction.Message, WrapAction.Cancel), r.state.wrapActions())
        assertEquals("the request messages the customer: never sent by itself", 0, r.count("request-permission"))
        r.calls.sendCallRequest(); r.settle()
        assertEquals(1, r.count("request-permission $james"))
        assertEquals(CallOutcome.PermissionRequested, r.state.outcome)
        assertEquals("Call request sent — you'll be told when James taps Allow", r.words)
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        // They tap Allow.
        r.raw("""{"type":"call_permission","wa_id":"$james","status":"granted","expires_at":null,"permanent":false}""")
        assertEquals(PermissionGrant(james, "Deacon James Mwangi"), r.calls.permissionGranted.value)
        assertEquals("the banner replaces the wrap-up", CallPhase.Idle, r.state.phase)
        r.api.connectError = null
        r.calls.callGranted(); r.settle()
        assertNull(r.calls.permissionGranted.value)
        assertEquals(2, r.count("connect $james"))
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
        assertEquals(CallPhase.RingingOut, r.state.phase)
    }

    @Test fun s06_alreadyRequestedSaysSoAtOnce() = rig { r ->
        r.api.connectError = err(409, "/admin/calls/connect", "No call permission")
        r.api.permissionStatus = "requested"
        r.place().await()
        assertEquals(CallOutcome.PermissionRequested, r.state.outcome)
        assertEquals(0, r.count("request-permission"))
    }

    // ── 7. Customer unavailable ─────────────────────────────────────────────
    @Test fun s07_customerUnavailable() = rig { r ->
        r.api.connectError = err(502, "/admin/calls/connect", "call failed: The customer's phone is switched off")
        r.place().await()
        assertEquals(CallOutcome.Failed("The customer's phone is switched off"), r.state.outcome)
        assertEquals("The customer's phone is switched off", r.words)
        assertEquals(listOf(WrapAction.TryAgain, WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        r.pass(60_000)
        assertEquals(CallPhase.Ended, r.state.phase)
        assertFalse(r.audio.inCall)
        assertTrue(r.media.peer.closed)
    }

    // ── 8. Answered while another agent is answering ────────────────────────
    @Test fun s08_answer409SaysWhoTookIt() = rig { r ->
        r.api.answerError = err(409, "/admin/calls/wacid.1/answer", "call already answered by Ann Wanjiru")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallOutcome.AnsweredElsewhere("Ann Wanjiru"), r.state.outcome)
        assertEquals("Answered by Ann", r.words)
        assertEquals("the colleague's live call is never cut off", 0, r.count("terminate"))
        assertTrue(r.media.peer.closed)
    }

    @Test fun s08_answer409NamingMeIsMyOtherDevice() = rig { r ->
        r.api.answerError = err(409, "/admin/calls/wacid.1/answer", "call already answered by Moses Mwicigi")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals("Answered on your other device", r.words)
    }

    @Test fun s08_decline409SaysAnsweredNotDeclined() = rig { r ->
        r.api.terminateErrors += err(409, "/admin/calls/wacid.1/terminate", "call already answered by Ann Wanjiru")
        r.ring()
        r.calls.hangup(); r.settle()
        assertEquals("Answered by Ann", r.words)
        assertEquals(CallOutcome.AnsweredElsewhere("Ann Wanjiru"), r.state.outcome)
        assertEquals("the refusal is final: no retry", 1, r.count("terminate"))
        r.pass(4_001)
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun s08_callback409SaysAnsweredNotSaved() = rig { r ->
        r.api.callbackErrors += err(409, "/admin/calls/wacid.1/callback", "call already answered by Ann Wanjiru")
        r.ring()
        r.calls.callback(); r.settle()
        assertEquals("Answered by Ann", r.words)
        assertEquals(1, r.count("callback wacid.1"))
    }

    @Test fun s08_endWhileConnectingBeforeTheAnswerWasAcceptedIsADecline() = rig { r ->
        r.api.answerGate = CompletableDeferred()   // the server hasn't accepted our answer yet
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallPhase.Connecting, r.state.phase)
        assertEquals(1, r.count("answer wacid.1"))
        r.calls.hangup(); r.settle()
        assertEquals(CallOutcome.Declined(), r.state.outcome)
        assertEquals("Call declined", r.words)
        assertEquals(1, r.count("terminate wacid.1"))
        // Once accepted, End ends a call.
        r.api.answerGate = null
        r.pass(13_000)
        r.ring("wacid.2"); r.calls.answer(); r.settle()
        r.calls.hangup(); r.settle()
        assertEquals(CallOutcome.Completed, r.state.outcome)
    }

    // ── 9. Network loss before answering ────────────────────────────────────
    @Test fun s09_noConnectionKeepsItRingingAndAnswerRetries() = rig { r ->
        r.api.iceError = offline("/admin/calls/ice-config")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("Incoming…", r.words)
        assertEquals("No connection — can't answer yet", r.state.error)
        assertTrue("still ringing", r.ringer.ringing)
        assertEquals(0, r.count("answer"))
        r.api.iceError = null
        r.calls.answer(); r.settle()
        assertEquals(CallPhase.Connecting, r.state.phase)
        assertNull(r.state.error)
        assertEquals(1, r.count("answer wacid.1"))
    }

    @Test fun s09_answerLostInFlightEndsAndHangsUpNeverRingsAgain() = rig { r ->
        r.api.answerError = timeout("/admin/calls/wacid.1/answer")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallPhase.Connecting, r.state.phase)
        r.pass(CallManager.ANSWER_CONFIRM_MS + 1)
        r.pass(1_801)
        assertEquals(CallOutcome.Failed(CallManager.ANSWER_DROPPED), r.state.outcome)
        assertEquals("The connection dropped while answering — call them back", r.words)
        assertEquals("nobody left on a silent line", 1, r.count("terminate wacid.1"))
        assertEquals("never rang again", 1, r.ringer.ringStarts)
        assertEquals(listOf(WrapAction.CallBack, WrapAction.Message, WrapAction.Done), r.state.wrapActions())
    }

    // ── 10. Network loss during a call ──────────────────────────────────────
    @Test fun s10_reconnectingIsHonest() = rig { r ->
        val p = r.live()
        r.pass(30_000)
        assertEquals("00:30", r.words)
        p.onEvent(PeerEvent.Interrupted); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertTrue(r.state.reconnecting)
        assertEquals("the timer never shows while nothing flows", "Reconnecting…", r.words)
        r.pass(5_000)
        assertEquals("Reconnecting…", r.words)
        assertEquals(0, r.count("terminate"))
    }

    // ── 11. Reconnection ────────────────────────────────────────────────────
    @Test fun s11_mediaRecoversWithinTheGrace() = rig { r ->
        val p = r.live()
        r.pass(20_000)
        p.onEvent(PeerEvent.Interrupted); r.settle()
        r.pass(CallManager.ICE_GRACE_MS - 1_000)
        p.onEvent(PeerEvent.Connected); r.settle()
        assertFalse(r.state.reconnecting)
        assertEquals(CallPhase.InCall, r.state.phase)
        assertEquals("00:29", r.words)
        r.pass(60_000)
        assertEquals("the grace timer is gone: the call goes on", CallPhase.InCall, r.state.phase)
        assertEquals(0, r.count("terminate"))
    }

    @Test fun s11_socketReconnectRereadsTheCallAndTakesTheServersWord() = rig { r ->
        r.live()
        r.pass(40_000)
        r.connected.value = false; r.settle()
        // Only the call's own row answers (the log read fails): GET /calls/{id} alone corrects it.
        r.api.listError = offline("/admin/calls")
        // The customer hung up while this phone couldn't hear.
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", waId = peter, status = "completed", duration = 42, agentId = "agent-me", startedAt = r.at(60_000)))
        r.connected.value = true; r.settle()
        assertTrue("GET /calls/{id}", "get wacid.1" in r.api.log)
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallOutcome.Completed, r.state.outcome)
    }

    @Test fun s11_ringingCallThatEndedOfflineShowsItsRealOutcome() = rig { r ->
        r.ring()
        r.connected.value = false; r.settle()
        r.api.listError = offline("/admin/calls")
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", waId = peter, status = "missed", startedAt = r.at(30_000)))
        r.connected.value = true; r.settle()
        assertEquals("Missed call", r.words)
        assertTrue("get wacid.1" in r.api.log)
        assertFalse(r.ringer.ringing)
    }

    // ── 12. Bluetooth / headset switching ───────────────────────────────────
    @Test fun s12_headsetsComeAndGoNeverTheSpeaker() = rig { r ->
        val buds = AudioRoute(AudioRouteKind.Bluetooth, "Pixel Buds")
        val wired = AudioRoute(AudioRouteKind.Wired)
        r.audio.plug(buds); r.settle()
        assertTrue("a headset: Audio opens a list", r.state.routeChoice)
        r.live()
        assertEquals("a call starts on the connected headset", buds, r.audio.route)
        r.audio.plug(wired); r.settle()
        assertEquals("a headset plugged in mid-call takes it", wired, r.audio.route)
        r.calls.selectRoute(buds); r.settle()
        assertEquals(buds, r.audio.route)
        assertEquals(buds, r.state.route)
        r.audio.unplug(buds); r.settle()
        assertEquals("the route in use gone: the other headset", wired, r.audio.route)
        r.audio.unplug(wired); r.settle()
        assertEquals("…then the earpiece, never the loudspeaker", AudioRoute.Earpiece, r.audio.route)
        assertFalse(r.audio.speakerOn)
        assertFalse(r.state.routeChoice)
        r.calls.toggleSpeaker(); r.settle()
        assertTrue(r.audio.speakerOn)
        r.calls.toggleSpeaker(); r.settle()
        assertEquals(AudioRoute.Earpiece, r.audio.route)
    }

    // ── 13. Background / locked phone ───────────────────────────────────────
    @Test fun s13_lockedPhoneNotificationAnswersInOneTap() = rig { r ->
        r.foreground.value = false; r.settle()
        r.ring()
        assertEquals(listOf(Triple("wacid.1", "Fr. Peter Kamau", peter)), r.ringer.posted)
        assertTrue(r.ringer.showing)
        assertTrue(r.ringer.ringing)
        r.calls.handleAction("answer", "wacid.1"); r.settle()
        assertEquals("one tap: straight to Connecting on the full card", CallPhase.Connecting, r.state.phase)
        assertFalse(r.state.minimised)
        assertFalse(r.ringer.showing)
        assertFalse(r.ringer.ringing)
        assertEquals(1, r.count("answer wacid.1"))
    }

    @Test fun s13_lockedPhoneNotificationDeclines() = rig { r ->
        r.foreground.value = false; r.settle()
        r.ring("wacid.7", name = "Grace Achieng")
        assertEquals("Grace Achieng", r.ringer.posted.single().second)
        r.calls.handleAction("decline", "wacid.7"); r.settle()
        assertEquals(CallOutcome.Declined(), r.state.outcome)
        assertEquals(1, r.count("terminate wacid.7"))
        assertFalse(r.ringer.showing)
        // Back on screen: nothing posted again.
        r.foreground.value = true; r.settle()
        assertEquals(1, r.ringer.posted.size)
    }

    // ── 14. Cancellation ────────────────────────────────────────────────────
    @Test fun s14_hangingUpOurCallBeforeTheyAnswer() = rig { r ->
        r.api.connectGate = CompletableDeferred()
        val call = r.place()
        r.calls.hangup(); r.settle()
        assertEquals(CallOutcome.Cancelled, r.state.outcome)
        assertEquals("Call cancelled", r.words)
        assertEquals(listOf(WrapAction.Done), r.state.wrapActions())
        // Meta placed it after all: it is hung up, their phone doesn't keep ringing.
        r.api.connectGate!!.complete(Unit); r.settle()
        call.await()
        assertEquals(1, r.count("terminate wacid.out1"))
        r.pass(2_001)
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun s14_cancelWhileItRingsThem() = rig { r ->
        r.place().await()
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        assertEquals(CallPhase.Placing, r.state.phase); r.raw("""{"type":"call_status","call_id":"${r.api.connectId}","status":"ringing"}""")
        assertEquals(CallPhase.RingingOut, r.state.phase)
        r.calls.hangup(); r.settle()
        assertEquals("Call cancelled", r.words)
        assertEquals(1, r.count("terminate wacid.out1"))
    }

    @Test fun s14_theyDontPickUp() = rig { r ->
        r.place().await()
        r.ended("wacid.out1", "no_answer")
        assertEquals("No answer", r.words)
        assertEquals(listOf(WrapAction.CallAgain, WrapAction.Message, WrapAction.Done), r.state.wrapActions())
    }

    // ── 15. Call dropped ────────────────────────────────────────────────────
    @Test fun s15_droppedCallSaysTheConnectedTime() = rig { r ->
        val p = r.live()
        r.pass(133_000)
        p.onEvent(PeerEvent.Interrupted); r.settle()
        r.pass(CallManager.ICE_GRACE_MS + 1)
        assertEquals(CallOutcome.ConnectionLost, r.state.outcome)
        assertEquals("the grace is not call time", "Call dropped · 2:13 — the connection was lost", r.words)
        assertEquals(1, r.count("terminate wacid.1"))
        assertEquals(listOf(WrapAction.CallAgain, WrapAction.OpenChat, WrapAction.Done), r.state.wrapActions())
        assertFalse(r.audio.inCall)
        r.pass(60_000)
        assertEquals("a call back is owed: the card waits", CallPhase.Ended, r.state.phase)
    }

    @Test fun s15_audioThatNeverArrivedIsNotACallDropped() = rig { r ->
        r.ring(); r.calls.answer(); r.settle()
        r.pass(CallManager.CONNECT_GUARD_MS + 1)
        assertEquals("never stuck on Connecting…", "The call audio couldn't connect", r.words)
        assertEquals(1, r.count("terminate wacid.1"))
    }

    // ── 16. Recording enabled / disabled ────────────────────────────────────
    @Test fun s16_recordingOn() = rig { r ->
        r.live()
        assertTrue(r.state.recording)
        assertEquals(1, r.media.recordings.size)
        r.pass(20_000)
        r.calls.hangup(); r.settle()
        assertFalse(r.state.recording)
        assertTrue(r.media.recordings.single().stopped)
        assertEquals("Recording saved", r.state.recordingNote)
        assertEquals(listOf("wacid.1"), r.api.uploads.map { it.first })
    }

    @Test fun s16_recordingOff() = rig { r ->
        r.api.ice = IceConfig(record = false)
        r.live()
        assertFalse("no ● Recording when nothing records", r.state.recording)
        assertTrue(r.media.recordings.isEmpty())
        r.calls.hangup(); r.settle()
        assertNull(r.state.recordingNote)
        assertEquals(0, r.count("recording"))
    }

    // ── 17. Completed with transcription ────────────────────────────────────
    @Test fun s17_completedWithTranscription() = rig { r ->
        r.api.ice = IceConfig(record = true, transcribe = true, autoTranscribe = true)
        r.live()
        r.pass(252_000)
        r.calls.hangup(); r.settle()
        assertEquals("Call ended · 4:12", r.words)
        assertEquals("Recording saved — summary in a minute", r.state.recordingNote)
        assertEquals(listOf("wacid.1"), r.api.uploads.map { it.first })
        r.pass(7_999)
        assertEquals("long enough to read the recording line", CallPhase.Ended, r.state.phase)
    }

    // ── 18. Without transcription ───────────────────────────────────────────
    @Test fun s18_withoutTranscription() = rig { r ->
        r.api.ice = IceConfig(record = true, transcribe = true, autoTranscribe = false)
        r.live(); r.calls.hangup(); r.settle()
        assertEquals("Recording saved — Transcribe from Calls", r.state.recordingNote)
        r.pass(13_000)
        r.api.ice = IceConfig(record = true, transcribe = false)
        r.live("wacid.2"); r.calls.hangup(); r.settle()
        assertEquals("Recording saved", r.state.recordingNote)
    }

    // ── 20. Back into the conversation ──────────────────────────────────────
    @Test fun s20_openChatFromALiveCallMinimisesIt() = rig { r ->
        r.live()
        assertEquals("Chat opens the customer's WhatsApp conversation", peter, r.calls.openChat())
        assertTrue(r.state.minimised)
        assertEquals("the call goes on in the bar", CallPhase.InCall, r.state.phase)
        assertEquals(0, r.count("terminate"))
        r.calls.expand()
        assertFalse(r.state.minimised)
    }

    @Test fun s20_openChatFromTheWrapUpClosesIt() = rig { r ->
        r.live(); r.calls.hangup(); r.settle()
        assertEquals(peter, r.calls.openChat())
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    // ── Around the scenarios ────────────────────────────────────────────────
    @Test fun aSecondCallerIsABannerNeverATakeOver() = rig { r ->
        r.live()
        r.ring("wacid.2", from = "254722000111", name = "Grace Achieng")
        assertEquals("wacid.1", r.state.callId)
        assertEquals(CallPhase.InCall, r.state.phase)
        assertEquals("Grace Achieng", r.state.waiting?.who)
        assertEquals("the live call is not interrupted by a ring", 1, r.ringer.ringStarts)
        r.calls.declineWaiting(); r.settle()
        assertNull(r.state.waiting)
        assertEquals(1, r.count("terminate wacid.2"))
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    @Test fun aNewRingReplacesAWrapUp() = rig { r ->
        r.ring(); r.ended("wacid.1", "missed")
        assertEquals(CallPhase.Ended, r.state.phase)
        r.ring("wacid.3", name = "Grace Achieng")
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("wacid.3", r.state.callId)
        assertEquals("Grace Achieng", r.state.who)
        assertNull(r.state.outcome)
    }

    @Test fun nameAndNumberNeverChangeMidCall() = rig { r ->
        r.live()
        val row = """{"id":"k1","call_id":"wacid.1","wa_id":"254799999999","name":"Somebody Else","conversation_id":"conv-x","direction":"inbound","status":"answered","agent_id":"agent-me"}"""
        r.raw("""{"type":"call_update","call":$row}""")
        assertEquals("Fr. Peter Kamau", r.state.who)
        assertEquals(peter, r.state.from)
        assertEquals(CallPhase.InCall, r.state.phase)
    }
    // ── 21. The 2026-09 refresh, end to end: permission truth → request → Allow → ringing → declined ──
    @Test fun s21_permissionTruthThenRingingThenDeclined() = rig { r ->
        r.api.permission = CallPermission(james, "unknown", metaStatus = "no_permission", canCall = false, canRequest = true,
            unansweredStreak = 0, source = "meta")
        r.place().await()
        assertEquals("James hasn't allowed WhatsApp calls yet", r.words)
        assertEquals("no doomed connect", 0, r.count("connect"))
        r.calls.sendCallRequest(); r.settle()
        assertEquals(CallOutcome.PermissionRequested, r.state.outcome)
        r.raw("""{"type":"call_permission","wa_id":"$james","status":"granted","expires_at":null,"permanent":true}""")
        assertNotNull(r.calls.permissionGranted.value)
        // Call now: Meta now says yes.
        r.api.permission = CallPermission(james, "granted", permanent = true, metaStatus = "permanent", canCall = true, source = "meta")
        r.calls.callGranted(); r.settle()
        assertEquals(1, r.count("connect $james"))
        assertEquals("Calling…", r.words)
        r.raw("""{"type":"call_status","call_id":"wacid.out1","status":"ringing"}""")
        assertEquals("Ringing…", r.words)
        r.raw("""{"type":"call_ended","call_id":"wacid.out1","outcome":"rejected","status":"REJECTED","direction":"outbound"}""")
        assertEquals("James declined the call", r.words)
        assertEquals(listOf(WrapAction.Message, WrapAction.Done), r.state.wrapActions())
        r.pass(60_000)
        assertEquals("the agent decides what's next", CallPhase.Ended, r.state.phase)
    }
}

/**
 * The scenarios that end in the Calls view and the inbox (17, 19, 20): the
 * call's `call_update` reaching its history row, "Mark follow-up done", and
 * "Open chat" landing on the right conversation.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallAcceptanceHistoryTest {
    @get:Rule val paparazzi = Paparazzi()

    @Before fun main() { Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun reset() { Dispatchers.resetMain() }

    @Test fun s17_theSummaryReachesTheHistoryRow() {
        val dash = dashboard(paparazzi.context, FakeNeema.withFixtures().also(CallsFixtures::install))
        val vm = CallsViewModel(dash)
        val before = vm.calls.value!!.first { it.callId == CallsFixtures.C1 }
        val row = CallsFixtures.row(
            before.id, CallsFixtures.C1, before.waId, before.name, "inbound", "completed", 184, "Moses Mwicigi",
            before.startedAt, "Wants two shirts by Friday.", "done", true,
            insights = """{"next_action":"Send the price list","follow_up_message":"Here are the prices, Father."}""",
        )
        vm.mergeRow(NeemaJson.parseToJsonElement(row) as JsonObject)
        val after = vm.calls.value!!.first { it.callId == CallsFixtures.C1 }
        assertEquals("Wants two shirts by Friday.", after.summary)
        assertEquals("done", after.transcriptStatus)
        assertEquals("Here are the prices, Father.", after.insights?.followUpMessage)
        assertEquals("merged in place, not duplicated", 1, vm.calls.value!!.count { it.callId == CallsFixtures.C1 })
    }

    @Test fun s19_followUpDoneLeavesFollowUps() {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        val vm = CallsViewModel(dashboard(paparazzi.context, fake))
        val owed = vm.calls.value!!.filter { it.followUpOpen }
        assertTrue(owed.isNotEmpty())
        val first = owed.first()
        vm.markFollowUpDone(first)
        assertEquals(1, fake.callsTo("POST", CallsFixtures.path(first.callId, "follow-up-done")).size)
        assertFalse("off the Follow-ups list", vm.calls.value!!.first { it.callId == first.callId }.followUpOpen)
        assertEquals(owed.size - 1, vm.calls.value!!.count { it.followUpOpen })
    }

    @Test fun s20_openChatLandsOnTheCustomersConversation() {
        val dash = dashboard(paparazzi.context, FakeNeema.withFixtures())
        // What CallStage's Chat / Message / Open chat does with CallManager.openChat()'s key.
        dash.openConversationFor("254712345678")
        assertEquals("254712345678", dash.openConvKey.value)
        assertEquals(ViewId.Conversations, dash.view.value)
        assertNotNull(dash.openConvKey.value)
    }

    // ── 22. Voicemail: the log's row and a live row update carry it ─────────
    @Test fun s22_voicemailReachesTheLog() {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        val vm = CallsViewModel(dashboard(paparazzi.context, fake))
        val c2 = vm.calls.value!!.first { it.callId == CallsFixtures.C2 }
        assertFalse(c2.hasVoicemail)
        val row = CallsFixtures.row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b02", CallsFixtures.C2, "254722000111", "Rev. Mary Achieng",
            "inbound", "missed", null, null, CallsFixtures.pyIso(130), null, "none", false).replace("\"has_recording\":false", "\"has_recording\":false,\"has_voicemail\":true")
        vm.mergeRow(NeemaJson.parseToJsonElement(row) as JsonObject)
        assertTrue(vm.calls.value!!.first { it.callId == CallsFixtures.C2 }.hasVoicemail)
    }
}
