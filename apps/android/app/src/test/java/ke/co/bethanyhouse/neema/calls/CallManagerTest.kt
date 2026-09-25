package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
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
import java.time.Instant

/**
 * The softphone's rules (lib/callContext.tsx) on the JVM: phases, the 12s
 * re-ring cooldown, the 2.5s / 12s poll cadence, every WebSocket frame, the
 * error copy, the mic prompt, recording upload, and the notification actions.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallManagerTest {
    private val base = Instant.parse("2026-09-25T10:00:00Z").toEpochMilli()

    private inner class Rig(val scope: TestScope) {
        val api = FakeCallApi()
        val media = FakeMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val foreground = MutableStateFlow(true)
        var signedIn = true
        var mic = true
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = api, events = frames, scope = scope.backgroundScope, foreground = foreground,
            signedInFn = { signedIn }, media = media, ringer = ringer, audio = audio,
            micGranted = { mic }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
        ).also { it.start() }
        val state get() = calls.state.value

        fun frame(vararg kv: Pair<String, String>) {
            frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) }))
            scope.runCurrent()
        }
        fun ring(id: String = "wacid.1", from: String = "254712345678", name: String? = "Fr. Peter Kamau") =
            if (name != null) frame("type" to "incoming_call", "call_id" to id, "from" to from, "name" to name)
            else frame("type" to "incoming_call", "call_id" to id, "from" to from)
        /** A frame exactly as routers/whatsapp_webhook.py publishes it (json.dumps), parsed as LiveSocket does. */
        fun raw(json: String) {
            frames.tryEmit(ke.co.bethanyhouse.neema.core.net.NeemaJson.parseToJsonElement(json) as JsonObject)
            scope.runCurrent()
        }
        fun at(ago: Long) = Instant.ofEpochMilli(base + scope.testScheduler.currentTime - ago).toString()
        fun settle() = scope.runCurrent()
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest {
        val r = Rig(this); r.settle(); block(r)
    }

    // ── Ringing ──────────────────────────────────────────────────────────────
    @Test fun incomingFrameRingsWithCallerAndRingtone() = rig { r ->
        r.ring()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("wacid.1", r.state.callId)
        assertEquals("254712345678", r.state.from)
        assertEquals("Fr. Peter Kamau", r.state.name)
        assertTrue(r.ringer.ringing)
        assertTrue("foreground: the card is the alert", r.ringer.posted.isEmpty())
    }

    @Test fun incomingFrameWithoutCallIdIsIgnored() = rig { r ->
        r.frame("type" to "incoming_call", "from" to "254700000000")
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun secondCallWhileRingingDoesNotReplaceTheFirst() = rig { r ->
        r.ring("wacid.1")
        r.ring("wacid.2", "254799999999", "Someone Else")
        assertEquals("wacid.1", r.state.callId)
    }

    @Test fun backgroundRingPostsTheNotificationAndForegroundDropsIt() = rig { r ->
        r.foreground.value = false; r.settle()
        r.ring(name = null)
        assertEquals(listOf(Triple("wacid.1", "+254712345678", "254712345678")), r.ringer.posted)
        r.foreground.value = true; r.settle()
        assertFalse(r.ringer.showing)
        r.foreground.value = false; r.settle()
        assertTrue("backgrounded again while still ringing", r.ringer.showing)
    }

    // ── Decline / callback / cooldown ────────────────────────────────────────
    @Test fun declineTerminatesShowsEndedThenIdleAndStartsTheCooldown() = rig { r ->
        r.ring()
        r.calls.hangup(); r.settle()
        assertTrue("terminate wacid.1" in r.api.log)
        assertEquals(CallPhase.Ended, r.state.phase)
        assertNull(r.state.note)
        assertFalse(r.ringer.ringing)
        advanceTimeBy(999); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
        advanceTimeBy(2); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertNull(r.state.callId)
        // Still "ringing" server-side: the same call must not re-ring within 12s…
        r.ring()
        assertEquals(CallPhase.Idle, r.state.phase)
        // …but a genuine retry after the cooldown does.
        advanceTimeBy(11_000); runCurrent()
        r.ring()
        assertEquals(CallPhase.Ringing, r.state.phase)
    }

    @Test fun cooldownIsPerCall() = rig { r ->
        r.ring("wacid.1"); r.calls.hangup(); r.settle()
        advanceTimeBy(1_100); runCurrent()
        r.ring("wacid.2")
        assertEquals(CallPhase.Ringing, r.state.phase)
    }

    @Test fun callbackPostsAndShowsTheNoteForLonger() = rig { r ->
        r.ring()
        r.calls.callback(); r.settle()
        assertTrue("callback wacid.1" in r.api.log)
        assertFalse("terminate wacid.1" in r.api.log)
        assertEquals(CallPhase.Ended, r.state.phase)
        assertEquals("Callback saved — find them under Calls", r.state.note)
        advanceTimeBy(1_500); runCurrent()
        assertEquals(CallPhase.Ended, r.state.phase)
        advanceTimeBy(200); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun hangupWhenIdleOrAlreadyEndedDoesNothing() = rig { r ->
        r.calls.hangup(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        r.ring()
        r.calls.hangup(); r.settle()
        r.calls.hangup(); r.settle()
        assertEquals(1, r.api.log.count { it == "terminate wacid.1" })
    }

    // ── WebSocket call_ended ─────────────────────────────────────────────────
    @Test fun callEndedFrameForThisCallEndsIt() = rig { r ->
        r.ring()
        r.frame("type" to "call_ended", "call_id" to "other")
        assertEquals(CallPhase.Ringing, r.state.phase)
        r.frame("type" to "call_ended", "call_id" to "wacid.1")
        assertEquals(CallPhase.Ended, r.state.phase)
        assertFalse(r.ringer.ringing)
        advanceTimeBy(1_001); runCurrent()
        assertEquals("the web left the card stuck here", CallPhase.Idle, r.state.phase)
        assertFalse("the caller hung up: nothing to terminate", r.api.log.any { it.startsWith("terminate") })
    }

    // ── Poll fallback ────────────────────────────────────────────────────────
    @Test fun pollCadenceIs12sIdleAnd2500msWhileRinging() = rig { r ->
        advanceTimeBy(11_999); runCurrent()
        assertEquals(0, r.api.log.count { it == "list" })
        advanceTimeBy(2); runCurrent()
        assertEquals(1, r.api.log.count { it == "list" })
        r.ring()
        advanceTimeBy(12_000); runCurrent()   // the idle wait already running finishes
        val n = r.api.log.count { it == "list" }
        advanceTimeBy(2_501); runCurrent()
        assertEquals(n + 1, r.api.log.count { it == "list" })
    }

    @Test fun pollCatchesAFreshRingingCallOnly() = rig { r ->
        r.api.calls = listOf(
            Call(id = "k0", callId = "old", waId = "254700000001", status = "ringing", startedAt = r.at(120_000)),
            Call(id = "k1", callId = "done", waId = "254700000002", status = "missed", startedAt = r.at(5_000)),
        )
        r.calls.pollOnce(); r.settle()
        assertEquals("older than 90s / not ringing: ignored", CallPhase.Idle, r.state.phase)
        r.api.calls = r.api.calls + Call(id = "k2", callId = "fresh", waId = "254711111111", name = "Rev. Mary Achieng", status = "ringing", startedAt = r.at(30_000))
        r.calls.pollOnce(); r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("fresh", r.state.callId)
        assertEquals("254711111111", r.state.from)
        assertEquals("Rev. Mary Achieng", r.state.name)
    }

    @Test fun pollWhileRingingTearsDownWhenTheCallerHungUp() = rig { r ->
        r.ring()
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", status = "ringing", startedAt = r.at(3_000)))
        r.calls.pollOnce(); r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.1", status = "missed", startedAt = r.at(3_000)))
        r.calls.pollOnce(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertFalse(r.ringer.ringing)
        assertFalse(r.api.log.any { it.startsWith("terminate") })
    }

    @Test fun pollSkipsWhenSignedOutAndSurvivesErrors() = rig { r ->
        r.signedIn = false
        r.calls.pollOnce()
        assertFalse("list" in r.api.log)
        r.signedIn = true
        r.api.listError = ApiException(500, "GET", "/admin/calls", "{}")
        r.calls.pollOnce()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    // ── Answer ───────────────────────────────────────────────────────────────
    @Test fun answerBuildsTheWebRtcAnswerAndGoesLive() = rig { r ->
        r.ring()
        r.calls.answer(); r.settle()
        assertEquals(CallPhase.Connecting, r.state.phase)
        assertFalse(r.ringer.ringing)
        assertTrue("ice-config" in r.api.log && "offer wacid.1" in r.api.log)
        val p = r.media.peer
        assertEquals(
            listOf("addMic(true)", "setRemote(Offer,v=0 caller-offer)", "createAnswer", "setLocal(Answer,v=0 our-answer)"),
            p.ops,
        )
        assertEquals("the gathered SDP is sent", "setLocal(Answer,v=0 our-answer)+candidates", r.api.lastAnswerSdp)
        assertTrue("in-call audio + mic service", r.audio.inCall)
        p.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
        assertEquals("recording starts once live", 1, r.media.recordings.size)
        advanceTimeBy(3_001); runCurrent()
        assertEquals(3, r.state.seconds)
    }

    @Test fun answerWaitsAtMost2500msForIceGathering() = rig { r ->
        r.media.gatherAtOnce = false
        r.ring()
        r.calls.answer(); r.settle()
        assertFalse(r.api.log.any { it.startsWith("answer") })
        advanceTimeBy(2_501); runCurrent()
        assertTrue("answer wacid.1" in r.api.log)
    }

    @Test fun answerFailureShowsCopyThenHangsUp() = rig { r ->
        r.api.offerError = ApiException(404, "GET", "/admin/calls/wacid.1/offer", """{"detail":"call offer expired or not found"}""")
        r.ring()
        r.calls.answer(); r.settle()
        assertEquals("Couldn't connect the call", r.state.error)
        assertEquals(CallPhase.Connecting, r.state.phase)
        advanceTimeBy(1_801); runCurrent()
        assertTrue("terminate wacid.1" in r.api.log)
        assertEquals(CallPhase.Ended, r.state.phase)
    }

    @Test fun answerAlreadyTakenBySomeoneElse() = rig { r ->
        r.api.answerError = ApiException(409, "POST", "/admin/calls/wacid.1/answer", """{"detail":"call already answered"}""")
        r.ring()
        r.calls.answer(); r.settle()
        assertEquals(CallManager.TAKEN_ELSEWHERE, r.state.error)
        advanceTimeBy(1_801); runCurrent()
        // The colleague who won the call keeps it: no terminate from this device.
        assertFalse(r.api.log.any { it.startsWith("terminate") })
        assertTrue(r.media.peer.closed)
        assertEquals(CallPhase.Ended, r.state.phase)
    }

    @Test fun answerAsksForTheMicAndProceedsWhenAllowed() = rig { r ->
        r.mic = false
        r.ring()
        r.calls.answer(); r.settle()
        assertTrue(r.calls.micRequest.value)
        assertTrue(r.media.peer.ops.isEmpty())
        r.mic = true
        r.calls.onMicResult(true); r.settle()
        assertFalse(r.calls.micRequest.value)
        assertTrue("answer wacid.1" in r.api.log)
        assertNull(r.state.error)
    }

    // ── The microphone foreground service (Android 14+ refuses it without the permission) ──
    @Test fun micServiceStartsOnlyOnceTheMicIsAllowed() = rig { r ->
        r.mic = false
        r.ring()
        r.calls.answer(); r.settle()
        assertTrue("audio routed while connecting", r.audio.inCall)
        assertFalse("no mic-type service while the prompt is up", r.audio.micService)
        r.mic = true
        r.calls.onMicResult(true); r.settle()
        assertTrue(r.audio.micService)
        assertEquals(1, r.audio.micLives)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        r.calls.hangup(); r.settle()
        assertFalse("back to the plain live service after the call", r.audio.micService || r.audio.inCall)
    }

    @Test fun micRefusedNeverStartsTheMicService() = rig { r ->
        r.mic = false
        r.ring(); r.calls.answer(); r.settle()
        r.calls.onMicResult(false); r.settle()
        advanceTimeBy(1_801); runCurrent()
        assertEquals(0, r.audio.micLives)
        // Outbound, refused too.
        advanceTimeBy(1_001); runCurrent()
        val b = async { r.calls.initiateCall("254712345678") }
        r.settle(); r.calls.onMicResult(false); r.settle()
        assertEquals(CallManager.MIC_BLOCKED, b.await().exceptionOrNull()!!.message)
        assertEquals(0, r.audio.micLives)
        assertFalse(r.audio.micService)
    }

    @Test fun outboundStartsTheMicServiceWithTheMic() = rig { r ->
        val a = async { r.calls.initiateCall("254712345678") }
        r.settle()
        assertTrue(a.await().isSuccess)
        assertEquals(1, r.audio.micLives)
        assertTrue(r.media.peer.hasMic)
    }

    @Test fun answerWithMicRefusedSaysMicrophoneBlocked() = rig { r ->
        r.mic = false
        r.ring()
        r.calls.answer(); r.settle()
        r.calls.onMicResult(false); r.settle()
        assertEquals(CallManager.MIC_BLOCKED, r.state.error)
        assertFalse(r.api.log.any { it.startsWith("answer") })
        advanceTimeBy(1_801); runCurrent()
        assertTrue("terminate wacid.1" in r.api.log)
    }

    @Test fun unansweredMicPromptTimesOutAsBlocked() = rig { r ->
        r.mic = false
        r.ring()
        r.calls.answer(); r.settle()
        advanceTimeBy(CallManager.MIC_PROMPT_TIMEOUT_MS + 1); runCurrent()
        assertEquals(CallManager.MIC_BLOCKED, r.state.error)
        assertFalse(r.calls.micRequest.value)
    }

    @Test fun hangingUpDuringTheMicPromptCancelsItQuietly() = rig { r ->
        r.mic = false
        r.ring()
        r.calls.answer(); r.settle()
        r.calls.hangup(); r.settle()
        assertFalse(r.calls.micRequest.value)
        assertEquals(CallPhase.Ended, r.state.phase)
        assertNull(r.state.error)
    }

    @Test fun peerDisconnectEndsTheCall() = rig { r ->
        r.ring(); r.calls.answer(); r.settle()
        val p = r.media.peer
        p.onEvent(PeerEvent.Connected); r.settle()
        p.onEvent(PeerEvent.Ended); r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        assertTrue(p.closed)
        advanceTimeBy(1_001); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertFalse(r.audio.inCall)
    }

    @Test fun eventsFromAClosedPeerAreIgnored() = rig { r ->
        r.ring(); r.calls.answer(); r.settle()
        val old = r.media.peer
        r.calls.hangup(); r.settle()
        advanceTimeBy(1_001); runCurrent()
        r.ring("wacid.2")
        old.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
    }

    // ── Mute / speaker / recording ───────────────────────────────────────────
    @Test fun muteNeedsTheMicThenTogglesTrackAndRecording() = rig { r ->
        r.ring()
        r.calls.toggleMute()
        assertFalse("no local stream yet", r.state.muted)
        r.calls.answer(); r.settle()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        r.calls.toggleMute()
        assertTrue(r.state.muted)
        assertEquals(false, r.media.peer.micEnabled)
        assertTrue(r.media.recordings.single().micMuted)
        r.calls.toggleMute()
        assertFalse(r.state.muted)
        assertEquals(true, r.media.peer.micEnabled)
    }

    @Test fun speakerRoutesAudio() = rig { r ->
        r.calls.toggleSpeaker()
        assertTrue(r.state.speaker && r.audio.speakerOn)
        r.calls.toggleSpeaker()
        assertFalse(r.state.speaker || r.audio.speakerOn)
    }

    @Test fun recordingUploadsOnHangup() = rig { r ->
        r.ring(); r.calls.answer(); r.settle()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        r.calls.hangup(); r.settle()
        val rec = r.media.recordings.single()
        assertTrue(rec.stopped)
        val (id, file) = r.api.uploads.single()
        assertEquals("wacid.1", id)
        assertEquals("wacid.1.m4a", file.first)
        assertEquals("audio/mp4", file.second)
        assertEquals("the whole recording, streamed from disk", 48_000, file.third)
        assertFalse("temp file removed", rec.file.exists())
    }

    @Test fun tinyRecordingsAreSkippedAndTheKillSwitchIsHonoured() = rig { r ->
        r.media.recordingBytes = 1_500
        r.ring(); r.calls.answer(); r.settle()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        r.calls.hangup(); r.settle()
        assertTrue(r.api.uploads.isEmpty())
        advanceTimeBy(1_001); runCurrent()
        r.api.ice = IceConfig(record = false)
        r.ring("wacid.2"); r.calls.answer(); r.settle()
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals("record:false → no second recording", 1, r.media.recordings.size)
    }

    // ── Outbound ─────────────────────────────────────────────────────────────
    @Test fun outboundCallPlacesTheOfferAndConnectsOnTheAnswerFrame() = rig { r ->
        val res = async { r.calls.initiateCall("+254712345678", "Fr. Peter Kamau") }
        r.settle()
        assertTrue(res.await().isSuccess)
        assertEquals(CallPhase.Connecting, r.state.phase)
        assertTrue(r.state.outbound)
        assertEquals("254712345678", r.state.from)
        assertEquals("wacid.out1", r.state.callId)
        val (to, sdp, name) = r.api.lastConnect!!
        assertEquals("+254712345678", to)
        assertEquals("setLocal(Offer,v=0 our-offer)+candidates", sdp)
        assertEquals("Fr. Peter Kamau", name)
        r.frame("type" to "outbound_answer", "call_id" to "someone-else", "sdp" to "x")
        assertFalse(r.media.peer.ops.any { it.startsWith("setRemote") })
        r.frame("type" to "outbound_answer", "call_id" to "wacid.out1", "sdp" to "v=0 their-answer")
        assertTrue("setRemote(Answer,v=0 their-answer)" in r.media.peer.ops)
        r.media.peer.onEvent(PeerEvent.Connected); r.settle()
        assertEquals(CallPhase.InCall, r.state.phase)
    }

    @Test fun outboundBlankNameIsNotSent() = rig { r ->
        val res = async { r.calls.initiateCall("254712345678", "") }
        r.settle(); res.await()
        assertNull(r.api.lastConnect!!.third)
    }

    @Test fun outboundWithoutCustomerPermissionSaysSoAndResets() = rig { r ->
        r.api.connectError = ApiException(409, "POST", "/admin/calls/connect", """{"detail":"This customer hasn't granted call permission yet."}""")
        val res = async { r.calls.initiateCall("254712345678", "Fr. Peter Kamau") }
        r.settle()
        val msg = res.await().exceptionOrNull()!!.message!!
        assertEquals(CallManager.NO_CALL_PERMISSION, msg)
        assertTrue("callers then ask the customer", msg.contains("permission", ignoreCase = true))
        assertEquals(msg, r.state.error)
        advanceTimeBy(2_199); runCurrent()
        assertEquals(CallPhase.Connecting, r.state.phase)
        advanceTimeBy(2); runCurrent()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertTrue(r.media.peer.closed)
        // The "permission" → requestPermission path: digits only.
        assertTrue(r.calls.requestPermission("+254 712 345 678").isSuccess)
        assertTrue("request-permission 254712345678" in r.api.log)
    }

    @Test fun requestPermissionFailureIsReported() = rig { r ->
        r.api.permissionError = ApiException(502, "POST", "/admin/calls/request-permission", "{}")
        assertTrue(r.calls.requestPermission("254712345678").isFailure)
    }

    @Test fun outboundOtherFailuresAndMicRefusal() = rig { r ->
        r.api.connectError = ApiException(502, "POST", "/admin/calls/connect", """{"detail":"call failed"}""")
        val a = async { r.calls.initiateCall("254712345678") }
        r.settle()
        assertEquals("Couldn't place the call", a.await().exceptionOrNull()!!.message)
        advanceTimeBy(2_201); runCurrent()

        r.api.connectError = null
        r.mic = false
        val b = async { r.calls.initiateCall("254712345678") }
        r.settle()
        r.calls.onMicResult(false); r.settle()
        val msg = b.await().exceptionOrNull()!!.message!!
        assertEquals(CallManager.MIC_BLOCKED, msg)
        assertFalse("not the customer's permission", msg.contains("permission", ignoreCase = true))
        assertFalse(r.api.log.count { it.startsWith("connect") } > 1)
    }

    @Test fun outboundWhileBusyIsRefused() = rig { r ->
        r.ring()
        val res = async { r.calls.initiateCall("254700000000") }
        r.settle()
        assertEquals("Already in a call", res.await().exceptionOrNull()!!.message)
        assertEquals("wacid.1", r.state.callId)
    }

    @Test fun hangingUpAPendingOutboundCallNeverTerminatesPending() = rig { r ->
        r.media.gatherAtOnce = false
        val res = async { r.calls.initiateCall("254712345678") }
        r.settle()
        r.calls.hangup(); r.settle()
        advanceTimeBy(2_600); runCurrent()
        assertTrue(res.await().isSuccess)
        assertFalse(r.api.log.any { it.startsWith("terminate") || it.startsWith("connect") })
    }

    @Test fun hangingUpWhileMetaPlacesTheCallTerminatesIt() = rig { r ->
        r.api.connectGate = CompletableDeferred()
        val res = async { r.calls.initiateCall("254712345678") }
        r.settle()
        r.calls.hangup(); r.settle()
        r.api.connectGate!!.complete(Unit); r.settle()
        assertTrue(res.await().isSuccess)
        assertTrue("terminate wacid.out1" in r.api.log)
    }

    @Test fun outboundErrorResetDoesNotWipeALaterCall() = rig { r ->
        r.api.connectError = ApiException(502, "POST", "/admin/calls/connect", "{}")
        val a = async { r.calls.initiateCall("254712345678") }
        r.settle(); a.await()
        r.calls.hangup(); r.settle()             // dismiss the error early
        advanceTimeBy(1_001); runCurrent()
        r.ring("wacid.9")
        advanceTimeBy(1_500); runCurrent()       // past the old 2.2s reset
        assertEquals(CallPhase.Ringing, r.state.phase)
    }

    // ── Notification actions ─────────────────────────────────────────────────
    @Test fun notificationAnswerAndDecline() = rig { r ->
        r.ring()
        r.calls.handleAction("answer", "wacid.other"); r.settle()
        assertEquals("a stale notification's action is ignored", CallPhase.Ringing, r.state.phase)
        r.calls.handleAction("answer", "wacid.1"); r.settle()
        assertTrue("answer wacid.1" in r.api.log)
        r.calls.hangup(); r.settle(); advanceTimeBy(1_001); runCurrent()
        advanceTimeBy(12_000); runCurrent()
        r.ring("wacid.2")
        r.calls.handleAction("decline", "wacid.2"); r.settle()
        assertTrue("terminate wacid.2" in r.api.log)
        assertEquals(CallPhase.Ended, r.state.phase)
    }

    @Test fun notificationActionsAfterAProcessRestart() = rig { r ->
        r.api.calls = listOf(Call(id = "k1", callId = "wacid.7", waId = "254712345678", status = "ringing", startedAt = r.at(10_000)))
        r.calls.handleAction("answer", "wacid.7"); r.settle()
        assertEquals("found by polling, then answered", CallPhase.Connecting, r.state.phase)
        assertTrue("answer wacid.7" in r.api.log)
        r.calls.hangup(); r.settle(); advanceTimeBy(1_001); runCurrent()
        r.calls.handleAction("decline", "wacid.8"); r.settle()
        assertTrue("terminate wacid.8" in r.api.log)
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun errorMapping() {
        val e409 = ApiException(409, "POST", "/admin/calls/connect", "{}")
        assertEquals(CallManager.NO_CALL_PERMISSION, CallManager.outboundError(e409))
        assertEquals("Couldn't place the call", CallManager.outboundError(ApiException(502, "POST", "/x", "{}")))
        assertEquals("Couldn't place the call", CallManager.outboundError(IllegalStateException("sdp")))
        assertEquals("Couldn't connect the call", CallManager.answerError(e409))
    }

    // ── WebSocket frames, byte for byte as the webhook publishes them ────────
    private val wacid = "wacid.HBgMMjU0NzEyMzQ1Njc4FQIAEhggQUFBQTFCMkMzRDRFNUY2QTdCOEM5RDBFMUYyHBgMMjU0NzAwMDAwMDAwFQIAAA=="

    @Test fun realIncomingCallFrameRings() = rig { r ->
        // _handle_calls, event == "connect" with an offer: `at` is Meta's string
        // timestamp, `name` null when the contacts block had no profile.
        r.raw("""{"type": "incoming_call", "call_id": "$wacid", "from": "254712345678", "name": null, "at": "1790330413"}""")
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals(wacid, r.state.callId)
        assertEquals("254712345678", r.state.from)
        assertNull(r.state.name)
    }

    @Test fun realOutboundAnswerFrameAppliesTheCustomersSdp() = rig { r ->
        r.api.connectId = wacid
        val placed = async { r.calls.initiateCall("+254712345678", "Fr. Peter Kamau") }
        r.settle()
        assertTrue(placed.await().isSuccess)
        // event == "connect" with sdp_type == "answer" → outbound_answer {call_id, sdp}.
        r.raw("""{"type": "outbound_answer", "call_id": "$wacid", "sdp": "v=0\r\na=setup:passive\r\n"}""")
        assertTrue(r.media.peer.ops.contains("setRemote(Answer,v=0\r\na=setup:passive\r\n)"))
        // Another agent's outbound call is not ours.
        r.raw("""{"type": "outbound_answer", "call_id": "wacid.other", "sdp": "v=0"}""")
        assertEquals(1, r.media.peer.ops.count { it.startsWith("setRemote") })
    }

    @Test fun realCallEndedFrameEndsTheCall() = rig { r ->
        r.raw("""{"type": "incoming_call", "call_id": "$wacid", "from": "254712345678", "name": "Fr. Peter Kamau", "at": "1790330413"}""")
        // event == "terminate": status is Meta's (e.g. "COMPLETED"), duration an int or null.
        r.raw("""{"type": "call_ended", "call_id": "$wacid", "status": "COMPLETED", "duration": 42}""")
        assertEquals(CallPhase.Ended, r.state.phase)
        assertFalse(r.ringer.ringing)
    }

    @Test fun unrelatedFramesOnTheSharedSocketAreIgnored() = rig { r ->
        // websocket.py relays every ws:channel:* to every client.
        r.raw("""{"type": "new_message", "conversation_id": "c1", "call_id": 5}""")
        r.raw("""{"type": "incoming_call", "from": "254712345678"}""")   // no call_id
        assertEquals(CallPhase.Idle, r.state.phase)
    }

}
