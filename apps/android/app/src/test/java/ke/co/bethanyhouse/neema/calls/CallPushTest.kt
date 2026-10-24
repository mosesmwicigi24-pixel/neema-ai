package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import ke.co.bethanyhouse.neema.core.notify.Push
import ke.co.bethanyhouse.neema.core.notify.PushRegistrar
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.testing.FakeNeema
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * Owner, 2026-10-24: "The calls should come through even the app is not open.
 * When any phone is on, route the call there." The server pushes every call
 * event to every signed-in phone (apps/api services/push.py); a push is handled
 * exactly like the socket frame: it rings, a colleague's answer stops it, a
 * ring heard on both paths rings once, and a ring that arrives long after the
 * caller gave up is not rung at all.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallPushTest {
    private val base = Instant.parse("2026-10-24T10:00:00Z").toEpochMilli()

    private inner class Rig(val scope: TestScope) {
        val api = FakeCallApi()
        val ringer = FakeRinger()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = api, events = frames, connected = MutableStateFlow(true), scope = scope.backgroundScope,
            foreground = MutableStateFlow(false), signedInFn = { true }, media = FakeMedia(), ringer = ringer, audio = FakeAudio(),
            micGranted = { true }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
            audioTrouble = MutableSharedFlow(),
        ).also { it.start() }
        val state get() = calls.state.value
        fun settle() = scope.runCurrent()
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest { val r = Rig(this); r.settle(); block(r) }

    private fun push(vararg kv: Pair<String, String>, now: Long = base) =
        Push.frameOf(mapOf(*kv), now)

    private val ring = arrayOf("type" to "incoming_call", "call_id" to "wacid.p1", "from" to "254712345678",
        "name" to "Fr. Peter Kamau", "channel" to "whatsapp", "at" to (base / 1000).toString())

    @Test fun aPushedRingRingsThisPhoneWithTheAppClosed() = rig { r ->
        r.calls.onPush(push(*ring)!!); r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("wacid.p1", r.state.callId)
        assertEquals("Fr. Peter Kamau", r.state.name)
    }

    @Test fun aRingHeardByPushAndSocketRingsOnce() = rig { r ->
        r.calls.onPush(push(*ring)!!); r.settle()
        r.frames.tryEmit(JsonObject(ring.associate { it.first to JsonPrimitive(it.second) })); r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("one ringing notification, not two", 1, r.ringer.posted.size)
    }

    @Test fun aColleagueAnsweringStopsThisPhone() = rig { r ->
        r.calls.onPush(push(*ring)!!); r.settle()
        r.calls.onPush(push("type" to "call_answered", "call_id" to "wacid.p1", "agent_id" to "someone-else",
            "agent_name" to "Ann", "direction" to "inbound")!!)
        r.settle(); r.scope.advanceTimeBy(10_000); r.settle()
        assertFalse("answered elsewhere: this phone stops", r.state.phase == CallPhase.Ringing)
    }

    @Test fun theCallerHangingUpStopsThisPhone() = rig { r ->
        r.calls.onPush(push(*ring)!!); r.settle()
        r.calls.onPush(push("type" to "call_ended", "call_id" to "wacid.p1", "outcome" to "missed")!!)
        r.settle(); r.scope.advanceTimeBy(10_000); r.settle()
        assertFalse(r.state.phase == CallPhase.Ringing)
    }

    @Test fun onlyCallEventsBecomeFramesAndAnOldRingIsNotRung() {
        assertNotNull(push(*ring))
        assertNull("a phone that was off gets the ring minutes later: not rung",
            push(*ring, now = base + Push.STALE_RING_MS + 1_000))
        assertNotNull("milliseconds are understood too",
            push("type" to "incoming_call", "call_id" to "x", "at" to base.toString(), now = base + 5_000))
        assertNotNull("no timestamp: rung (the call log decides)", push("type" to "incoming_call", "call_id" to "x"))
        assertNull(push("type" to "call_update", "call_id" to "x"))
        assertNull(push("type" to "incoming_call"))
        assertNull(push("call_id" to "x"))
    }

    private class Tok : TokenProvider {
        override suspend fun validAccessToken() = "tok"
        override suspend fun forceRefresh(): String? = null
        override fun onRejected(token: String?) {}
    }

    @Test fun thePhoneIsRegisteredOnSignInAndTakenOffOnSignOut() = runBlocking {
        val fake = FakeNeema()
        fake.on("POST", "/admin/push/register", body = """{"ok":true,"push":true}""")
        fake.on("POST", "/admin/push/unregister", body = """{"ok":true}""")
        val http = NeemaHttp("https://neema.test", Tok(), fake, Dispatchers.Unconfined)
        val agent = MutableStateFlow<String?>(null)
        val reg = PushRegistrar(CoroutineScope(Dispatchers.Unconfined), http, agent,
            token = { "fcm-token-" + "a".repeat(40) }, enabled = { true }, appVersion = "1.0.0 (90)", device = { "samsung SM-X910" })
        reg.start()
        assertTrue("signed out: not registered", fake.calls.none { it.path.endsWith("/push/register") })
        agent.value = "agent-1"
        val sent = fake.calls.filter { it.path.endsWith("/admin/push/register") }
        assertEquals(1, sent.size)
        val b = sent[0].body!!
        assertTrue(b.contains("\"token\":\"fcm-token-aaaa") && b.contains("\"platform\":\"android\"") &&
            b.contains("\"app_version\":\"1.0.0 (90)\"") && b.contains("\"device\":\"samsung SM-X910\""))
        reg.onNewToken("fcm-token-" + "b".repeat(40))
        assertEquals("a rotated token is sent at once", 2, fake.calls.count { it.path.endsWith("/admin/push/register") })
        reg.unregister()
        val off = fake.calls.single { it.path.endsWith("/admin/push/unregister") }
        assertTrue("the latest token is the one taken off", off.body!!.contains("bbbb"))
    }

    @Test fun pushOffBuildsNeverTalkAboutIt() = runBlocking {
        val fake = FakeNeema()
        val http = NeemaHttp("https://neema.test", Tok(), fake, Dispatchers.Unconfined)
        val reg = PushRegistrar(CoroutineScope(Dispatchers.Unconfined), http, MutableStateFlow("agent-1"),
            token = { "t".repeat(50) }, enabled = { false })
        reg.start(); reg.onNewToken("x".repeat(50)); reg.unregister()
        assertFalse(reg.register())
        assertTrue(fake.calls.isEmpty())
    }

    @Test fun aFailedRegistrationNeverThrows() = runBlocking {
        val fake = FakeNeema()
        fake.on("POST", "/admin/push/register", code = 503, body = "down")
        val http = NeemaHttp("https://neema.test", Tok(), fake, Dispatchers.Unconfined)
        val reg = PushRegistrar(CoroutineScope(Dispatchers.Unconfined), http, MutableStateFlow("agent-1"),
            token = { "t".repeat(50) }, enabled = { true })
        assertFalse(reg.register())
    }
}
