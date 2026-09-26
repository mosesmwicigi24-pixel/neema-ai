package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import ke.co.bethanyhouse.neema.testing.FakeNeema
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException
import java.net.SocketTimeoutException

/** lib/api.ts req(): bearer auth, the 30 s ceiling, 401 handling and error mapping. */
@OptIn(ExperimentalCoroutinesApi::class)
class NeemaHttpTest {
    private class Tokens(var current: String?, var refreshTo: String?) : TokenProvider {
        var refreshes = 0
        val rejected = mutableListOf<String?>()
        override suspend fun validAccessToken() = current
        override suspend fun forceRefresh(): String? { refreshes++; return refreshTo?.also { current = it } }
        override fun onRejected(token: String?) { rejected += token }
    }

    private val fake = FakeNeema()
    private val tokens = Tokens("tok-1", null)
    private val http = NeemaHttp("https://neema.test", tokens, fake, Dispatchers.Unconfined)

    private fun <T> expectApi(block: suspend () -> T): ApiException = runBlocking {
        try { block(); fail("expected ApiException"); throw IllegalStateException() } catch (e: ApiException) { e }
    }

    @Test
    fun everyCallCarriesTheBearerTokenUnderApi() = runBlocking {
        fake.on("GET", "/admin/me", body = """{"ok":true}""")
        http.get<OkResponse>("/admin/me")
        val c = fake.calls.single()
        assertEquals("/admin/me", c.path)
        assertEquals("Bearer tok-1", c.headers["Authorization"])
        assertEquals("application/json", c.headers["Accept"])
    }

    @Test
    fun noTokenMeansNoAuthorizationHeader() = runBlocking {
        tokens.current = null
        fake.on("GET", "/health", body = "{}")
        http.raw("GET", "/health")
        assertNull(fake.calls.single().headers["Authorization"])
    }

    @Test
    fun bodilessPostsSendAnEmptyJsonBody() = runBlocking {
        fake.on("POST", "/admin/actions/x/veto", body = "{}")
        fake.on("DELETE", "/admin/roles/r", body = """{"ok":true}""")
        http.raw("POST", "/admin/actions/x/veto")
        http.delete<OkResponse>("/admin/roles/r")
        assertEquals("", fake.calls[0].body)
        assertNull(fake.calls[1].body)
    }

    @Test
    fun blankAndUnitBodiesDecode() = runBlocking {
        fake.on("PATCH", "/admin/catalog/1", body = "")
        http.patch<JsonObject, Unit>("/admin/catalog/1", JsonObject(emptyMap()))
        assertEquals(null, http.decode<OkResponse?>(""))
    }

    @Test
    fun a401IsRescuedByOneRefreshAndRetried() = runBlocking {
        tokens.refreshTo = "tok-2"
        fake.on("GET", "/admin/agents") { req, _ ->
            if (req.header("Authorization") == "Bearer tok-2") 200 to "[]" else 401 to """{"detail":"Token expired"}"""
        }
        assertEquals("[]", http.raw("GET", "/admin/agents"))
        assertEquals(listOf<String?>("tok-1"), tokens.rejected)
        assertEquals(1, tokens.refreshes)
        assertEquals(2, fake.calls.size)
    }

    @Test
    fun a401ThatCannotBeRefreshedSignalsSessionExpired() = runTest {
        val expired = async(UnconfinedTestDispatcher(testScheduler)) { http.sessionExpired.first() }
        fake.on("GET", "/admin/orders", code = 401, body = """{"detail":"Not authenticated"}""")
        try { http.raw("GET", "/admin/orders"); fail() } catch (e: ApiException) {
            assertEquals(401, e.status)
            assertEquals("Session expired", e.body)
        }
        expired.await()
        assertEquals("no retry without a fresh token", 1, fake.calls.size)
    }

    @Test
    fun aSecond401AfterRefreshAlsoSignalsSessionExpired() = runTest {
        tokens.refreshTo = "tok-2"
        val expired = async(UnconfinedTestDispatcher(testScheduler)) { http.sessionExpired.first() }
        fake.on("GET", "/admin/orders", code = 401, body = "{}")
        try { http.raw("GET", "/admin/orders"); fail() } catch (e: ApiException) { assertEquals(401, e.status) }
        expired.await()
        assertEquals(2, fake.calls.size)
    }

