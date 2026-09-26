package ke.co.bethanyhouse.neema.feature.conversations

import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * What a failed request means for the thing it tried to do. A phone on a
 * Nairobi network drops connections mid-request all the time: a send that
 * timed out may well have reached the customer, and saying "failed" then
 * invites a second, duplicate send.
 */
internal enum class Fate {
    /** The server never acted on it (refused, or the request never left the phone). */
    NotSent,
    /** It may have happened: check the server before calling it either way. */
    Unknown,
    /** It happened — only the answer was unreadable. */
    Done,
}

internal fun fateOf(e: Throwable): Fate = when (e) {
    is ApiException -> when {
        e.status == 0 -> if (neverConnected(e)) Fate.NotSent else Fate.Unknown
        // 500: the work may be done and only the bookkeeping failed; a gateway
        // error may have been answered by a proxy after the API had the request.
        e.status == 500 || e.status in 502..504 -> Fate.Unknown
        else -> Fate.NotSent
    }
    // A 2xx whose body didn't decode: the server did it.
    is kotlinx.serialization.SerializationException -> Fate.Done
    is java.io.IOException -> Fate.Unknown
    else -> Fate.NotSent
}

/**
 * The request never reached the server: no DNS, no route, the connection
 * refused. The HTTP layer folds the cause into the message, so read both.
 */
internal fun neverConnected(e: Throwable): Boolean {
    var c: Throwable? = e
    while (c != null) {
        if (c is java.net.UnknownHostException || c is java.net.ConnectException || c is java.net.NoRouteToHostException) return true
        c = c.cause.takeIf { it !== c }
    }
    val m = ((e as? ApiException)?.body ?: e.message).orEmpty().lowercase()
    return listOf(
        "unable to resolve host", "no address associated", "failed to connect", "connection refused",
        "network is unreachable", "no route to host", "unknownhost",
    ).any { it in m }
}

internal fun timedOut(e: Throwable): Boolean =
    e is ApiException && e.status == 0 && ("timed out" in e.body.lowercase() || "timeout" in e.body.lowercase())

internal fun statusOf(e: Throwable): Int = (e as? ApiException)?.status ?: -1

/** 404 for the conversation itself — someone deleted it — not a route the server lacks ("Not Found"). */
internal fun conversationGone(e: Throwable): Boolean =
    e is ApiException && e.status == 404 && readableDetail(e)?.let { it != "Not Found" } == true

/**
 * The server's `detail` when it is written for people: a plain string from
 * `HTTPException(detail=…)`. Never a proxy's HTML page, a pydantic error
 * list, or a bare status phrase.
 */
internal fun readableDetail(e: Throwable): String? {
    val api = e as? ApiException ?: return null
    val d = runCatching { ((NeemaJson.parseToJsonElement(api.body) as? JsonObject)?.get("detail") as? JsonPrimitive)?.takeIf { it.isString }?.content }
        .getOrNull()?.trim() ?: return null
    if (d.isEmpty() || d.length > 300 || d.startsWith("<") || d == "Internal Server Error") return null
    return d
}

/**
 * The words for a failure the person can act on. The transport problems get
 * plain sentences of their own; anything else says [fallback] — the web's
 * copy for that action — unless [useDetail] and the server explained itself.
 */
internal fun whyFailed(e: Throwable, fallback: String, useDetail: Boolean = false): String {
    if (e is NotDelivered) return e.message.orEmpty().take(160).ifBlank { fallback }
    val api = e as? ApiException ?: return fallback
    return when {
        api.status == 0 && timedOut(api) -> "No answer from the server — the connection is too slow right now."
        api.status == 0 && neverConnected(api) -> "No connection — check your internet and try again."
        api.status == 0 -> "The connection dropped — try again."
        api.status == 401 -> "Your session expired — sign in again."
        api.status == 429 -> "Too many requests — wait a moment and try again."
        api.status == 500 -> "Something went wrong on the server — try again."
        api.status in 502..504 -> "Neema's server is unavailable right now — try again shortly."
        useDetail -> readableDetail(api) ?: fallback
        else -> fallback
    }
}

/** POST /reply answered 200 {ok:false, error}: the channel refused it — nothing went out. */
internal class NotDelivered(message: String) : IllegalStateException(message)

/** Why the inbox list couldn't load, for the line beside Retry. */
internal fun listErrorText(e: Throwable): String = whyFailed(e, "The server sent an answer the app couldn't read.", useDetail = true)
