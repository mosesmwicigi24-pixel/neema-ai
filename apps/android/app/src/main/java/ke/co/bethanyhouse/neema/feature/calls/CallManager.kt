package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject

/** idle | ringing | connecting | in_call | ended (lib/callContext.tsx). */
enum class CallPhase { Idle, Ringing, Connecting, InCall, Ended }

data class CallUiState(
    val phase: CallPhase = CallPhase.Idle,
    val callId: String? = null,
    /** Customer wa_id (digits, no +). */
    val from: String? = null,
    val name: String? = null,
    val muted: Boolean = false,
    val speaker: Boolean = false,
    val seconds: Int = 0,
    val error: String? = null,
    val note: String? = null,
    /** True while we placed the call (ringing THEM). */
    val outbound: Boolean = false,
)

/**
 * The WhatsApp softphone: incoming-call ringing, answer / decline / callback,
 * outbound calls, mute, and call recording — the port of lib/callContext.tsx.
 * Process-wide (lives in AppContainer) so a call survives navigating between
 * screens.
 *
 * This class is the web's rules and nothing else: the device side (WebRTC,
 * audio routing, ringtone, notification, the mic permission) arrives through
 * the interfaces in CallPorts.kt, so every rule here runs on the JVM in tests.
 *
 * PUBLIC CONTRACT — other features call only [state], [initiateCall],
 * [requestPermission], [hangup] and (MainActivity) [handleIntent].
 *
 * Threading: every state change runs on [main]; peer events hop there first.
 *
 * Microphone: the browser asks for the mic inside getUserMedia, in the middle
 * of answering or placing a call. Here the same moment raises [micRequest];
 * [CallStage] (always composed while signed in) shows the system prompt and
 * reports back through [onMicResult]. Refused (or unanswered for a minute),
 * the call fails with "Microphone blocked — allow it and try again", as the
 * web's does.
 *
 * Deliberate differences from the web (all web bugs, none visible otherwise):
 *  - a `call_ended` frame ends the call properly (the web showed "ended" and
 *    never returned to idle, leaving the card stuck);
 *  - an outbound call hung up while Meta was still placing it is terminated
 *    (the web left the customer's phone ringing with nobody on the line);
 *  - hang-up / callback taps on a call that already ended are ignored (a
 *    double tap re-terminated and restarted the "Call ended" timer);
 *  - the poll keeps running in the background (the web skips hidden tabs)
 *    so a call still rings the phone through the notification.
 */
