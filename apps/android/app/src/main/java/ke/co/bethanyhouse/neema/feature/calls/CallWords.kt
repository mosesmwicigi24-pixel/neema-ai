package ke.co.bethanyhouse.neema.feature.calls

import androidx.compose.ui.graphics.vector.ImageVector
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.util.Fmt

/**
 * How a logged call reads wherever it is listed (the Calls view, the customer
 * panel, the thread pill): a direction icon and an outcome WORD in its tone —
 * never colour alone (CALLING_UX.md §5, §7).
 */
enum class CallTone { Live, Good, Bad, Warn, Neutral }

data class CallRowWords(val label: String, val tone: CallTone, val icon: ImageVector)

/** Outgoing / incoming / missed / call-back icon and the outcome word for [c]'s status. */
fun callRowWords(c: Call): CallRowWords {
    val out = c.direction == "outbound"
    val dir = if (out) CallIcons.DirOut else CallIcons.DirIn
    return when (c.status) {
        "ringing" -> CallRowWords(if (out) "Calling…" else "Ringing…", CallTone.Live, dir)
        "answered" -> CallRowWords("On a call", CallTone.Live, dir)
        "completed", "ended" -> CallRowWords(if (out) "Outgoing" else "Incoming", CallTone.Good, dir)
        "missed" -> CallRowWords("Missed", CallTone.Bad, CallIcons.DirMissed)
        "declined" -> CallRowWords("Declined", CallTone.Warn, dir)
        "callback" -> CallRowWords("Call back", CallTone.Warn, CallIcons.DirBack)
        "no_answer" -> CallRowWords("No answer", CallTone.Bad, dir)
        // The customer declined OUR call (Meta's REJECTED) — not a follow-up, but not a good outcome.
        "rejected" -> CallRowWords("Declined by customer", CallTone.Bad, dir)
        "cancelled" -> CallRowWords("Cancelled", CallTone.Neutral, dir)
        "failed" -> CallRowWords("Failed", CallTone.Bad, dir)
        else -> CallRowWords(c.status.replace('_', ' ').replaceFirstChar { it.uppercase() }.ifEmpty { "Call" }, CallTone.Neutral, dir)
    }
}

/** The two channels that call (CALLING_UX.md §1, §2.0). */
const val WHATSAPP = "whatsapp"
const val MESSENGER = "messenger"

/** A row / event's channel, WhatsApp when it says none (older rows and frames carry none). */
fun channelOf(v: String?): String = if (v?.trim()?.lowercase() == MESSENGER) MESSENGER else WHATSAPP

/** Where the call is, in words: "WhatsApp" / "Messenger". */
fun channelLabel(ch: String?): String = if (channelOf(ch) == MESSENGER) "Messenger" else "WhatsApp"

/** The customer's handle on the call's channel: the wa_id, or the PSID on Messenger (never shown). */
fun callHandle(c: Call): String =
    (if (channelOf(c.channel) == MESSENGER) c.externalId else c.waId ?: c.externalId)?.removePrefix("+").orEmpty()

/** "Messenger caller": a Messenger call with no name yet (a PSID is no number and is never shown). */
const val MESSENGER_CALLER = "Messenger caller"

/** "4:12" for a call that connected, "" otherwise. */
fun callDuration(s: Int?): String = if (s == null || s <= 0) "" else callLength(s)

/** The agent's first name ("Moses Mwicigi" → "Moses"). */
fun agentFirst(name: String?): String? = name?.trim()?.split(Regex("\\s+"))?.firstOrNull()?.takeIf { it.isNotEmpty() }

/** A voicemail arrived for this call: the "Voicemail" badge (rows, details) and the thread pill's " · voicemail". */
const val VOICEMAIL = "Voicemail"

/**
 * When something becomes possible, relative to [now]: "in 12 min", "in 5 h",
 * "on 3 Oct 2026" — "now" once it is past.
 */
