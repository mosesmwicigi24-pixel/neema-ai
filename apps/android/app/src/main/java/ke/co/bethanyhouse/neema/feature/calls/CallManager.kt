package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallChannels
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.model.PermissionRequestResponse
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import java.io.File

/**
 * Where the call on this phone is (docs/CALLING_UX.md §3). Exactly one at a
 * time; the words on screen are always the phase's own ([statusText]).
 * "Reconnecting" is [CallUiState.reconnecting] on a live call (the timer keeps
 * the call's true length through it); "ending" never shows — hang-up ends the
 * call on this phone at once and the terminate follows in the background.
 */
enum class CallPhase {
    Idle,
    /** Ringing this phone (inbound). */
    Ringing,
    /** Outbound: building the offer, asking Meta to place the call ("Calling…"). */
    Placing,
    /** Outbound: Meta is ringing the customer ("Ringing…"). */
    RingingOut,
    /** Answered, the media not flowing yet ("Connecting…"). */
    Connecting,
    /** Media flowing; the timer runs from here. */
    InCall,
    /** The wrap-up card: the [CallUiState.outcome] and what to do next. */
    Ended,
}

/** How a call ended, as the wrap-up card says it (the §3 table). */
sealed interface CallOutcome {
    /**
     * How long the wrap-up stays by itself. Null: until the agent acts or
     * dismisses it — the team still owes the customer something.
     */
    val autoCloseMs: Long? get() = null

    data object Completed : CallOutcome { override val autoCloseMs get() = 8_000L }
    /**
     * Another agent took it ([agent], their name), or this agent on another
     * device ([mine]: "Answered on your other device").
     */
    data class AnsweredElsewhere(val agent: String?, val mine: Boolean = false) : CallOutcome { override val autoCloseMs get() = 4_000L }
    /** Declined for the whole team; [agent] null when it was this agent. */
    data class Declined(val agent: String? = null) : CallOutcome { override val autoCloseMs get() = 5_000L }
    /** The caller gave up while it rang ([note]: why, when the server said more — a line under "Missed call"). */
    data class Missed(val note: String? = null) : CallOutcome
    /** Saved to call back ([agent]: the colleague who did, null when it was this agent). */
    data class Callback(val saved: CallbackSave, val agent: String? = null) : CallOutcome {
        override val autoCloseMs get() = if (saved == CallbackSave.NotSaved) null else 4_000L
    }
    /** Our call rang out unanswered. */
    data object NoAnswer : CallOutcome
    /** The customer declined OUR call (Meta's REJECTED): "{First} declined the call". */
    data object Rejected : CallOutcome
    /** The agent hung up our call before the customer answered. */
    data object Cancelled : CallOutcome { override val autoCloseMs get() = 2_000L }
    /** The media dropped and did not come back. */
    data object ConnectionLost : CallOutcome
    /**
     * The server's reason, and its `action` (CALLING_UX.md §2.1): retry (or
     * null — an older server) offers Try again; wait / admin / none never do.
     * [until]: when a `wait` may end, if the server said.
     */
    data class Failed(val reason: String, val action: String? = null, val until: String? = null) : CallOutcome
    /** The customer hasn't allowed business calls: the agent may send WhatsApp's call request. */
    data object PermissionNeeded : CallOutcome
    /** The call request found they had already allowed calls permanently: "Call now". */
    data object AlreadyAllowed : CallOutcome
    /** Nothing more is owed here: the "{First} allowed calls" banner follows when they tap Allow. */
    data object PermissionRequested : CallOutcome { override val autoCloseMs get() = 6_000L }
    data object MicBlocked : CallOutcome
}

enum class CallbackSave { Saved, Retrying, NotSaved }

/** What the wrap-up card offers (in this order; the first is the primary one when [WrapAction.primary]). */
enum class WrapAction(val label: String) {
    OpenChat("Open chat"), CallAgain("Call again"), CallBack("Call back"), TryAgain("Try again"),
    Message("Message"), SendCallRequest("Send call request"), OpenSettings("Open settings"),
    CallNow("Call now"), CallingSettings("Open WhatsApp calling settings"),
    Done("Done"), Cancel("Cancel"),
}

/**
 * Why the call request didn't go (a refusal of POST /calls/request-permission
 * with the server's `code` / `action`): `template_required` (outside the 24 h
 * window with no approved template — [adminCanFix] offers Settings →
 * WhatsApp calling), `138009` (the 1-a-day / 2-a-week limit).
 */
data class CallRefusal(val code: String?, val action: String?, val detail: String, val adminCanFix: Boolean = false)

/** Meta flagged or restricted calling on the number (`calling_restricted`): the Calls view's banner. */
data class CallingRestriction(val reasons: List<String>, val at: String?)

/** A second caller while this phone is on a call: a banner, never a take-over. [from]: wa_id, or the PSID on Messenger. */
data class WaitingCall(val callId: String, val from: String?, val name: String?, val channel: String = WHATSAPP) {
    val who: String get() = name?.takeIf { it.isNotBlank() }
        ?: if (channel == MESSENGER) MESSENGER_CALLER else from?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Someone"
}

/**
 * A customer this phone asked allowed calls: "{First} allowed calls — Call now".
 * [waId]: their handle on [channel] (the PSID on Messenger).
 */
data class PermissionGrant(val waId: String, val name: String?, val channel: String = WHATSAPP)

data class CallUiState(
    val phase: CallPhase = CallPhase.Idle,
    val callId: String? = null,
    /** Customer wa_id (digits, no +) — on Messenger their PSID, which is never shown. */
    val from: String? = null,
    /** "whatsapp" | "messenger": where the call is (the card's look and words follow it). */
    val channel: String = WHATSAPP,
    val name: String? = null,
    val muted: Boolean = false,
    val seconds: Int = 0,
    /** Said inline on a live card ("No connection — can't answer yet"); the wrap-up says [outcome]. */
    val error: String? = null,
    /** True while we placed the call (ringing THEM). */
    val outbound: Boolean = false,
    /** The network blipped mid-call: ICE is trying to recover (see [CallManager.ICE_GRACE_MS]). */
    val reconnecting: Boolean = false,
    /** A request the card is waiting on (saving a callback, sending a call request): its buttons are disabled. */
    val busy: Boolean = false,
    /** Set in [CallPhase.Ended]. */
    val outcome: CallOutcome? = null,
    /** The customer's WhatsApp conversation (from the ring or a `call_update`), for "Open chat". */
    val conversationId: String? = null,
    val personId: String? = null,
    /** Where the call's audio plays, and what it could play through. */
    val route: AudioRoute = AudioRoute.Earpiece,
    val routes: List<AudioRoute> = listOf(AudioRoute.Earpiece, AudioRoute.Speaker),
    /** A recording is really running (the only time "● Recording" shows). */
    val recording: Boolean = false,
    /** After the call: "Recording saved — …", or null when nothing was recorded. */
    val recordingNote: String? = null,
    /** The call shrank to the bar at the top of the app (§6). */
    val minimised: Boolean = false,
    val waiting: WaitingCall? = null,
    /**
     * Whether the customer allowed calls, as the server read it before this
     * call was placed (and as `call_permission` frames update it): the
     * wrap-up says it honestly, the card warns about unanswered calls.
     */
    val permission: CallPermission? = null,
    /** A refused call request (see [CallRefusal]). */
    val refusal: CallRefusal? = null,
    /** WhatsApp records and transcribes this call itself (ice-config `meta_transcription`). */
    val metaTranscription: Boolean = false,
) {
    val speaker: Boolean get() = route.kind == AudioRouteKind.Speaker
    /** A Messenger call (CALLING_UX.md §2.0): Messenger's look, never the PSID on screen. */
    val messenger: Boolean get() = channel == MESSENGER
    /** "WhatsApp" / "Messenger". */
    val app: String get() = channelLabel(channel)
    /** Their number to show under the name (never a PSID). */
    val number: String? get() = from?.takeIf { it.isNotEmpty() && !messenger }
    /** Ringing, placing, connecting or on a call — anything but idle and the wrap-up. */
    val live: Boolean get() = phase != CallPhase.Idle && phase != CallPhase.Ended
    /** Name, else +number ("Messenger caller" on Messenger), else "Unknown caller". */
    val who: String get() = name?.takeIf { it.isNotBlank() }
        ?: if (messenger) MESSENGER_CALLER else number?.let { "+$it" } ?: "Unknown caller"
    /**
     * The key "Open chat" / "Message" opens: the wa_id (the inbox matches it),
     * else the conversation. On Messenger the conversation first, else the PSID.
     */
    val chatKey: String? get() = if (messenger) conversationId?.takeIf { it.isNotEmpty() } ?: from?.takeIf { it.isNotEmpty() }
        else from?.takeIf { it.isNotEmpty() } ?: conversationId?.takeIf { it.isNotEmpty() }
    /** A headset or Bluetooth is there: the audio button opens a list instead of toggling the speaker. */
    val routeChoice: Boolean get() = routes.any { it.isHeadset }
}

/** mm:ss for the live timer (tabular numerals on screen). */
fun mmss(s: Int): String = "%02d:%02d".format(s / 60, s % 60)

/** "4:12" — a finished call's length. */
fun callLength(s: Int): String = "${s / 60}:${(s % 60).toString().padStart(2, '0')}"

/**
 * The name to address a customer by: the first word, skipping a title
 * ("Fr. Peter Kamau" → "Peter"); null when there is no name.
 */
fun firstNameOf(name: String?): String? {
    val words = name?.trim()?.split(Regex("\\s+"))?.filter { it.isNotEmpty() }.orEmpty()
    if (words.isEmpty() || name.orEmpty().trim().startsWith("+")) return null
    fun title(w: String) = w.endsWith(".") || w.lowercase() in TITLES
    return words.firstOrNull { !title(it) } ?: words.first()
}

/** Words that come before a name ("Deacon James", "Rev Mary"): never what the customer is called by. */
private val TITLES = setOf(
    "fr", "father", "rev", "revd", "reverend", "sr", "sister", "br", "bro", "brother", "dr", "mr", "mrs", "ms", "prof",
    "deacon", "pastor", "bishop", "archbishop", "canon", "most", "the", "rt", "right", "very", "askofu", "mkuu",
)

/** The status line under the name — the §3 words for every phase and outcome. */
fun CallUiState.statusText(): String = when (phase) {
    CallPhase.Idle -> ""
    CallPhase.Ringing -> "Incoming…"
    CallPhase.Placing -> "Calling…"
    CallPhase.RingingOut -> "Ringing…"
    CallPhase.Connecting -> if (reconnecting) "Reconnecting…" else "Connecting…"
    CallPhase.InCall -> if (reconnecting) "Reconnecting…" else mmss(seconds)
    CallPhase.Ended -> outcome?.let { outcomeText(it) } ?: "Call ended"
}

/** The wrap-up's words for [o] (a table row of CALLING_UX.md §3). */
fun CallUiState.outcomeText(o: CallOutcome): String {
    // Addressed by first name (titles skipped); no name: their number, as the web's firstName() (never a PSID).
    val first = firstNameOf(name) ?: number?.let { "+$it" }
    return when (o) {
        CallOutcome.Completed -> if (seconds > 0) "Call ended · ${callLength(seconds)}" else "Call ended"
        is CallOutcome.AnsweredElsewhere ->
            if (o.mine) "Answered on your other device" else "Answered by ${agentFirst(o.agent) ?: "a colleague"}"
        is CallOutcome.Declined -> agentFirst(o.agent)?.let { "Declined by $it" } ?: "Call declined"
        is CallOutcome.Missed -> "Missed call"
        is CallOutcome.Callback -> when (o.saved) {
            CallbackSave.Saved -> agentFirst(o.agent)?.let { "$it saved it to call back — find it under Calls" } ?: CallManager.CALLBACK_SAVED
            CallbackSave.Retrying -> CallManager.CALLBACK_RETRYING
            CallbackSave.NotSaved -> CallManager.CALLBACK_FAILED
        }
        CallOutcome.NoAnswer -> "No answer"
        CallOutcome.Rejected -> "${first ?: "The customer"} declined the call"
        CallOutcome.AlreadyAllowed -> "${first ?: "This customer"} already allows calls — call now"
        CallOutcome.Cancelled -> "Call cancelled"
        CallOutcome.ConnectionLost ->
            if (seconds > 0) "Call dropped · ${callLength(seconds)} — the connection was lost" else "Call dropped — the connection was lost"
        is CallOutcome.Failed -> o.reason
        CallOutcome.PermissionNeeded -> "${first ?: "This customer"} hasn't allowed $app calls yet"
        CallOutcome.PermissionRequested -> "Call request sent — you'll be told when ${first ?: "they"} tap${if (first == null) "" else "s"} Allow"
        CallOutcome.MicBlocked -> CallManager.MIC_BLOCKED_WRAP
    }
}

/**
 * The wrap-up's second line, under the outcome: why a call was missed when
 * the server said more, and what "Send call request" does (CallStage.tsx).
 * Null when the outcome says it all — or when [CallUiState.error] says
 * something more pressing in its place.
 */
fun CallUiState.outcomeNote(): String? {
    if (phase != CallPhase.Ended || error != null) return null
    return when (val o = outcome) {
        is CallOutcome.Missed -> o.note
        CallOutcome.PermissionNeeded -> {
            // Where their permission stands (declined, revoked, asked already), then what the button does —
            // or why it can't be pressed yet.
            val state = permission?.takeIf { it.status == "denied" || it.status == "requested" }
                ?.let { permissionLine(it, firstNameOf(name) ?: "them", AppClock.now()) }
            listOfNotNull(
                state, sendRequestBlocked() ?: if (messenger) CallManager.PERMISSION_EXPLAINED_MESSENGER else CallManager.PERMISSION_EXPLAINED,
            ).joinToString("\n")
        }
        is CallOutcome.Failed -> when (o.action) {
            "admin" -> CallManager.ADMIN_MUST_ACT
            "wait" -> o.until?.let { "You can try again ${untilText(it, AppClock.now())}" } ?: CallManager.WAIT_A_MOMENT
            "none" -> CallManager.MESSAGE_INSTEAD
            else -> null
        }
        else -> null
    }
}

