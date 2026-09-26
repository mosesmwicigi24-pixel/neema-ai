package ke.co.bethanyhouse.neema.feature.calls

import androidx.compose.ui.graphics.vector.ImageVector
import ke.co.bethanyhouse.neema.core.model.Call

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
        "no_answer" -> CallRowWords("No answer", CallTone.Warn, dir)
        "cancelled" -> CallRowWords("Cancelled", CallTone.Neutral, dir)
        "failed" -> CallRowWords("Failed", CallTone.Bad, dir)
        else -> CallRowWords(c.status.replace('_', ' ').replaceFirstChar { it.uppercase() }.ifEmpty { "Call" }, CallTone.Neutral, dir)
    }
}

/** "4:12" for a call that connected, "" otherwise. */
fun callDuration(s: Int?): String = if (s == null || s <= 0) "" else callLength(s)

/** The agent's first name ("Moses Mwicigi" → "Moses"). */
fun agentFirst(name: String?): String? = name?.trim()?.split(Regex("\\s+"))?.firstOrNull()?.takeIf { it.isNotEmpty() }