    @Test
    fun serverErrorsCarryTheDetail() {
        fake.on("POST", "/admin/agents", code = 422, body = """{"detail":"Missing required fields: email"}""")
        val e = expectApi { http.raw("POST", "/admin/agents") }
        assertEquals(422, e.status)
        assertEquals("Missing required fields: email", e.detail)
        assertEquals("POST", e.method)
        assertEquals("/admin/agents", e.path)
        assertTrue(e.message!!, e.message!!.startsWith("POST /admin/agents → 422"))
    }

    @Test
    fun structuredOrNonJsonDetailsFallBackSensibly() {
        fake.on("GET", "/a", code = 422, body = """{"detail":[{"loc":["body","email"],"msg":"field required"}]}""")
        fake.on("GET", "/b", code = 502, body = "<html>Bad Gateway</html>")
        assertTrue(expectApi { http.raw("GET", "/a") }.detail.contains("field required"))
        assertEquals("<html>Bad Gateway</html>", expectApi { http.raw("GET", "/b") }.detail)
    }

    @Test
    fun networkFailuresAreStatusZero() {
        fake.on("GET", "/down") { _, _ -> throw IOException("Connection reset") }
        fake.on("GET", "/slow") { _, _ -> throw SocketTimeoutException("read timed out") }
        val down = expectApi { http.raw("GET", "/down") }
        assertEquals(0, down.status)
        assertEquals("Connection reset", down.body)
        val slow = expectApi { http.raw("GET", "/slow") }
        assertEquals(0, slow.status)
        assertEquals("timed out after 30s", slow.body)
    }

    @Test
    fun a404IsAnErrorNotASessionProblem() = runBlocking {
        fake.on("GET", "/admin/orders/x", code = 404, body = """{"detail":"Order not found"}""")
        val e = expectApi { http.raw("GET", "/admin/orders/x") }
        assertEquals(404, e.status)
        assertEquals(0, tokens.refreshes)
        assertFalse(tokens.rejected.isNotEmpty())
    }

    @Test
    fun absoluteUrlsAreUsedAsIs() = runBlocking {
        fake.on("GET", "/media/x.jpg", body = "{}")
        http.raw("GET", "https://neema.test/api/media/x.jpg")
        assertEquals("/media/x.jpg", fake.calls.single().path)
    }

    /** Calls' carry-over: api.calls.uploadRecording(id, UploadFile.of(file, …)) survives a token refresh. */
    @Test
    fun aFileBackedRecordingIsResentWholeAfterA401() = runBlocking {
        tokens.refreshTo = "tok-2"
        val f = java.io.File.createTempFile("wacid", ".m4a").apply {
            deleteOnExit(); writeBytes(ByteArray(64 * 1024) { (it % 239).toByte() })
        }
        val sizes = mutableListOf<Int>()
        fake.on("POST", "/admin/calls/wacid.9/recording") { req, body ->
            sizes += body!!.length
            if (req.header("Authorization") == "Bearer tok-2") 200 to """{"ok":true,"will_transcribe":false}"""
            else 401 to """{"detail":"Token expired"}"""
        }
        val api = ke.co.bethanyhouse.neema.core.api.NeemaApi(http)
        val res = api.calls.uploadRecording("wacid.9", ke.co.bethanyhouse.neema.core.api.UploadFile.of(f, "wacid.9.m4a", "audio/mp4"))
        assertEquals(false, res.willTranscribe)
        assertEquals("sent twice (401, then the retry)", 2, sizes.size)
        assertEquals("the retry re-read the whole file", sizes[0], sizes[1])
        assertTrue(sizes[0] > 64 * 1024)
    }

    @Test
    fun aMissingRecordingFileIsANetworkStyleErrorNotACrash() {
        val gone = java.io.File("/nonexistent/neema/rec.m4a")
        fake.on("POST", "/admin/calls/x/recording", body = "{}")
        val api = ke.co.bethanyhouse.neema.core.api.NeemaApi(http)
        val e = expectApi { api.calls.uploadRecording("x", ke.co.bethanyhouse.neema.core.api.UploadFile.of(gone, mimeType = "audio/mp4")) }
        assertEquals(0, e.status)
    }
}
