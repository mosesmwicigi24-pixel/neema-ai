package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.feature.calls.CallApi
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallMedia
import ke.co.bethanyhouse.neema.feature.calls.CallOutcome
import ke.co.bethanyhouse.neema.feature.calls.CallPeer
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallRecording
import ke.co.bethanyhouse.neema.feature.calls.MESSENGER
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.SdpType
import ke.co.bethanyhouse.neema.feature.calls.WHATSAPP
import ke.co.bethanyhouse.neema.feature.calls.rtcGuard
import kotlinx.coroutines.CompletableDeferred
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
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * "The app closes when I call a customer on WhatsApp": every step of placing
 * and answering a call — on WhatsApp and on Messenger — is made to fail with
 * the kind of throwable a device's audio stack or WebRTC's native side throws
 * (an Error, not an Exception). The call must end on the card, the audio and
 * peer must be let go, nothing may escape to the caller's viewModelScope, and
 * the very next call must go through.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallResilienceTest {
    private val base = Instant.parse("2026-09-29T10:00:00Z").toEpochMilli()

    /** Where a fault can be injected. */
    enum class Step { CreatePeer, AddMic, CreateOffer, CreateAnswer, SetLocal, SetRemote, StartRecording }

    /** A native-side failure, as an UnsatisfiedLinkError or a device's audio HAL throws it. */
    class NativeBoom(step: Step) : Error("native failure at $step")

    /** [FakeMedia] with one-shot faults: each armed step throws once, then works again. */
    class FlakyMedia(val inner: FakeMedia = FakeMedia()) : CallMedia {
        val faults = mutableMapOf<Step, Throwable>()
        val peers = mutableListOf<FlakyPeer>()
        val peer get() = peers.last()
        fun arm(step: Step, t: Throwable = NativeBoom(step)) { faults[step] = t }
        fun fire(step: Step) { faults.remove(step)?.let { throw it } }
        override fun createPeer(config: IceConfig, onEvent: (PeerEvent) -> Unit): CallPeer {
            fire(Step.CreatePeer)
            return FlakyPeer(inner.createPeer(config, onEvent) as FakePeer, this).also { peers += it }
        }
        override fun startRecording(micMuted: Boolean): CallRecording { fire(Step.StartRecording); return inner.startRecording(micMuted) }
    }

    class FlakyPeer(val inner: FakePeer, private val m: FlakyMedia) : CallPeer by inner {
        override fun addMic(enabled: Boolean) { m.fire(Step.AddMic); inner.addMic(enabled) }
        override suspend fun createOffer(): String { m.fire(Step.CreateOffer); return inner.createOffer() }
        override suspend fun createAnswer(): String { m.fire(Step.CreateAnswer); return inner.createAnswer() }
        override suspend fun setLocal(type: SdpType, sdp: String) { m.fire(Step.SetLocal); inner.setLocal(type, sdp) }
        override suspend fun setRemote(type: SdpType, sdp: String) { m.fire(Step.SetRemote); inner.setRemote(type, sdp) }
    }

    /** [FakeCallApi] whose connect can throw any Throwable (FakeCallApi only throws Exceptions). */
    class ThrowingApi(val inner: FakeCallApi) : CallApi by inner {
        var connectFault: Throwable? = null
        override suspend fun connect(to: String, sdp: String, name: String?): String {
            connectFault?.let { connectFault = null; throw it }
            return inner.connect(to, sdp, name)
        }
    }

    private inner class Rig(val scope: TestScope) {
        val api = FakeCallApi()
        val throwing = ThrowingApi(api)
        val media = FlakyMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val connected = MutableStateFlow(true)
        var mic = true
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = throwing, events = frames, connected = connected, scope = scope.backgroundScope, foreground = MutableStateFlow(true),
            signedInFn = { true }, media = media, ringer = ringer, audio = audio,
            micGranted = { mic }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
        ).also { it.start() }
        val state get() = calls.state.value

        fun frame(vararg kv: Pair<String, String>) {
            frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) }))
            scope.runCurrent()
        }
        fun settle() = scope.runCurrent()
        /** Let any wrap-up close itself, back to Idle. */
        fun drain() { scope.advanceTimeBy(60_000); scope.runCurrent() }
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest {
        val r = Rig(this); r.settle(); block(r)
    }

    /** Place a call and return what initiateCall answered (it must never throw). */
    private suspend fun TestScope.place(r: Rig, channel: String): Result<Unit> {
        val to = if (channel == MESSENGER) "7788990011" else "+254712345678"
        val res = async { r.calls.initiateCall(to, "Fr. Peter Kamau", "conv-1", channel) }
        r.settle()
        return res.await()
    }

    /** A clean call on [channel], all the way to InCall, then hung up. */
    private suspend fun TestScope.cleanCall(r: Rig, channel: String) {
        assertTrue("the next call goes through", place(r, channel).isSuccess)
        if (channel == WHATSAPP) {
            r.frame("type" to "outbound_answer", "call_id" to r.api.connectId, "sdp" to "v=0 their-answer")
        } else {
            r.frame("type" to "call_answered", "call_id" to r.api.messengerConnectId)
        }
        r.media.peer.inner.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertTrue(r.audio.inCall)
        r.calls.hangup(); r.settle()
        r.drain()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertFalse(r.audio.inCall)
    }

    private fun assertFailedCleanly(r: Rig, res: Result<Unit>, step: Step) {
        val err = res.exceptionOrNull()
        assertTrue("$step: initiateCall reports a failure", err is CallManager.CallError)
        assertTrue("$step: the card already says it", (err as CallManager.CallError).shown)
        assertEquals("$step: ended on the card", CallPhase.Ended, r.state.phase)
        assertTrue("$step: a failed call, not a crash (${r.state.outcome})", r.state.outcome is CallOutcome.Failed)
        assertFalse("$step: the call audio is let go", r.audio.inCall)
        assertFalse("$step: the mic service is let go", r.audio.micService)
        r.media.peers.lastOrNull()?.let { assertTrue("$step: the peer is closed", it.inner.closed) }
    }

    // ── Cycle 6: outgoing WhatsApp, a native failure at every step ───────────
    @Test fun whatsappOutboundSurvivesANativeFailureAtEveryStep() = rig { r ->
        for (step in listOf(Step.CreatePeer, Step.AddMic, Step.CreateOffer, Step.SetLocal)) {
            r.media.arm(step)
            val res = place(r, WHATSAPP)
            assertFailedCleanly(r, res, step)
            assertEquals(CallManager.DEVICE_CALL_FAILED, res.exceptionOrNull()!!.message)
            r.drain()
            cleanCall(r, WHATSAPP)
        }
    }

    @Test fun whatsappOutboundSurvivesAnErrorFromTheServerCall() = rig { r ->
        // An Error out of the HTTP layer (an OOM on a huge body, a broken TLS provider).
        r.throwing.connectFault = OutOfMemoryError("response body")
        val res = place(r, WHATSAPP)
        assertFailedCleanly(r, res, Step.SetLocal)
        assertEquals(CallManager.DEVICE_CALL_FAILED, res.exceptionOrNull()!!.message)
        r.drain()
        // …and a class that fails to initialise the first time WebRTC is touched.
        r.media.arm(Step.CreatePeer, ExceptionInInitializerError("webrtc class init"))
        assertFailedCleanly(r, place(r, WHATSAPP), Step.CreatePeer)
        r.drain()
        cleanCall(r, WHATSAPP)
    }

    @Test fun whatsappAnswerThatThePeerRefusesEndsTheCallNotTheApp() = rig { r ->
        assertTrue(place(r, WHATSAPP).isSuccess)
        r.media.arm(Step.SetRemote)
        r.frame("type" to "outbound_answer", "call_id" to r.api.connectId, "sdp" to "v=0 their-answer")
        r.drain()
        assertFalse(r.audio.inCall)
        assertTrue(r.state.phase == CallPhase.Idle || r.state.phase == CallPhase.Ended)
        r.drain()
        cleanCall(r, WHATSAPP)
    }

    @Test fun tenCallsInARowWithFailuresBetweenThem() = rig { r ->
        val steps = listOf(Step.CreatePeer, Step.AddMic, Step.CreateOffer, Step.SetLocal)
        repeat(10) { i ->
            val channel = if (i % 2 == 0) WHATSAPP else MESSENGER
            r.media.arm(steps[i % steps.size])
            assertFailedCleanly(r, place(r, channel), steps[i % steps.size])
            r.drain()
            cleanCall(r, channel)
        }
        assertTrue("every peer made was closed", r.media.peers.all { it.inner.closed })
    }

    // ── Cycle 7: answering an incoming call, a native failure at every step ──
    @Test fun incomingAnswerSurvivesANativeFailureAtEveryStep() = rig { r ->
        var n = 0
        for (step in listOf(Step.CreatePeer, Step.AddMic, Step.SetRemote, Step.CreateAnswer, Step.SetLocal)) {
            val id = "wacid.in${n++}"
            r.frame("type" to "incoming_call", "call_id" to id, "from" to "254712345678", "name" to "Fr. Peter Kamau")
            assertEquals("$step: rings", CallPhase.Ringing, r.state.phase)
            r.media.arm(step)
            r.calls.answer(); r.settle()
            r.drain()
            assertFalse("$step: the call audio is let go", r.audio.inCall)
            assertFalse("$step: the mic service is let go", r.audio.micService)
            r.media.peers.lastOrNull()?.let { assertTrue("$step: the peer is closed", it.inner.closed) }
            assertEquals("$step: ended on the card", CallPhase.Ended, r.state.phase)
            r.calls.dismiss(); r.settle()
            assertEquals("$step: back to idle", CallPhase.Idle, r.state.phase)
        }
        // …and the next incoming call is answered and connects.
        r.frame("type" to "incoming_call", "call_id" to "wacid.ok", "from" to "254712345678", "name" to "Fr. Peter Kamau")
        r.calls.answer(); r.settle()
        r.media.peer.inner.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    @Test fun incomingMessengerAnswerSurvivesANativeFailure() = rig { r ->
        r.api.messengerCalls += "c_msg.in1"
        r.frame("type" to "incoming_call", "call_id" to "c_msg.in1", "from" to "7788990011", "name" to "Grace", "channel" to MESSENGER)
        r.media.arm(Step.CreateOffer)
        r.calls.answer(); r.settle()
        r.drain()
        assertFalse(r.audio.inCall)
        assertEquals(CallPhase.Ended, r.state.phase)
        r.calls.dismiss(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        r.api.messengerCalls += "c_msg.in2"
        r.frame("type" to "incoming_call", "call_id" to "c_msg.in2", "from" to "7788990011", "name" to "Grace", "channel" to MESSENGER)
        r.calls.answer(); r.settle()
        r.media.peer.inner.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    // ── Cycle 8: outgoing Messenger ──────────────────────────────────────────
    @Test fun messengerOutboundHappyPath() = rig { r ->
        cleanCall(r, MESSENGER)
        assertEquals("7788990011", r.api.lastMessengerConnect!!.first)
    }

    @Test fun messengerOutboundSurvivesANativeFailureAtEveryStep() = rig { r ->
        for (step in listOf(Step.CreatePeer, Step.AddMic, Step.CreateOffer, Step.SetLocal)) {
            r.media.arm(step)
            val res = place(r, MESSENGER)
            assertFailedCleanly(r, res, step)
            r.drain()
            cleanCall(r, MESSENGER)
        }
    }

    @Test fun messengerAnswerThePeerRefusesDoesNotCrash() = rig { r ->
        r.media.arm(Step.SetRemote)
        val res = place(r, MESSENGER)
        // Meta's answer was refused inside placeMessenger (logged): the call is placed, the card carries on.
        assertTrue(res.isSuccess || res.exceptionOrNull() is CallManager.CallError)
        r.calls.hangup(); r.settle(); r.drain()
        assertFalse(r.audio.inCall)
        cleanCall(r, MESSENGER)
    }

    // ── Cycle 9: the agent's own taps ────────────────────────────────────────
    @Test fun doubleTapIsAlreadyInACallNotACrash() = rig { r ->
        r.api.connectGate = CompletableDeferred()
        val a = async { r.calls.initiateCall("254712345678", "Fr. Peter Kamau") }
        r.settle()
        val b = async { r.calls.initiateCall("254712345678", "Fr. Peter Kamau", channel = MESSENGER) }
        r.settle()
        assertEquals("Already in a call", b.await().exceptionOrNull()!!.message)
        r.api.connectGate!!.complete(Unit); r.settle()
        assertTrue(a.await().isSuccess)
        assertEquals(1, r.media.peers.size)
    }

    @Test fun hangingUpWhilePlacingTerminatesAndTheNextCallWorks() = rig { r ->
        for (channel in listOf(WHATSAPP, MESSENGER)) {
            r.api.connectGate = CompletableDeferred()
            val a = async { r.calls.initiateCall(if (channel == MESSENGER) "7788990011" else "254712345678", "Grace", channel = channel) }
            r.settle()
            r.calls.hangup(); r.settle()
            r.api.connectGate!!.complete(Unit); r.settle()
            assertTrue("$channel: hung up before it was placed is not a failure", a.await().isSuccess)
            assertFalse(r.audio.inCall)
            r.api.connectGate = null
            r.drain()
            cleanCall(r, channel)
        }
    }

    @Test fun micDeniedOnEitherChannelSaysSoAndLetsGo() = rig { r ->
        for (channel in listOf(WHATSAPP, MESSENGER)) {
            r.mic = false
            val res = async { r.calls.initiateCall(if (channel == MESSENGER) "7788990011" else "254712345678", "Grace", channel = channel) }
            r.settle()
            r.calls.onMicResult(false); r.settle()
            assertTrue(res.await().isFailure)
            assertEquals(CallOutcome.MicBlocked, r.state.outcome)
            assertFalse(r.audio.inCall)
            r.drain()
            r.mic = true
            cleanCall(r, channel)
        }
    }

    @Test fun rtcGuardSwallowsWhatANativeCallbackThrows() {
        var after = false
        rtcGuard("onIceCandidate") { throw NativeBoom(Step.SetLocal) }
        rtcGuard("onTrack") { throw IllegalStateException("MediaStreamTrack has been disposed.") }
        rtcGuard("onConnectionChange") { after = true }
        assertTrue("the guard runs the callback", after)
    }
}
