package ke.co.bethanyhouse.neema.core.net

import ke.co.bethanyhouse.neema.core.auth.AuthException
import kotlinx.serialization.SerializationException

/**
 * What to tell a person when a request failed — one voice for the whole app.
 *
 * The server's own `detail` wins when it is written for people ("Order not
 * found", "Stock is too low for 3 × Kiondo"); FastAPI's stock phrases
 * ("Not Found", "Internal Server Error"), pydantic field lists and proxy
 * HTML pages never reach the screen — the status speaks instead.
 */
object ErrorText {
    const val OFFLINE = "Network problem — check your connection"
    const val TIMED_OUT = "The server is taking too long to answer. Check your connection and try again."
    const val SESSION = "Your session has expired. Sign in again to continue."
    const val FORBIDDEN = "You don't have permission to do that."
    const val GONE = "That's no longer there — someone may have deleted it."
    const val CONFLICT = "That changed in the meantime. Refresh to see the latest."
    const val TOO_LARGE = "That's too large to send."
    const val INVALID = "Some details weren't accepted. Please check them and try again."
    const val SERVER = "Something went wrong on the server. Please try again."
    const val DOWN = "Neema's server can't be reached right now. Please try again in a moment."
    const val UNREADABLE = "The server sent an answer the app couldn't read. Please try again."
    const val UNKNOWN = "Something went wrong"

    /** Detail strings FastAPI / Starlette / proxies use that say nothing to a person. */
    private val STOCK = setOf(
        "not found", "method not allowed", "internal server error", "bad gateway", "service unavailable",
        "gateway timeout", "bad request", "unprocessable entity", "too many requests", "forbidden",
        "unauthorized", "not authenticated", "conflict", "request entity too large", "payload too large",
    )

    /** A `detail` that reads as a sentence for people, or null. */
    fun humanDetail(e: ApiException): String? {
        val d = e.detail.trim()
        if (d.isEmpty() || d.length > 300) return null
        if (d.first() in "<{[") return null
        if (d.lowercase().trimEnd('.') in STOCK) return null
        // A pydantic 422 list names fields ("field required; value is not a valid email").
        if (e.status == 422 && Regex("\"detail\"\\s*:\\s*\\[").containsMatchIn(e.body)) return null
        return d
    }

    fun of(t: Throwable): String = when (t) {
        is ApiException -> ofApi(t)
        is AuthException -> t.message ?: UNKNOWN
        is SerializationException -> UNREADABLE
        is RefreshUnavailable -> if (t.timedOut) TIMED_OUT else if (t.status == 0) OFFLINE else DOWN
        else -> t.message?.ifBlank { null } ?: UNKNOWN
    }

    private fun ofApi(e: ApiException): String {
        if (e.malformed) return UNREADABLE
        val human = humanDetail(e)
        return when (e.status) {
            0 -> if (e.timedOut) TIMED_OUT else OFFLINE
            401 -> SESSION
            403 -> human ?: FORBIDDEN
            404 -> human ?: GONE
            409 -> human ?: CONFLICT
            413 -> TOO_LARGE
            422, 400 -> human ?: INVALID
            429 -> tooMany(e.retryAfterSeconds)
            // FastAPI uses these for real answers too ("WhatsApp sending is not
            // configured.", "Hub rejected the order: …"); a bare gateway page is an outage.
            502, 503, 504 -> human ?: DOWN
            in 500..599 -> human ?: SERVER
            else -> human ?: "Something went wrong (${e.status}). Please try again."
        }
    }

    private fun tooMany(after: Long?): String = when {
        after == null || after <= 1 -> "Too many requests. Please wait a moment and try again."
        after < 90 -> "Too many requests. Please wait $after seconds and try again."
        else -> "Too many requests. Please wait ${(after + 59) / 60} minutes and try again."
    }
}
