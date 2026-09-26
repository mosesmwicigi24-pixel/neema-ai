package ke.co.bethanyhouse.neema.feature.orders

import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** What kind of failure a request met — how the Orders, Deals and Leads screens read it. */
enum class FailKind { Offline, Timeout, SessionExpired, Forbidden, NotFound, Conflict, Invalid, RateLimited, ServerError, Unavailable, Garbled }

/**
 * A failed request, read for people. [status] is the HTTP code (0 = no
 * answer), [detail] the server's own words when they are meant for a person
 * (FastAPI's `detail` string, never an HTML page or a stack trace).
 */
data class SalesFailure(
    val kind: FailKind,
    val status: Int,
    val detail: String?,
    /** A connection that was never made: refused, no route, no DNS — nothing reached the server. */
    val neverSent: Boolean = false,
) {
    /**
     * The request may have reached the server and done its work even though no
     * good answer came back: a timeout, a dropped connection mid-request, a
     * gateway (502/504) that forwarded it, or a 2xx whose body could not be
     * read. An action that failed this way must be reconciled by re-reading,
     * never reported as "failed" (it may have sent the message).
     */
    val mayHaveHappened: Boolean
        get() = kind == FailKind.Timeout || kind == FailKind.Garbled ||
            status == 502 || status == 504 || (kind == FailKind.Offline && !neverSent)

    /** The words for a toast or an inline error; [gone] is what a 404 means on this screen. */
    fun message(gone: String = "It no longer exists — someone may have deleted it"): String = when (kind) {
        FailKind.Offline -> "No connection — check your internet and try again"
        FailKind.Timeout -> "The server took too long to answer — try again"
        FailKind.SessionExpired -> "Your session expired — sign in again to continue"
        FailKind.Forbidden -> detail ?: "Your role doesn't allow that"
        FailKind.NotFound -> gone
        FailKind.Conflict -> detail ?: "That changed meanwhile — showing the latest"
        FailKind.Invalid -> detail ?: "The server didn't accept that"
        FailKind.RateLimited -> "Too many requests — wait a moment and try again"
        FailKind.ServerError -> detail ?: "The server hit an error — try again"
        FailKind.Unavailable -> "The server is unavailable right now — try again shortly"
        FailKind.Garbled -> "The server sent an answer the app couldn't read"
    }
}

/** Server `detail`s that are FastAPI's defaults, not words written for a person. */
private val GENERIC_DETAILS = setOf("not found", "internal server error", "bad gateway", "service unavailable", "method not allowed")

/** The server's `detail` when it is a short sentence for a person; null for pages, dumps and defaults. */
internal fun humanDetail(body: String): String? {
    val d = runCatching {
        when (val el = (NeemaJson.parseToJsonElement(body) as? JsonObject)?.get("detail")) {
            is JsonPrimitive -> el.content.takeIf { el.isString }
            is JsonArray -> el.mapNotNull { e -> ((e as? JsonObject)?.get("msg") as? JsonPrimitive)?.content }
                .joinToString("; ").ifEmpty { null }
            else -> null
        }
    }.getOrNull()?.trim() ?: return null
    if (d.isEmpty() || d.length > 200 || d.contains('<') || d.lowercase() in GENERIC_DETAILS) return null
    return d
}

private val NEVER_SENT = listOf("failed to connect", "unable to resolve host", "connection refused", "network is unreachable", "no address associated")

/** Read any throwable from an API call as a [SalesFailure]. Cancellation is not a failure: it is rethrown. */
fun salesFailureOf(e: Throwable): SalesFailure {
    if (e is CancellationException) throw e
    val api = e as? ApiException ?: return SalesFailure(FailKind.Garbled, 200, null)
    // The core flags an unreadable body and a timeout explicitly — trust them first.
    if (api.malformed) return SalesFailure(FailKind.Garbled, api.status, null)
    if (api.timedOut) return SalesFailure(FailKind.Timeout, 0, null)
    val detail = humanDetail(api.body)
    return when (val s = api.status) {
        0 -> if (api.body.contains("timed out", ignoreCase = true)) SalesFailure(FailKind.Timeout, 0, null)
        else SalesFailure(FailKind.Offline, 0, null, neverSent = NEVER_SENT.any { api.body.contains(it, ignoreCase = true) })
        401 -> SalesFailure(FailKind.SessionExpired, s, null)
        403 -> SalesFailure(FailKind.Forbidden, s, detail)
        404, 410 -> SalesFailure(FailKind.NotFound, s, detail)
        409 -> SalesFailure(FailKind.Conflict, s, detail)
        400, 422 -> SalesFailure(FailKind.Invalid, s, detail)
        429 -> SalesFailure(FailKind.RateLimited, s, detail)
        502, 503, 504 -> SalesFailure(FailKind.Unavailable, s, null)
        else -> if (s >= 500) SalesFailure(FailKind.ServerError, s, detail) else SalesFailure(FailKind.Invalid, s, detail)
    }
}
