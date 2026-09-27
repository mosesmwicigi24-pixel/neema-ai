package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.LogItem
import ke.co.bethanyhouse.neema.feature.calls.insertByTime
import ke.co.bethanyhouse.neema.feature.calls.logItems
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant
import kotlin.random.Random

/**
 * Garbage in, no crash out (2026-09-27, "Neema closed because this app has a
 * bug"). Thousands of seeded random socket frames — every event type the
 * server publishes plus unknown ones, each field any JSON shape — go straight
 * into CallManager.onFrame (no safety net in between: a throw fails the test),
 * and the phone still rings a real call afterwards. The Calls log is fuzzed
 * the same way: random live updates never repeat a lazy-list key.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class FrameFuzzTest {
    private val base = Instant.parse("2026-09-25T10:00:00Z").toEpochMilli()

    private val types = listOf(
        "incoming_call", "call_answered", "call_ended", "call_update", "call_permission", "call_status",
        "calling_restricted", "call_settings", "media_update", "outbound_answer", "notification", "pong", "", "???",
    )
    private val keys = listOf(
        "call_id", "from", "external_id", "name", "conversation_id", "person_id", "channel", "sdp", "sdp_type",
        "status", "outcome", "duration", "agent_id", "agent_name", "version", "reasons", "at", "call", "wa_id",
        "response", "is_permanent", "expiration_timestamp", "psid", "type",
    )

    private fun Random.value(depth: Int = 0): JsonElement = when (nextInt(if (depth > 1) 8 else 11)) {
        0 -> JsonNull
        1 -> JsonPrimitive("")
        2 -> JsonPrimitive(listOf("wacid.1", "wacid.2", "c_1", "pending", "254712345678", "messenger", "whatsapp").random(this))
        3 -> JsonPrimitive(nextLong())
        4 -> JsonPrimitive(nextDouble() * 1e12)
        5 -> JsonPrimitive(nextBoolean())
        6 -> JsonPrimitive(listOf("NaN", "-1", "1e309", "ringing", "rejected", "offer", "answer", "v=0\r\n", "ü👩🏽‍💻", "x".repeat(5000)).random(this))
        7 -> JsonPrimitive(listOf("2026-09-27T18:35:00Z", "2026-09-27 18:35:00", "not a date", "+0000", "9999999999").random(this))
        8 -> JsonArray(List(nextInt(4)) { value(depth + 1) })
        9 -> JsonObject(List(nextInt(4)) { keys.random(this) to value(depth + 1) }.toMap())
        else -> JsonObject(mapOf("call_id" to value(depth + 1), "status" to value(depth + 1), "started_at" to value(depth + 1)))
    }

    private fun Random.frame(): JsonObject {
        val m = HashMap<String, JsonElement>()
        m["type"] = if (nextInt(10) == 0) value() else JsonPrimitive(types.random(this))
        repeat(nextInt(8)) { m[keys.random(this)] = value() }
        if (nextBoolean()) m["call_id"] = JsonPrimitive(listOf("wacid.1", "wacid.2", "c_1", "pending").random(this))
        return JsonObject(m)
    }

    @Test fun randomFramesNeverThrowAndThePhoneStillRings() = runTest {
        val api = FakeCallApi()
        val d = StandardTestDispatcher(testScheduler)
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val calls = CallManager(
            api = api, events = frames, connected = MutableStateFlow(true), scope = backgroundScope,
            foreground = MutableStateFlow(true), signedInFn = { true }, media = FakeMedia(), ringer = FakeRinger(),
            audio = FakeAudio(), micGranted = { true }, main = d, io = d, now = { base + testScheduler.currentTime },
        ).also { it.start() }
        runCurrent()
        val rnd = Random(20260927)
        repeat(4000) { i ->
            calls.onFrame(rnd.frame())
            runCurrent()
            if (i % 250 == 0) { advanceTimeBy(15_000); runCurrent() }
        }
        // Whatever state the storm left, a fresh call still rings this phone.
        for (id in listOf("wacid.1", "wacid.2", "c_1", "pending")) {
            calls.onFrame(JsonObject(mapOf("type" to JsonPrimitive("call_ended"), "call_id" to JsonPrimitive(id), "outcome" to JsonPrimitive("missed"))))
        }
        advanceTimeBy(120_000); runCurrent()
        calls.dismiss()
        runCurrent()
        calls.onFrame(JsonObject(mapOf("type" to JsonPrimitive("incoming_call"), "call_id" to JsonPrimitive("wacid.fresh"),
            "from" to JsonPrimitive("254700000001"), "name" to JsonPrimitive("Grace Wanjiku"))))
        runCurrent()
        assertEquals("wacid.fresh", calls.state.value.callId)
        assertEquals(CallPhase.Ringing, calls.state.value.phase)
    }

    @Test fun randomLiveUpdatesNeverRepeatALogKey() {
        val rnd = Random(927)
        val days = listOf("2026-09-27T12:00:00Z", "2026-09-26T08:00:00Z", "2026-09-12T10:00:00Z", "2026-08-01T00:00:00Z", null, "garbage")
        var log = (0 until 60).map { Call(callId = "c$it", status = "completed", startedAt = days[it % 4]) }
            .sortedByDescending { it.startedAt }
        repeat(3000) {
            val id = if (rnd.nextBoolean()) "c${rnd.nextInt(80)}" else "n${rnd.nextInt(500)}"
            val row = Call(callId = id, status = "missed", startedAt = days.random(rnd))
            log = if (log.any { it.callId == id }) log.map { if (it.callId == id) row else it } else insertByTime(log, row) ?: log
            val keys = logItems(log).map { when (it) { is LogItem.Day -> it.key; is LogItem.Row -> it.key } }
            assertEquals("a repeated lazy key crashes the Calls screen", keys.size, keys.toSet().size)
        }
    }
}
