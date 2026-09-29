package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.MESSENGER
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.WHATSAPP
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Deferred
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
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException
import java.time.Instant
import kotlin.random.Random

/**
 * Seeded random simulations of an agent's day on the softphone: WhatsApp and
 * Messenger, placing and answering, with the taps, server frames, network
 * failures, device (native) failures, slow servers and timing a real phone
 * sees, in random order. After every step, and at the end of every run:
 *
 * - nothing escapes (initiateCall returns, never throws; no coroutine fails);
 * - no WebRTC peer is ever used after close() (on a phone: a native crash);
 * - with no call up, the call audio and the microphone service are let go
 *   and every peer is closed;
 * - once the dust settles, a clean call on each channel still connects.
 *
 * A failure prints its seed and the steps that led there, so it replays exactly.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallSimulationTest {
    private val base = Instant.parse("2026-09-29T10:00:00Z").toEpochMilli()

    private inner class Sim(val scope: TestScope, val rnd: Random) {
        val api = FakeCallApi()
        val throwing = CallResilienceTest.ThrowingApi(api)
        val media = CallResilienceTest.FlakyMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 256)
        val foreground = MutableStateFlow(true)
        val connected = MutableStateFlow(true)
        var mic = true
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = throwing, events = frames, connected = connected, scope = scope.backgroundScope, foreground = foreground,
            signedInFn = { true }, media = media, ringer = ringer, audio = audio,
            micGranted = { mic }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
        ).also { it.start() }
        val log = mutableListOf<String>()
        val placed = mutableListOf<Deferred<Result<Unit>>>()
        var incoming = 0
        val peers get() = media.peers.map { it.inner }

        fun emit(vararg kv: Pair<String, String>) { frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) })) }
        fun state() = calls.state.value

        /** The ids a frame could be about: the live call, the last placed ones, a stranger's. */
        fun someId(): String = listOf(
            state().callId ?: "wacid.none", api.connectId, api.messengerConnectId, "wacid.in$incoming", "c_msg.in$incoming", "wacid.stranger",
        ).random(rnd)

        fun check(where: String) {
            peers.forEachIndexed { i, p -> if (p.usedAfterClose.isNotEmpty()) fail("$where: peer $i used after close ${p.usedAfterClose}\n${log.joinToString("\n")}") }
            val s = state()
            if (s.phase == CallPhase.Idle || s.phase == CallPhase.Ended) {
                if (audio.inCall) fail("$where: call audio held with no call (${s.phase})\n${log.joinToString("\n")}")
                if (audio.micService) fail("$where: microphone service up with no call (${s.phase})\n${log.joinToString("\n")}")
                peers.forEachIndexed { i, p -> if (!p.closed) fail("$where: peer $i still open with no call\n${log.joinToString("\n")}") }
            }
        }

        fun step(n: Int) {
            val s = state()
            val what = when (rnd.nextInt(100)) {
                in 0..11 -> {
                    val ch = if (rnd.nextBoolean()) WHATSAPP else MESSENGER
                    placed += scope.async { calls.initiateCall(if (ch == MESSENGER) "7788990011" else "254712345678", listOf("Fr. Peter Kamau", "", null).random(rnd), null, ch) }
                    "place $ch"
                }
                in 12..19 -> { calls.hangup(); "hang up" }
                in 20..25 -> { calls.answer(); "answer" }
                in 26..33 -> {
                    incoming++
                    val m = rnd.nextBoolean()
                    val id = if (m) "c_msg.in$incoming" else "wacid.in$incoming"
                    if (m) api.messengerCalls += id
                    if (m) emit("type" to "incoming_call", "call_id" to id, "from" to "7788990011", "name" to "Grace", "channel" to MESSENGER)
                    else emit("type" to "incoming_call", "call_id" to id, "from" to "254712345678", "name" to "Fr. Peter Kamau")
                    "ring $id"
                }
                in 34..40 -> { val id = someId(); emit("type" to "outbound_answer", "call_id" to id, "sdp" to "v=0 their-answer"); "answer frame $id" }
                in 41..45 -> { val id = someId(); emit("type" to "call_status", "call_id" to id, "status" to listOf("ringing", "accepted", "rejected", "completed", "failed").random(rnd)); "status $id" }
                in 46..51 -> { val id = someId(); emit("type" to "call_ended", "call_id" to id); "ended $id" }
                in 52..55 -> { val id = someId(); emit("type" to "call_answered", "call_id" to id, "by" to listOf("Moses", "Grace Wanjiru").random(rnd)); "answered elsewhere $id" }
                in 56..58 -> { val id = someId(); emit("type" to "media_update", "call_id" to id, "sdp" to "v=0 renegotiate"); "media_update $id" }
                in 59..66 -> {
                    val p = media.peers.lastOrNull()?.inner ?: return log.add("$n: (no peer)").let { }
                    val ev = listOf(PeerEvent.Connected, PeerEvent.Connected, PeerEvent.Interrupted, PeerEvent.Ended).random(rnd)
                    p.onEvent(ev); "peer $ev"
                }
                in 67..72 -> {
                    // A device failure somewhere in the next WebRTC step (an Error, as the native side throws).
                    val st = CallResilienceTest.Step.entries.random(rnd); media.arm(st); "arm native fault $st"
                }
                in 73..77 -> {
                    when (rnd.nextInt(5)) {
                        0 -> { api.connectError = ApiException(409, "POST", "/admin/calls/connect", """{"detail":"This customer hasn't granted call permission yet."}"""); "server: no permission" }
                        1 -> { api.connectError = IOException("Connection reset"); "server: connection drop on connect" }
                        2 -> { api.answerError = ApiException(409, "POST", "/admin/calls/x/answer", """{"detail":"call already answered by Grace"}"""); "server: taken elsewhere" }
                        3 -> { throwing.connectFault = OutOfMemoryError("response"); "server: Error on connect" }
                        else -> { api.connectError = null; api.answerError = null; "server: healthy" }
                    }
                }
                in 78..80 -> {
                    // A slow server: the next connect waits until released a few steps later.
                    if (api.connectGate == null) { api.connectGate = CompletableDeferred(); "server: slow connect" }
                    else { api.connectGate?.complete(Unit); api.connectGate = null; "server: slow connect answers" }
                }
                in 81..83 -> {
                    if (media.inner.sdpGate == null) { media.inner.sdpGate = CompletableDeferred(); "webrtc: slow SDP" }
                    else { media.inner.sdpGate?.complete(Unit); media.peers.forEach { it.inner.sdpGate?.complete(Unit) }; media.inner.sdpGate = null; "webrtc: SDP done" }
                }
                in 84..85 -> { mic = !mic; "mic permission ${if (mic) "on" else "off"}" }
                86 -> { calls.onMicResult(rnd.nextBoolean()); "mic prompt answered" }
                87 -> { foreground.value = !foreground.value; "app ${if (foreground.value) "foreground" else "background"}" }
                88 -> { connected.value = !connected.value; "socket ${if (connected.value) "up" else "down"}" }
                in 89..90 -> { calls.toggleMute(); calls.toggleSpeaker(); "mute + speaker" }
                91 -> { calls.minimise(); calls.expand(); "minimise + expand" }
                92 -> { calls.redial(); "redial" }
                93 -> { calls.callback(); "call back" }
                94 -> { calls.dismiss(); "dismiss wrap-up" }
                95 -> { calls.endAndAnswer(); "end and answer waiting" }
                96 -> { calls.declineWaiting(); "decline waiting" }
                else -> { val ms = listOf(100L, 1_000L, 2_500L, 5_000L, 13_000L, 60_000L, 130_000L).random(rnd); scope.advanceTimeBy(ms); "wait ${ms}ms" }
            }
            scope.runCurrent()
            log += "$n: $what → ${state().phase}${state().callId?.let { " $it" } ?: ""}"
            check("step $n ($what) from ${s.phase}")
        }

        /** Every slow thing answers, time passes, the card is closed: the phone is at rest. */
        fun settleDown() {
            api.connectGate?.complete(Unit); api.connectGate = null
            media.inner.sdpGate?.complete(Unit); media.inner.sdpGate = null
            media.peers.forEach { it.inner.sdpGate?.complete(Unit) }
            media.faults.clear()
            api.connectError = null; api.answerError = null; throwing.connectFault = null
            mic = true; connected.value = true; foreground.value = true
            repeat(3) { scope.advanceTimeBy(150_000); scope.runCurrent(); calls.hangup(); scope.runCurrent(); calls.dismiss(); scope.runCurrent() }
            scope.advanceTimeBy(150_000); scope.runCurrent()
        }
    }

    private fun simulate(seed: Int, steps: Int, stats: MutableMap<String, Int>) = runTest {
        val sim = Sim(this, Random(seed))
        runCurrent()
        try {
            repeat(steps) { sim.step(it) }
            sim.settleDown()
            sim.check("at rest")
            assertEquals("seed $seed: at rest", CallPhase.Idle, sim.state().phase)
            // Every placement came back (never threw — async would rethrow here).
            sim.placed.forEach { d -> assertTrue("seed $seed: a placement never finished", d.isCompleted); d.await() }
            // …and the phone still calls, on both channels.
            for (ch in listOf(WHATSAPP, MESSENGER)) {
                val r = async { sim.calls.initiateCall(if (ch == MESSENGER) "7788990011" else "254712345678", "Grace", null, ch) }
                runCurrent()
                assertTrue("seed $seed: a clean $ch call after the run: ${r.await().exceptionOrNull()?.message}", r.await().isSuccess)
                if (ch == WHATSAPP) sim.emit("type" to "outbound_answer", "call_id" to sim.api.connectId, "sdp" to "v=0 their-answer")
                else sim.emit("type" to "call_answered", "call_id" to sim.api.messengerConnectId)
                runCurrent()
                sim.media.peers.last().inner.onEvent(PeerEvent.Connected); runCurrent()
                assertEquals("seed $seed: $ch connects", CallPhase.InCall, sim.state().phase)
                sim.calls.hangup(); runCurrent(); advanceTimeBy(10_000); runCurrent(); sim.calls.dismiss(); runCurrent()
                sim.check("after the clean $ch call")
                assertFalse(sim.audio.inCall)
            }
            synchronized(stats) {
                stats.merge("runs", 1, Int::plus)
                stats.merge("peers", sim.media.peers.size, Int::plus)
                stats.merge("placements", sim.placed.size, Int::plus)
                stats.merge("reachedInCall", if (sim.log.any { it.endsWith("InCall") || it.contains("→ InCall") }) 1 else 0, Int::plus)
                stats.merge("nativeFaults", sim.log.count { "native fault" in it }, Int::plus)
            }
        } catch (e: Throwable) {
            throw AssertionError("seed $seed failed: ${e.message}\n--- steps ---\n${sim.log.takeLast(40).joinToString("\n")}", e)
        }
    }

    @Test fun twoThousandRandomAgentDays() {
        val stats = sortedMapOf<String, Int>()
        for (seed in 1..2_000) simulate(seed, steps = 60, stats = stats)
        println("CALL SIMULATION: $stats")
        assertEquals(2_000, stats["runs"])
        assertTrue("the simulation reaches live calls, not just failures", (stats["reachedInCall"] ?: 0) > 200)
    }

    @Test fun twoHundredLongShifts() {
        val stats = sortedMapOf<String, Int>()
        for (seed in 10_001..10_200) simulate(seed, steps = 400, stats = stats)
        println("CALL SIMULATION (long): $stats")
        assertEquals(200, stats["runs"])
    }
}
