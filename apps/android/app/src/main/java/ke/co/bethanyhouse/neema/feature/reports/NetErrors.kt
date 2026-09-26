package ke.co.bethanyhouse.neema.feature.reports

import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.net.ApiException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ensureActive
import java.io.IOException

/**
 * What a failed request means to the person holding the phone, for the
 * Reports, Analytics, Catalog, Team, Profile and Settings screens.
 *
 * The web toasts `e.message`, which reads "POST /admin/agents → 500: Internal
 * Server Error" or a proxy's HTML page. Here each failure gets plain words:
 * the server's `detail` only when it was written for people, never markup, a
 * JSON dump or FastAPI's stock "Not Found" / "Internal Server Error".
 */

/** The HTTP status of a failed call; 0 = never got an answer; null = not an HTTP failure. */
internal fun Throwable.httpStatus(): Int? = (this as? ApiException)?.status

/**
 * A timeout or a connection that dropped after the request left: the server
 * may have done it. A request that never left (no network, the host
 * unreachable, the connection refused) did not.
 */
internal fun Throwable.mayHaveApplied(): Boolean =
    ((this is ApiException && status == 0) || (this is IOException && this !is ApiException)) && !neverSent()

/** The phone never reached the server: nothing can have happened there. */
internal fun Throwable.neverSent(): Boolean {
    if (this is java.net.ConnectException || this is java.net.UnknownHostException || this is java.net.NoRouteToHostException) return true
    val text = ((this as? ApiException)?.takeIf { it.status == 0 }?.body ?: return false).lowercase()
    return "failed to connect" in text || "unable to resolve host" in text || "connection refused" in text ||
        "no address associated" in text || "network is unreachable" in text
}

internal fun Throwable.isTimeout(): Boolean {
    val text = ((this as? ApiException)?.body ?: message).orEmpty().lowercase()
    return "timed out" in text || "timeout" in text
}

/** The server's `detail` when it is a sentence meant for a person, else null. */
internal fun ApiException.readableDetail(): String? {
    val d = detail.trim()
    if (d.isEmpty() || d.length > 200) return null
    if (d.startsWith("<") || d.startsWith("{") || d.startsWith("[")) return null
    // Only FastAPI's own `{"detail": …}` speaks for the server; a bare body is
    // a proxy's page or a stack's stock text.
    if (!body.trimStart().startsWith("{")) return null
    if (d.equals("Not Found", true) || d.equals("Internal Server Error", true) ||
        d.equals("Bad Gateway", true) || d.equals("Service Unavailable", true) ||
        d.equals("Gateway Timeout", true) || d.equals("Method Not Allowed", true)
    ) return null
    return d
}

internal const val OFFLINE_TEXT = "You're offline or the server can't be reached — check your connection and try again."
internal const val TIMEOUT_TEXT = "The server took too long to answer — check your connection and try again."
internal const val DROPPED_TEXT = "The connection dropped before the answer arrived — try again."
internal const val BUSY_TEXT = "Too many requests — wait a moment, then try again."
internal const val DOWN_TEXT = "The server is unavailable right now — try again in a moment."
internal const val EXPIRED_TEXT = "Your session expired — sign in again, then retry."
internal const val GARBLED_TEXT = "The server sent an answer the app couldn't read — try again."

/**
 * Plain words for [e]. [fallback] is what a failure with nothing better to
 * say reads (a 500, an unknown status); [notFound] what a 404 says when the
 * server gave no sentence of its own.
 */
internal fun friendlyError(
    e: Throwable,
    fallback: String = "Something went wrong — please try again.",
    notFound: String = "That no longer exists — someone else may have removed it.",
): String = if (e is ApiException && e.malformed) {
    GARBLED_TEXT // the core flags a 2xx it couldn't parse (captive portal, cut-off body)
} else when (e) {
    is ApiException -> when (e.status) {
        0 -> when {
            e.isTimeout() -> TIMEOUT_TEXT
            e.neverSent() -> OFFLINE_TEXT
            else -> DROPPED_TEXT
        }
        401 -> EXPIRED_TEXT
        403 -> e.readableDetail()?.takeUnless { it.equals("Not authenticated", true) || it.equals("Forbidden", true) }
            ?: "You don't have permission to do that."
        404 -> e.readableDetail()?.takeUnless { it.endsWith(" not found", true) } ?: notFound
        409 -> e.readableDetail() ?: "That changed on the server meanwhile — showing the latest."
        422 -> e.readableDetail() ?: "The server couldn't accept that — check the fields and try again."
        429 -> BUSY_TEXT
        502, 503, 504 -> DOWN_TEXT
        in 500..599 -> fallback
        else -> e.readableDetail() ?: fallback
    }
    is kotlinx.serialization.SerializationException, is IllegalArgumentException -> GARBLED_TEXT
    is IOException -> if (e.isTimeout()) TIMEOUT_TEXT else DROPPED_TEXT
    else -> fallback
}

/** Never let "the screen went away" read as a failure: cancellation always propagates. */
internal fun Throwable.rethrowIfCancelled() { if (this is CancellationException) throw this }

/**
 * Throws if the screen's scope was cancelled (signed out, left for good) while
 * the request was on the wire — so a failure that arrives afterwards is never
 * toasted for a screen that is gone.
 */
internal suspend fun stillHere() { kotlinx.coroutines.currentCoroutineContext()[kotlinx.coroutines.Job]?.ensureActive() }

/** [runCatching] for coroutines: a failure is caught, a cancellation is not. */
internal suspend fun <T> attempt(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    Result.failure(e)
}

/** [text] with every occurrence of [secret] masked — a typed password is never read back in a toast. */
internal fun String.masking(secret: String): String =
    if (secret.length < 3) this else replace(secret, "••••••")

/**
 * A 403 means the server's idea of this agent's access differs from the
 * app's — an admin changed their role or overrides since the last 180 s
 * agents poll. Re-read `/admin/me` and the team now so the nav (and every
 * `can()` gate) corrects itself instead of waiting up to three minutes.
 *
 * None of the Reports / Analytics / Catalog endpoints is permission-guarded
 * on the server today (they only need a signed-in agent), so this is a
 * safety net for a future guard or a proxy rule.
 *
 * TODO(core): switch to `dash.onForbidden()` once core adds it.
 */
internal fun DashboardViewModel.recheckAccessOn(e: Throwable?) {
    if (e?.httpStatus() == 403) {
        refetchMe()
        refetchAgents()
    }
}
