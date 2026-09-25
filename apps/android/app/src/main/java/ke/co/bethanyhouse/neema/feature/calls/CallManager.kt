package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.notify.LiveService
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.IceCandidateErrorEvent
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.audio.JavaAudioDeviceModule
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

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
 * The WhatsApp softphone: WebRTC peer connection, incoming-call ringing,
 * answer / decline / callback, outbound calls, mute, and call recording.
 * Port of lib/callContext.tsx. Process-wide (lives in AppContainer) so a call
 * survives navigating between screens.
 *
 * PUBLIC CONTRACT — other features call only these members.
 *
 * Threading: every state change runs on the main thread; WebRTC observer
 * callbacks (signalling thread) hop there first, and peer connections are
 * torn down on IO so a close() never runs on the thread that delivers them.
 *
 * The microphone permission is asked for by the UI ([CallStage] /
 * [rememberMicPermission]) before [answer] / [initiateCall]; without it both
 * fail with "Microphone blocked — allow it and try again", as the web does
 * when getUserMedia is refused.
 */
class CallManager(
    private val context: Context,
    private val api: NeemaApi,
    private val socket: LiveSocket,
    private val scope: CoroutineScope,
    /** True while the app is on screen (the incoming-call notification only fires when not). */
    private val foreground: StateFlow<Boolean>,
    private val signedInFn: () -> Boolean,
    private val prefs: ke.co.bethanyhouse.neema.core.util.AppPrefs,
) {
    private val _state = MutableStateFlow(CallUiState())
    val state: StateFlow<CallUiState> = _state.asStateFlow()

    /**
     * Set when the agent tapped "Answer" on the notification but the app has no
     * microphone permission yet: [CallStage] asks for it, then calls [answer].
     */
    private val _pendingAnswer = MutableStateFlow(false)
    val pendingAnswer: StateFlow<Boolean> = _pendingAnswer.asStateFlow()
    fun consumePendingAnswer() { _pendingAnswer.value = false }

    private val alert = CallAlert(context, scope)
    private val audio = context.getSystemService(AudioManager::class.java)

    // ── WebRTC ───────────────────────────────────────────────────────────────
    @Volatile private var recorder: CallRecorder? = null

    /** One factory for the process; its audio module feeds the recorder. */
    private val factory: PeerConnectionFactory by lazy {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions(),
        )
        val adm = JavaAudioDeviceModule.builder(context.applicationContext)
            .setUseHardwareAcousticEchoCanceler(true)
            .setUseHardwareNoiseSuppressor(true)
            .setSamplesReadyCallback { s -> recorder?.onMicSamples(s) }
            .setPlaybackSamplesReadyCallback { s -> recorder?.onRemoteSamples(s) }
            .createAudioDeviceModule()
        PeerConnectionFactory.builder().setAudioDeviceModule(adm).createPeerConnectionFactory()
    }

    private var pc: PeerConnection? = null
    private var audioSource: AudioSource? = null
    private var localTrack: AudioTrack? = null
    private var gathering: CompletableDeferred<Unit>? = null

    // ── Refs (the web's useRef state) ────────────────────────────────────────
    /** The call currently on screen. */
    private var activeId: String? = null
    /** callId → when we last dismissed it (the 12s re-ring cooldown). */
    private val endedAt = HashMap<String, Long>()
    private var recEnabled = true
    private var recCallId: String? = null
    private var timerJob: Job? = null
    private var resetJob: Job? = null
    private var started = false

    // Audio routing, restored after the call.
    private var inCallAudio = false
    private var prevMode = AudioManager.MODE_NORMAL
    private var focusRequest: AudioFocusRequest? = null
    private var liveForCall = false

    private val phase: CallPhase get() = _state.value.phase
    private fun update(f: (CallUiState) -> CallUiState) { _state.value = f(_state.value) }
    private fun ui(block: suspend CoroutineScope.() -> Unit): Job = scope.launch(Dispatchers.Main, block = block)

    private val signedIn: Boolean
        get() = signedInFn()

    private fun micGranted() =
        ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    /** Begin listening for incoming_call / outbound_answer / call_ended and the poll fallback. */
    fun start() {
        if (started) return
        started = true

        // Primary path: the live WebSocket event (instant).
        ui {
            socket.events.collect { evt ->
                when (evt.str("type")) {
                    "incoming_call" -> {
                        Log.d(TAG, "WS event: $evt")
                        val id = evt.str("call_id") ?: return@collect
                        startRinging(id, evt.str("from") ?: "", evt.str("name"))
                    }
                    "outbound_answer" -> if (evt.str("call_id") == activeId) {
                        // The customer accepted OUR call — apply their SDP answer to connect.
                        Log.d(TAG, "outbound answered")
                        val sdp = evt.str("sdp") ?: return@collect
                        val p = pc ?: return@collect
                        runCatching { p.setRemote(SessionDescription(SessionDescription.Type.ANSWER, sdp)) }
                    }
                    "call_ended" -> {
                        Log.d(TAG, "WS event: $evt")
                        // The web only tore down media and showed "ended" here,
                        // which left the card stuck; finish() also returns to idle
                        // and starts the re-ring cooldown.
                        val cur = _state.value
                        if (cur.callId != null && cur.callId == evt.str("call_id") && cur.phase != CallPhase.Ended) finish()
                    }
                }
            }
        }

        // Fallback path: poll the call log for a fresh "ringing" call, so the card
        // appears even if the WS event was missed. 2.5s only while RINGING (hang-up
        // detection needs it); 12s otherwise. Only while signed in.
        ui {
            while (isActive) {
                delay(if (phase == CallPhase.Ringing) 2_500 else 12_000)
                if (!signedIn) continue
                runCatching { api.calls.list() }.onSuccess { calls ->
                    val now = System.currentTimeMillis()
                    if (phase == CallPhase.Ringing) {
                        // The caller hung up (row no longer "ringing") — tear the card down.
                        val cur = calls.find { it.callId == activeId }
                        if (cur != null && cur.status != "ringing") {
                            cleanup(); activeId = null
                            update { CallUiState() }
                        }
                        return@onSuccess
                    }
                    if (phase != CallPhase.Idle) return@onSuccess
                    val ringing = calls.find { c ->
                        c.status == "ringing" && Fmt.millis(c.startedAt)?.let { now - it < 90_000 } == true
                    }
                    if (ringing != null) {
                        Log.d(TAG, "poll fallback caught ringing call: ${ringing.callId}")
                        startRinging(ringing.callId, ringing.waId ?: "", ringing.name)
                    }
                }
            }
        }

        // Phase side effects: ring + notify while ringing; timer + recording while
        // live; in-call audio routing + mic foreground service while a call runs.
        ui {
            state.map { it.phase }.distinctUntilChanged().collect { p ->
                if (p == CallPhase.Ringing) {
                    alert.startRinging()
                    if (!foreground.value) {
                        val s = _state.value
                        s.callId?.let { alert.postIncoming(it, who(s), s.from?.takeIf { f -> f.isNotEmpty() }) }
                    }
                } else {
                    alert.stopRinging()
                    alert.cancelIncoming()
                }
                if (p == CallPhase.InCall) {
                    startRecording()   // begins once (guarded); remote audio is flowing by now
                    timerJob?.cancel()
                    timerJob = ui { while (isActive) { delay(1_000); update { it.copy(seconds = it.seconds + 1) } } }
                } else {
                    timerJob?.cancel(); timerJob = null
                }
                if (p == CallPhase.Connecting || p == CallPhase.InCall) enterCallAudio()
                else if (p == CallPhase.Idle || p == CallPhase.Ended) leaveCallAudio()
            }
        }
        // The app went to the background while a call is still ringing: notify.
        ui {
            foreground.collect { fg ->
                val s = _state.value
                if (!fg && s.phase == CallPhase.Ringing) s.callId?.let { alert.postIncoming(it, who(s), s.from?.takeIf { f -> f.isNotEmpty() }) }
            }
        }
    }

    private fun who(s: CallUiState) = s.name?.takeIf { it.isNotBlank() } ?: s.from?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Unknown"

    /** A notification action (answer/decline/show) routed through MainActivity. */
    fun handleIntent(intent: Intent) {
        val action = intent.getStringExtra(Notifier.EXTRA_CALL_ACTION) ?: return
        val id = intent.getStringExtra(Notifier.EXTRA_CALL_ID)
        val s = _state.value
        val matches = id == null || id == s.callId
        when (action) {
            "answer" -> if (matches && s.phase == CallPhase.Ringing) {
                alert.cancelIncoming()
                if (micGranted()) answer() else _pendingAnswer.value = true
            }
            "decline" -> if (matches && s.phase == CallPhase.Ringing) hangup()
            else -> Unit   // "show": the activity is up; CallStage renders the call
        }
    }

    // Start ringing for a given call (shared by the WS event + the poll fallback).
    // A short cooldown stops a still-"ringing" record from instantly re-ringing
    // after a decline / failed answer, while allowing a genuine retry after ~12s.
    private fun startRinging(callId: String, from: String, name: String?) {
        if (phase != CallPhase.Idle) return
        val ended = endedAt[callId]
        if (ended != null && System.currentTimeMillis() - ended < 12_000) return
        activeId = callId
        update { it.copy(callId = callId, from = from, name = name, phase = CallPhase.Ringing) }
    }

    // ── Recording ────────────────────────────────────────────────────────────
    private fun startRecording() {
        if (recorder != null || !recEnabled) return
        if (localTrack == null) return
        runCatching {
            val r = CallRecorder(context.cacheDir)
            r.micMuted = _state.value.muted
            r.start()
            recorder = r
            recCallId = activeId ?: _state.value.callId
            Log.d(TAG, "recording started")
        }.onFailure { Log.w(TAG, "recording unavailable", it) }
    }

    /** Stop + upload. Called at the top of cleanup() so it flushes on EVERY end path. */
    private fun stopRecording() {
        val r = recorder ?: return
        val callId = recCallId
        recorder = null
        recCallId = null
        scope.launch(Dispatchers.IO) {
            val file = r.stop() ?: return@launch
            try {
                if (callId == null || callId == "pending") return@launch
                if (file.length() < 2_000) return@launch   // skip near-silent / empty recordings
                api.calls.uploadRecording(callId, UploadFile(file.readBytes(), "$callId.m4a", "audio/mp4"))
            } catch (e: Exception) {
                Log.w(TAG, "recording upload failed", e)
            } finally { file.delete() }
        }
    }

    // ── Teardown ─────────────────────────────────────────────────────────────
    private fun cleanup() {
        stopRecording()
        val p = pc; val t = localTrack; val s = audioSource
        pc = null; localTrack = null; audioSource = null
        gathering?.complete(Unit); gathering = null
        if (p != null || t != null || s != null) scope.launch(Dispatchers.IO) {
            runCatching { p?.close() }
            runCatching { p?.dispose() }
            runCatching { t?.dispose() }
            runCatching { s?.dispose() }
        }
        alert.stopRinging()
        alert.cancelIncoming()
    }

    private fun finish(noteText: String? = null) {
        cleanup()
        activeId?.let { endedAt[it] = System.currentTimeMillis() }
        activeId = null
        update { it.copy(phase = CallPhase.Ended, note = noteText ?: it.note) }
        resetJob?.cancel()
        resetJob = ui {
            delay(if (noteText != null) 1_600 else 1_000)
            update { CallUiState() }
        }
    }

    fun hangup() {
        ui {
            val id = _state.value.callId
            cleanup()
            if (id != null && id != "pending") runCatching { api.calls.terminate(id) }   // may already be gone
            finish()
        }
    }

    fun callback() {
        ui {
            val id = _state.value.callId
            cleanup()
            if (id != null && id != "pending") runCatching { api.calls.callback(id) }
            finish("Callback saved — find them under Calls")
        }
    }

    // ── Answer an inbound call ───────────────────────────────────────────────
    fun answer() {
        ui {
            val s = _state.value
            val callId = s.callId ?: return@ui
            if (s.phase != CallPhase.Ringing) return@ui
            update { it.copy(error = null, phase = CallPhase.Connecting) }
            alert.stopRinging(); alert.cancelIncoming()
            try {
                if (!micGranted()) throw MicBlocked()
                val cfgD = async { api.calls.iceConfig() }
                val offerD = async { api.calls.offer(callId) }
                val cfg = cfgD.await(); val offer = offerD.await()
                recEnabled = cfg.record != false
                if (_state.value.callId != callId || phase != CallPhase.Connecting) return@ui   // hung up meanwhile
                val p = buildPc(cfg)
                addMic(p)
                p.setRemote(SessionDescription(SessionDescription.Type.OFFER, offer.sdp))
                val answer = p.create(offer = false)
                p.setLocal(answer)
                awaitGathering()
                if (pc !== p) return@ui
                api.calls.answer(callId, p.localDescription?.description ?: answer.description)
            } catch (e: Exception) {
                Log.w(TAG, "answer failed", e)
                update { it.copy(error = if (e is MicBlocked) MIC_BLOCKED else "Couldn't connect the call") }
                delay(1_800)
                if (_state.value.callId == callId && phase != CallPhase.Ended && phase != CallPhase.Idle) hangup()
            }
        }
    }

    fun toggleMute() {
        val t = localTrack ?: return
        val next = !_state.value.muted
        t.setEnabled(!next)
        recorder?.micMuted = next
        update { it.copy(muted = next) }
    }

    /** Earpiece ↔ loudspeaker (the web plays through the computer's speakers). */
    fun toggleSpeaker() {
        val next = !_state.value.speaker
        setSpeaker(next)
        update { it.copy(speaker = next) }
    }

    /** Business-initiated call. Result.failure carries a user-facing message. */
    suspend fun initiateCall(to: String, name: String? = null): Result<Unit> = withContext(Dispatchers.Main) {
        if (phase != CallPhase.Idle) return@withContext Result.failure(CallError("Already in a call"))
        resetJob?.cancel()
        update {
            CallUiState(phase = CallPhase.Connecting, callId = "pending", from = to.removePrefix("+"), name = name, outbound = true)
        }
        try {
            if (!micGranted()) throw MicBlocked()
            val cfg = api.calls.iceConfig()
            recEnabled = cfg.record != false
            val p = buildPc(cfg)
            addMic(p)
            val offer = p.create(offer = true)
            p.setLocal(offer)
            awaitGathering()
            if (pc !== p) return@withContext Result.failure(CallError("Call cancelled"))
            val resp = api.calls.connect(to, p.localDescription?.description ?: offer.description, name?.takeIf { it.isNotEmpty() })
            activeId = resp.callId
            update { if (it.callId == "pending") it.copy(callId = resp.callId) else it }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.w(TAG, "outbound call failed", e)
            val friendly = when {
                e is MicBlocked -> MIC_BLOCKED
                e is ApiException && e.status == 409 -> "Customer hasn't granted call permission. Send the WhatsApp template first."
                else -> "Couldn't place the call"
            }
            update { it.copy(error = friendly) }
            ui {
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
        runCatching { api.calls.requestPermission(to.filter { it.isDigit() }); Unit }

    // ── Peer connection plumbing ─────────────────────────────────────────────
    private fun iceServers(cfg: IceConfig): List<PeerConnection.IceServer> = cfg.iceServers.mapNotNull { s ->
        // `urls` may be a single string or an array (RTCIceServer allows both).
        val urls = when (val u = s.urls) {
            is JsonArray -> u.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            is JsonPrimitive -> listOfNotNull(u.contentOrNull)
            else -> emptyList()
        }.filter { it.isNotBlank() }
        if (urls.isEmpty()) null
        else PeerConnection.IceServer.builder(urls)
            .setUsername(s.username ?: "")
            .setPassword(s.credential ?: "")
            .createIceServer()
    }

    private fun buildPc(cfg: IceConfig): PeerConnection {
        Log.d(TAG, "ICE servers: ${cfg.iceServers}")
        val rtc = PeerConnection.RTCConfiguration(iceServers(cfg)).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }
        val g = CompletableDeferred<Unit>()
        gathering = g
        var self: PeerConnection? = null
        val observer = object : PeerConnection.Observer {
            override fun onConnectionChange(newState: PeerConnection.PeerConnectionState) {
                Log.d(TAG, "connectionState: $newState")
                ui {
                    if (self == null || pc !== self) return@ui
                    when (newState) {
                        PeerConnection.PeerConnectionState.CONNECTED -> setInCall()
                        PeerConnection.PeerConnectionState.FAILED,
                        PeerConnection.PeerConnectionState.DISCONNECTED,
                        PeerConnection.PeerConnectionState.CLOSED -> finish()
                        else -> Unit
                    }
                }
            }
            override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) {
                Log.d(TAG, "iceConnectionState: $newState")
                if (newState == PeerConnection.IceConnectionState.CONNECTED || newState == PeerConnection.IceConnectionState.COMPLETED) {
                    ui { if (self != null && pc === self) setInCall() }
                }
            }
            override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) {
                if (newState == PeerConnection.IceGatheringState.COMPLETE) g.complete(Unit)
            }
            override fun onIceCandidate(candidate: IceCandidate) {
                if (candidate.sdp.contains("typ relay")) Log.d(TAG, "got TURN relay candidate ✓")
            }
            override fun onIceCandidateError(event: IceCandidateErrorEvent) {
                Log.w(TAG, "ICE candidate error: ${event.errorText} ${event.url}")
            }
            override fun onTrack(transceiver: RtpTransceiver) {
                // Remote audio plays through the audio device module on its own.
                transceiver.receiver.track()?.setEnabled(true)
            }
            override fun onSignalingChange(newState: PeerConnection.SignalingState) {}
            override fun onIceConnectionReceivingChange(receiving: Boolean) {}
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {}
            override fun onAddStream(stream: MediaStream) {}
            override fun onRemoveStream(stream: MediaStream) {}
            override fun onDataChannel(dc: DataChannel) {}
            override fun onRenegotiationNeeded() {}
        }
        val p = factory.createPeerConnection(rtc, observer) ?: error("Couldn't create the peer connection")
        self = p
        pc = p
        return p
    }

    /** Studio-ish mic: echo cancellation + noise suppression + auto gain. */
    private fun addMic(p: PeerConnection) {
        val constraints = MediaConstraints().apply {
            mandatory.add(MediaConstraints.KeyValuePair("googEchoCancellation", "true"))
            mandatory.add(MediaConstraints.KeyValuePair("googNoiseSuppression", "true"))
            mandatory.add(MediaConstraints.KeyValuePair("googAutoGainControl", "true"))
            mandatory.add(MediaConstraints.KeyValuePair("googHighpassFilter", "true"))
        }
        val src = factory.createAudioSource(constraints)
        val track = factory.createAudioTrack("neema-mic", src)
        track.setEnabled(!_state.value.muted)
        audioSource = src
        localTrack = track
        p.addTrack(track, listOf("neema"))
    }

    private fun setInCall() {
        if (phase == CallPhase.Connecting || phase == CallPhase.Ringing) update { it.copy(phase = CallPhase.InCall) }
    }

    /** Wait for ICE gathering to finish, capped at 2.5s (as the web does). */
    private suspend fun awaitGathering() {
        val g = gathering ?: return
        withTimeoutOrNull(2_500) { g.await() }
    }

    private suspend fun PeerConnection.create(offer: Boolean): SessionDescription =
        suspendCancellableCoroutine { cont ->
            val obs = object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription) { if (cont.isActive) cont.resume(sdp) }
                override fun onCreateFailure(error: String?) { if (cont.isActive) cont.resumeWithException(IllegalStateException(error)) }
                override fun onSetSuccess() {}
                override fun onSetFailure(error: String?) {}
            }
            val c = MediaConstraints().apply {
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
            }
            if (offer) createOffer(obs, c) else createAnswer(obs, c)
        }

    private suspend fun PeerConnection.setLocal(sdp: SessionDescription) = setDesc(sdp, local = true)
    private suspend fun PeerConnection.setRemote(sdp: SessionDescription) = setDesc(sdp, local = false)

    private suspend fun PeerConnection.setDesc(sdp: SessionDescription, local: Boolean): Unit =
        suspendCancellableCoroutine { cont ->
            val obs = object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription?) {}
                override fun onCreateFailure(error: String?) {}
                override fun onSetSuccess() { if (cont.isActive) cont.resume(Unit) }
                override fun onSetFailure(error: String?) { if (cont.isActive) cont.resumeWithException(IllegalStateException(error)) }
            }
            if (local) setLocalDescription(obs, sdp) else setRemoteDescription(obs, sdp)
        }

    // ── Audio routing ────────────────────────────────────────────────────────
    private fun enterCallAudio() {
        if (!inCallAudio) {
            inCallAudio = true
            prevMode = audio.mode
            runCatching {
                audio.mode = AudioManager.MODE_IN_COMMUNICATION
                if (Build.VERSION.SDK_INT >= 26) {
                    val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                        .setAudioAttributes(
                            AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build(),
                        ).build()
                    audio.requestAudioFocus(req)
                    focusRequest = req
                }
            }
            if (_state.value.speaker) setSpeaker(true)
        }
        if (!liveForCall) {
            // Keep capturing audio while the app is in the background.
            liveForCall = true
            LiveService.startForCall(context)
        }
    }

    private fun leaveCallAudio() {
        if (inCallAudio) {
            inCallAudio = false
            setSpeaker(false)
            runCatching { focusRequest?.let { audio.abandonAudioFocusRequest(it) } }
            focusRequest = null
            runCatching { audio.mode = prevMode }
        }
        if (liveForCall) {
            liveForCall = false
            if (prefs.backgroundLive.value && signedIn) LiveService.start(context) else LiveService.stop(context)
        }
    }

    private fun setSpeaker(on: Boolean) {
        runCatching {
            if (Build.VERSION.SDK_INT >= 31) {
                if (on) {
                    audio.availableCommunicationDevices
                        .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
                        ?.let { audio.setCommunicationDevice(it) }
                } else audio.clearCommunicationDevice()
            } else {
                @Suppress("DEPRECATION")
                audio.isSpeakerphoneOn = on
            }
        }
    }

    private class MicBlocked : Exception("Permission denied")
    /** A failed call carrying the user-facing message. */
    class CallError(message: String) : Exception(message)

    companion object {
        private const val TAG = "CallManager"
        const val MIC_BLOCKED = "Microphone blocked — allow it and try again"
    }
}
