package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.util.AppClock

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallOffer
import ke.co.bethanyhouse.neema.core.model.CallTranscript
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.IceSpec
import ke.co.bethanyhouse.neema.feature.calls.NeemaCallApi
import ke.co.bethanyhouse.neema.feature.calls.iceSpecs
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures.C1
import ke.co.bethanyhouse.neema.testing.testContainer
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.builtins.ListSerializer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * The softphone's API contract against what routers/admin.py's `/calls*`
 * handlers really send and accept: exact method, encoded path, query and body
 * for every request, and decoding of the real response shapes — including the
 * nulls, the legacy rows with missing keys, `+00:00` microsecond timestamps,
 * the two ICE `urls` shapes, and every error body the handlers raise.
 * (Paparazzi only supplies an Android context here.)
 */
class CallApiContractTest {
    @get:Rule val paparazzi = Paparazzi()

    private fun rig(): Pair<FakeNeema, NeemaCallApi> {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        fake.on("GET", CallsFixtures.route(C1, "offer"), body = CallsFixtures.offer(C1))
        // calls_answer / terminate / callback → {"ok": True, "call_id": call_id}
        for (s in listOf("answer", "terminate", "callback")) fake.on("POST", CallsFixtures.route(C1, s), body = """{"ok":true,"call_id":"$C1"}""")
        // calls_connect → {"ok": True, "call_id": <Meta's new wacid>}
        fake.on("POST", "/admin/calls/connect", body = """{"ok":true,"call_id":"${CallsFixtures.wacid("T1VU")}"}""")
        // calls_request_permission → {"ok": True}
        fake.on("POST", "/admin/calls/request-permission", body = """{"ok":true}""")
        // calls_upload_recording → {"ok": True, "call_id": ..., "will_transcribe": auto}
        fake.on("POST", CallsFixtures.route(C1, "recording"), body = """{"ok":true,"call_id":"$C1","will_transcribe":false}""")
        return fake to NeemaCallApi(testContainer(paparazzi.context, fake).api)
    }

    private fun FakeNeema.last(m: String, p: String) = calls.last { it.method == m && it.path == p }

    // ── Requests ─────────────────────────────────────────────────────────────
    @Test fun everyRequestMatchesTheHandlers() = runBlocking {
        val (fake, api) = rig()
        api.list(); api.iceConfig(); api.offer(C1)
        api.answer(C1, "v=0 answer"); api.terminate(C1); api.callback(C1)
        api.connect("254712345678", "v=0 our-offer", "Fr. Peter Kamau")
        api.requestPermission("254712345678")
        val rec = java.io.File.createTempFile("rec", ".m4a").apply { writeBytes(ByteArray(3000) { 7 }); deleteOnExit() }
        api.uploadRecording(C1, UploadFile.of(rec, "$C1.m4a", "audio/mp4"))

        // The wacid's `==` is percent-encoded, exactly as encodeURIComponent does.
        val enc = C1.replace("=", "%3D")
        assertEquals("/admin/calls/$enc/offer", CallsFixtures.path(C1, "offer"))

        // list_calls: GET, no `limit` (the web sends none; the handler defaults to 50).
        assertNull(fake.last("GET", "/admin/calls").query)
        assertTrue(fake.calls.any { it.method == "GET" && it.path == "/admin/calls/ice-config" && it.query == null })
        assertTrue(fake.calls.any { it.method == "GET" && it.path == "/admin/calls/$enc/offer" })
        // calls_answer reads body["sdp"]; terminate/callback take no body (the web posts {}).
        assertEquals("""{"sdp":"v=0 answer"}""", fake.last("POST", "/admin/calls/$enc/answer").body)
        assertEquals("{}", fake.last("POST", "/admin/calls/$enc/terminate").body)
        assertEquals("{}", fake.last("POST", "/admin/calls/$enc/callback").body)
        // calls_connect reads to / sdp / name; calls_request_permission reads to.
        assertEquals("""{"to":"254712345678","sdp":"v=0 our-offer","name":"Fr. Peter Kamau"}""",
            fake.last("POST", "/admin/calls/connect").body)
        assertEquals("""{"to":"254712345678"}""", fake.last("POST", "/admin/calls/request-permission").body)
        // calls_upload_recording: `file: UploadFile = File(...)`; the extension
        // comes from the file name (a wacid has dots — splitext still yields .m4a).
        val up = fake.last("POST", "/admin/calls/$enc/recording")
        val body = up.body.orEmpty()
        assertTrue(body.contains("Content-Disposition: form-data; name=\"file\"; filename=\"$C1.m4a\""))
        assertTrue(body.contains("Content-Type: audio/mp4") && body.length > 3000)
        assertEquals(".m4a", "$C1.m4a".substring("$C1.m4a".lastIndexOf('.')))
    }