/**
 * "You can ask again in 5 h": Send call request can't be pressed yet — Meta's
 * limit (1 a day, 2 a week) is used up. Null when a request may be sent.
 */
fun CallUiState.sendRequestBlocked(): String? {
    val p = permission
    val limited = refusal?.code == "138009" || refusal?.code == "request_limit" || (p != null && p.canRequest == false && p.status != "granted" && p.status != "requested")
    if (!limited) return null
    return p?.requestAvailableAt?.let { "You can ask again ${untilText(it, AppClock.now())}" } ?: "You can ask again later"
}

/**
 * The line shown on the card before the call goes through, when this customer
 * left our last calls unanswered — WhatsApp removes the permission after 4 in
 * a row. A caution, never a block.
 */
fun CallUiState.callCaution(): String? {
    if (!outbound || (phase != CallPhase.Placing && phase != CallPhase.RingingOut)) return null
    // WhatsApp's rule: Messenger has no unanswered-call revoke to warn about.
    if (channel != WHATSAPP) return null
    val n = permission?.unansweredStreak ?: 0
    if (n < 2) return null
    return "${firstNameOf(name) ?: "This customer"} missed your last $n calls — WhatsApp removes call permission after 4 in a row. Consider a message first."
}

/**
 * What the wrap-up card offers for its outcome, the primary action first.
 * Chat actions need someone to write to; call actions a number to call.
 */
fun CallUiState.wrapActions(): List<WrapAction> {
    val o = outcome ?: return listOf(WrapAction.Done)
    val chat = chatKey != null
    val dial = !from.isNullOrEmpty()
    fun list(vararg a: WrapAction?) = a.filterNotNull()
    return when (o) {
        CallOutcome.Completed -> list(WrapAction.OpenChat.takeIf { chat }, WrapAction.CallAgain.takeIf { dial }, WrapAction.Done)
        is CallOutcome.AnsweredElsewhere, is CallOutcome.Callback, CallOutcome.Cancelled -> list(WrapAction.Done)
        is CallOutcome.Declined -> list(WrapAction.Message.takeIf { chat }, WrapAction.Done)
        is CallOutcome.Missed -> list(WrapAction.CallBack.takeIf { dial }, WrapAction.Message.takeIf { chat }, WrapAction.Done)
        CallOutcome.NoAnswer -> list(WrapAction.CallAgain.takeIf { dial }, WrapAction.Message.takeIf { chat }, WrapAction.Done)
        CallOutcome.Rejected -> list(WrapAction.Message.takeIf { chat }, WrapAction.Done)
        CallOutcome.AlreadyAllowed -> list(WrapAction.CallNow.takeIf { dial }, WrapAction.Message.takeIf { chat }, WrapAction.Done)
        CallOutcome.ConnectionLost -> list(WrapAction.CallAgain.takeIf { dial }, WrapAction.OpenChat.takeIf { chat }, WrapAction.Done)
        // Only a retryable failure offers another go (wait / admin / none: trying again won't help).
        is CallOutcome.Failed -> list(
            (if (outbound) WrapAction.TryAgain else WrapAction.CallBack).takeIf { dial && (o.action == null || o.action == "retry") },
            WrapAction.Message.takeIf { chat }, WrapAction.Done,
        )
        // No template outside the 24 h window: asking again can't work — an admin can fix it in Settings.
        CallOutcome.PermissionNeeded -> if (refusal?.code == "template_required") list(
            WrapAction.CallingSettings.takeIf { refusal?.adminCanFix == true }, WrapAction.Message.takeIf { chat }, WrapAction.Cancel,
        ) else list(WrapAction.SendCallRequest.takeIf { dial }, WrapAction.Message.takeIf { chat }, WrapAction.Cancel)
        CallOutcome.PermissionRequested -> list(WrapAction.Message.takeIf { chat }, WrapAction.Done)
        CallOutcome.MicBlocked -> list(WrapAction.OpenSettings, WrapAction.Done)
    }
}

/**
 * The softphone (WhatsApp and Messenger — CALLING_UX.md §2.0: a Messenger
 * call's SDP runs the other way, see [answer] / [placeMessenger] /
 * `media_update`): incoming-call ringing, answer / decline / callback,
 * outbound calls, mute, audio routes, the wrap-up after a call, and call
 * recording — the port of lib/callContext.tsx, grown into docs/CALLING_UX.md.
 * Process-wide (lives in AppContainer) so a call survives navigating between
 * screens.
 *
 * This class is the rules and nothing else: the device side (WebRTC, audio
 * routing, ringtone, notification, the mic permission) arrives through the
 * interfaces in CallPorts.kt, so every rule here runs on the JVM in tests.
 *
 * PUBLIC CONTRACT — other features call only [state], [permissionGranted],
 * [initiateCall], [requestPermission], [hangup], [openChat] and (MainActivity)
 * [handleIntent]; the call card and bar call the rest.
 *
 * Threading: every state change runs on [main]; peer events hop there first.
 *
 * Microphone: the browser asks for the mic inside getUserMedia, in the middle
 * of answering or placing a call. Here the same moment raises [micRequest];
 * [CallStage] (always composed while signed in) shows the system prompt and
 * reports back through [onMicResult]. Refused (or unanswered for a minute),
 * the call ends with "Microphone blocked".
 *
 * Several agents, one call (CALLING_UX.md §4): ringing stops here the moment
 * `call_answered` (a colleague — "Answered by Ann"), `call_ended` (its
 * outcome), a poll that finds the row not ringing, or our own 409 / 410
 * arrives. After the socket reconnects or the app returns to the front, a
 * phone that shows a call re-reads its row ([resync]) and corrects itself.
 *
 * The wrap-up ([CallPhase.Ended]) stays until the agent acts when the team
 * still owes the customer something (missed, no answer, dropped, failed,
 * permission); neutral ones close by themselves ([CallOutcome.autoCloseMs]).
 * A new ring replaces it at once. A second caller during a live call is a
 * [CallUiState.waiting] banner — never a take-over.
 *
 * Deliberate differences from the web (all web bugs, none visible otherwise):
 *  - a `call_ended` frame ends the call properly (the web showed "ended" and
 *    never returned to idle, leaving the card stuck);
 *  - an outbound call hung up while Meta was still placing it is terminated
 *    (the web left the customer's phone ringing with nobody on the line);
 *  - hang-up / callback taps on a call that already ended are ignored (a
 *    double tap re-terminated and restarted the "Call ended" timer);
 *  - an answer refused with 409 ("call already answered" — a colleague picked
 *    up first) says so and does NOT terminate: the web's hangup() there cut
 *    off the colleague's live call;
 *  - the poll keeps running in the background (the web skips hidden tabs)
 *    so a call still rings the phone through the notification;
 *  - the poll only rings for INBOUND rows: a colleague's outbound call is a
 *    "ringing" row too (calls_connect), and the web rang every other agent's
 *    softphone for it (answering then failed — there is no offer to fetch);
 *  - missed frames are caught up at once instead of on the next 12s tick:
 *    the call log is polled as soon as the socket (re)connects — which is
 *    also how a process restarted by LiveService finds a call that is
 *    ringing right now — and when the app comes back to the foreground;
 *  - a call that rang in while another was live (the web ignores it, as
 *    here — beyond the banner) is looked for again the moment this one is
 *    over, not up to 12s later, so the waiting customer rings through
 *    straight away;
 *  - a `call_ended` for a call this phone never showed starts its cooldown,
 *    so an `incoming_call` delivered late (out of order) or a lagging
 *    "ringing" row can't ring a call that is already over;
 *  - the poll cadence changes as soon as ringing starts (see [start]), so
 *    a call answered on a colleague's phone stops this one within 2.5s;
 *  - an `outbound_answer` that beats connect's reply (slow, or timed out and
 *    found by [findPlacedCall]) is kept and applied once the id is known —
 *    the web dropped it, leaving a customer who picked up in silence;
 *  - ringing stops after [RING_TIMEOUT_MS] even if every end signal was lost
 *    (the server treats a call still ringing after 2 minutes as missed);
 *  - a refused microphone ends the call on this phone only: nothing was
 *    answered, so a colleague can still pick it up (declining would end it
 *    for the whole team).
 *
 * Network failures (a phone network drops calls the web never sees):
 *  - a "disconnected" peer is a blip, not the end: the call shows
 *    "Reconnecting…" and ends only if ICE has not recovered within
 *    [ICE_GRACE_MS] (the web hangs up on the first blip);
 *  - hang-up ends the call on this phone at once; the terminate request
 *    follows in the background and is retried while the server can't be
 *    reached (the web waited up to 30s for it, the card frozen meanwhile);
 *  - an answer or outbound call whose request timed out may still have gone
 *    through: an answer waits for the media to connect before calling it
 *    failed, an outbound call looks for the row the server wrote;
 *  - an answer that couldn't even start (no connection before anything was
 *    sent) leaves the call ringing, says so, and lets the agent tap Answer
 *    again;
 *  - the callback note says the callback was saved only once the server said
 *    so; otherwise it says it is still trying, and retries;
 *  - recordings are kept on disk until uploaded ([RecordingOutbox]).
 */