fun untilText(iso: String, now: Long): String {
    val t = Fmt.millis(iso) ?: return "later"
    val mins = (t - now + 59_999L) / 60_000L
    return when {
        mins <= 0 -> "now"
        mins < 60 -> "in $mins min"
        mins < 24 * 60 -> "in ${(mins + 59) / 60} h"
        else -> "on ${Fmt.date(iso)}"
    }
}

/**
 * Where a customer's call permission stands, in words (CALLING_UX.md §2.1):
 * "Allowed permanently", "Allowed until {date}", "Request sent {time} —
 * waiting for {First}", "{First} declined calls", "Permission revoked after
 * unanswered calls" — null when there is nothing to say (never asked; a
 * call may still go through).
 */
fun permissionLine(p: CallPermission, first: String, now: Long): String? = when {
    p.status == "granted" && (p.permanent || p.metaStatus == "permanent") -> "Allowed permanently"
    p.status == "granted" && p.expiresAt != null -> "Allowed until ${Fmt.date(p.expiresAt)}"
    p.status == "granted" -> "Allowed calls"
    p.status == "requested" -> {
        val at = (p.requestedAt ?: p.at)?.let { Fmt.timeAgo(it, now) }?.takeIf { it != "—" }
        "Request sent${at?.let { " $it" } ?: ""} — waiting for $first"
    }
    p.status == "denied" && p.revoked -> "Permission revoked after unanswered calls"
    p.status == "denied" -> "$first declined calls"
    // Meta says they haven't allowed calls (and nobody asked yet): said, as the web does.
    p.metaStatus == "no_permission" -> "$first hasn't allowed calls yet"
    else -> null
}

/**
 * Everything the customer panel says about calling them: the [permissionLine],
 * when a new request can go ("You can ask again {relative}"), and — only when
 * Meta gave it — "Calls left today: N".
 */
fun permissionLines(p: CallPermission, first: String, now: Long): List<String> = listOfNotNull(
    permissionLine(p, first, now),
    p.requestAvailableAt?.takeIf { p.canRequest == false && p.status != "granted" }?.let { "You can ask again ${untilText(it, now)}" },
    p.callsLeftToday?.let { "Calls left today: $it" },
)

/**
 * A speaker-separated transcript ("Agent: …\nCustomer: …", as the server
 * stores WhatsApp's) as turns — null when it isn't one, i.e. when any line
 * lacks those labels (a Whisper transcript, or another labelling: plain text then).
 */
fun transcriptTurns(text: String): List<Pair<String, String>>? {
    val label = Regex("^(Agent|Customer)\\s*:\\s*(.*)$", RegexOption.IGNORE_CASE)
    val lines = text.lines().map { it.trim() }.filter { it.isNotEmpty() }
    if (lines.isEmpty()) return null
    return lines.map { l ->
        val m = label.matchEntire(l) ?: return null
        m.groupValues[1].lowercase().replaceFirstChar { it.uppercase() } to m.groupValues[2]
    }
}

/** The restriction banner's second line: Meta's reasons, and what it means for calls. */
fun restrictionText(r: CallingRestriction): String {
    val why = r.reasons.map { it.replace('_', ' ').lowercase().replaceFirstChar { c -> c.uppercase() } }.filter { it.isNotBlank() }
    return (if (why.isEmpty()) "" else why.joinToString(" · ") + ". ") +
        "Calls you place may fail until it lifts (up to 7 days)."
}

/**
 * Why a chat's app can't call right now — the "call on WhatsApp instead"
 * sheet's first line (CustomerSidebar.tsx cantCallWhy). Messenger can call
 * when the server's switch is on; Instagram has no business calling API.
 */
fun cantCallWhy(app: String): String =
    if (app == "Messenger") "Messenger calling isn't switched on for Neema yet." else "$app doesn't let businesses take calls."

/** The thread pill's words: the server's label (else the row's word), and " · voicemail" when one came with the call. */
fun threadCallLabel(body: String, call: Call?): String {
    val label = body.ifBlank { call?.let { callRowWords(it).label } ?: "Call" }
    return if (call?.hasVoicemail == true && !label.contains("voicemail", ignoreCase = true)) "$label · voicemail" else label
}
