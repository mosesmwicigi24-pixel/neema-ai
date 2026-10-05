package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.crash.CrashVault
import ke.co.bethanyhouse.neema.feature.calls.AudioRoute
import ke.co.bethanyhouse.neema.feature.calls.CallAudio
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.MESSENGER
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.WHATSAPP
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
 * The call ends while WebRTC is still working on it — the agent taps End as
 * the offer is made, the customer hangs up as the agent answers, the answer
 * frame lands a beat after the call was torn down. On a phone, touching the
 * PeerConnection after close() is a native crash (use after dispose) that no
 * catch can stop: the app closes. Here the fake peer records every such use;
 * there must be none.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallNativeSafetyTest {
    private val base = Instant.parse("2026-09-29T10:00:00Z").toEpochMilli()

    /** A device whose audio stack refuses once (a vendor quirk), then works. */
    class FlakyAudio(val inner: FakeAudio = FakeAudio()) : CallAudio by inner {
        var failEnter = 0
        override fun enter(route: AudioRoute) {
            if (failEnter > 0) { failEnter--; throw IllegalStateException("audio HAL refused MODE_IN_COMMUNICATION") }
            inner.enter(route)
        }
    }

    private inner class Rig(val scope: TestScope) {
        val api = FakeCallApi()
        val media = FakeMedia()
        val ringer = FakeRinger()
        val audio = FlakyAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val trouble = MutableSharedFlow<Boolean>(extraBufferCapacity = 8)
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = api, events = frames, connected = MutableStateFlow(true), scope = scope.backgroundScope,
            foreground = MutableStateFlow(true), signedInFn = { true }, media = media, ringer = ringer, audio = audio,
            micGranted = { true }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
            audioTrouble = trouble,
        ).also { it.start() }
        val state get() = calls.state.value
        fun emit(vararg kv: Pair<String, String>) { frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) })) }
        fun settle() = scope.runCurrent()
        fun drain() { scope.advanceTimeBy(60_000); scope.runCurrent() }
        fun assertNoNativeUseAfterClose() = media.peers.forEachIndexed { i, p ->
            assertTrue("peer $i used after close: ${p.usedAfterClose}", p.usedAfterClose.isEmpty())
        }
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest { val r = Rig(this); r.settle(); block(r) }

    @Test fun answerFrameLandingJustAsTheCallEndsNeverTouchesTheClosedPeer() = rig { r ->
        val placed = async { r.calls.initiateCall("254712345678", "Fr. Peter Kamau") }
        r.settle(); assertTrue(placed.await().isSuccess)
        // Their phone picks up as the agent taps End: the answer is applied a beat later.
        r.emit("type" to "outbound_answer", "call_id" to r.api.connectId, "sdp" to "v=0 their-answer")
        r.calls.hangup()
        r.settle(); r.drain()
        assertTrue(r.media.peer.closed)
        r.assertNoNativeUseAfterClose()
    }

    @Test fun hangingUpWhileTheOfferIsMadeNeverUsesTheClosedPeer() = rig { r ->
        for (channel in listOf(WHATSAPP, MESSENGER)) {
            val gate = CompletableDeferred<Unit>()
            r.media.sdpGate = gate               // WebRTC takes its time over the offer…
            r.api.lastConnect = null; r.api.lastMessengerConnect = null
            val placed = async { r.calls.initiateCall(if (channel == MESSENGER) "7788990011" else "254712345678", "Grace", channel = channel) }
            r.settle()
            assertEquals(listOf("addMic(true)", "createOffer"), r.media.peer.ops)
            r.calls.hangup(); r.settle()        // …the agent taps End meanwhile
            gate.complete(Unit); r.settle()     // …and the offer comes back
            r.media.sdpGate = null
            assertTrue(placed.await().isSuccess)
            assertFalse("$channel: the offer isn't applied to a closed peer", r.media.peer.ops.any { it.startsWith("setLocal") })
            assertEquals("$channel: nothing was placed", null, if (channel == MESSENGER) r.api.lastMessengerConnect else r.api.lastConnect)
            r.drain()
            r.assertNoNativeUseAfterClose()
        }
    }

    @Test fun callerHangingUpMidAnswerNeverUsesTheClosedPeer() = rig { r ->
        // WhatsApp: setRemote → createAnswer → setLocal, each a wait; Messenger: createOffer → setLocal.
        var n = 0
        for (messenger in listOf(false, true)) for (stepsBeforeEnd in 0..2) {
            val id = if (messenger) "c_msg.in${n++}" else "wacid.in${n++}"
            if (messenger) r.api.messengerCalls += id
            r.emit("type" to "incoming_call", "call_id" to id, "from" to "254712345678", "name" to "Fr. Peter Kamau",
                *(if (messenger) arrayOf("channel" to MESSENGER) else emptyArray()))
            r.settle()
            assertEquals(CallPhase.Ringing, r.state.phase)
            val gate = CompletableDeferred<Unit>()
            r.media.sdpGate = gate
            r.calls.answer(); r.settle()
            val p = r.media.peer
            r.media.sdpGate = null
            // The caller hangs up somewhere inside the SDP steps.
            repeat(stepsBeforeEnd) { gate.complete(Unit); r.settle() }
            r.emit("type" to "call_ended", "call_id" to id); r.settle()
            if (!gate.isCompleted) gate.complete(Unit)
            r.settle(); r.drain()
            assertTrue("$id: the peer was let go", p.closed)
            r.assertNoNativeUseAfterClose()
            r.calls.dismiss(); r.settle(); r.drain()
        }
    }

    @Test fun aDeviceAudioFailureDoesNotBreakEveryLaterCall() = rig { r ->
        r.audio.failEnter = 1
        val first = async { r.calls.initiateCall("254712345678", "Grace") }
        r.settle(); first.await()
        r.calls.hangup(); r.settle(); r.drain(); r.calls.dismiss(); r.settle()
        // The phase collector survived that failure: the next call gets its call audio.
        val next = async { r.calls.initiateCall("254712345678", "Grace") }
        r.settle(); assertTrue(next.await().isSuccess)
        assertTrue("call audio for the next call", r.audio.inner.inCall)
        r.emit("type" to "outbound_answer", "call_id" to r.api.connectId, "sdp" to "v=0 their-answer"); r.settle()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    /**
     * The crash in the owner's video: "Calling…", then the app closes a second
     * later. WebRTC's microphone thread asserts the recorder is recording
     * (WebRtcAudioRecord$AudioRecordThread.run, offset 47 in the 137 AAR) —
     * false when another app holds the mic or the audio mode is mid-switch —
     * and that AssertionError, on WebRTC's own thread, used to close the app.
     */
    @Test fun webRtcsMicThreadAssertingEndsOnlyThatThreadAndTheCardSaysSo() {
        val before = Thread.getDefaultUncaughtExceptionHandler()
        val fatal = mutableListOf<String>()
        val told = java.util.Collections.synchronizedList(mutableListOf<String>())
        try {
            CrashVault.onContained = { told += it }
            CrashVault.installHandler(previous = { t, _ -> fatal += t.name })
            for (name in listOf("AudioRecordJavaThread", "AudioTrackJavaThread", "neema-worker")) {
                val t = Thread({ throw AssertionError("Expected condition to be true") }, name)
                t.start(); t.join()
            }
            assertEquals("WebRTC's audio threads: contained, and the call is told", listOf("AudioRecordJavaThread", "AudioTrackJavaThread"), told.toList())
            assertEquals("anything else still goes to the system", listOf("neema-worker"), fatal)
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(before)
            CrashVault.onContained = null
        }
    }

    @Test fun aMicrophoneWebRtcCouldNotStartIsSaidOnTheCard() = rig { r ->
        r.trouble.tryEmit(true); r.settle()
        assertEquals("no call: nothing to say", null, r.state.error)
        val placed = async { r.calls.initiateCall("254712345678", "Grace") }
        r.settle(); assertTrue(placed.await().isSuccess)
        r.trouble.tryEmit(true); r.settle()
        assertEquals(CallManager.MIC_UNAVAILABLE, r.state.error)
        assertEquals("the call stays up: the agent decides", CallPhase.Placing, r.state.phase)
        r.emit("type" to "outbound_answer", "call_id" to r.api.connectId, "sdp" to "v=0 their-answer"); r.settle()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        r.trouble.tryEmit(false); r.settle()
        assertEquals(CallManager.SPEAKER_UNAVAILABLE, r.state.error)
    }

    @Test fun webRtcsOwnAudioThreadsAreContainedAndNothingElseIs() {
        assertTrue(CrashVault.contained("AudioTrackJavaThread"))
        assertTrue(CrashVault.contained("AudioRecordJavaThread"))
        assertFalse(CrashVault.contained("main"))
        assertFalse(CrashVault.contained("neema-call-close"))
        assertFalse(CrashVault.contained(null))
    }
}