class CallManager internal constructor(
    private val api: CallApi,
    private val events: Flow<JsonObject>,
    /** The live socket's state: every (re)connect polls at once for frames missed while it was down. */
    private val connected: StateFlow<Boolean>,
    scope: CoroutineScope,
    /** True while the app is on screen (the incoming-call notification only fires when not). */
    private val foreground: StateFlow<Boolean>,
    private val signedInFn: () -> Boolean,
    private val media: CallMedia,
    private val ringer: CallRinger,
    private val audio: CallAudio,
    private val micGranted: () -> Boolean,
    private val main: CoroutineDispatcher,
    io: CoroutineDispatcher,
    private val now: () -> Long,
    /** Where recordings wait until the server has them. */
    outboxDir: File = java.nio.file.Files.createTempDirectory("neema-call-rec").toFile(),
    /** The signed-in agent: tells a colleague's `call_answered` from this agent's own. */
    private val myAgentId: () -> String? = { null },
    /** The signed-in agent's name: a 409 naming it means this agent's other device holds the call. */
    private val myAgentName: () -> String? = { null },
) {
    constructor(
        context: Context,
        api: NeemaApi,
        socket: LiveSocket,
        scope: CoroutineScope,
        foreground: StateFlow<Boolean>,
        signedInFn: () -> Boolean,
        prefs: AppPrefs,
        agentIdFn: () -> String? = { null },
        agentNameFn: () -> String? = { null },
    ) : this(
        api = NeemaCallApi(api),
        events = socket.events,
        connected = socket.connected,
        scope = scope,
        foreground = foreground,
        signedInFn = signedInFn,
        media = WebRtcMedia(context),
        ringer = CallAlert(context, scope) { prefs.alerts.value },
        audio = AndroidCallAudio(context) { prefs.backgroundLive.value && signedInFn() },
        micGranted = {
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        },
        main = Dispatchers.Main,
        io = Dispatchers.IO,
        now = System::currentTimeMillis,
        outboxDir = File(context.filesDir, "call-recordings"),
        myAgentId = agentIdFn,
        myAgentName = agentNameFn,
    )

    private val ui = CoroutineScope(scope.coroutineContext + main)
    private val bg = CoroutineScope(scope.coroutineContext + io)
    private val outbox = RecordingOutbox(outboxDir, now)

    private val _state = MutableStateFlow(CallUiState(routes = audio.routes.value, route = preferredRoute(audio.routes.value)))
    val state: StateFlow<CallUiState> = _state.asStateFlow()

    /** Tests: when the live call started, on the injected clock (null when none is live). */
    internal val liveSinceForTest: Long? get() = liveSince

    private val _micRequest = MutableStateFlow(false)
    /** True while a call is waiting for the agent to allow the microphone. */
    val micRequest: StateFlow<Boolean> = _micRequest.asStateFlow()
    private var micWaiter: CompletableDeferred<Boolean>? = null

    private val _permissionGranted = MutableStateFlow<PermissionGrant?>(null)
    /** A customer this phone asked has allowed calls: the "{First} allowed calls — Call now" banner. */
    val permissionGranted: StateFlow<PermissionGrant?> = _permissionGranted.asStateFlow()

    private val _restriction = MutableStateFlow<CallingRestriction?>(null)
    /**
     * Meta flagged or restricted calling on the number (`calling_restricted`):
     * the Calls view's banner — calls we place may fail until it lifts.
     */
    val restriction: StateFlow<CallingRestriction?> = _restriction.asStateFlow()
    fun dismissRestriction() { _restriction.value = null }

    private val _channels = MutableStateFlow<CallChannels?>(null)
    /**
     * Which channels can call right now (GET /calls/channels, read at start,
     * on every socket reconnect and with each ice-config). Null until read —
     * Messenger counts as off until then, so a Messenger Call button never
     * shows before the server said it may.
     */
    val channels: StateFlow<CallChannels?> = _channels.asStateFlow()

    /** Messenger calls can be placed now (the server's `messenger_calling_enabled` switch, as last read). */
    val messengerCallsOn: Boolean get() = _channels.value?.messenger?.outbound == true

    /** This agent may open Settings → WhatsApp calling (manage_settings); the dashboard sets it. */
    @Volatile var canManageSettings: () -> Boolean = { false }

    // ── Refs (the web's useRef state) ────────────────────────────────────────
    private var peer: CallPeer? = null
    /** The call currently on screen. */
    private var activeId: String? = null
    /** callId → when we last dismissed it (the 12s re-ring cooldown). */
    private val endedAt = LinkedHashMap<String, Long>()   // oldest first
    private var recEnabled = true
    /** The server transcribes recordings (and without being asked): what the wrap-up promises. */
    private var transcribes = false
    private var autoTranscribes = false
    /** WhatsApp records + transcribes the call itself: "summary in a minute" even with nothing recorded here. */
    private var metaTranscribes = false
    /** A `call_status: ringing` for our call that beat connect's reply (applied once the id is known). */
    private var earlyRinging: String? = null
    private var recording: CallRecording? = null
    private var recCallId: String? = null
    private var timerJob: Job? = null
    /**
     * When the call went live, on [now]'s clock. The timer is worked out from
     * it on every tick — never counted up — so a main thread held back by a
     * screen-off doze, a busy frame or the app in the background can't make
     * the call look shorter than it is.
     */
    private var liveSince: Long? = null
    /** When this phone started ringing: an answer that goes back to ringing keeps the 2-minute limit. */
    private var ringSince: Long? = null
    private var resetJob: Job? = null
    private var ringTimeoutJob: Job? = null
    /** Running while a "disconnected" peer has its chance to recover. */
    private var graceJob: Job? = null
    /** Our SDP answer went to the server (its reply may yet be lost). */
    private var answerPosted = false
    /**
     * The server accepted our answer: hanging up now ends a call. Until then
     * End on a "Connecting…" incoming call is a decline — the call still rings
     * for the team (CallStage.tsx / callContext hangup()).
     */
    private var answerAccepted = false
    /** When the media path dropped (entering "Reconnecting…"): a dropped call lasted until here, not through the grace. */
    private var droppedAt: Long? = null
    /** "Connecting…" never lasts: the audio must arrive within [CONNECT_GUARD_MS]. */
    private var connectGuard: Job? = null
    /** The call's audio route is set up (communication mode, focus). */
    private var audioIn = false
    /**
     * The customer's SDP answer to OUR call, when it arrived before we knew
     * the call's id (connect's reply was slow, or timed out and the row had
     * to be looked up): applied the moment the id is known, so a customer who
     * picked up quickly isn't left in silence.
     */
    private var earlyAnswer: Pair<String, String>? = null
    /** An incoming call was ignored because another call was on screen: look again once it's over. */
    private var missedWhileBusy = false
    /** "channel:handle" → name of the customers this phone asked for call permission (for the "allowed calls" banner). */
    private val askedPermission = LinkedHashMap<String, String?>()
    private fun askKey(channel: String, handle: String) = "$channel:$handle"

    // ── Messenger's SDP (CALLING_UX.md §2.0) ────────────────────────────────
    /** The current peer has its remote description (Meta's answer): a renegotiation offer may be applied. */
    private var remoteReady = false
    /** The highest `media_update` version applied to the call on screen (older ones are stale). */
    private var mediaVersion = Int.MIN_VALUE
    /** A `media_update` that came before the call was set up: (callId, version, sdp), applied once it is. */
    private var pendingMedia: Triple<String, Int, String>? = null
    /** The media path is up (the peer said connected, and hasn't dropped since). */
    private var mediaUp = false
    /** Remote offers are applied one at a time (a renegotiation and a media_update may meet). */
    private val sdpLock = kotlinx.coroutines.sync.Mutex()
    private var started = false

    private val phase: CallPhase get() = _state.value.phase
    private fun update(f: (CallUiState) -> CallUiState) { _state.value = f(_state.value) }

    init {
        (ringer as? CallAlert)?.onAction = { action, id -> handleAction(action, id) }
    }

    /** Begin listening for the call frames, the poll fallback and the audio routes. */
    fun start() {
        if (started) return
        started = true
        // A ringing notification left behind by a process that died mid-ring.
        ringer.cancelIncoming()
        // Raw audio a process killed mid-call left behind (no call is live yet).
        bg.launch { runCatching { media.sweepLeftovers() } }

        // Primary path: the live WebSocket event (instant).
        // One bad frame costs that frame, never the listener: a throw here would
        // end the collector (and with it every later call on this phone).
        ui.launch {
            events.collect { e ->
                try { onFrame(e) } catch (x: CancellationException) { throw x } catch (x: Exception) {
                    logW("call frame failed: ${e.str("type")}", x)
                    ke.co.bethanyhouse.neema.core.crash.CrashVault.recordNonFatal(x, "call-frame:${e.str("type")}")
                }
            }
        }

        // Catch-up: frames sent while the socket was down are lost. Poll the
        // moment it (re)connects — after a network drop, after the process was
        // restarted by LiveService, after the app returns from a socket-less
        // background — and when the app comes back on screen. A call on screen
        // re-reads its own row too: it may have ended while we couldn't hear.
        ui.launch {
            var was = connected.value
            connected.collect { c -> if (c && !was) catchUp(); was = c }
        }
        ui.launch {
            var was = foreground.value
            foreground.collect { fg -> if (fg && !was) catchUp(); was = fg }
        }
        // Recordings a previous session could not upload.
        drainRecordings()
        // Which channels can call (Messenger sits behind a server switch).
        loadChannels()

        // Headsets come and go: the call follows them (see [onRoutes]).
        ui.launch { audio.routes.collect { r -> guarded("routes") { onRoutes(r) } } }

        // Fallback path: poll the call log for a fresh "ringing" call, so the card
        // appears even if the WS event was missed. 2.5s only while RINGING (hang-up
        // detection needs it); 12s otherwise. The cadence switches the moment the
        // phone starts or stops ringing (the web keeps a 12s wait already running,
        // so a colleague's answer — which sends no frame — could leave this phone
        // ringing for up to 12s).
        ui.launch {
            state.map { it.phase == CallPhase.Ringing }.distinctUntilChanged().collectLatest { ringing ->
                val every = if (ringing) RING_POLL_MS else IDLE_POLL_MS
                while (isActive) {
                    delay(every)
                    pollOnce()
                }
            }
        }

        // Phase side effects: ring + notify while ringing; timer + recording while
        // live; in-call audio routing + mic foreground service while a call runs.
        ui.launch {
            // One failure (a device's audio or ringer refusing) must not end this collector:
            // every later call would get no audio mode, ringing, timer or recording.
            state.map { it.phase }.distinctUntilChanged().collect { p -> guarded("phase") {
                ringTimeoutJob?.cancel(); ringTimeoutJob = null
                if (p == CallPhase.Ringing) {
                    ringer.startRinging()
                    if (!foreground.value) postIncoming()
                    val id = _state.value.callId
                    val left = RING_TIMEOUT_MS - (now() - (ringSince ?: now())).coerceAtLeast(0)
                    ringTimeoutJob = ui.launch {
                        delay(left.coerceAtLeast(0))
                        // Every end signal was lost: the caller is long gone.
                        if (phase == CallPhase.Ringing && _state.value.callId == id) finish(CallOutcome.Missed())
                    }
                } else {
                    ringer.stopRinging()
                    ringer.cancelIncoming()
                }
                // A caller who rang in during the last call may still be waiting.
                if ((p == CallPhase.Idle || p == CallPhase.Ended) && missedWhileBusy) {
                    missedWhileBusy = false
                    ui.launch { pollOnce() }
                }
                if (p == CallPhase.InCall) {
                    startRecording()   // begins once (guarded); remote audio is flowing by now
                    timerJob?.cancel()
                    val since = liveSince ?: (now() - _state.value.seconds * 1_000L).also { liveSince = it }
                    timerJob = ui.launch {
                        while (isActive) {
                            // Wake on the next whole second of the call, then read the clock.
                            delay(1_000L - (now() - since).mod(1_000L))
                            tickTimer()
                        }
                    }
                } else {
                    timerJob?.cancel(); timerJob = null
                    liveSince = null
                }
                if (p in AUDIO_PHASES) enterAudio() else leaveAudio()
            } }
        }
        // The app went to the background while a call is still ringing: notify.
        // Back on screen, the card is the alert — drop the notification.
        ui.launch {
            foreground.collect { fg ->
                // Back on screen mid-call: the timer reads the true length at once.
                if (fg && phase == CallPhase.InCall) tickTimer()
                if (phase != CallPhase.Ringing) return@collect
                if (fg) ringer.cancelIncoming() else postIncoming()
            }
        }
    }

    private fun catchUp() {
        ui.launch { pollOnce() }
        ui.launch { resync() }
        drainRecordings()
        loadChannels()
    }

    /** GET /calls/channels. A failure keeps what was known (unknown = Messenger off). */
    fun loadChannels() {
        ui.launch {
            if (!signedInFn()) return@launch
            try { _channels.value = api.channels() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { logW("channels unavailable", e) }
        }
    }

    /** The live call's length from [liveSince] (the only way [CallUiState.seconds] moves). */
    private fun tickTimer() {
        // Only a live call's clock moves: a tick that lands after the call ended must not
        // overwrite the length the wrap-up says (a dropped call's is the connected time).
        if (phase != CallPhase.InCall) return
        val since = liveSince ?: return
        val secs = ((now() - since) / 1_000L).toInt().coerceAtLeast(0)
        if (secs != _state.value.seconds) update { it.copy(seconds = secs) }
    }

    /** The poll cadence: 2.5s while ringing, 12s otherwise (restarted when ringing starts / stops). */
    internal fun pollDelay(): Long = if (phase == CallPhase.Ringing) RING_POLL_MS else IDLE_POLL_MS

    private fun postIncoming() {
        val s = _state.value
        val id = s.callId ?: return
        ringer.postIncoming(id, s.who, s.number, s.app)
    }

    // ── Audio routes ─────────────────────────────────────────────────────────
    /** What a call starts on, as phones do: a connected headset, else the earpiece (the speaker only when there is nothing else). */
    private fun preferredRoute(routes: List<AudioRoute>): AudioRoute =
        routes.lastOrNull { it.kind == AudioRouteKind.Bluetooth } ?: routes.lastOrNull { it.kind == AudioRouteKind.Wired }
            ?: quietRoute(routes)

    /** Never the loudspeaker when the phone has an earpiece: a headset that goes must not blast the call into the room. */
    private fun quietRoute(routes: List<AudioRoute>): AudioRoute =
        routes.firstOrNull { it.kind == AudioRouteKind.Earpiece } ?: routes.firstOrNull() ?: AudioRoute.Earpiece

    private fun enterAudio() {
        if (audioIn) return
        audioIn = true
        val r = preferredRoute(_state.value.routes)
        update { it.copy(route = r) }
        audio.enter(r)
    }

    private fun leaveAudio() {
        if (!audioIn) return
        audioIn = false
        audio.leave()
    }

    /**
     * The outputs changed. Outside a call the button just shows what a call
     * would start on. During one: a headset that was just connected takes the
     * call (as a phone does); the route in use disappearing (unplugged, out of
     * range) falls back to another headset, else the earpiece — never the
     * loudspeaker while there is an earpiece.
     */
    private fun onRoutes(routes: List<AudioRoute>) {
        val s = _state.value
        val before = s.routes
        update { it.copy(routes = routes) }
        if (!audioIn) {
            update { it.copy(route = preferredRoute(routes)) }
            return
        }
        val added = routes.filter { r -> r.isHeadset && before.none { it == r } }
        val next = when {
            added.isNotEmpty() -> added.last()
            s.route !in routes -> routes.lastOrNull { it.isHeadset } ?: quietRoute(routes)
            else -> null
        }
        if (next != null && next != s.route) selectRoute(next)
    }

    /** The audio list's choice (or [toggleSpeaker]'s). */
    fun selectRoute(route: AudioRoute) {
        if (route !in _state.value.routes) return
        update { it.copy(route = route) }
        audio.select(route)
    }

    /** Earpiece (or the headset) ↔ loudspeaker: the audio button when there is nothing else to choose. */
    fun toggleSpeaker() {
        val s = _state.value
        val next = if (s.speaker) s.routes.lastOrNull { it.isHeadset } ?: quietRoute(s.routes) else AudioRoute.Speaker
        if (next !in s.routes) return
        selectRoute(next)
    }

    // ── Frames ───────────────────────────────────────────────────────────────
    /** One WebSocket frame (only the call types matter here). */
    internal fun onFrame(evt: JsonObject) {
        when (evt.str("type")) {
            "incoming_call" -> {
                logD("WS event: $evt")
                val id = evt.str("call_id") ?: return
                val ch = channelOf(evt.str("channel"))
                // Messenger: `from` is their PSID (`external_id` too); no name — it follows in a call_update.
                val from = (evt.str("from") ?: evt.str("external_id"))?.removePrefix("+").orEmpty()
                val s = _state.value
                if (s.live && id != s.callId) {
                    missedWhileBusy = true
                    // On a call: a banner, never a take-over (there is no hold in the API).
                    if (s.phase != CallPhase.Ringing && !endedAt.containsKey(id)) {
                        update { it.copy(waiting = WaitingCall(id, from, evt.str("name"), ch)) }
                    }
                }
                startRinging(id, from, evt.str("name"), evt.str("conversation_id"), evt.str("person_id"), ch)
            }
            "outbound_answer" -> {
                val id = evt.str("call_id") ?: return
                val sdp = evt.str("sdp") ?: return
                val s = _state.value
                if (id == activeId) {
                    // The customer accepted OUR call — apply their SDP answer to connect.
                    logD("outbound answered")
                    val p = peer ?: return
                    if (phase == CallPhase.Placing || phase == CallPhase.RingingOut) { update { it.copy(phase = CallPhase.Connecting) }; armConnectGuard(id) }
                    // Posted: the call may have ended (and its peer closed) before this runs.
                    ui.launch { if (peer === p) runCatching { p.setRemote(SdpType.Answer, sdp) } }
                } else if (activeId == null && s.outbound && s.callId == "pending" && s.phase == CallPhase.Placing) {
                    // Ours, most likely, but connect hasn't told us its id yet.
                    earlyAnswer = id to sdp
                }
            }
            "call_answered" -> onAnswered(evt)
            // Messenger: the customer picked up our call, or changed media — a new offer (§2.0).
            "media_update" -> {
                val id = evt.str("call_id") ?: return
                val sdp = evt.str("sdp")?.takeIf { it.isNotBlank() }
                val type = evt.str("sdp_type")
                if (sdp == null || (type != null && type != "offer")) { logD("media_update without an offer — ignored"); return }
                val v = evt.str("version")?.toDoubleOrNull()?.toInt() ?: 0
                onMediaUpdate(id, v, sdp)
            }
            // Meta rings the customer's phone now: "Calling…" becomes "Ringing…" — only on this.
            "call_status" -> {
                val id = evt.str("call_id") ?: return
                if (evt.str("status") != "ringing") return
                val s = _state.value
                if (s.outbound && s.phase == CallPhase.Placing) {
                    if (s.callId == id) update { it.copy(phase = CallPhase.RingingOut) }
                    else if (s.callId == "pending") earlyRinging = id
                }
            }
            "calling_restricted" -> {
                val reasons = (evt["reasons"] as? kotlinx.serialization.json.JsonArray)?.mapNotNull {
                    (it as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { p -> p.isString }?.content
                        ?: (it as? JsonObject)?.let { o -> o.str("reason") ?: o.str("type") ?: o.str("description") }
                }.orEmpty()
                _restriction.value = CallingRestriction(reasons, evt.str("at"))
            }
            "call_ended" -> {
                logD("WS event: $evt")
                val id = evt.str("call_id") ?: return
                val cur = _state.value
                if (cur.waiting?.callId == id) update { it.copy(waiting = null) }
                if (cur.callId == id && cur.live) {
                    finish(outcomeOf(evt.str("outcome"), cur, evt.str("agent_name"), evt.str("agent_id")), evt.str("duration")?.toIntOrNull())
                }
                // A no_answer corrected to rejected a moment later: the latest word wins.
                else if (cur.callId == id && evt.str("outcome") == "rejected") correctToRejected()
                // A call we never showed (or not yet: frames can arrive out of
                // order): it is over, so a late incoming_call must not ring it.
                else if (cur.callId != id && !endedAt.containsKey(id)) markEnded(id)
            }
            "call_update" -> {
                val row = (evt["call"] as? JsonObject)?.let {
                    runCatching { NeemaJson.decodeFromJsonElement(Call.serializer(), it) }.getOrNull()
                } ?: return
                applyRow(row)
            }
            "call_permission" -> onPermission(evt)
        }
    }

    /**
     * Someone answered. For our outbound call that is the customer picking up;
     * for a call ringing here it is a colleague (this phone stops at once);
     * while this phone is still answering, a colleague who won the race.
     */
    private fun onAnswered(evt: JsonObject) {
        val id = evt.str("call_id") ?: return
        val s = _state.value
        if (s.waiting?.callId == id) update { it.copy(waiting = null) }
        if (s.callId != id) return
        val agentId = evt.str("agent_id")
        when (s.phase) {
            CallPhase.Ringing -> finish(CallOutcome.AnsweredElsewhere(evt.str("agent_name"), mine = isMe(agentId)))
            CallPhase.Placing, CallPhase.RingingOut -> if (s.outbound) customerAnswered(id)
            CallPhase.Connecting -> if (!s.outbound && takenBySomeoneElse(agentId)) finish(CallOutcome.AnsweredElsewhere(evt.str("agent_name")))
            else -> Unit
        }
    }

    /**
     * The customer picked up OUR call. WhatsApp: their answer's media follows
     * ("Connecting…"). Messenger: the media path to Meta may be up already
     * (its answer came back with connect) — then they're talking now; never
     * before this moment, whatever the media did.
     */
    private fun customerAnswered(id: String) {
        val s = _state.value
        if (s.callId != id || !s.outbound || (s.phase != CallPhase.Placing && s.phase != CallPhase.RingingOut)) return
        if (s.messenger && mediaUp && peer != null) {
            update { it.copy(phase = CallPhase.InCall) }
            return
        }
        update { it.copy(phase = CallPhase.Connecting) }
        armConnectGuard(id)
    }

    /**
     * `media_update {version, sdp}` (Messenger): the offer with the highest
     * version is applied as a remote offer and answered locally — nothing is
     * sent back (Meta documents no route for it; the web does the same).
     * Stale versions, other calls' and SDP-less frames are ignored; one that
     * arrives before the call is set up is held and applied once it is.
     */
    private fun onMediaUpdate(id: String, version: Int, sdp: String) {
        val s = _state.value
        when {
            s.callId == id && s.live -> applyMediaUpdate(id, version, sdp)
            // Our call whose id connect hasn't told us yet.
            s.live && s.outbound && s.callId == "pending" -> holdMedia(id, version, sdp)
            else -> Unit
        }
    }

    private fun holdMedia(id: String, version: Int, sdp: String) {
        val had = pendingMedia
        if (had == null || had.first != id || had.second < version) pendingMedia = Triple(id, version, sdp)
    }

    private fun applyMediaUpdate(id: String, version: Int, sdp: String) {
        if (version <= mediaVersion) { logD("stale media_update v$version ignored"); return }
        val p = peer
        if (p == null || !remoteReady) { holdMedia(id, version, sdp); return }
        mediaVersion = version
        ui.launch { applyRemoteOffer(p, sdp, "media_update") }
    }

    /** A held media_update for [id], now that the call has Meta's answer. */
    private fun flushMedia(id: String) {
        val m = pendingMedia?.takeIf { it.first == id } ?: return
        pendingMedia = null
        applyMediaUpdate(id, m.second, m.third)
    }

    /**
     * Meta's offer (a renegotiation after accept / connect, or a media_update)
     * → a local answer. A failure is logged, never fatal: the call keeps the
     * media it has.
     */
    private suspend fun applyRemoteOffer(p: CallPeer, sdp: String, why: String): Boolean = sdpLock.withLock {
        if (peer !== p) return@withLock false
        try {
            p.setRemote(SdpType.Offer, sdp)
            if (peer !== p) return@withLock false
            val answer = p.createAnswer()
            if (peer !== p) return@withLock false
            p.setLocal(SdpType.Answer, answer)
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            logW("Messenger $why offer not applied", e)
            false
        }
    }

    private fun takenBySomeoneElse(agentId: String?): Boolean {
        val me = myAgentId() ?: return false
        return agentId != null && agentId != me
    }

    /** [agentId] is the signed-in agent (on this or another of their devices). */
    private fun isMe(agentId: String?): Boolean = agentId != null && agentId == myAgentId()

    /** A 409's "answered by {name}" names the signed-in agent: their other device has the call. */
    private fun namesMe(who: String?): Boolean {
        val me = myAgentName()?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        return who != null && who.trim().equals(me, ignoreCase = true)
    }

    /** `call_permission`: a customer this phone asked has allowed calls (or not). */
    private fun onPermission(evt: JsonObject) {
        // Matched by channel + handle: the wa_id, or (Messenger) the PSID in `external_id`.
        val ch = channelOf(evt.str("channel"))
        val wa = (if (ch == MESSENGER) evt.str("external_id") else evt.str("wa_id") ?: evt.str("external_id"))
            ?.removePrefix("+")?.takeIf { it.isNotEmpty() } ?: return
        // The card showing this customer says where their permission stands now.
        val cur = _state.value
        val sameCall = cur.from == wa && cur.channel == ch
        if (sameCall && cur.phase != CallPhase.Idle) {
            val st = evt.str("status") ?: "unknown"
            val prev = cur.permission ?: CallPermission(waId = wa)
            update {
                it.copy(permission = prev.copy(
                    status = st, expiresAt = evt.str("expires_at"), permanent = evt.str("permanent") == "true",
                    revoked = evt.str("revoked") == "true", at = evt.str("at") ?: prev.at,
                    canCall = when (st) { "granted" -> true; "denied" -> false; else -> prev.canCall },
                ))
            }
        }
        val key = askKey(ch, wa)
        if (evt.str("status") != "granted" || !askedPermission.containsKey(key)) return
        val name = askedPermission.remove(key)
        _permissionGranted.value = PermissionGrant(wa, name, ch)
        // The wrap-up that said "call request sent" has its answer: the banner replaces it.
        val s = _state.value
        if (s.phase == CallPhase.Ended && s.from == wa && s.channel == ch &&
            (s.outcome == CallOutcome.PermissionRequested || s.outcome == CallOutcome.PermissionNeeded)
        ) dismiss()
    }

    /**
     * What a call's end means for this phone: the server's outcome, read
     * against where this phone was (a "completed" call that was still ringing
     * here was answered by a colleague).
     */
    private fun outcomeOf(status: String?, s: CallUiState, agent: String?, agentId: String?): CallOutcome = when (status) {
        "answered" -> CallOutcome.AnsweredElsewhere(agent, mine = isMe(agentId))
        "completed", "ended" ->
            if (s.phase == CallPhase.Ringing) CallOutcome.AnsweredElsewhere(agent, mine = isMe(agentId)) else CallOutcome.Completed
        "missed" -> CallOutcome.Missed()
        // "Declined by Ann" only when it was a colleague (the web's `other`).
        "declined" -> CallOutcome.Declined(agent.takeIf { takenBySomeoneElse(agentId) })
        "callback" -> CallOutcome.Callback(CallbackSave.Saved, agent.takeIf { takenBySomeoneElse(agentId) })
        "no_answer" -> CallOutcome.NoAnswer
        "rejected" -> CallOutcome.Rejected
        "cancelled" -> CallOutcome.Cancelled
        "failed" -> CallOutcome.Failed(CALL_NOT_CONNECTED)
        // An older frame without an outcome: judge by where the call was.
        else -> when (s.phase) {
            CallPhase.Ringing -> CallOutcome.Missed()
            CallPhase.Placing, CallPhase.RingingOut -> CallOutcome.NoAnswer
            else -> if (s.reconnecting) CallOutcome.ConnectionLost else CallOutcome.Completed
        }
    }

    /**
     * A call's current row (a `call_update`, the re-sync, the poll): fill in
     * what the ring didn't carry (the chat, the person, the name) and correct
     * a phase the server knows to be over.
     */
    private fun applyRow(row: Call) {
        val s = _state.value
        if (row.callId.isEmpty() || row.callId != s.callId) return
        update {
            it.copy(
                conversationId = row.conversationId ?: it.conversationId,
                personId = row.personId ?: it.personId,
                name = it.name?.takeIf { n -> n.isNotBlank() } ?: row.name,
                channel = if (channelOf(row.channel) == MESSENGER) MESSENGER else it.channel,
            )
        }
        val st = row.status
        if (st.isEmpty()) return
        when (s.phase) {
            // Saving a callback: the server marks the row itself; the card ends with its note.
            CallPhase.Ringing -> if (st != "ringing" && !s.busy) finish(outcomeOf(st, s, row.agentName, row.agentId))
            CallPhase.Placing, CallPhase.RingingOut -> when {
                st == "answered" -> if (s.outbound) customerAnswered(row.callId)
                st != "ringing" -> finish(outcomeOf(st, s, row.agentName, row.agentId), row.duration)
            }
            CallPhase.Connecting, CallPhase.InCall -> when {
                st == "answered" -> if (s.phase == CallPhase.Connecting && !s.outbound && takenBySomeoneElse(row.agentId)) {
                    finish(CallOutcome.AnsweredElsewhere(row.agentName))
                }
                st != "ringing" -> finish(outcomeOf(st, s, row.agentName, row.agentId), row.duration)
            }
            CallPhase.Ended -> if (st == "rejected") correctToRejected()
            else -> Unit
        }
    }

    /** Meta's REJECTED can land just after the call was taken as unanswered: "{First} declined the call". */
    private fun correctToRejected() {
        val s = _state.value
        if (s.phase != CallPhase.Ended || !s.outbound || s.outcome != CallOutcome.NoAnswer) return
        update { it.copy(outcome = CallOutcome.Rejected) }
        scheduleClose(CallOutcome.Rejected)
    }

    /**
     * One pass of the poll fallback. Passes never overlap: the tick, a
     * reconnect, a return to the app and the end of a call asking at once on
     * a slow network share one GET (see [SingleFlight]).
     */
    internal suspend fun pollOnce() = polls.run()

    private val polls = SingleFlight(ui) { pollNow() }

    private suspend fun pollNow() {
        if (!signedInFn()) return
        val calls = try { api.list() } catch (e: CancellationException) { throw e } catch (e: Exception) { return }
        val t = now()
        val s = _state.value
        if (s.phase == CallPhase.Ringing) {
            // The caller hung up, or a colleague answered (row no longer "ringing").
            if (calls.any { it.isFreshInboundRing(t) && it.callId != activeId }) missedWhileBusy = true
            calls.find { it.callId == activeId }?.let(::applyRow)
            return
        }
        if (s.live) {
            // Busy with another call: remember that someone is waiting, and show them.
            val other = calls.firstOrNull { it.isFreshInboundRing(t) && it.callId != s.callId && !coolingDown(it.callId, t) }
            if (other != null) {
                missedWhileBusy = true
                if (s.waiting == null) update { it.copy(waiting = WaitingCall(other.callId, callHandle(other), other.name, channelOf(other.channel))) }
            }
            s.waiting?.let { w ->
                val row = calls.find { it.callId == w.callId }
                if (row != null && row.status != "ringing") update { it.copy(waiting = null) }
            }
            if (s.callId != "pending") calls.find { it.callId == s.callId }?.let(::applyRow)
            return
        }
        val ringing = calls.find { it.isFreshInboundRing(t) && !coolingDown(it.callId, t) }
        if (ringing != null) {
            logD("poll fallback caught ringing call: ${ringing.callId}")
            startRinging(ringing.callId, callHandle(ringing), ringing.name, ringing.conversationId, ringing.personId, channelOf(ringing.channel))
        }
    }

    /**
     * After the socket reconnects or the app returns to the front: the call on
     * screen re-reads its own row and takes the server's word for how it
     * ended while this phone couldn't hear (CALLING_UX.md §4).
     */
    internal suspend fun resync() = resyncs.run()

    private val resyncs = SingleFlight(ui) { resyncNow() }

    private suspend fun resyncNow() {
        if (!signedInFn()) return
        val s = _state.value
        val id = s.callId?.takeIf { it != "pending" } ?: return
        if (!s.live) return
        val row = try { api.get(id) } catch (e: CancellationException) { throw e } catch (e: Exception) { return }
        applyRow(row)
    }

    /** A row the poll fallback rings for: inbound, still ringing, started under 90s ago. */
    private fun Call.isFreshInboundRing(t: Long) =
        status == "ringing" && direction != "outbound" && Fmt.millis(startedAt)?.let { t - it < 90_000 } == true

    /**
     * Remembers that [callId] is over. Bounded: a long shift sees a
     * `call_ended` frame for every call any agent takes, so beyond
     * [ENDED_MAX] the entries past any use (the re-ring cooldown and the
     * outbound-row lookup both look back minutes, not hours) are dropped,
     * then the oldest.
     */
    private fun markEnded(callId: String) {
        val t = now()
        endedAt.remove(callId)   // re-inserted at the end: the map stays oldest-first
        endedAt[callId] = t
        if (endedAt.size <= ENDED_MAX) return
        endedAt.values.removeAll { t - it > ENDED_KEEP_MS }
        val it = endedAt.entries.iterator()
        while (endedAt.size > ENDED_MAX && it.hasNext()) { it.next(); it.remove() }
    }

    /** How many ended calls are remembered (tests: it stays bounded under a burst). */
    internal val endedCount: Int get() = endedAt.size

    private fun coolingDown(callId: String, t: Long) = endedAt[callId]?.let { t - it < RERING_COOLDOWN_MS } == true

    /** A notification action (answer/decline/end/show) routed through MainActivity or a broadcast. */
    fun handleIntent(intent: Intent) {
        val action = intent.getStringExtra(Notifier.EXTRA_CALL_ACTION) ?: return
        handleAction(action, intent.getStringExtra(Notifier.EXTRA_CALL_ID))
    }

    /** "answer" | "decline" | "end" | "show" from the call notifications. */
    internal fun handleAction(action: String, id: String?) {
        val s = _state.value
        val matches = id == null || id == s.callId
        when (action) {
            "answer" -> when {
                // One tap from a locked phone: straight to Connecting, on the full card.
                matches && s.phase == CallPhase.Ringing -> { ringer.cancelIncoming(); update { it.copy(minimised = false) }; answer() }
                // The process was restarted since the notification went up: find
                // the call again, then answer it if it's still ringing.
                !s.live && id != null -> ui.launch {
                    ringer.cancelIncoming()
                    pollOnce()
                    if (_state.value.callId == id && phase == CallPhase.Ringing) answer()
                }
            }
            "decline" -> when {
                matches && s.phase == CallPhase.Ringing -> hangup()
                // A call this process no longer tracks: still tell the server.
                !s.live && id != null -> ui.launch {
                    ringer.cancelIncoming()
                    markEnded(id)
                    terminateSoon(id)
                }
            }
            // The ongoing-call notification's End.
            "end" -> if (matches && s.live && s.phase != CallPhase.Ringing) hangup()
            else -> Unit   // "show": the activity is up; CallStage renders the call
        }
    }

    // Start ringing for a given call (shared by the WS event + the poll fallback).
    // A short cooldown stops a still-"ringing" record from instantly re-ringing
    // after a decline / failed answer, while allowing a genuine retry after ~12s.
    // A wrap-up on screen gives way at once.
    private fun startRinging(
        callId: String, from: String, name: String?, conversationId: String? = null, personId: String? = null,
        channel: String = WHATSAPP,
    ) {
        if (_state.value.live) return
        if (coolingDown(callId, now())) return
        resetJob?.cancel(); resetJob = null
        activeId = callId
        ringSince = now()
        answerPosted = false
        resetSdp(keepFor = callId)
        val s = _state.value
        _state.value = CallUiState(
            phase = CallPhase.Ringing, callId = callId, from = from, name = name, channel = channel,
            conversationId = conversationId, personId = personId,
            routes = s.routes, route = preferredRoute(s.routes),
        )
    }

    /** A new call: nothing of the last one's SDP state carries over (a frame held for [keepFor] does). */
    private fun resetSdp(keepFor: String? = null) {
        remoteReady = false
        mediaUp = false
        mediaVersion = Int.MIN_VALUE
        if (pendingMedia?.first != keepFor) pendingMedia = null
    }

    // ── Microphone ───────────────────────────────────────────────────────────
    /** The UI's answer to [micRequest]. */
    fun onMicResult(granted: Boolean) {
        val w = micWaiter
        micWaiter = null
        _micRequest.value = false
        w?.complete(granted)
    }

    private suspend fun ensureMic(): Boolean {
        if (micGranted()) return true
        val w = micWaiter ?: CompletableDeferred<Boolean>().also { micWaiter = it }
        _micRequest.value = true
        val granted = withTimeoutOrNull(MIC_PROMPT_TIMEOUT_MS) { w.await() } ?: false
        if (micWaiter === w) { micWaiter = null; _micRequest.value = false }
        return granted
    }

    // ── Recording ────────────────────────────────────────────────────────────
    private fun startRecording() {
        if (recording != null || !recEnabled) return
        val p = peer ?: return
        if (!p.hasMic) return
        recording = try { media.startRecording(_state.value.muted) } catch (e: Throwable) {
            logW("recording unavailable", e); null
        } ?: return
        recCallId = activeId ?: _state.value.callId
        update { it.copy(recording = true) }
    }

    /** Stop + upload. Called at the top of cleanup() so it flushes on EVERY end path. */
    private fun stopRecording() {
        val r = recording ?: return
        val callId = recCallId
        recording = null
        recCallId = null
        update {
            it.copy(
                recording = false,
                recordingNote = when {
                    autoTranscribes || metaTranscribes -> RECORDING_SAVED_AUTO
                    transcribes -> RECORDING_SAVED_MANUAL
                    else -> RECORDING_SAVED
                },
            )
        }
        bg.launch {
            val file = try { r.stop() } catch (e: Throwable) { null } ?: return@launch
            if (callId == null || callId == "pending" || file.length() < MIN_RECORDING_BYTES) {
                file.delete()   // skip near-silent / empty recordings
                return@launch
            }
            // Kept on disk until the server has it: an upload that fails now
            // (often the very network drop that ended the call) is retried later.
            if (outbox.put(callId, file)) drain()
        }
    }

    /** Uploads the recordings still waiting (see [RecordingOutbox]). */
    private fun drainRecordings() { bg.launch { drain() } }

    private suspend fun drain() {
        if (!signedInFn()) return
        outbox.drain { id, f ->
            // Streamed from disk: an hour-long call never sits in memory.
            try { api.uploadRecording(id, UploadFile.of(f, "$id.m4a", "audio/mp4")) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { logW("recording upload failed", e); throw e }
        }
    }

    private fun readConfig(cfg: IceConfig) {
        recEnabled = cfg.record != false
        transcribes = cfg.transcribe == true
        autoTranscribes = cfg.autoTranscribe == true
        metaTranscribes = cfg.metaTranscription == true
        cfg.channels?.let { _channels.value = it }
        if (_state.value.metaTranscription != metaTranscribes) update { it.copy(metaTranscription = metaTranscribes) }
    }

    // ── Teardown ─────────────────────────────────────────────────────────────
    private fun cleanup() {
        graceJob?.cancel(); graceJob = null
        timerJob?.cancel(); timerJob = null
        connectGuard?.cancel(); connectGuard = null
        droppedAt = null
        stopRecording()
        peer?.let { p -> peer = null; runCatching { p.close() } }
        micWaiter?.let { w -> micWaiter = null; _micRequest.value = false; w.complete(false) }
        ringer.stopRinging()
        ringer.cancelIncoming()
    }

    /**
     * The call is over on this phone: the wrap-up with its [outcome]. A neutral
     * one closes by itself; a caller waiting behind this call rings at once.
     */
    private fun finish(outcome: CallOutcome, serverSeconds: Int? = null, promoteWaiting: Boolean = true, connectedSeconds: Int? = null) {
        cleanup()
        activeId?.let { markEnded(it) }
        activeId = null
        earlyAnswer = null
        val waiting = _state.value.waiting
        update {
            it.copy(
                phase = CallPhase.Ended, outcome = outcome, reconnecting = false, busy = false, error = null,
                seconds = connectedSeconds ?: if (it.seconds == 0 && serverSeconds != null) serverSeconds else it.seconds,
                waiting = null,
                recordingNote = if (outcome == CallOutcome.Completed || outcome == CallOutcome.ConnectionLost) {
                    // WhatsApp transcribes the call itself: a summary follows even when nothing was recorded here.
                    it.recordingNote ?: META_SUMMARY.takeIf { _ -> it.metaTranscription && (connectedSeconds ?: it.seconds) > 0 }
                } else null,
            )
        }
        scheduleClose(outcome)
        if (promoteWaiting && waiting != null && !endedAt.containsKey(waiting.callId)) {
            missedWhileBusy = false   // this is the look-again
            promote(waiting)
        }
    }

    /** A neutral wrap-up closes by itself (long enough to read a recording note). */
    private fun scheduleClose(outcome: CallOutcome) {
        resetJob?.cancel(); resetJob = null
        val base = outcome.autoCloseMs ?: return
        val ms = if (_state.value.recordingNote != null) maxOf(base, 8_000L) else base
        resetJob = ui.launch {
            delay(ms)
            if (phase == CallPhase.Ended && _state.value.outcome === outcome) toIdle()
        }
    }

    /**
     * A decline / call-back the server refused with 409 "call already answered
     * by Ann": a colleague picked up a moment before the tap (routers/admin.py
     * _refuse_if_colleagues_call). The wrap-up says so instead of "Call declined".
     */
    private fun yieldTo(callId: String, who: String?) {
        val s = _state.value
        if (s.phase != CallPhase.Ended || s.callId != callId) return
        if (s.outcome !is CallOutcome.Declined && s.outcome !is CallOutcome.Callback) return
        val o = CallOutcome.AnsweredElsewhere(who, mine = namesMe(who))
        update { it.copy(outcome = o, busy = false) }
        scheduleClose(o)
    }

    /**
     * The call that kept [w] waiting is over: ring them now — after one quick
     * read that they are still on the line (a caller who gave up meanwhile
     * must not ring). No answer from the server: the frame is trusted.
     */
    private fun promote(w: WaitingCall) {
        ui.launch {
            val rows = try { api.list() } catch (e: CancellationException) { throw e } catch (_: Exception) { null }
            if (_state.value.live) return@launch
            val row = rows?.find { it.callId == w.callId }
            if (row != null && row.status != "ringing") { markEnded(w.callId); return@launch }
            startRinging(w.callId, row?.let(::callHandle)?.takeIf { it.isNotEmpty() } ?: w.from ?: "", row?.name ?: w.name,
                row?.conversationId, row?.personId, row?.let { channelOf(it.channel) } ?: w.channel)
        }
    }

    private fun toIdle() {
        resetJob?.cancel(); resetJob = null
        val routes = _state.value.routes
        _state.value = CallUiState(routes = routes, route = preferredRoute(routes))
    }

    /** The wrap-up's Done / Cancel (a live call is never dismissed — it is hung up). */
    fun dismiss() {
        if (phase == CallPhase.Ended) toIdle()
    }

    /** §6: the call shrinks to the bar at the top of the app; the rest of Neema stays usable. */
    fun minimise() { if (phase != CallPhase.Idle && phase != CallPhase.Ringing) update { it.copy(minimised = true) } }

    fun expand() { update { it.copy(minimised = false) } }

    /**
     * "Open chat" / "Message": the key of the customer's conversation to open
     * (null when there is nobody to write to). A live call shrinks to the bar
     * rather than ending; a wrap-up closes.
     */
    fun openChat(): String? {
        val s = _state.value
        val key = s.chatKey ?: return null
        if (s.live && s.phase != CallPhase.Ringing) update { it.copy(minimised = true) }
        else if (s.phase == CallPhase.Ended) dismiss()
        return key
    }

    /** "Call again" / "Call back" / "Try again" from the wrap-up. */
    fun redial() {
        val s = _state.value
        val to = s.from?.takeIf { it.isNotEmpty() } ?: return
        if (s.live) return
        ui.launch { initiateCall(to, s.name, s.conversationId, s.channel) }
    }

    /**
     * Ends the call on this phone at once (a second tap finds it over), then
     * tells the server in the background — a slow or unreachable server never
     * keeps a live-looking card on screen. What the tap meant depends on where
     * the call was: a ringing call is declined (for the whole team), our call
     * not yet answered is cancelled, a call that was answered is completed.
     */
    fun hangup() {
        ui.launch {
            val s = _state.value
            if (!s.live || s.busy) return@launch
            val id = s.callId
            val outcome = when (s.phase) {
                CallPhase.Ringing -> CallOutcome.Declined()
                CallPhase.Placing, CallPhase.RingingOut -> CallOutcome.Cancelled
                CallPhase.Connecting -> if (!s.outbound && !answerAccepted) CallOutcome.Declined() else CallOutcome.Completed
                else -> CallOutcome.Completed
            }
            // The call's true length at the tap (the clock, not the last tick).
            val connected = liveSince?.let { ((now() - it) / 1_000L).toInt().coerceAtLeast(0) }
            finish(outcome, connectedSeconds = connected)
            if (id != null && id != "pending") {
                terminateSoon(id, onTaken = if (outcome is CallOutcome.Declined) ({ who: String? -> yieldTo(id, who) }) else null)
            }
        }
    }

    /**
     * Sign-out: ends the call on this phone and waits — at most [timeoutMs] —
     * for the server to hear it, so the terminate still goes out under the
     * session that is about to be cleared (fired and forgotten, it raced the
     * sign-out and was refused with a 401, leaving the customer on the line).
     *
     * A call that is only ringing is let go on this phone without declining
     * it: a colleague may still answer. The card goes straight to idle — the
     * next agent to sign in sees nothing of this call.
     */
    suspend fun endForSignOut(timeoutMs: Long = SIGN_OUT_TERMINATE_MS) = withContext(main) {
        val s = _state.value
        resetJob?.cancel(); resetJob = null
        _permissionGranted.value = null
        askedPermission.clear()
        if (s.phase == CallPhase.Idle) return@withContext
        val id = s.callId
        val terminateId = id?.takeIf { s.live && s.phase != CallPhase.Ringing && it != "pending" }
        cleanup()
        id?.let { markEnded(it) }
        activeId = null
        earlyAnswer = null
        toIdle()
        if (terminateId != null) withTimeoutOrNull(timeoutMs) {
            try { api.terminate(terminateId) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
        }
    }

    /**
     * POST /terminate, retried a couple of times while the server can't be
     * reached — otherwise the customer's phone keeps ringing, or the call stays
     * up on their side, until Meta times it out.
     */
    private fun terminateSoon(id: String, onTaken: ((String?) -> Unit)? = null) {
        ui.launch {
            for (attempt in 0..TERMINATE_RETRY_MS.size) {
                try { api.terminate(id); return@launch }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) {
                    // 409: a colleague answered a moment earlier — their call is left alone.
                    if (e.statusOrNull() == 409) { onTaken?.invoke(e.answeredBy()); return@launch }
                    // 502 "terminate failed": Meta says the call is already over, or couldn't be reached.
                    if (!RecordingOutbox.isTransient(e) || attempt == TERMINATE_RETRY_MS.size) return@launch
                    delay(TERMINATE_RETRY_MS[attempt])
                }
            }
        }
    }

    /**
     * Decline now, call them back later. The card waits for the server (its
     * buttons disabled) so "Saved to call back" is only said once it is; a
     * request that never got an answer keeps retrying in the background.
     */
    fun callback() {
        ui.launch {
            val s = _state.value
            if (!s.live || s.busy) return@launch
            val id = s.callId
            cleanup()
            if (id == null || id == "pending") { finish(CallOutcome.Callback(CallbackSave.Saved)); return@launch }
            update { it.copy(busy = true) }
            val saved = try {
                api.callback(id); CallbackSave.Saved
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logW("callback failed", e)
                if (e.statusOrNull() == 409) {
                    // A colleague answered a moment before the tap: their call goes on.
                    if (_state.value.callId == id) { val who = e.answeredBy(); finish(CallOutcome.AnsweredElsewhere(who, mine = namesMe(who))) }
                    return@launch
                }
                if (RecordingOutbox.isTransient(e) && e.statusOrNull() != 401) { callbackSoon(id); CallbackSave.Retrying }
                else CallbackSave.NotSaved
            }
            if (_state.value.callId != id) return@launch   // the card has moved on
            finish(CallOutcome.Callback(saved))
        }
    }

    /** Background retries of POST /callback (idempotent: terminate + mark it callback). */
    private fun callbackSoon(id: String) {
        ui.launch {
            for (wait in TERMINATE_RETRY_MS) {
                delay(wait)
                try { api.callback(id); return@launch }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { if (!RecordingOutbox.isTransient(e)) return@launch }
            }
        }
    }

    // ── The second caller (a banner while this phone is on a call) ───────────
    /** Decline the waiting caller — for the whole team, as any decline. */
    fun declineWaiting() {
        val w = _state.value.waiting ?: return
        update { it.copy(waiting = null) }
        markEnded(w.callId)
        terminateSoon(w.callId)
    }

    /** "Call back later" for the waiting caller: it ends and lands under Calls → Follow-ups. */
    fun callbackWaiting() {
        val w = _state.value.waiting ?: return
        update { it.copy(waiting = null) }
        markEnded(w.callId)
        ui.launch {
            try { api.callback(w.callId) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (RecordingOutbox.isTransient(e)) callbackSoon(w.callId) }
        }
    }

    /** "End & answer": the API has no hold, so taking the waiting caller means hanging up this call. */
    fun endAndAnswer() {
        ui.launch {
            val s = _state.value
            val w = s.waiting ?: return@launch
            if (!s.live || s.busy || s.phase == CallPhase.Ringing) return@launch
            val id = s.callId
            finish(CallOutcome.Completed, promoteWaiting = false)
            if (id != null && id != "pending") terminateSoon(id)
            // The agent chose them: straight to answering (a 409 / 410 says if they are gone).
            startRinging(w.callId, w.from ?: "", w.name, channel = w.channel)
            if (_state.value.callId == w.callId && phase == CallPhase.Ringing) answer()
        }
    }

    // ── Answer an inbound call ───────────────────────────────────────────────
    fun answer() {
        ui.launch {
            val s = _state.value
            val callId = s.callId ?: return@launch
            if (s.phase != CallPhase.Ringing || s.busy) return@launch
            update { it.copy(error = null, phase = CallPhase.Connecting, minimised = false) }
            answerPosted = false
            answerAccepted = false
            ringer.stopRinging(); ringer.cancelIncoming()
            fun stillMine() = _state.value.callId == callId && (phase == CallPhase.Connecting || phase == CallPhase.InCall)
            try {
                val (cfg, offer) = coroutineScope {
                    val c = async { api.iceConfig() }
                    val o = async { api.offer(callId) }
                    c.await() to o.await()
                }
                readConfig(cfg)
                if (!stillMine()) return@launch   // hung up meanwhile
                // Messenger sends no offer (CALLING_UX.md §2.0): WE build the offer and
                // accept with it; Meta's answer comes back in the reply.
                val reversed = offer.offerRequired ||
                    (offer.sdp.isNullOrEmpty() && (channelOf(offer.channel) == MESSENGER || _state.value.messenger))
                if (reversed && !_state.value.messenger) update { it.copy(channel = MESSENGER) }
                val p = newPeer(cfg)
                if (!ensureMic()) throw MicBlocked()
                if (peer !== p) return@launch
                p.addMic(!_state.value.muted)
                audio.micLive()
                val mine: String
                // Each step suspends: a hang-up meanwhile closes the peer, which must not be used again.
                if (reversed) {
                    mine = p.createOffer()
                    if (peer !== p) return@launch
                    p.setLocal(SdpType.Offer, mine)
                } else {
                    p.setRemote(SdpType.Offer, offer.sdp.orEmpty())
                    if (peer !== p) return@launch
                    mine = p.createAnswer()
                    if (peer !== p) return@launch
                    p.setLocal(SdpType.Answer, mine)
                }
                awaitGathering(p)
                if (peer !== p) return@launch
                answerPosted = true
                val resp = api.answer(callId, p.localSdp ?: mine)
                answerAccepted = true
                if (reversed && !acceptMessengerAnswer(p, callId, resp)) return@launch
                if (stillMine() && phase == CallPhase.Connecting) armConnectGuard(callId)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                // An Error too (a device's audio stack, WebRTC's native side): a
                // failed answer, never the whole app closing on the agent.
                logW("answer failed", e)
                reportUnexpected(e, "call-answer")
                if (!stillMine()) return@launch
                when {
                    // Messenger calling was switched off since we last looked.
                    e.isMessengerOff() -> {
                        loadChannels()
                        finish(CallOutcome.Failed(e.messengerOffReason(), "none")); return@launch
                    }
                    // 409: a colleague won the redis lock and is talking to the customer.
                    // Only this device's side goes — never terminate their call.
                    e.isTakenElsewhere() -> {
                        val who = e.answeredBy()
                        finish(CallOutcome.AnsweredElsewhere(who, mine = namesMe(who))); return@launch
                    }
                    // 410, or the offer is gone (404): the caller hung up — nothing to terminate.
                    e.isCallGone() || e.isOfferGone() -> { finish(CallOutcome.Missed(CALL_GONE)); return@launch }
                    // Nothing was answered: colleagues' phones still ring, so this one just steps back.
                    e is MicBlocked -> { finish(CallOutcome.MicBlocked); return@launch }
                    // Nothing reached Meta yet (no connection before our answer left): keep it
                    // ringing and let the agent tap Answer again.
                    !answerPosted && e.statusOrNull() == 0 -> {
                        cleanup()
                        update { it.copy(phase = CallPhase.Ringing, error = if (e.isTimeout()) ANSWER_SLOW_RETRY else ANSWER_NO_CONNECTION) }
                        return@launch
                    }
                }
                if (e.isAmbiguous("/answer")) {
                    // The accept may have reached Meta even though its answer never
                    // came back: if the media connects, the call went through.
                    withTimeoutOrNull(ANSWER_CONFIRM_MS) {
                        state.first { it.callId != callId || it.phase != CallPhase.Connecting }
                    }
                    if (!stillMine() || phase == CallPhase.InCall) return@launch
                }
                // Our answer left but its reply never came, and no audio followed: the
                // call may be up with nobody on it here — hang it up, say what happened.
                val why = if (answerPosted && e.statusOrNull() == 0) ANSWER_DROPPED else answerError(e)
                update { it.copy(error = why) }
                delay(1_800)
                if (_state.value.callId != callId || !_state.value.live) return@launch
                // Connected after all (the error was about a request whose work was done).
                if (phase == CallPhase.InCall) { update { it.copy(error = null) }; return@launch }
                finish(CallOutcome.Failed(why, (e as? ApiException)?.action))
                terminateSoon(callId)
            }
        }
    }

    /**
     * Meta's answer to our offer, then (when present) its renegotiation offer,
     * then any media_update that came early. Accepted but nothing to apply
     * (or an answer the peer refuses): the call can't carry audio — it is
     * ended, never left as a silent line. False when the call is over.
     */
    private suspend fun acceptMessengerAnswer(p: CallPeer, callId: String, resp: ke.co.bethanyhouse.neema.core.model.CallSdpResponse): Boolean {
        if (peer !== p) return false
        val answer = resp.sdp?.takeIf { it.isNotBlank() }
        val applied = answer != null && try {
            p.setRemote(SdpType.Answer, answer); true
        } catch (e: CancellationException) { throw e } catch (e: Throwable) { logW("Messenger answer rejected", e); false }
        if (peer !== p || _state.value.callId != callId) return false
        if (!applied) {
            finish(CallOutcome.Failed(if (answer == null) AUDIO_NOT_CONNECTED else AUDIO_SETUP_FAILED))
            terminateSoon(callId)
            return false
        }
        remoteReady = true
        resp.renegotiationSdp?.let { applyRemoteOffer(p, it, "accept") }
        flushMedia(callId)
        return peer === p
    }

    fun toggleMute() {
        val p = peer ?: return
        if (!p.hasMic) return
        val next = !_state.value.muted
        p.setMicEnabled(!next)
        recording?.micMuted = next
        update { it.copy(muted = next) }
    }

    /**
     * Business-initiated call: WE call the customer. Build an offer, ask Meta to
     * place the call ("Calling…"); once it rings them ("Ringing…") the
     * customer's SDP answer arrives as an outbound_answer frame. Without their
     * call permission (409) the wrap-up says so and offers the call request —
     * never sent by itself, it messages the customer.
     * Result.failure carries the user-facing message ([CallError.shown]: the
     * card already says it); a call the agent hung up before it was placed
     * counts as success (there is nothing to report).
     */
    suspend fun initiateCall(
        to: String, name: String? = null, conversationId: String? = null,
        /** "messenger": [to] is their PSID and the call goes out on Messenger (CALLING_UX.md §2.0). */
        channel: String = WHATSAPP,
    ): Result<Unit> = try {
        placeCall(to, name, conversationId, channel)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Throwable) {
        // The last net: whatever slipped past placeCall's own handling ends the
        // call on the card — the caller (a screen's viewModelScope) never sees it.
        logW("outbound call broke", e)
        reportUnexpected(e, "call-place")
        withContext(NonCancellable + main) {
            runCatching { if (_state.value.outbound && _state.value.live) finish(CallOutcome.Failed(DEVICE_CALL_FAILED)) }
        }
        Result.failure(CallError(DEVICE_CALL_FAILED, shown = true))
    }

    private suspend fun placeCall(
        to: String, name: String?, conversationId: String?, channel: String,
    ): Result<Unit> = withContext(main) {
        if (_state.value.live) return@withContext Result.failure(CallError("Already in a call"))
        val messenger = channelOf(channel) == MESSENGER
        val wa = if (messenger) to.filter { it.isDigit() } else to.removePrefix("+")
        if (messenger && wa.isEmpty()) return@withContext Result.failure(CallError("No Messenger id for this customer."))
        resetJob?.cancel(); resetJob = null
        earlyAnswer = null
        earlyRinging = null
        answerPosted = false
        answerAccepted = false
        resetSdp()
        val routes = _state.value.routes
        _state.value = CallUiState(
            phase = CallPhase.Placing, callId = "pending", from = wa, name = name, outbound = true,
            channel = if (messenger) MESSENGER else WHATSAPP,
            conversationId = conversationId, routes = routes, route = preferredRoute(routes),
        )
        fun stillMine() = _state.value.outbound && _state.value.callId == "pending" && phase == CallPhase.Placing
        val startedAfter = now() - CLOCK_SKEW_MS
        try {
            // Permission truth first (Meta's answer, read alongside the ICE config): a customer
            // who hasn't allowed calls goes straight to "Send call request" — no doomed connect.
            // A slow or failed read never holds the call up: it is placed as before.
            val (cfg, perm) = coroutineScope {
                val p = async { readPermission(wa, messenger) }
                api.iceConfig() to p.await()
            }
            readConfig(cfg)
            if (!stillMine()) return@withContext Result.success(Unit)
            if (perm != null) update { it.copy(permission = perm) }
            if (perm != null && perm.canCall == false && perm.status != "granted") {
                finish(if (perm.status == "requested") CallOutcome.PermissionRequested else CallOutcome.PermissionNeeded)
                return@withContext Result.failure(CallError(NO_CALL_PERMISSION, shown = true))
            }
            val p = newPeer(cfg)
            if (!ensureMic()) throw MicBlocked()
            if (peer !== p) return@withContext Result.success(Unit)
            p.addMic(!_state.value.muted)
            audio.micLive()
            val offer = p.createOffer()
            if (peer !== p) return@withContext Result.success(Unit)   // hung up while the offer was made
            p.setLocal(SdpType.Offer, offer)
            awaitGathering(p)
            if (peer !== p) return@withContext Result.success(Unit)
            if (messenger) return@withContext placeMessenger(p, wa, p.localSdp ?: offer, name)
            val id = try {
                api.connect(to, p.localSdp ?: offer, name?.takeIf { it.isNotEmpty() })
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // No answer came back, but Meta may be ringing the customer now:
                // find the row calls_connect wrote before calling it a failure.
                if (!e.isAmbiguous("/admin/calls/connect")) throw e
                findPlacedCall(to, startedAfter) ?: throw e
            }
            if (peer !== p) {
                // Hung up while Meta was placing it: don't leave their phone ringing.
                try { api.terminate(id) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
                return@withContext Result.success(Unit)
            }
            activeId = id
            // Placed: still "Calling…" until Meta says their phone rings (`call_status`), which may have come already.
            val ringing = earlyRinging == id
            earlyRinging = null
            update { if (it.callId == "pending") it.copy(callId = id, phase = if (ringing) CallPhase.RingingOut else CallPhase.Placing) else it }
            earlyAnswer?.let { (early, sdp) ->
                earlyAnswer = null
                if (early == id) {
                    logD("outbound answered (early)")
                    if (phase == CallPhase.Placing || phase == CallPhase.RingingOut) { update { it.copy(phase = CallPhase.Connecting) }; armConnectGuard(id) }
                    runCatching { p.setRemote(SdpType.Answer, sdp) }
                }
            }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            // An Error too (a device's audio stack, WebRTC's native side): a failed
            // call on the card, never the whole app closing under the agent.
            logW("outbound call failed", e)
            reportUnexpected(e, "call-place")
            // A connect that timed out and left no row: it may yet ring them.
            val friendly = if (e.isAmbiguous("/admin/calls/connect") && e.isTimeout()) UNCONFIRMED_CALL else outboundError(e)
            if (!stillMine()) return@withContext Result.failure(CallError(friendly))
            val outcome = when {
                e is MicBlocked -> CallOutcome.MicBlocked
                // Messenger calling was switched off since we last looked: call them on WhatsApp instead.
                e.isMessengerOff() -> { loadChannels(); CallOutcome.Failed(e.messengerOffReason(), "none") }
                e is ApiException && (e.status == 409 || e.action == "request_permission") -> {
                    // Asked already (and waiting on their Allow), or never: the card says which.
                    val perm = readPermission(wa, messenger)
                    if (perm != null && stillMine()) update { it.copy(permission = perm) }
                    if (perm?.status == "requested") CallOutcome.PermissionRequested else CallOutcome.PermissionNeeded
                }
                friendly == UNCONFIRMED_CALL -> CallOutcome.Failed(UNCONFIRMED_CALL)
                else -> CallOutcome.Failed(
                    e.serverReason() ?: friendly, (e as? ApiException)?.action, (e as? ApiException)?.field("request_available_at"),
                )
            }
            if (!stillMine()) return@withContext Result.failure(CallError(friendly))
            finish(outcome)
            Result.failure(CallError(friendly, shown = true))
        }
    }

    /**
     * The Messenger half of [initiateCall]: connect with our offer; Meta's
     * answer comes back at once and is applied (then its renegotiation, and
     * any media_update that beat the reply). The card stays "Calling…" /
     * "Ringing…" until `call_answered` — the media path to Meta may come up
     * before the customer picks up, and that is not them answering.
     */
    private suspend fun placeMessenger(p: CallPeer, psid: String, sdp: String, name: String?): Result<Unit> {
        // Never retried, never looked up after a timeout: a second connect would ring them twice.
        val resp = api.connectMessenger(psid, sdp, name?.takeIf { it.isNotBlank() })
        val id = resp.callId.takeIf { it.isNotEmpty() } ?: throw CallError(CALL_NOT_CONNECTED)
        if (peer !== p) {
            try { api.terminate(id) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
            return Result.success(Unit)
        }
        activeId = id
        val ringing = earlyRinging == id
        earlyRinging = null
        update { if (it.callId == "pending") it.copy(callId = id, phase = if (ringing) CallPhase.RingingOut else CallPhase.Placing) else it }
        val answer = resp.sdp?.takeIf { it.isNotBlank() }
        if (answer != null) {
            try { p.setRemote(SdpType.Answer, answer); remoteReady = true }
            catch (e: CancellationException) { throw e } catch (e: Throwable) { logW("Messenger answer rejected", e) }
        }
        if (remoteReady) {
            resp.renegotiationSdp?.let { applyRemoteOffer(p, it, "connect") }
            flushMedia(id)
        }
        return Result.success(Unit)
    }

    /**
     * Ask the customer for permission to call them (WhatsApp's interactive
     * call_permission_request inside the 24 h window, the approved template
     * outside it). It messages the customer, so only ever on the agent's tap —
     * "Send call request" on the wrap-up or the customer panel. Their Allow
     * arrives as `call_permission` and raises [permissionGranted] on this
     * phone. A refusal is an [ApiException] with the server's `code` /
     * `action` (template_required, 138009 — see [requestRefusal]).
     */
    suspend fun requestPermission(to: String, name: String? = null, channel: String = WHATSAPP): Result<PermissionRequestResponse> {
        val wa = to.filter { it.isDigit() }
        val ch = channelOf(channel)
        return try {
            val who = name ?: withContext(main) { _state.value.takeIf { it.from == wa && it.channel == ch }?.name }
            // Messenger: the `calling_optin` message (Accept / Decline); WhatsApp: its call-permission request.
            val r = if (ch == MESSENGER) api.requestMessengerPermission(wa) else api.requestPermission(wa, who?.takeIf { it.isNotBlank() })
            if (!r.alreadyPermitted) withContext(main) { askedPermission[askKey(ch, wa)] = who }
            Result.success(r)
        } catch (e: CancellationException) { throw e } catch (e: Exception) {
            if (e.isMessengerOff()) loadChannels()
            Result.failure(e)
        }
    }

    /** The wrap-up's "Send call request". */
    fun sendCallRequest() {
        ui.launch {
            val s = _state.value
            val to = s.from?.takeIf { it.isNotEmpty() } ?: return@launch
            if (s.phase != CallPhase.Ended || s.outcome != CallOutcome.PermissionNeeded || s.busy) return@launch
            if (s.sendRequestBlocked() != null || s.refusal?.code == "template_required") return@launch
            update { it.copy(busy = true, error = null) }
            val r = requestPermission(to, s.name, s.channel)
            val now = _state.value
            if (now.phase != CallPhase.Ended || now.from != to || now.outcome != CallOutcome.PermissionNeeded) return@launch
            val resp = r.getOrNull()
            val e = r.exceptionOrNull()
            when {
                // They had allowed calls permanently already: nothing to ask — "Call now".
                resp?.alreadyPermitted == true -> {
                    update { it.copy(busy = false, outcome = CallOutcome.AlreadyAllowed, permission = resp.permission ?: it.permission) }
                    scheduleClose(CallOutcome.AlreadyAllowed)
                }
                resp != null -> {
                    update { it.copy(busy = false, outcome = CallOutcome.PermissionRequested, permission = resp.permission ?: it.permission) }
                    // Nothing more is owed on this card: it closes as the web's does (the banner follows the Allow).
                    scheduleClose(CallOutcome.PermissionRequested)
                }
                else -> {
                    val refusal = requestRefusal(e, canManageSettings())
                    update {
                        when (refusal?.code) {
                            // The limit (Messenger's: 2 a day): the button waits, saying when it can be pressed again.
                            "138009", "request_limit" -> it.copy(
                                busy = false, refusal = refusal,
                                permission = (it.permission ?: CallPermission(waId = to)).copy(
                                    canRequest = false,
                                    requestAvailableAt = (e as? ApiException)?.field("request_available_at") ?: it.permission?.requestAvailableAt,
                                ),
                            )
                            "template_required" -> it.copy(busy = false, refusal = refusal, error = refusal.detail)
                            else -> it.copy(busy = false, refusal = refusal, error = permissionRequestError(e))
                        }
                    }
                }
            }
        }
    }

    /** The wrap-up's "Call now" (the call request found they already allowed calls). */
    fun callNow() {
        val s = _state.value
        val to = s.from?.takeIf { it.isNotEmpty() } ?: return
        if (s.live) return
        ui.launch { initiateCall(to, s.name, s.conversationId, s.channel) }
    }

    /**
     * GET /calls/permission, capped at [PERMISSION_READ_MS]: null when it is
     * slow or fails (the call is placed as it always was).
     */
    private suspend fun readPermission(wa: String, messenger: Boolean = false): CallPermission? = try {
        withTimeoutOrNull(PERMISSION_READ_MS) { if (messenger) api.messengerPermission(wa) else api.permission(wa) }
    } catch (e: CancellationException) { throw e } catch (e: Exception) {
        if (e.isMessengerOff()) loadChannels()
        null
    }

    /** The banner's "Call now" for a customer who just allowed calls. */
    fun callGranted() {
        val g = _permissionGranted.value ?: return
        _permissionGranted.value = null
        if (_state.value.live) return
        ui.launch { initiateCall(g.waId, g.name, channel = g.channel) }
    }

    fun dismissGrant() { _permissionGranted.value = null }

    /**
     * The outbound row calls_connect records once Meta placed the call: to this
     * customer, still ringing, started since we asked. Looked for twice (the
     * server may still be finishing the request that timed out on us).
     */
    private suspend fun findPlacedCall(to: String, since: Long): String? {
        val wa = to.filter { it.isDigit() }
        repeat(2) { i ->
            if (i > 0) delay(PLACED_LOOKUP_GAP_MS)
            val rows = try { api.list() } catch (e: CancellationException) { throw e } catch (_: Exception) { null }
            rows?.firstOrNull {
                it.direction == "outbound" && it.status == "ringing" && it.waId == wa &&
                    !endedAt.containsKey(it.callId) && (Fmt.millis(it.startedAt) ?: 0L) >= since
            }?.let { return it.callId }
        }
        return null
    }

    // ── Peer connection plumbing ─────────────────────────────────────────────
    private fun newPeer(cfg: IceConfig): CallPeer {
        var self: CallPeer? = null
        val p = media.createPeer(cfg) { ev ->
            ui.launch {
                val me = self
                if (me == null || peer !== me) return@launch
                when (ev) {
                    PeerEvent.Connected -> {
                        mediaUp = true
                        graceJob?.cancel(); graceJob = null
                        connectGuard?.cancel(); connectGuard = null
                        droppedAt = null
                        if (_state.value.reconnecting) update { it.copy(reconnecting = false) }
                        setInCall()
                    }
                    PeerEvent.Interrupted -> { mediaUp = false; onInterrupted(me) }
                    PeerEvent.Ended -> { mediaUp = false; when {
                        // The path failed for good while it was recovering, or before any audio: gone.
                        _state.value.reconnecting || phase == CallPhase.Connecting -> loseConnection()
                        // Messenger: our call's path to Meta failed before they picked up.
                        phase == CallPhase.Placing || phase == CallPhase.RingingOut -> loseConnection()
                        else -> finish(CallOutcome.Completed)
                    } }
                }
            }
        }
        self = p
        peer = p
        remoteReady = false
        mediaUp = false
        return p
    }

    /**
     * The media path dropped. A phone on a moving network loses it for a few
     * seconds all the time and ICE brings it back by itself; the web ended the
     * call on the first blip. Hold on for [ICE_GRACE_MS], then give up.
     */
    private fun onInterrupted(p: CallPeer) {
        if (phase != CallPhase.InCall && phase != CallPhase.Connecting) return
        if (graceJob?.isActive == true) return
        if (phase == CallPhase.InCall) droppedAt = now()
        update { it.copy(reconnecting = true) }
        graceJob = ui.launch {
            delay(ICE_GRACE_MS)
            if (peer !== p) return@launch
            graceJob = null
            loseConnection()
        }
    }

    /**
     * The media is gone for good: "Call dropped · 2:13" — the time it was
     * really connected, not the grace spent waiting — or, when no audio ever
     * flowed, "The call audio couldn't connect". Either way the call is hung
     * up behind it, so the customer isn't left on a silent line.
     */
    private fun loseConnection() {
        val id = _state.value.callId
        val since = liveSince
        if (since == null) finish(CallOutcome.Failed(AUDIO_NOT_CONNECTED))
        else finish(CallOutcome.ConnectionLost, connectedSeconds = (((droppedAt ?: now()) - since) / 1_000L).toInt().coerceAtLeast(0))
        if (id != null && id != "pending") terminateSoon(id)
    }

    /** Answered (or the customer picked up), but the audio must arrive: never sit on "Connecting…" forever. */
    private fun armConnectGuard(id: String) {
        connectGuard?.cancel()
        connectGuard = ui.launch {
            delay(CONNECT_GUARD_MS)
            connectGuard = null
            val s = _state.value
            if (s.phase == CallPhase.Connecting && s.callId == id && !s.reconnecting) {
                finish(CallOutcome.Failed(AUDIO_NOT_CONNECTED))
                terminateSoon(id)
            }
        }
    }

    private fun setInCall() {
        val s = _state.value
        // Messenger: Meta's media server answered our offer before the customer picked up —
        // the call goes live on `call_answered`, never on the media alone.
        if (s.outbound && s.messenger && (s.phase == CallPhase.Placing || s.phase == CallPhase.RingingOut)) return
        if (phase == CallPhase.Connecting || phase == CallPhase.Ringing || phase == CallPhase.RingingOut) {
            update { it.copy(phase = CallPhase.InCall) }
        }
    }

    /** Wait for ICE gathering to finish, capped at 2.5s (as the web does). */
    private suspend fun awaitGathering(p: CallPeer) {
        withTimeoutOrNull(GATHER_TIMEOUT_MS) { p.awaitGathering() }
    }

    private class MicBlocked : Exception("Permission denied")

    /**
     * A failure the call flow doesn't expect (not the server's, not the
     * network's, not a refused microphone): kept as a crash report so the
     * trace reaches the team — the agent only sees the call fail.
     */
    /** One step of a long-lived collector: a failure is recorded, and the collector carries on. */
    private inline fun guarded(where: String, block: () -> Unit) {
        try { block() } catch (e: CancellationException) { throw e } catch (e: Throwable) {
            logW("$where failed", e)
            runCatching { ke.co.bethanyhouse.neema.core.crash.CrashVault.recordNonFatal(e, "call-$where") }
        }
    }

    private fun reportUnexpected(e: Throwable, where: String) {
        if (e is ApiException || e is CallError || e is MicBlocked || e.isOffline() || e.isTimeout()) return
        runCatching { ke.co.bethanyhouse.neema.core.crash.CrashVault.recordNonFatal(e, where) }
    }

    /** A failed call carrying the user-facing message ([shown]: the call card already says it). */
    class CallError(message: String, val shown: Boolean = false) : Exception(message)

    companion object {
        private const val TAG = "CallManager"

        /** The phases with the call's audio set up (communication mode, focus, route). */
        private val AUDIO_PHASES = setOf(CallPhase.Placing, CallPhase.RingingOut, CallPhase.Connecting, CallPhase.InCall)

        // android.util.Log is a stub on the plain JVM (unit tests): never let logging throw.
        private fun logD(msg: String) { runCatching { Log.d(TAG, msg) } }
        private fun logW(msg: String, e: Throwable) { runCatching { Log.w(TAG, msg, e) } }
        const val MIC_BLOCKED = "Microphone blocked — allow it and try again"
        /** The phone or tablet couldn't set the call's audio up (the report goes to the team). */
        const val DEVICE_CALL_FAILED = "This device couldn't start the call — try again, or call from another phone"
        /** The wrap-up's words for a refused microphone (its button opens the settings). */
        const val MIC_BLOCKED_WRAP = "Microphone blocked — allow it in settings"
        const val NO_CALL_PERMISSION = "This customer hasn't allowed WhatsApp calls yet — send them a call request"
        const val RING_POLL_MS = 2_500L
        const val IDLE_POLL_MS = 12_000L
        const val RERING_COOLDOWN_MS = 12_000L
        const val GATHER_TIMEOUT_MS = 2_500L
        const val MIC_PROMPT_TIMEOUT_MS = 60_000L
        const val MIN_RECORDING_BYTES = 2_000L
        /** Ended calls remembered before old ones are dropped ([markEnded]). */
        const val ENDED_MAX = 256
        /** An ended call older than this is past every use of [endedAt]. */
        const val ENDED_KEEP_MS = 10 * 60_000L
        /** routers/admin.py list_calls marks a call still "ringing" after 2 minutes as missed. */
        const val RING_TIMEOUT_MS = 120_000L

        const val TAKEN_ELSEWHERE = "Another agent already answered this call"
        const val CALL_GONE = "This call has already ended"
        const val ANSWER_OFFLINE = "No connection — couldn't answer the call"
        const val ANSWER_SLOW = "The server took too long — couldn't connect the call"
        /** An answer that never left this phone: the call still rings and Answer stays live. */
        const val ANSWER_NO_CONNECTION = "No connection — can't answer yet"
        const val ANSWER_SLOW_RETRY = "The server is slow — tap Answer to try again"
        const val OUTBOUND_OFFLINE = "No connection — the call wasn't placed"
        /** Our answer reached the server but its reply (and the audio) never came back. */
        const val ANSWER_DROPPED = "The connection dropped while answering — call them back"
        /** Answered, but no audio ever flowed. */
        const val AUDIO_NOT_CONNECTED = "The call audio couldn't connect"
        /** Meta's answer to our offer couldn't be applied. */
        const val AUDIO_SETUP_FAILED = "Couldn't set up the call audio"
        /** 409 `messenger_calling_off` with no sentence of its own. */
        const val MESSENGER_OFF = "Messenger calling is switched off — call them on WhatsApp instead."
        /** Under "{First} hasn't allowed WhatsApp calls yet" (CallStage.tsx). */
        const val PERMISSION_EXPLAINED =
            "WhatsApp only lets a business call someone who allowed it. The request is a WhatsApp message with an Allow button."
        /** The same for Messenger (CallStage.tsx). */
        const val PERMISSION_EXPLAINED_MESSENGER =
            "Messenger only lets a business call someone who accepted a call request. The request is a Messenger message with Accept and Decline buttons."
        const val OUTBOUND_SLOW = "The server took too long — couldn't place the call"
        /** connect timed out and no placed call turned up: it may still be ringing them. */
        const val UNCONFIRMED_CALL = "Couldn't confirm the call went through — check Calls before trying again"
        const val CALL_NOT_CONNECTED = "The call couldn't be connected"
        const val SESSION_EXPIRED = "Your session expired — sign in again"
        const val CALLBACK_SAVED = "Saved to call back — find it under Calls"
        const val CALLBACK_RETRYING = "Callback not saved yet — retrying"
        const val CALLBACK_FAILED = "Couldn't save the callback"
        const val RECORDING_SAVED_AUTO = "Recording saved — summary in a minute"
        const val RECORDING_SAVED_MANUAL = "Recording saved — Transcribe from Calls"
        const val RECORDING_SAVED = "Recording saved"
        /** Nothing recorded here, but WhatsApp records and transcribes the call itself. */
        const val META_SUMMARY = "Recorded by WhatsApp — summary in a minute"
        /** A refusal whose `action` is admin: no Try again. */
        const val ADMIN_MUST_ACT = "An admin needs to fix this — trying again won't help."
        /** `action` wait with no time given. */
        const val WAIT_A_MOMENT = "Wait a little before trying again."
        /** `action` none: calling won't work — write to them. */
        const val MESSAGE_INSTEAD = "Send them a message instead."
        /** How long the permission read may hold up placing a call. */
        const val PERMISSION_READ_MS = 1_500L

        /** How long a "disconnected" call may take to recover before it is ended. */
        const val ICE_GRACE_MS = 10_000L
        /** How long an answer whose request timed out may take to connect anyway. */
        const val ANSWER_CONFIRM_MS = 8_000L
        /** How long "Connecting…" may last once the call was answered (callContext CONNECT_GUARD_MS). */
        const val CONNECT_GUARD_MS = 20_000L
        /** Waits between the terminate / callback retries. */
        val TERMINATE_RETRY_MS = longArrayOf(2_000L, 5_000L)
        const val PLACED_LOOKUP_GAP_MS = 3_000L
        /** How long sign-out waits for a live call's terminate before clearing the session anyway. */
        const val SIGN_OUT_TERMINATE_MS = 3_000L
        /** The server's clock vs this phone's, when matching the row an outbound call created. */
        const val CLOCK_SKEW_MS = 120_000L

        private fun Throwable.statusOrNull() = (this as? ApiException)?.status

        /** 409 `messenger_calling_off`: the server's switch is off (every Messenger action says so). */
        internal fun Throwable.isMessengerOff() = this is ApiException && code == "messenger_calling_off"

        private fun Throwable.messengerOffReason(): String =
            (this as? ApiException)?.detail?.trim()?.takeIf { it.isNotEmpty() && !it.startsWith("<") && it.length <= 200 } ?: MESSENGER_OFF

        /** The request left but no answer came back: it may have done its work. */
        private fun Throwable.isAmbiguous(pathEnd: String) =
            this is ApiException && status == 0 && path.endsWith(pathEnd)

        private fun Throwable.isTimeout() = this is ApiException && status == 0 && body.startsWith("timed out")
        private fun Throwable.isOffline() = this is ApiException && status == 0 && !isTimeout()

        /** POST /admin/calls/{id}/answer's 409 (routers/admin.py calls_answer: "call already answered by {name}"). */
        private fun Throwable.isTakenElsewhere() =
            this is ApiException && status == 409 && path.endsWith("/answer") && !isMessengerOff()

        /** POST /answer's 410: "This call has already ended." (the caller gave up, a colleague declined). */
        private fun Throwable.isCallGone() = this is ApiException && status == 410

        /** GET /offer's 404 "call offer expired or not found": the caller hung up. */
        private fun Throwable.isOfferGone() =
            this is ApiException && status == 404 && path.endsWith("/offer")

        /** The winner's name in a 409's "call already answered by Ann" (null when it isn't named). */
        internal fun Throwable.answeredBy(): String? {
            val d = (this as? ApiException)?.detail ?: return null
            return Regex("answered by (.+)$", RegexOption.IGNORE_CASE).find(d.trim())?.groupValues?.get(1)?.trim()?.trimEnd('.')
                ?.takeIf { it.isNotEmpty() && it != "None" && !it.equals("a colleague", ignoreCase = true) }
        }

        /**
         * A connect refusal the agent can act on (routers/admin.py calls_connect's
         * 502 "call failed: <reason>") — never an HTML error page or a stack of codes.
         */
        private fun Throwable.serverReason(): String? {
            val a = this as? ApiException ?: return null
            // A structured refusal (`code`) says what happened whatever its status; an older one only on connect's 502.
            if (a.code == null && (a.status != 502 || !a.path.endsWith("/connect"))) return null
            val d = a.detail.trim().removePrefix("call failed:").trim()
            if (d.isEmpty() || d.startsWith("<") || d.length > 160) return null
            return d.replaceFirstChar { it.uppercase() }
        }

        /** answer()'s catch in lib/callContext.tsx (plus the 409 a colleague's answer causes). */
        internal fun answerError(e: Throwable): String = when {
            e is MicBlocked -> MIC_BLOCKED
            // accept's structured 502: the reason Meta gave, said for people.
            e is ApiException && e.status == 502 && e.code != null ->
                e.detail.trim().removePrefix("accept failed:").trim().takeIf { it.isNotEmpty() && !it.startsWith("<") && it.length <= 160 }
                    ?.replaceFirstChar { it.uppercase() } ?: "Couldn't connect the call"
            e.isTakenElsewhere() -> TAKEN_ELSEWHERE
            e.isOfferGone() || e.isCallGone() -> CALL_GONE
            e.isTimeout() -> ANSWER_SLOW
            e.isOffline() -> ANSWER_OFFLINE
            e.statusOrNull() == 401 -> SESSION_EXPIRED
            else -> "Couldn't connect the call"
        }

        /** initiateCall()'s catch in lib/callContext.tsx. Never says "permission" but for the 409. */
        internal fun outboundError(e: Throwable): String = when {
            e is MicBlocked -> MIC_BLOCKED
            e is ApiException && e.status == 409 -> NO_CALL_PERMISSION
            e.isTimeout() -> OUTBOUND_SLOW
            e.isOffline() -> OUTBOUND_OFFLINE
            e.statusOrNull() == 401 -> SESSION_EXPIRED
            // Not the server, not the network: this device couldn't set the call up.
            e is Error -> DEVICE_CALL_FAILED
            else -> "Couldn't place the call"
        }

        /** Why "Send call request" didn't go. */
        internal fun permissionRequestError(e: Throwable?): String = when {
            e == null -> "Couldn't send the call request"
            e.isTimeout() -> "No answer from the server — the request may still arrive. Check the chat before sending again."
            e.isOffline() -> "No connection — the call request wasn't sent"
            e.statusOrNull() == 401 -> SESSION_EXPIRED
            // A structured refusal: the server's sentence, without its "permission request failed:" prefix.
            e is ApiException && e.code != null -> e.detail.trim().removePrefix("permission request failed:").trim()
                .takeIf { it.isNotEmpty() && !it.startsWith("<") && it.length <= 200 }?.replaceFirstChar { it.uppercase() }
                ?: "Couldn't send the call request"
            else -> "Couldn't send the call request"
        }

        /** A call request's structured refusal (null for a plain network failure). */
        fun requestRefusal(e: Throwable?, admin: Boolean): CallRefusal? {
            val a = e as? ApiException ?: return null
            val code = a.code ?: return null
            return CallRefusal(code, a.action, a.detail.trim(), adminCanFix = admin && code == "template_required")
        }
    }
}
