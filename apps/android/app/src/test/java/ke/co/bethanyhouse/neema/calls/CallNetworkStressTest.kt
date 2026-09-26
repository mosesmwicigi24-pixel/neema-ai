package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.RecordingOutbox
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.Instant

/**
 * The softphone on a bad phone network: every call step (ice-config, offer,
 * answer, connect, terminate, callback, the recording upload, the poll) when
 * the network drops, the server is slow or the answer never comes back, plus
 * impatient taps. Failures are what NeemaHttp really throws: status 0 with
 * "timed out after 30s" for a timeout, status 0 with the IOException's text
 * when there is no connection.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallNetworkStressTest {
    private val base = Instant.parse("2026-09-25T10:00:00Z").toEpochMilli()

    private fun timeout(method: String, path: String) = ApiException(0, method, path, "timed out after 30s")
    private fun offline(method: String, path: String) = ApiException(0, method, path, "Failed to connect to neema.bethanyhouse.co.ke/41.90.1.2:443")

    private inner class Rig(val scope: TestScope, val outboxDir: File = Files.createTempDirectory("rec-outbox").toFile()) {
        val api = FakeCallApi()
        val media = FakeMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val foreground = MutableStateFlow(true)
        val connected = MutableStateFlow(true)
        var signedIn = true
        private val d = StandardTestDispatcher(scope.testScheduler)
        fun manager() = CallManager(
            api = api, events = frames, connected = connected, scope = scope.backgroundScope, foreground = foreground,
            signedInFn = { signedIn }, media = media, ringer = ringer, audio = audio,
            micGranted = { true }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
            outboxDir = outboxDir,
        ).also { it.start() }
        val calls = manager()
        val state get() = calls.state.value

        fun frame(vararg kv: Pair<String, String>) {
            frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) }))
            scope.runCurrent()
        }
        fun ring(id: String = "wacid.1") = frame("type" to "incoming_call", "call_id" to id, "from" to "254712345678", "name" to "Fr. Peter Kamau")
        fun at(ago: Long) = Instant.ofEpochMilli(base + scope.testScheduler.currentTime - ago).toString()
        fun settle() = scope.runCurrent()
        fun count(prefix: String) = api.log.count { it.startsWith(prefix) }
        /** Ring, answer and connect: a live call. */
        fun live(): FakePeer { ring(); calls.answer(); settle(); media.peer.onEvent(PeerEvent.Connected); settle(); return media.peer }
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest {
        val r = Rig(this); r.settle(); block(r)
    }

    // ── The network drops mid-call ───────────────────────────────────────────
    @Test fun aShortBlipRecoversAndTheCallGoesOn() = rig { r ->
        val p = r.live()
        p.onEvent(PeerEvent.Interrupted); r.settle()
        assertEquals("still in the call", CallPhase.InCall, r.state.phase)
        assertTrue(r.state.reconnecting)
        assertFalse(p.closed)
        advanceTimeBy(4_000); runCurrent()
        p.onEvent(PeerEvent.Connected); r.settle()
        assertFalse(r.state.reconnecting)
        advanceTimeBy(CallManager.ICE_GRACE_MS * 3); runCurrent()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertEquals("the timer kept running through the blip", (4_000 + CallManager.ICE_GRACE_MS * 3) / 1000, r.state.seconds.toLong())
        assertEquals(0, r.count("terminate"))
    }

    @Test fun aDropThatNeverRecoversEndsAfterTheGraceAndTellsTheServer() = rig { r ->
        val p = r.live()
        p.onEvent(PeerEvent.Interrupted); r.settle()
        advanceTimeBy(CallManager.ICE_GRACE_MS - 1); runCurrent()
        assertEquals(CallPhase.InCall, r.state.phase)
        advanceTimeBy(2); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallManager.CONNECTION_LOST, r.state.note)
        assertFalse(r.state.reconnecting)
        assertTrue(p.closed)
        assertEquals(1, r.count("terminate wacid.1"))
        assertEquals("the recording is still uploaded", 1, r.api.uploads.size)
        advanceTimeBy(1_601); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun iceFailingWhileReconnectingEndsAtOnce() = rig { r ->
        val p = r.live()
        p.onEvent(PeerEvent.Interrupted); r.settle()
        p.onEvent(PeerEvent.Ended); r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallManager.CONNECTION_LOST, r.state.note)
        // The grace timer is gone with the call: nothing fires later.
        advanceTimeBy(CallManager.ICE_GRACE_MS + 1); runCurrent()
        assertEquals(0, r.count("terminate"))
    }

    @Test fun hangingUpWhileReconnectingEndsCleanly() = rig { r ->
        val p = r.live()
        p.onEvent(PeerEvent.Interrupted); r.settle()
        r.calls.hangup(); r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertNull("a plain hang-up, not a lost connection", r.state.note)
        advanceTimeBy(CallManager.ICE_GRACE_MS + 1); runCurrent()
        assertEquals("one terminate: the grace timer died with the call", 1, r.count("terminate"))
    }

    // ── Terminate failing ────────────────────────────────────────────────────
    @Test fun hangupEndsTheCallHereEvenWhenTheServerIsUnreachable() = rig { r ->
        r.live()
        repeat(5) { r.api.terminateErrors += offline("POST", "/admin/calls/wacid.1/terminate") }
        r.calls.hangup(); r.settle()
        assertEquals("ended on this phone at once", CallPhase.Ended, r.state.phase)
        assertFalse(r.audio.inCall)
        assertTrue(r.media.peer.closed)
        assertEquals(1, r.count("terminate"))
        advanceTimeBy(2_001); runCurrent()
        assertEquals("retried", 2, r.count("terminate"))
        advanceTimeBy(5_001); runCurrent()
        assertEquals(3, r.count("terminate"))
        advanceTimeBy(60_000); runCurrent()
        assertEquals("bounded: three tries", 3, r.count("terminate"))
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun terminateRetryStopsOnceItGetsThrough() = rig { r ->
        r.live()
        r.api.terminateErrors += timeout("POST", "/admin/calls/wacid.1/terminate")
        r.calls.hangup(); r.settle()
        advanceTimeBy(60_000); runCurrent()
        assertEquals(2, r.count("terminate"))
    }

    @Test fun rapidHangupTapsTerminateOnce() = rig { r ->
        r.live()
        repeat(4) { r.calls.hangup() }
        r.settle()
        assertEquals(1, r.count("terminate"))
        advanceTimeBy(1_001); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun declineFromTheNotificationRetriesTheTerminateToo() = rig { r ->
        r.api.terminateErrors += offline("POST", "/admin/calls/wacid.8/terminate")
        r.calls.handleAction("decline", "wacid.8"); r.settle()
        advanceTimeBy(2_001); runCurrent()
        assertEquals(2, r.count("terminate wacid.8"))
    }

    // ── Callback ─────────────────────────────────────────────────────────────
    @Test fun callbackSaysSavedOnlyOnceTheServerSaidSo() = rig { r ->
        r.api.callbackGate = CompletableDeferred()
        r.ring()
        r.calls.callback(); r.settle()
        assertTrue("waiting on the server, buttons disabled", r.state.busy)
        assertFalse("ringing stopped at once", r.ringer.ringing)
        assertEquals(CallPhase.Ringing, r.state.phase)
        // Impatient taps: none of them sends anything.
        r.calls.callback(); r.calls.hangup(); r.calls.answer(); r.settle()
        assertEquals(1, r.count("callback"))
        assertEquals(0, r.count("terminate") + r.count("offer") + r.count("ice-config"))
        // The poll sees the row already marked: the card still ends with the note.
        r.api.calls = listOf(Call(id = "k", callId = "wacid.1", waId = "254712345678", status = "callback", startedAt = r.at(5_000)))
        r.calls.pollOnce(); r.settle()
        assertTrue(r.state.busy)
        r.api.callbackGate!!.complete(Unit); r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallManager.CALLBACK_SAVED, r.state.note)
        assertFalse(r.state.busy)
    }

    @Test fun callbackOfflineSaysSoAndKeepsTrying() = rig { r ->
        r.api.callbackErrors += offline("POST", "/admin/calls/wacid.1/callback")
        r.ring()
        r.calls.callback(); r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals(CallManager.CALLBACK_RETRYING, r.state.note)
        advanceTimeBy(2_001); runCurrent()
        assertEquals("retried in the background", 2, r.count("callback wacid.1"))
        advanceTimeBy(60_000); runCurrent()
        assertEquals("and stops once it got through", 2, r.count("callback wacid.1"))
    }

    @Test fun callbackRefusedSaysItWasNotSaved() = rig { r ->
        r.api.callbackErrors += ApiException(401, "POST", "/admin/calls/wacid.1/callback", "Session expired")
        r.ring()
        r.calls.callback(); r.settle()
        assertEquals(CallManager.CALLBACK_FAILED, r.state.note)
        advanceTimeBy(60_000); runCurrent()
        assertEquals(1, r.count("callback"))
    }

    // ── Answer ───────────────────────────────────────────────────────────────
    @Test fun rapidAnswerTapsAnswerOnce() = rig { r ->
        r.ring()
        repeat(5) { r.calls.answer() }
        r.settle()
        assertEquals(1, r.count("offer"))
        assertEquals(1, r.count("answer"))
        assertEquals(1, r.media.peers.size)
    }

    @Test fun answerThenDeclineAtOnceNeverAnswers() = rig { r ->
        r.ring()
        r.calls.answer(); r.calls.hangup(); r.settle()
        assertEquals(0, r.count("answer"))
        assertEquals(1, r.count("terminate wacid.1"))
        assertEquals(CallPhase.Ended, r.state.phase)
        assertNull(r.state.error)
    }

    @Test fun answerTimedOutButTheCallConnectedIsKept() = rig { r ->
        r.api.answerError = timeout("POST", "/admin/calls/wacid.1/answer")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals("no failure shown while it may have worked", CallPhase.Connecting, r.state.phase)
        assertNull(r.state.error)
        advanceTimeBy(3_000); runCurrent()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        advanceTimeBy(20_000); runCurrent()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertNull(r.state.error)
        assertEquals("the live call is never terminated", 0, r.count("terminate"))
    }

    @Test fun answerTimedOutAndNothingConnectedFailsWithTheReason() = rig { r ->
        r.api.answerError = timeout("POST", "/admin/calls/wacid.1/answer")
        r.ring(); r.calls.answer(); r.settle()
        advanceTimeBy(CallManager.ANSWER_CONFIRM_MS + 1); runCurrent()
        assertEquals(CallManager.ANSWER_SLOW, r.state.error)
        advanceTimeBy(1_801); runCurrent()
        assertEquals(1, r.count("terminate wacid.1"))
        assertEquals(CallPhase.Ended, r.state.phase)
    }

    @Test fun answerWhileOfflineSaysSo() = rig { r ->
        r.api.iceError = offline("GET", "/admin/calls/ice-config")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallManager.ANSWER_OFFLINE, r.state.error)
        advanceTimeBy(1_801); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
    }

    @Test fun answerAfterTheCallerHungUpSaysTheCallEnded() = rig { r ->
        r.api.offerError = ApiException(404, "GET", "/admin/calls/wacid.1/offer", """{"detail":"call offer expired or not found"}""")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals(CallManager.CALL_GONE, r.state.error)
        advanceTimeBy(1_801); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals("nothing to terminate: the caller is gone", 0, r.count("terminate"))
    }

    @Test fun anAnswerErrorAfterTheMediaConnectedDoesNotHangUp() = rig { r ->
        // A 502 from Meta's accept, yet the media came up while the copy showed.
        r.api.answerError = ApiException(502, "POST", "/admin/calls/wacid.1/answer", """{"detail":"accept failed: boom"}""")
        r.ring(); r.calls.answer(); r.settle()
        assertEquals("Couldn't connect the call", r.state.error)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        advanceTimeBy(1_801); runCurrent()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertNull(r.state.error)
        assertEquals(0, r.count("terminate"))
    }

    // ── Outbound ─────────────────────────────────────────────────────────────
    @Test fun connectTimedOutButMetaPlacedTheCallIsAdopted() = rig { r ->
        r.api.connectError = timeout("POST", "/admin/calls/connect")
        r.api.calls = listOf(
            Call(id = "old", callId = "wacid.old", waId = "254712345678", direction = "outbound", status = "ringing", startedAt = r.at(10 * 60_000)),
            Call(id = "k", callId = "wacid.placed", waId = "254712345678", direction = "outbound", status = "ringing", startedAt = r.at(1_000)),
        )
        val res = async { r.calls.initiateCall("+254712345678", "Fr. Peter Kamau") }
        r.settle()
        assertTrue("not a failure: the call is ringing them", res.await().isSuccess)
        assertEquals("wacid.placed", r.state.callId)
        assertNull(r.state.error)
        r.frame("type" to "outbound_answer", "call_id" to "wacid.placed", "sdp" to "v=0 their-answer")
        assertTrue("setRemote(Answer,v=0 their-answer)" in r.media.peer.ops)
    }

    @Test fun connectTimedOutWithNoPlacedCallSaysItCouldNotConfirm() = rig { r ->
        r.api.connectError = timeout("POST", "/admin/calls/connect")
        val res = async { r.calls.initiateCall("254712345678") }
        r.settle()
        advanceTimeBy(CallManager.PLACED_LOOKUP_GAP_MS + 1); runCurrent()
        assertEquals(CallManager.UNCONFIRMED_CALL, res.await().exceptionOrNull()!!.message)
        assertEquals("looked twice", 2, r.count("list"))
        assertFalse("never mistaken for the permission prompt", CallManager.UNCONFIRMED_CALL.contains("permission", ignoreCase = true))
        advanceTimeBy(2_201); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun placingACallOfflineSaysSo() = rig { r ->
        r.api.iceError = offline("GET", "/admin/calls/ice-config")
        val res = async { r.calls.initiateCall("254712345678") }
        r.settle()
        assertEquals(CallManager.OUTBOUND_OFFLINE, res.await().exceptionOrNull()!!.message)
        assertEquals(CallManager.OUTBOUND_OFFLINE, r.state.error)
        assertEquals(0, r.count("connect"))
    }

    @Test fun rapidCallTapsPlaceOneCall() = rig { r ->
        val a = async { r.calls.initiateCall("254712345678") }
        val b = async { r.calls.initiateCall("254712345678") }
        r.settle()
        assertTrue(a.await().isSuccess)
        assertEquals("Already in a call", b.await().exceptionOrNull()!!.message)
        assertEquals(1, r.count("connect"))
    }

    @Test fun errorCopyForEveryFailure() {
        assertEquals(CallManager.ANSWER_SLOW, CallManager.answerError(timeout("GET", "/admin/calls/x/offer")))
        assertEquals(CallManager.ANSWER_OFFLINE, CallManager.answerError(offline("GET", "/admin/calls/ice-config")))
        assertEquals(CallManager.SESSION_EXPIRED, CallManager.answerError(ApiException(401, "GET", "/admin/calls/ice-config", "Session expired")))
        assertEquals("Couldn't connect the call", CallManager.answerError(ApiException(502, "GET", "/admin/calls/x/offer", "<html>Bad gateway</html>")))
        assertEquals(CallManager.OUTBOUND_SLOW, CallManager.outboundError(timeout("GET", "/admin/calls/ice-config")))
        assertEquals(CallManager.OUTBOUND_OFFLINE, CallManager.outboundError(offline("POST", "/admin/calls/connect")))
        assertEquals("Couldn't place the call", CallManager.outboundError(ApiException(503, "POST", "/admin/calls/connect", "<html>503</html>")))
        for (m in listOf(CallManager.OUTBOUND_SLOW, CallManager.OUTBOUND_OFFLINE, CallManager.SESSION_EXPIRED, CallManager.MIC_BLOCKED)) {
            assertFalse(m, m.contains("permission", ignoreCase = true))
        }
    }

    // ── A call arriving while offline, and a flaky poll ──────────────────────
    @Test fun aCallThatRangWhileOfflineRingsOnReconnect() = rig { r ->
        r.connected.value = false; r.settle()
        r.api.listError = offline("GET", "/admin/calls")
        advanceTimeBy(CallManager.IDLE_POLL_MS * 2 + 1); runCurrent()
        assertEquals("poll errors are silent", CallPhase.Idle, r.state.phase)
        r.api.listError = null
        r.api.calls = listOf(Call(id = "k", callId = "wacid.5", waId = "254712345678", status = "ringing", startedAt = r.at(8_000)))
        r.connected.value = true; r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("wacid.5", r.state.callId)
    }

    @Test fun aFailingPollNeverTearsDownARingingCall() = rig { r ->
        r.ring()
        r.api.listError = ApiException(502, "GET", "/admin/calls", "<html><body>Bad Gateway</body></html>")
        advanceTimeBy(CallManager.RING_POLL_MS * 4 + 1); runCurrent()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertTrue(r.ringer.ringing)
    }

    // ── Recording upload ─────────────────────────────────────────────────────
    @Test fun aRecordingThatFailsToUploadIsKeptAndSentOnReconnect() = rig { r ->
        r.api.uploadErrors += offline("POST", "/admin/calls/wacid.1/recording")
        r.live()
        r.calls.hangup(); r.settle()
        assertTrue(r.api.uploads.isEmpty())
        assertEquals("kept on disk", 1, r.outboxDir.listFiles()!!.size)
        assertFalse("moved out of the cache", r.media.recordings.single().file.exists())
        r.connected.value = false; r.settle()
        r.connected.value = true; r.settle()
        assertEquals("wacid.1", r.api.uploads.single().first)
        assertEquals("wacid.1.m4a", r.api.uploads.single().second.first)
        assertEquals(48_000, r.api.uploads.single().second.third)
        assertEquals("deleted once the server has it", 0, r.outboxDir.listFiles()!!.size)
    }

    @Test fun aRecordingLeftByAnEarlierSessionIsSentAtStart() = runTest {
        val dir = Files.createTempDirectory("rec-outbox").toFile()
        val first = Rig(this, dir); first.settle()
        first.api.uploadErrors += timeout("POST", "/admin/calls/wacid.1/recording")
        first.live(); first.calls.hangup(); first.settle()
        assertEquals(1, dir.listFiles()!!.size)
        // The app is killed and started again.
        val second = Rig(this, dir); second.settle()
        assertEquals("wacid.1", second.api.uploads.single().first)
        assertEquals(0, dir.listFiles()!!.size)
    }

    @Test fun aRecordingTheServerRefusesIsDroppedNotRetried() = rig { r ->
        r.api.uploadErrors += ApiException(403, "POST", "/admin/calls/wacid.1/recording", """{"detail":"Call recording is disabled."}""")
        r.live(); r.calls.hangup(); r.settle()
        assertEquals(0, r.outboxDir.listFiles()!!.size)
        r.foreground.value = false; r.settle(); r.foreground.value = true; r.settle()
        assertEquals(1, r.count("recording"))
    }

    @Test fun uploadsWaitForSignIn() = rig { r ->
        r.api.uploadErrors += ApiException(401, "POST", "/admin/calls/wacid.1/recording", "Session expired")
        r.live(); r.calls.hangup(); r.settle()
        assertEquals("kept for after sign-in", 1, r.outboxDir.listFiles()!!.size)
        r.signedIn = false
        r.connected.value = false; r.settle(); r.connected.value = true; r.settle()
        assertEquals(1, r.count("recording"))
        r.signedIn = true
        r.foreground.value = false; r.settle(); r.foreground.value = true; r.settle()
        assertEquals(1, r.api.uploads.size)
    }

    // ── The outbox itself ────────────────────────────────────────────────────
    @Test fun outboxIsBoundedByCountAndAge() = runTest {
        var t = base
        val dir = Files.createTempDirectory("rec-outbox").toFile()
        val box = RecordingOutbox(dir) { t }
        repeat(RecordingOutbox.MAX_FILES + 3) { i ->
            t += 1_000
            val f = File.createTempFile("call", ".m4a").apply { writeBytes(ByteArray(3_000)) }
            assertTrue(box.put("wacid.$i==", f))
        }
        assertEquals(RecordingOutbox.MAX_FILES, box.pending().size)
        assertEquals("the oldest went first", "wacid.3==", box.pending().first().first)
        t += RecordingOutbox.MAX_AGE_MS + 1
        box.prune()
        assertTrue(box.pending().isEmpty())
    }

    @Test fun outboxSendsOldestFirstAndStopsAtATransientFailure() = runTest {
        var t = base
        val dir = Files.createTempDirectory("rec-outbox").toFile()
        val box = RecordingOutbox(dir) { t }
        for (id in listOf("a", "b", "c")) { t += 1; box.put(id, File.createTempFile("call", ".m4a").apply { writeBytes(ByteArray(3_000)) }) }
        val sent = mutableListOf<String>()
        val n = box.drain { id, _ ->
            if (id == "b") throw ApiException(503, "POST", "/admin/calls/b/recording", "<html>down</html>")
            sent += id
        }
        assertEquals(1, n)
        assertEquals(listOf("a"), sent)
        assertEquals(listOf("b", "c"), box.pending().map { it.first })
        box.drain { id, _ -> sent += id }
        assertEquals(listOf("a", "b", "c"), sent)
        assertTrue(box.pending().isEmpty())
    }
}
