package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.NeemaCallApi
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import ke.co.bethanyhouse.neema.testing.testContainer
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * The softphone's requests over the real HTTP client, against the fake backend:
 * the same paths and bodies as callsApi in lib/api.ts (routers/admin.py).
 * (Paparazzi only supplies an Android context here.)
 */
class CallApiContractTest {
    @get:Rule val paparazzi = Paparazzi()

    private fun rig(): Pair<FakeNeema, NeemaCallApi> {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        fake.on("GET", "/admin/calls/ice-config", body = """{"ice_servers":[{"urls":"turn:turn.example:3478","username":"u","credential":"p"},
            {"urls":["stun:stun.example:3478"]}],"record":false}""")
        fake.on("GET", "/admin/calls/[^/]+/offer", body = """{"call_id":"wacid.1","sdp":"v=0 offer","from":"254712345678"}""")
        fake.on("POST", "/admin/calls/connect", body = """{"ok":true,"call_id":"wacid.out9"}""")
        return fake to NeemaCallApi(testContainer(paparazzi.context, fake).api)
    }

    @Test fun pathsAndBodies() = runBlocking {
        val (fake, api) = rig()
        assertEquals(7, api.list().size)
        val ice = api.iceConfig()
        assertEquals(2, ice.iceServers.size)
        assertEquals(false, ice.record)
        assertEquals("v=0 offer", api.offer("wacid.1").sdp)
        api.answer("wacid.1", "v=0 answer")
        api.terminate("wacid.1")
        api.callback("wacid.1")
        assertEquals("wacid.out9", api.connect("254712345678", "v=0 our-offer", "Fr. Peter Kamau"))
        api.requestPermission("254712345678")
        val rec = java.io.File.createTempFile("rec", ".m4a").apply { writeBytes(ByteArray(3000) { 7 }); deleteOnExit() }
        api.uploadRecording("wacid.1", rec, "wacid.1.m4a", "audio/mp4")

        fun body(m: String, p: String) = fake.calls.last { it.method == m && it.path == p }.body.orEmpty()
        assertEquals("""{"sdp":"v=0 answer"}""", body("POST", "/admin/calls/wacid.1/answer"))
        assertEquals("{}", body("POST", "/admin/calls/wacid.1/terminate"))
        assertEquals("{}", body("POST", "/admin/calls/wacid.1/callback"))
        assertEquals("""{"to":"254712345678","sdp":"v=0 our-offer","name":"Fr. Peter Kamau"}""", body("POST", "/admin/calls/connect"))
        assertEquals("""{"to":"254712345678"}""", body("POST", "/admin/calls/request-permission"))
        val upload = body("POST", "/admin/calls/wacid.1/recording")
        assertTrue(upload.contains("name=\"file\"") && upload.contains("filename=\"wacid.1.m4a\""))
        assertTrue("streamed body carries the file", upload.contains("Content-Type: audio/mp4") && upload.length > 3000)
    }

    @Test fun connectWithoutPermissionMapsToTheWebCopy() = runBlocking {
        val (fake, api) = rig()
        fake.on("POST", "/admin/calls/connect", code = 409,
            body = """{"detail":"This customer hasn't granted call permission yet. Send the WhatsApp template first, or wait until they message/call us."}""")
        val e = runCatching { api.connect("254712345678", "sdp", null) }.exceptionOrNull()
        assertTrue(e is ApiException && e.status == 409)
        assertEquals(CallManager.NO_CALL_PERMISSION, CallManager.outboundError(e!!))
        assertEquals("""{"to":"254712345678","sdp":"sdp"}""", fake.calls.last().body)
    }
}