class CallManager internal constructor(
    private val api: CallApi,
    private val events: Flow<JsonObject>,
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
) {
    constructor(
        context: Context,
        api: NeemaApi,
        socket: LiveSocket,
        scope: CoroutineScope,
        foreground: StateFlow<Boolean>,
        signedInFn: () -> Boolean,
        prefs: AppPrefs,
    ) : this(
        api = NeemaCallApi(api),
        events = socket.events,
        scope = scope,
        foreground = foreground,
        signedInFn = signedInFn,
        media = WebRtcMedia(context),
        ringer = CallAlert(context, scope),
        audio = AndroidCallAudio(context) { prefs.backgroundLive.value && signedInFn() },
        micGranted = {
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        },
        main = Dispatchers.Main,
        io = Dispatchers.IO,
        now = System::currentTimeMillis,
    )

    private val ui = CoroutineScope(scope.coroutineContext + main)
    private val bg = CoroutineScope(scope.coroutineContext + io)

    private val _state = MutableStateFlow(CallUiState())
    val state: StateFlow<CallUiState> = _state.asStateFlow()

    private val _micRequest = MutableStateFlow(false)
    /** True while a call is waiting for the agent to allow the microphone. */
    val micRequest: StateFlow<Boolean> = _micRequest.asStateFlow()
    private var micWaiter: CompletableDeferred<Boolean>? = null

    // ── Refs (the web's useRef state) ────────────────────────────────────────
    private var peer: CallPeer? = null
    /** The call currently on screen. */
    private var activeId: String? = null
    /** callId → when we last dismissed it (the 12s re-ring cooldown). */
    private val endedAt = HashMap<String, Long>()
    private var recEnabled = true
    private var recording: CallRecording? = null
    private var recCallId: String? = null
    private var timerJob: Job? = null
    private var resetJob: Job? = null
    private var started = false

    private val phase: CallPhase get() = _state.value.phase
    private fun update(f: (CallUiState) -> CallUiState) { _state.value = f(_state.value) }

    init {
        (ringer as? CallAlert)?.onDecline = { id -> handleAction("decline", id) }
    }

    /** Begin listening for incoming_call / outbound_answer / call_ended and the poll fallback. */
    fun start() {
        if (started) return
        started = true
        // A ringing notification left behind by a process that died mid-ring.
        ringer.cancelIncoming()

        // Primary path: the live WebSocket event (instant).
        ui.launch { events.collect(::onFrame) }

        // Fallback path: poll the call log for a fresh "ringing" call, so the card
        // appears even if the WS event was missed. 2.5s only while RINGING (hang-up
        // detection needs it); 12s otherwise.
        ui.launch {
            while (isActive) {
                delay(pollDelay())
                pollOnce()
            }
        }

        // Phase side effects: ring + notify while ringing; timer + recording while
        // live; in-call audio routing + mic foreground service while a call runs.
        ui.launch {
            state.map { it.phase }.distinctUntilChanged().collect { p ->
                if (p == CallPhase.Ringing) {
                    ringer.startRinging()
                    if (!foreground.value) postIncoming()
                } else {
                    ringer.stopRinging()
                    ringer.cancelIncoming()
                }
                if (p == CallPhase.InCall) {
                    startRecording()   // begins once (guarded); remote audio is flowing by now
                    timerJob?.cancel()
                    timerJob = ui.launch { while (isActive) { delay(1_000); update { it.copy(seconds = it.seconds + 1) } } }
                } else {
                    timerJob?.cancel(); timerJob = null
                }
                if (p == CallPhase.Connecting || p == CallPhase.InCall) audio.enter(_state.value.speaker)
                else if (p == CallPhase.Idle || p == CallPhase.Ended) audio.leave()
            }
        }
        // The app went to the background while a call is still ringing: notify.
        // Back on screen, the card is the alert — drop the notification.
        ui.launch {
            foreground.collect { fg ->
                if (phase != CallPhase.Ringing) return@collect
                if (fg) ringer.cancelIncoming() else postIncoming()
            }
        }
    }

    /** The poll cadence: 2.5s while ringing, 12s otherwise. */
    internal fun pollDelay(): Long = if (phase == CallPhase.Ringing) RING_POLL_MS else IDLE_POLL_MS

    private fun postIncoming() {
        val s = _state.value
        val id = s.callId ?: return
        ringer.postIncoming(id, who(s), s.from?.takeIf { it.isNotEmpty() })
    }

    /** One WebSocket frame (only the three call types matter here). */
    internal fun onFrame(evt: JsonObject) {
        when (evt.str("type")) {
            "incoming_call" -> {
                logD("WS event: $evt")
                val id = evt.str("call_id") ?: return
                startRinging(id, evt.str("from") ?: "", evt.str("name"))
            }
            "outbound_answer" -> if (evt.str("call_id") == activeId && activeId != null) {
                // The customer accepted OUR call — apply their SDP answer to connect.
                logD("outbound answered")
                val sdp = evt.str("sdp") ?: return
                val p = peer ?: return
                ui.launch { runCatching { p.setRemote(SdpType.Answer, sdp) } }
            }
            "call_ended" -> {
                logD("WS event: $evt")
                val cur = _state.value
                if (cur.callId != null && cur.callId == evt.str("call_id") && cur.phase != CallPhase.Ended) finish()
            }
        }
    }

    /** One pass of the poll fallback. */
    internal suspend fun pollOnce() {
        if (!signedInFn()) return
        val calls = try { api.list() } catch (e: CancellationException) { throw e } catch (e: Exception) { return }
        val t = now()
        if (phase == CallPhase.Ringing) {
            // The caller hung up (row no longer "ringing") — tear the card down.
            val cur = calls.find { it.callId == activeId }
            if (cur != null && cur.status != "ringing") {
                cleanup(); activeId = null
                update { CallUiState() }
            }
            return
        }
        if (phase != CallPhase.Idle) return
        val ringing = calls.find { c ->
            c.status == "ringing" && Fmt.millis(c.startedAt)?.let { t - it < 90_000 } == true
        }
        if (ringing != null) {
            logD("poll fallback caught ringing call: ${ringing.callId}")
            startRinging(ringing.callId, ringing.waId ?: "", ringing.name)
        }
    }

    private fun who(s: CallUiState) =
        s.name?.takeIf { it.isNotBlank() } ?: s.from?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Unknown"

    /** A notification action (answer/decline/show) routed through MainActivity. */
    fun handleIntent(intent: Intent) {
        val action = intent.getStringExtra(Notifier.EXTRA_CALL_ACTION) ?: return
        handleAction(action, intent.getStringExtra(Notifier.EXTRA_CALL_ID))
    }

    /** "answer" | "decline" | "show" from the incoming-call notification. */
    internal fun handleAction(action: String, id: String?) {
        val s = _state.value
        val matches = id == null || id == s.callId
        when (action) {
            "answer" -> when {
                matches && s.phase == CallPhase.Ringing -> { ringer.cancelIncoming(); answer() }
                // The process was restarted since the notification went up: find
                // the call again, then answer it if it's still ringing.
                s.phase == CallPhase.Idle && id != null -> ui.launch {
                    ringer.cancelIncoming()
                    pollOnce()
                    if (_state.value.callId == id && phase == CallPhase.Ringing) answer()
                }
            }
            "decline" -> when {
                matches && s.phase == CallPhase.Ringing -> hangup()
                // A call this process no longer tracks: still tell the server.
                s.phase == CallPhase.Idle && id != null -> ui.launch {
                    ringer.cancelIncoming()
                    endedAt[id] = now()
                    try { api.terminate(id) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
                }
            }
            else -> Unit   // "show": the activity is up; CallStage renders the call
        }
    }

    // Start ringing for a given call (shared by the WS event + the poll fallback).
    // A short cooldown stops a still-"ringing" record from instantly re-ringing
    // after a decline / failed answer, while allowing a genuine retry after ~12s.
    private fun startRinging(callId: String, from: String, name: String?) {
        if (phase != CallPhase.Idle) return
        val ended = endedAt[callId]
        if (ended != null && now() - ended < RERING_COOLDOWN_MS) return
        activeId = callId
        update { it.copy(callId = callId, from = from, name = name, phase = CallPhase.Ringing) }
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
        recording = try { media.startRecording(_state.value.muted) } catch (e: Exception) {
            logW("recording unavailable", e); null
        } ?: return
        recCallId = activeId ?: _state.value.callId
    }

    /** Stop + upload. Called at the top of cleanup() so it flushes on EVERY end path. */
    private fun stopRecording() {
        val r = recording ?: return
        val callId = recCallId
        recording = null
        recCallId = null
        bg.launch {
            val file = try { r.stop() } catch (e: Exception) { null } ?: return@launch
            try {
                if (callId == null || callId == "pending") return@launch
                if (file.length() < MIN_RECORDING_BYTES) return@launch   // skip near-silent / empty recordings
                api.uploadRecording(callId, UploadFile(file.readBytes(), "$callId.m4a", "audio/mp4"))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logW("recording upload failed", e)
            } finally { file.delete() }
        }
    }

    // ── Teardown ─────────────────────────────────────────────────────────────
    private fun cleanup() {
        stopRecording()
        peer?.let { p -> peer = null; runCatching { p.close() } }
        micWaiter?.let { w -> micWaiter = null; _micRequest.value = false; w.complete(false) }
        ringer.stopRinging()
        ringer.cancelIncoming()
    }

    private fun finish(noteText: String? = null) {
        cleanup()
        activeId?.let { endedAt[it] = now() }
        activeId = null
        update { it.copy(phase = CallPhase.Ended, note = noteText ?: it.note) }
        resetJob?.cancel()
        resetJob = ui.launch {
            delay(if (noteText != null) 1_600 else 1_000)
            update { CallUiState() }
        }
    }

    private val live: Boolean get() = phase != CallPhase.Idle && phase != CallPhase.Ended

    fun hangup() {
        ui.launch {
            if (!live) return@launch
            val id = _state.value.callId
            cleanup()
            if (id != null && id != "pending") {
                try { api.terminate(id) } catch (e: CancellationException) { throw e } catch (_: Exception) { /* gone */ }
            }
            finish()
        }
    }

    fun callback() {
        ui.launch {
            if (!live) return@launch
            val id = _state.value.callId
            cleanup()
            if (id != null && id != "pending") {
                try { api.callback(id) } catch (e: CancellationException) { throw e } catch (_: Exception) { /* recorded UI-side */ }
            }
            finish("Callback saved — find them under Calls")
        }
    }

    // ── Answer an inbound call ───────────────────────────────────────────────
    fun answer() {
        ui.launch {
            val s = _state.value
            val callId = s.callId ?: return@launch
            if (s.phase != CallPhase.Ringing) return@launch
            update { it.copy(error = null, phase = CallPhase.Connecting) }
            ringer.stopRinging(); ringer.cancelIncoming()
            fun stillMine() = _state.value.callId == callId && (phase == CallPhase.Connecting || phase == CallPhase.InCall)
            try {
                val (cfg, offer) = coroutineScope {
                    val c = async { api.iceConfig() }
                    val o = async { api.offer(callId) }
                    c.await() to o.await()
                }
                recEnabled = cfg.record != false
                if (!stillMine()) return@launch   // hung up meanwhile
                val p = newPeer(cfg)
                if (!ensureMic()) throw MicBlocked()
                if (peer !== p) return@launch
                p.addMic(!_state.value.muted)
                p.setRemote(SdpType.Offer, offer.sdp)
                val answer = p.createAnswer()
                p.setLocal(SdpType.Answer, answer)
                awaitGathering(p)
                if (peer !== p) return@launch
                api.answer(callId, p.localSdp ?: answer)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logW("answer failed", e)
                if (!stillMine()) return@launch
                update { it.copy(error = answerError(e)) }
                delay(1_800)
                if (_state.value.callId == callId && live) hangup()
            }
        }
    }

    fun toggleMute() {
        val p = peer ?: return
        if (!p.hasMic) return
        val next = !_state.value.muted
        p.setMicEnabled(!next)
        recording?.micMuted = next
        update { it.copy(muted = next) }
    }

    /** Earpiece ↔ loudspeaker (the web plays through the computer's speakers). */
    fun toggleSpeaker() {
        val next = !_state.value.speaker
        audio.setSpeaker(next)
        update { it.copy(speaker = next) }
    }

    /**
     * Business-initiated call: WE call the customer. Build an offer, ask Meta to
     * place the call; the customer's SDP answer arrives as an outbound_answer
     * frame. Needs the customer's call permission (409 otherwise).
     * Result.failure carries the user-facing message; a call the agent hung up
     * before it was placed counts as success (there is nothing to report).
     */
    suspend fun initiateCall(to: String, name: String? = null): Result<Unit> = withContext(main) {
        if (phase != CallPhase.Idle) return@withContext Result.failure(CallError("Already in a call"))
        resetJob?.cancel()
        update {
            CallUiState(phase = CallPhase.Connecting, callId = "pending", from = to.removePrefix("+"), name = name, outbound = true)
        }
        fun stillMine() = _state.value.outbound && _state.value.callId == "pending" && phase == CallPhase.Connecting
        try {
            val cfg = api.iceConfig()
            recEnabled = cfg.record != false
            if (!stillMine()) return@withContext Result.success(Unit)
            val p = newPeer(cfg)
            if (!ensureMic()) throw MicBlocked()
            if (peer !== p) return@withContext Result.success(Unit)
            p.addMic(!_state.value.muted)
            val offer = p.createOffer()
            p.setLocal(SdpType.Offer, offer)
            awaitGathering(p)
            if (peer !== p) return@withContext Result.success(Unit)
            val id = api.connect(to, p.localSdp ?: offer, name?.takeIf { it.isNotEmpty() })
            if (peer !== p) {
                // Hung up while Meta was placing it: don't leave their phone ringing.
                try { api.terminate(id) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
                return@withContext Result.success(Unit)
            }
            activeId = id
            update { if (it.callId == "pending") it.copy(callId = id) else it }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logW("outbound call failed", e)
            val friendly = outboundError(e)
            if (!stillMine()) return@withContext Result.failure(CallError(friendly))
            update { it.copy(error = friendly) }
            resetJob?.cancel()
            resetJob = ui.launch {
                delay(2_200)
                cleanup()
                update { CallUiState() }
            }
            Result.failure(CallError(friendly))
        }
    }

    /**
     * Ask the customer for permission to call them (WhatsApp's interactive
     * call_permission_request). The web's customer panel sends this
     * automatically when [initiateCall] fails for lack of permission — callers
     * check `message.contains("permission", ignoreCase = true)`.
     */
    suspend fun requestPermission(to: String): Result<Unit> =
        try { api.requestPermission(to.filter { it.isDigit() }); Result.success(Unit) }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) { Result.failure(e) }

    // ── Peer connection plumbing ─────────────────────────────────────────────
    private fun newPeer(cfg: IceConfig): CallPeer {
        var self: CallPeer? = null
        val p = media.createPeer(cfg) { ev ->
            ui.launch {
                if (self == null || peer !== self) return@launch
                when (ev) {
                    PeerEvent.Connected -> setInCall()
                    PeerEvent.Ended -> finish()
                }
            }
        }
        self = p
        peer = p
        return p
    }

    private fun setInCall() {
        if (phase == CallPhase.Connecting || phase == CallPhase.Ringing) update { it.copy(phase = CallPhase.InCall) }
    }

    /** Wait for ICE gathering to finish, capped at 2.5s (as the web does). */
    private suspend fun awaitGathering(p: CallPeer) {
        withTimeoutOrNull(GATHER_TIMEOUT_MS) { p.awaitGathering() }
    }

    private class MicBlocked : Exception("Permission denied")

    /** A failed call carrying the user-facing message. */
    class CallError(message: String) : Exception(message)

    companion object {
        private const val TAG = "CallManager"

        // android.util.Log is a stub on the plain JVM (unit tests): never let logging throw.
        private fun logD(msg: String) { runCatching { Log.d(TAG, msg) } }
        private fun logW(msg: String, e: Throwable) { runCatching { Log.w(TAG, msg, e) } }
        const val MIC_BLOCKED = "Microphone blocked — allow it and try again"
        const val NO_CALL_PERMISSION = "Customer hasn't granted call permission. Send the WhatsApp template first."
        const val RING_POLL_MS = 2_500L
        const val IDLE_POLL_MS = 12_000L
        const val RERING_COOLDOWN_MS = 12_000L
        const val GATHER_TIMEOUT_MS = 2_500L
        const val MIC_PROMPT_TIMEOUT_MS = 60_000L
        const val MIN_RECORDING_BYTES = 2_000L

        /** answer()'s catch in lib/callContext.tsx. */
        internal fun answerError(e: Throwable): String =
            if (e is MicBlocked) MIC_BLOCKED else "Couldn't connect the call"

        /** initiateCall()'s catch in lib/callContext.tsx. */
        internal fun outboundError(e: Throwable): String = when {
            e is MicBlocked -> MIC_BLOCKED
            e is ApiException && e.status == 409 -> NO_CALL_PERMISSION
            else -> "Couldn't place the call"
        }
    }
}