    @Test fun connectWithoutANameOmitsIt() = runBlocking {
        val (fake, api) = rig()
        api.connect("254712345678", "sdp", null)
        assertEquals("""{"to":"254712345678","sdp":"sdp"}""", fake.calls.last().body)
    }

    // ── Responses ────────────────────────────────────────────────────────────
    @Test fun theCallLogDecodesAsTheHandlerBuildsIt() = runBlocking {
        val (_, api) = rig()
        val rows = api.list()
        assertEquals(7, rows.size)
        val first = rows[0]
        assertEquals(CallsFixtures.K1, first.id)
        assertEquals(C1, first.callId)
        assertEquals(184, first.duration)
        assertEquals("done", first.transcriptStatus)
        assertTrue(first.hasRecording)
        // started_at is isoformat(): "…T09:20:13.482915+00:00" — parsed, not dropped.
        assertTrue(first.startedAt!!.endsWith("+00:00"))
        val t = Fmt.millis(first.startedAt)!!
        assertTrue(kotlin.math.abs(AppClock.now() - 40 * 60_000L - t) < 60_000)
        // The bare row calls_upload_recording creates: no wa_id, no name.
        val bare = rows.first { it.callId == CallsFixtures.C6 }
        assertNull(bare.waId); assertNull(bare.name)
    }

    @Test fun legacyAndNullHeavyRowsStillDecode() {
        // A row from before the transcript migration (keys missing), and one with
        // every nullable as null (started_at included — the handler allows it).
        val json = """[
          {"id":"a","call_id":"wacid.X","wa_id":"254700000001","name":null,"direction":"inbound","status":"missed","duration":null,"agent_name":null,"started_at":"2026-09-25T09:20:13.482915+00:00"},
          {"id":"b","call_id":"wacid.Y","wa_id":null,"name":null,"direction":"outbound","status":"ringing","duration":null,"agent_name":null,
           "started_at":null,"summary":null,"transcript_status":null,"has_recording":false}]"""
        val rows = NeemaJson.decodeFromString(ListSerializer(Call.serializer()), json)
        assertEquals(2, rows.size)
        assertFalse(rows[0].hasRecording)
        assertNull(rows[0].transcriptStatus)
        assertNull(rows[1].startedAt)
        assertNull(Fmt.millis(rows[1].startedAt))
        // A naive timestamp (no offset) is read as UTC.
        assertEquals(java.time.Instant.parse("2026-09-25T09:20:13.482Z").toEpochMilli(), Fmt.millis("2026-09-25T09:20:13.482915"))
    }

    @Test fun iceConfigCarriesBothUrlShapesAndTheTurnCredentials() = runBlocking {
        val (_, api) = rig()
        val cfg = api.iceConfig()
        assertEquals(true, cfg.record)
        assertEquals(
            listOf(
                IceSpec(listOf("turn:turn.bethanyhouse.co.ke:3478"), "neema", "s3cret"),
                IceSpec(listOf("stun:stun.l.google.com:19302"), "", ""),
                IceSpec(listOf("turn:openrelay.metered.ca:80", "turn:openrelay.metered.ca:443",
                    "turn:openrelay.metered.ca:443?transport=tcp"), "openrelayproject", "openrelayproject"),
            ),
            iceSpecs(cfg),
        )
    }

    @Test fun iceConfigToleratesAMissingRecordFlagAndOddEntries() {
        // TURN_URL unset → only the STUN + openrelay; a username with an empty
        // credential (TURN_CREDENTIAL unset) and an entry with null urls.
        val cfg = NeemaJson.decodeFromString(IceConfig.serializer(), """{"ice_servers":[
            {"urls":"turn:t.example:3478","username":"u","credential":""},{"urls":null},{"urls":[]}]}""")
        assertNull(cfg.record)   // CallManager records unless record == false
        assertEquals(listOf(IceSpec(listOf("turn:t.example:3478"), "u", "")), iceSpecs(cfg))
    }

    @Test fun offerWithNullsDecodes() {
        // calls_get_offer returns data.get("sdp") / data.get("from") — null when the webhook had none.
        val o = NeemaJson.decodeFromString(CallOffer.serializer(), """{"call_id":"$C1","sdp":null,"from":null}""")
        assertEquals("", o.sdp); assertEquals("", o.from)
        val real = NeemaJson.decodeFromString(CallOffer.serializer(), CallsFixtures.offer(C1))
        assertTrue(real.sdp.contains("a=setup:actpass") && real.sdp.contains("\r\n"))
    }

