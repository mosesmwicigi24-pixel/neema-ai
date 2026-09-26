package ke.co.bethanyhouse.neema.feature.conversations.customer

import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * How a CRM request failed, in the terms the panel acts on. The web's crmReq
 * throws one opaque `Error` for all of these and says "Failed to save"; on a
 * Nairobi phone network the difference matters — an offline tap can simply be
 * retried, a timeout may already have landed, a 404 means someone else merged
 * or removed the record, a 429 means back off.
 */
internal enum class Failure { Offline, Uncertain, SessionExpired, Forbidden, NotFound, Conflict, Invalid, RateLimited, Server, Unreadable, Other }

/**
 * Errors OkHttp raises before a single byte left the phone: no DNS, no route,
 * refused. Anything else at status 0 (a timeout, a reset mid-answer) may have
 * reached the server and been acted on.
 */
private val NEVER_SENT = listOf(
    "unable to resolve host", "failed to connect", "connection refused", "network is unreachable",
    "no address associated", "no route to host",
)

internal fun Throwable.failure(): Failure {
    if (this is SerializationException) return Failure.Unreadable
    val e = this as? ApiException ?: return Failure.Other
    return when (e.status) {
        0 -> {
            val b = e.body.lowercase()
            if ("timed out" in b || "timeout" in b) Failure.Uncertain
            else if (NEVER_SENT.any { it in b }) Failure.Offline
            else Failure.Uncertain
        }
        401 -> Failure.SessionExpired
        403 -> Failure.Forbidden
        404, 410 -> Failure.NotFound
        409 -> Failure.Conflict
        400, 422 -> Failure.Invalid
        429 -> Failure.RateLimited
        // A gateway that gave up waiting: the request may well be running.
        504 -> Failure.Uncertain
        in 500..599 -> Failure.Server
        else -> Failure.Other
    }
}

/** The request may have reached the server and been acted on: never call that a failure. */
internal val Throwable.mayHaveLanded: Boolean get() = failure() == Failure.Uncertain

/**
 * The server's `detail` when it is written for people: a JSON `{"detail": "…"}`
 * string (not pydantic's list, not a proxy's HTML page, not a stack trace).
 */
internal fun Throwable.humanDetail(): String? {
    val e = this as? ApiException ?: return null
    if (e.status >= 500 || e.status == 0) return null
    val d = runCatching { (NeemaJson.parseToJsonElement(e.body) as? JsonObject)?.get("detail") as? JsonPrimitive }
        .getOrNull()?.takeIf { it.isString }?.content?.trim() ?: return null
    if (d.isEmpty() || d.length > 160 || '<' in d || d.startsWith("[") || d.startsWith("{")) return null
    return d.replaceFirstChar { it.uppercase() }.trimEnd('.') + "."
}

/** Plain words for why it failed, to follow "Failed to save — ". */
internal fun Throwable.reason(): String = when (failure()) {
    Failure.Offline -> "you're offline. Check your connection and try again."
    Failure.Uncertain -> "the server took too long to answer."
    Failure.SessionExpired -> "your session expired. Sign in again, then retry."
    Failure.Forbidden -> humanDetail()?.takeUnless { it.equals("Admin only.", true) || it.equals("Not authenticated.", true) }
        ?.lowercaseFirst() ?: "you don't have permission to do that."
    Failure.NotFound -> "it no longer exists."
    Failure.Conflict -> humanDetail()?.lowercaseFirst() ?: "it changed meanwhile."
    Failure.Invalid -> humanDetail()?.lowercaseFirst() ?: "the server didn't accept that."
    Failure.RateLimited -> "too many requests. Wait a moment, then try again."
    Failure.Server -> "the server had a problem. Try again in a moment."
    Failure.Unreadable -> "the server sent an answer the app couldn't read."
    Failure.Other -> "something went wrong. Try again."
}

private fun String.lowercaseFirst(): String {
    // Keep acronyms, names and "I" ("WhatsApp …", "KES …") as they are.
    val word = substringBefore(' ')
    val plain = word.isNotEmpty() && word[0].isUpperCase() && word.drop(1).all { it.isLowerCase() } && word != "I"
    return if (plain) replaceFirstChar { it.lowercase() } else this
}
