package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.ErrorText
import ke.co.bethanyhouse.neema.core.net.RefreshUnavailable
import kotlinx.serialization.SerializationException
import org.junit.Assert.assertEquals
import org.junit.Test

/** dash.errorText: one voice for every failure, with words for people. */
class ErrorTextTest {
    private fun of(status: Int, body: String = "", retryAfter: Long? = null) =
        ErrorText.of(ApiException(status, "POST", "/admin/x", body, retryAfterSeconds = retryAfter))

    @Test fun networkAndTimeout() {
        assertEquals(ErrorText.OFFLINE, of(0, "Unable to resolve host"))
        assertEquals(ErrorText.OFFLINE, of(0, "Connection reset"))
        assertEquals(ErrorText.TIMED_OUT, of(0, "timed out after 30s"))
        assertEquals(ErrorText.TIMED_OUT, of(0, "timed out after 10 min"))
    }

    @Test fun theServersOwnWordsWinWhenMeantForPeople() {
        assertEquals("Order not found", of(404, """{"detail":"Order not found"}"""))
        assertEquals("Only admins can do this", of(403, """{"detail":"Only admins can do this"}"""))
        assertEquals("Conversation is already assigned", of(409, """{"detail":"Conversation is already assigned"}"""))
        assertEquals("WhatsApp sending is not configured.", of(503, """{"detail":"WhatsApp sending is not configured."}"""))
        assertEquals("Could not compose the message", of(500, """{"detail":"Could not compose the message"}"""))
        assertEquals("Email already registered", of(422, """{"detail":"Email already registered"}"""))
    }

    @Test fun stockPhrasesPagesAndFieldListsGetPlainWords() {
        assertEquals(ErrorText.SESSION, of(401, "Session expired"))
        assertEquals(ErrorText.FORBIDDEN, of(403, """{"detail":"Not authenticated"}"""))
        assertEquals(ErrorText.GONE, of(404, """{"detail":"Not Found"}"""))
        assertEquals(ErrorText.CONFLICT, of(409, ""))
        assertEquals(ErrorText.TOO_LARGE, of(413, "<html><head><title>413 Request Entity Too Large</title></head></html>"))
        assertEquals(ErrorText.INVALID, of(422, """{"detail":[{"loc":["body","email"],"msg":"field required","type":"missing"}]}"""))
        assertEquals(ErrorText.SERVER, of(500, """{"detail":"Internal Server Error"}"""))
        assertEquals(ErrorText.SERVER, of(500, "Internal Server Error"))
        assertEquals(ErrorText.DOWN, of(502, "<html>Bad Gateway</html>"))
        assertEquals(ErrorText.DOWN, of(503, ""))
        assertEquals(ErrorText.DOWN, of(504, "<!DOCTYPE html><html><body>Gateway Time-out</body></html>"))
        assertEquals("Something went wrong (418). Please try again.", of(418, ""))
    }

    @Test fun backOffWordsFollowRetryAfter() {
        assertEquals("Too many requests. Please wait a moment and try again.", of(429, ""))
        assertEquals("Too many requests. Please wait 30 seconds and try again.", of(429, "", 30))
        assertEquals("Too many requests. Please wait 2 minutes and try again.", of(429, "", 120))
    }

    @Test fun otherThrowables() {
        assertEquals(ErrorText.UNREADABLE, ErrorText.of(ApiException(200, "", "(response)", "<html>", malformed = true)))
        assertEquals(ErrorText.UNREADABLE, ErrorText.of(SerializationException("Unexpected JSON token")))
        assertEquals("Invalid email or password. Please try again.", ErrorText.of(AuthException("Invalid email or password. Please try again.")))
        assertEquals(ErrorText.OFFLINE, ErrorText.of(RefreshUnavailable(0, false, "reset")))
        assertEquals(ErrorText.TIMED_OUT, ErrorText.of(RefreshUnavailable(0, true, "timed out")))
        assertEquals("boom", ErrorText.of(IllegalStateException("boom")))
        assertEquals(ErrorText.UNKNOWN, ErrorText.of(IllegalStateException()))
    }
}