    @Test fun transcriptDecodesEveryVariant() = runBlocking {
        val (fake, _) = rig()
        val done = testContainer(paparazzi.context, fake).api.calls.transcript(C1)
        assertEquals("done", done.status)
        assertEquals("en", done.language)
        assertTrue(done.recordingUrl!!.startsWith("https://") && done.recordingUrl!!.endsWith(".m4a"))
        // A legacy row: transcript_status NULL → status null; the panel reads it as "".
        val legacy = NeemaJson.decodeFromString(CallTranscript.serializer(),
            """{"call_id":"$C1","status":null,"transcript":null,"summary":null,"language":null,"has_recording":false,"recording_url":null}""")
        assertEquals("", legacy.status)
        assertNull(legacy.recordingUrl)
        // MEDIA_PUBLIC_URL unset: recording_url is the bare saved file name.
        val bare = NeemaJson.decodeFromString(CallTranscript.serializer(),
            """{"call_id":"$C1","status":"recorded","transcript":null,"summary":null,"language":null,"has_recording":true,"recording_url":"call_0f3e.m4a"}""")
        assertEquals("call_0f3e.m4a", bare.recordingUrl)
    }

    // ── Errors ───────────────────────────────────────────────────────────────
    @Test fun connectErrorsMapToTheWebCopy() = runBlocking {
        val (fake, api) = rig()
        suspend fun fail(code: Int, detail: String): Throwable {
            fake.on("POST", "/admin/calls/connect", code = code, body = """{"detail":"$detail"}""")
            return runCatching { api.connect("254712345678", "sdp", null) }.exceptionOrNull()!!
        }
        // calls_connect: Meta error 138006 → 409 with the permission detail.
        val e409 = fail(409, "This customer hasn't granted call permission yet. Send the WhatsApp template first, or wait until they message/call us.")
        assertTrue(e409 is ApiException && e409.status == 409)
        assertEquals(CallManager.NO_CALL_PERMISSION, CallManager.outboundError(e409))
        assertTrue((e409 as ApiException).detail.startsWith("This customer hasn't granted call permission"))
        assertEquals("Couldn't place the call", CallManager.outboundError(fail(400, "A valid phone number is required.")))
        assertEquals("Couldn't place the call", CallManager.outboundError(fail(400, "sdp offer is required")))
        assertEquals("Couldn't place the call", CallManager.outboundError(fail(502, "call failed: WA call connect failed (500)")))
        assertEquals("Couldn't place the call", CallManager.outboundError(fail(502, "Meta did not return a call id")))
    }

    @Test fun answerErrorsMapPerHandler() = runBlocking {
        val (fake, api) = rig()
        fake.on("POST", CallsFixtures.route(C1, "answer"), code = 409, body = """{"detail":"call already answered"}""")
        val taken = runCatching { api.answer(C1, "sdp") }.exceptionOrNull()!!
        assertEquals(CallManager.TAKEN_ELSEWHERE, CallManager.answerError(taken))
        fake.on("POST", CallsFixtures.route(C1, "answer"), code = 502, body = """{"detail":"accept failed: boom"}""")
        assertEquals("Couldn't connect the call", CallManager.answerError(runCatching { api.answer(C1, "sdp") }.exceptionOrNull()!!))
        fake.on("GET", CallsFixtures.route(C1, "offer"), code = 404, body = """{"detail":"call offer expired or not found"}""")
        assertEquals(CallManager.CALL_GONE,CallManager.answerError(runCatching { api.offer(C1) }.exceptionOrNull()!!))
        fake.on("GET", CallsFixtures.route(C1, "offer"), code = 503, body = """{"detail":"calling unavailable"}""")
        assertEquals("Couldn't connect the call", CallManager.answerError(runCatching { api.offer(C1) }.exceptionOrNull()!!))
    }

    @Test fun recordingRefusalsSurfaceAsApiErrors() = runBlocking {
        val (fake, api) = rig()
        val rec = java.io.File.createTempFile("rec", ".m4a").apply { writeBytes(ByteArray(3000)); deleteOnExit() }
        for ((code, detail) in listOf(403 to "Call recording is disabled.", 413 to "Recording too large — max 60 MB.", 400 to "Empty recording.")) {
            fake.on("POST", CallsFixtures.route(C1, "recording"), code = code, body = """{"detail":"$detail"}""")
            val e = runCatching { api.uploadRecording(C1, UploadFile.of(rec, "$C1.m4a", "audio/mp4")) }.exceptionOrNull()
            assertTrue(e is ApiException && e.status == code && e.detail == detail)
        }
    }

    @Test fun transcriptNotFoundIsAnError() = runBlocking {
        val (fake, _) = rig()
        fake.on("GET", CallsFixtures.route(C1, "transcript"), code = 404, body = """{"detail":"Call not found"}""")
        val api = testContainer(paparazzi.context, fake).api
        val e = runCatching { api.calls.transcript(C1) }.exceptionOrNull()
        assertNotNull(e); assertTrue(e is ApiException && e.status == 404)
    }
}
