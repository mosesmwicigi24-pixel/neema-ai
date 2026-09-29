package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.notify.LiveService
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
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
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

private const val TAG = "CallManager"

/**
 * WebRTC calls us back on its own threads (signalling, audio, network). A
 * throw there has no coroutine or UI to land in: Android kills the process.
 * Every callback body runs through this — a failure is logged and kept as a
 * crash report, and the call carries on (or ends through its own events).
 */
internal inline fun rtcGuard(where: String, block: () -> Unit) {
    try { block() } catch (t: Throwable) {
        runCatching { Log.w(TAG, "WebRTC callback failed: $where", t) }
        runCatching { ke.co.bethanyhouse.neema.core.crash.CrashVault.recordNonFatal(t, "webrtc-$where") }
    }
}

/** [CallMedia] over the WebRTC SDK: one factory per process, whose audio module feeds the recorder. */
internal class WebRtcMedia(private val context: Context) : CallMedia {
    @Volatile private var recorder: CallRecorder? = null

    private val factory: PeerConnectionFactory by lazy {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions(),
        )
        val adm = JavaAudioDeviceModule.builder(context.applicationContext)
            .setUseHardwareAcousticEchoCanceler(true)
            .setUseHardwareNoiseSuppressor(true)
            // The recorder is fed on WebRTC's audio threads: a failing recorder must never take the call (or the app) down.
            .setSamplesReadyCallback { s -> rtcGuard("mic-samples") { recorder?.onMicSamples(s) } }
            .setPlaybackSamplesReadyCallback { s -> rtcGuard("remote-samples") { recorder?.onRemoteSamples(s) } }
            // A microphone or speaker the device refuses (in use, a vendor quirk) is logged, not thrown.
            .setAudioRecordErrorCallback(object : JavaAudioDeviceModule.AudioRecordErrorCallback {
                override fun onWebRtcAudioRecordInitError(msg: String?) { Log.w(TAG, "mic init: $msg"); CallAudioTrouble.mic() }
                override fun onWebRtcAudioRecordStartError(code: JavaAudioDeviceModule.AudioRecordStartErrorCode?, msg: String?) { Log.w(TAG, "mic start $code: $msg"); CallAudioTrouble.mic() }
                override fun onWebRtcAudioRecordError(msg: String?) { Log.w(TAG, "mic: $msg"); CallAudioTrouble.mic() }
            })
            .setAudioTrackErrorCallback(object : JavaAudioDeviceModule.AudioTrackErrorCallback {
                override fun onWebRtcAudioTrackInitError(msg: String?) { Log.w(TAG, "speaker init: $msg"); CallAudioTrouble.speaker() }
                override fun onWebRtcAudioTrackStartError(code: JavaAudioDeviceModule.AudioTrackStartErrorCode?, msg: String?) { Log.w(TAG, "speaker start $code: $msg"); CallAudioTrouble.speaker() }
                override fun onWebRtcAudioTrackError(msg: String?) { Log.w(TAG, "speaker: $msg"); CallAudioTrouble.speaker() }
            })
            .createAudioDeviceModule()
        PeerConnectionFactory.builder().setAudioDeviceModule(adm).createPeerConnectionFactory()
    }

    /**
     * A device whose ABI the WebRTC library doesn't ship fails to load it with
     * an Error (UnsatisfiedLinkError), which the call's catch-Exception would
     * let through and crash the app: turn it into a failed call instead.
     */
    override fun createPeer(config: IceConfig, onEvent: (PeerEvent) -> Unit): CallPeer =
        try { Peer(config, onEvent) } catch (e: LinkageError) { throw IllegalStateException("WebRTC unavailable", e) }

    override fun sweepLeftovers() {
        if (recorder != null) return
        val n = CallRecorder.sweepLeftovers(context.cacheDir)
        if (n > 0) Log.d(TAG, "swept $n leftover recording files")
    }

    override fun startRecording(micMuted: Boolean): CallRecording? {
        val r = CallRecorder(context.cacheDir)
        r.micMuted = micMuted
        r.start()
        recorder = r
        Log.d(TAG, "recording started")
        return object : CallRecording {
            override var micMuted: Boolean
                get() = r.micMuted
                set(v) { r.micMuted = v }
            override fun stop(): File? {
                if (recorder === r) recorder = null
                return r.stop()
            }
        }
    }

    private inner class Peer(cfg: IceConfig, onEvent: (PeerEvent) -> Unit) : CallPeer {
        private val gathered = CompletableDeferred<Unit>()
        private var source: AudioSource? = null
        private var track: AudioTrack? = null
        private val pc: PeerConnection

        /**
         * PeerConnection.dispose() frees the native object but leaves the Java one
         * pointing at it: any later call on it (an answer applied a beat after the
         * call ended, an offer finishing after a hang-up) reads freed memory and
         * the process dies with a native crash no catch can stop. Every use goes
         * through [live]: once [closed] it refuses before touching native code,
         * and the teardown waits for a use already under way.
         */
        private val lock = Any()
        @Volatile private var closed = false
        /** SDP steps waiting on WebRTC: a closed peer may never answer them, so close() fails them. */
        private val waiting = java.util.Collections.newSetFromMap(java.util.concurrent.ConcurrentHashMap<kotlinx.coroutines.CancellableContinuation<*>, Boolean>())

        private fun <T> track(cont: kotlinx.coroutines.CancellableContinuation<T>) {
            waiting += cont
            cont.invokeOnCancellation { waiting -= cont }
        }

        private inline fun <T> live(what: String, block: () -> T): T {
            if (closed) throw IllegalStateException("call already ended ($what)")
            synchronized(lock) {
                if (closed) throw IllegalStateException("call already ended ($what)")
                return block()
            }
        }

        init {
            Log.d(TAG, "ICE servers: ${cfg.iceServers}")
            val rtc = PeerConnection.RTCConfiguration(iceServers(cfg)).apply {
                sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            }
            val observer = object : PeerConnection.Observer {
                override fun onConnectionChange(newState: PeerConnection.PeerConnectionState) = rtcGuard("connection") {
                    Log.d(TAG, "connectionState: $newState")
                    when (newState) {
                        PeerConnection.PeerConnectionState.CONNECTED -> onEvent(PeerEvent.Connected)
                        // A blip, not the end: CallManager gives ICE a grace period to recover.
                        PeerConnection.PeerConnectionState.DISCONNECTED -> onEvent(PeerEvent.Interrupted)
                        PeerConnection.PeerConnectionState.FAILED,
                        PeerConnection.PeerConnectionState.CLOSED -> onEvent(PeerEvent.Ended)
                        else -> Unit
                    }
                }
                override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) = rtcGuard("ice") {
                    Log.d(TAG, "iceConnectionState: $newState")
                    if (newState == PeerConnection.IceConnectionState.CONNECTED ||
                        newState == PeerConnection.IceConnectionState.COMPLETED
                    ) onEvent(PeerEvent.Connected)
                }
                override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) = rtcGuard("gathering") {
                    if (newState == PeerConnection.IceGatheringState.COMPLETE) gathered.complete(Unit)
                }
                override fun onIceCandidate(candidate: IceCandidate) = rtcGuard("candidate") {
                    if (candidate.sdp?.contains("typ relay") == true) Log.d(TAG, "got TURN relay candidate ✓")
                }
                override fun onIceCandidateError(event: IceCandidateErrorEvent) = rtcGuard("candidate-error") {
                    Log.w(TAG, "ICE candidate error: ${event.errorText} ${event.url}")
                }
                override fun onTrack(transceiver: RtpTransceiver) = rtcGuard("track") {
                    // Remote audio plays through the audio device module on its own.
                    // (A track already disposed — the call ended meanwhile — throws: guarded.)
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
            pc = factory.createPeerConnection(rtc, observer) ?: error("Couldn't create the peer connection")
        }

        override val hasMic: Boolean get() = track != null

        override fun addMic(enabled: Boolean) = live("addMic") {
            val constraints = MediaConstraints().apply {
                mandatory.add(MediaConstraints.KeyValuePair("googEchoCancellation", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("googNoiseSuppression", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("googAutoGainControl", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("googHighpassFilter", "true"))
            }
            val src = factory.createAudioSource(constraints)
            val t = factory.createAudioTrack("neema-mic", src)
            t.setEnabled(enabled)
            source = src
            track = t
            pc.addTrack(t, listOf("neema"))
            Unit
        }

        override fun setMicEnabled(enabled: Boolean) {
            runCatching { live("mic") { track?.setEnabled(enabled) } }
        }

        override suspend fun createOffer(): String = create(offer = true)
        override suspend fun createAnswer(): String = create(offer = false)

        private suspend fun create(offer: Boolean): String = suspendCancellableCoroutine { cont ->
            track(cont)
            val obs = object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription) = rtcGuard("sdp-create") { if (cont.isActive) cont.resume(sdp.description) }
                override fun onCreateFailure(error: String?) = rtcGuard("sdp-create-failed") { if (cont.isActive) cont.resumeWithException(IllegalStateException(error)) }
                override fun onSetSuccess() {}
                override fun onSetFailure(error: String?) {}
            }
            val c = MediaConstraints().apply {
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
            }
            try { live("create") { if (offer) pc.createOffer(obs, c) else pc.createAnswer(obs, c) } }
            catch (e: IllegalStateException) { if (cont.isActive) cont.resumeWithException(e) }
        }

        override suspend fun setLocal(type: SdpType, sdp: String) = setDesc(type, sdp, local = true)
        override suspend fun setRemote(type: SdpType, sdp: String) = setDesc(type, sdp, local = false)

        private suspend fun setDesc(type: SdpType, sdp: String, local: Boolean): Unit = suspendCancellableCoroutine { cont ->
            track(cont)
            val obs = object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription?) {}
                override fun onCreateFailure(error: String?) {}
                override fun onSetSuccess() = rtcGuard("sdp-set") { if (cont.isActive) cont.resume(Unit) }
                override fun onSetFailure(error: String?) = rtcGuard("sdp-set-failed") { if (cont.isActive) cont.resumeWithException(IllegalStateException(error)) }
            }
            val desc = SessionDescription(if (type == SdpType.Offer) SessionDescription.Type.OFFER else SessionDescription.Type.ANSWER, sdp)
            try { live("setDescription") { if (local) pc.setLocalDescription(obs, desc) else pc.setRemoteDescription(obs, desc) } }
            catch (e: IllegalStateException) { if (cont.isActive) cont.resumeWithException(e) }
        }

        override suspend fun awaitGathering() = gathered.await()

        override val localSdp: String? get() = runCatching { live("localSdp") { pc.localDescription?.description } }.getOrNull()

        /** Torn down off the main thread so close() never runs on the thread that delivers events. */
        override fun close() {
            gathered.complete(Unit)
            if (closed) return   // once: a second dispose frees freed memory
            closed = true
            // Whoever waits on an offer / answer hears the call ended, instead of hanging.
            waiting.toList().forEach { c -> runCatching { c.resumeWith(Result.failure(IllegalStateException("call ended"))) } }
            waiting.clear()
            val t = track; val s = source
            track = null; source = null
            Thread({
                // Under the lock: a setRemote / createOffer already inside native code finishes first.
                synchronized(lock) {
                    runCatching { pc.close() }
                    runCatching { pc.dispose() }
                    runCatching { t?.dispose() }
                    runCatching { s?.dispose() }
                }
            }, "neema-call-close").start()
        }
    }

    private fun iceServers(cfg: IceConfig): List<PeerConnection.IceServer> = iceSpecs(cfg).map { s ->
        PeerConnection.IceServer.builder(s.urls).setUsername(s.username).setPassword(s.credential).createIceServer()
    }
}

/** One RTCIceServer, flattened for the WebRTC SDK's builder. */
internal data class IceSpec(val urls: List<String>, val username: String, val credential: String)

/**
 * GET /admin/calls/ice-config's `ice_servers` (services/wa_calling.py
 * ice_servers()) as the SDK wants them: `urls` is a single string for our
 * coturn and the STUN, a LIST for the openrelay fallback; the STUN entry has no
 * username/credential. Entries without a usable URL are dropped.
 */
internal fun iceSpecs(cfg: IceConfig): List<IceSpec> = cfg.iceServers.mapNotNull { s ->
    val urls = when (val u = s.urls) {
        is JsonArray -> u.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        is JsonPrimitive -> listOfNotNull(u.contentOrNull)
        else -> emptyList()
    }.filter { it.isNotBlank() }
    if (urls.isEmpty()) null else IceSpec(urls, s.username ?: "", s.credential ?: "")
}

/**
 * Communication-mode audio with focus, the output route (earpiece, speaker,
 * wired headset, Bluetooth), and the microphone foreground service that keeps
 * the call alive in the background.
 *
 * Routes: API 31+ asks the system for its communication devices
 * (`availableCommunicationDevices` / `setCommunicationDevice`, following
 * `OnCommunicationDeviceChangedListener`); older phones get the classic
 * speakerphone / Bluetooth SCO switches, best effort. Plug-ins and unplugs
 * reach [routes] through an AudioDeviceCallback; which route the call takes
 * is [CallManager]'s rule.
 */
internal class AndroidCallAudio(
    private val context: Context,
    /** Whether the always-on live service should come back after the call. */
    private val keepLive: () -> Boolean,
) : CallAudio {
    private val audio = context.getSystemService(AudioManager::class.java)
    private var inCall = false
    /** The live service runs with the microphone type for this call. */
    private var micService = false
    private var prevMode = AudioManager.MODE_NORMAL
    private var focus: AudioFocusRequest? = null
    private var scoOn = false

    private val _routes = MutableStateFlow(readRoutes())
    override val routes: StateFlow<List<AudioRoute>> = _routes.asStateFlow()

    private val deviceCallback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>?) { refresh() }
        override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>?) { refresh() }
    }
    private var commListener: Any? = null

    init {
        // A null handler: callbacks arrive on the main looper.
        runCatching { audio.registerAudioDeviceCallback(deviceCallback, null) }
    }

    private fun refresh() { _routes.value = readRoutes() }

    /** Earpiece and speaker first (when the device has them), then the headsets. */
    private fun readRoutes(): List<AudioRoute> = runCatching {
        val out = ArrayList<AudioRoute>()
        val devices: List<AudioDeviceInfo> = if (Build.VERSION.SDK_INT >= 31) audio.availableCommunicationDevices
            else audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).toList()
        val hasEarpiece = devices.any { it.type == AudioDeviceInfo.TYPE_BUILTIN_EARPIECE } ||
            (Build.VERSION.SDK_INT < 31 && context.packageManager.hasSystemFeature(PackageManager.FEATURE_TELEPHONY))
        if (hasEarpiece) out += AudioRoute.Earpiece
        out += AudioRoute.Speaker
        if (devices.any { it.type in WIRED }) out += AudioRoute(AudioRouteKind.Wired)
        devices.firstOrNull { it.type in BLUETOOTH }?.let { d ->
            out += AudioRoute(AudioRouteKind.Bluetooth, d.productName?.toString()?.takeIf { it.isNotBlank() })
        }
        out.toList()
    }.getOrDefault(listOf(AudioRoute.Earpiece, AudioRoute.Speaker))

    override fun enter(route: AudioRoute) {
        if (inCall) return
        inCall = true
        prevMode = audio.mode
        runCatching {
            audio.mode = AudioManager.MODE_IN_COMMUNICATION
            val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                ).build()
            audio.requestAudioFocus(req)
            focus = req
        }
        if (Build.VERSION.SDK_INT >= 31) runCatching {
            val l = AudioManager.OnCommunicationDeviceChangedListener { refresh() }
            audio.addOnCommunicationDeviceChangedListener(ContextCompat.getMainExecutor(context), l)
            commListener = l
        }
        refresh()
        apply(route)
        // The microphone-type service waits for micLive(): on Android 14+
        // starting it before RECORD_AUDIO is granted throws, and the live
        // service would stop with it.
    }

    override fun micLive() {
        // Not tied to inCall: enter() runs from the phase collector and may land a beat later.
        if (micService) return
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        if (!granted) return
        micService = true
        // Keep capturing audio while the app is in the background.
        LiveService.startForCall(context)
    }

    override fun leave() {
        if (!inCall && !micService) return
        inCall = false
        micService = false
        if (Build.VERSION.SDK_INT >= 31) runCatching {
            (commListener as? AudioManager.OnCommunicationDeviceChangedListener)?.let { audio.removeOnCommunicationDeviceChangedListener(it) }
        }
        commListener = null
        runCatching {
            if (Build.VERSION.SDK_INT >= 31) audio.clearCommunicationDevice()
            else {
                @Suppress("DEPRECATION")
                audio.isSpeakerphoneOn = false
                if (scoOn) { @Suppress("DEPRECATION") audio.stopBluetoothSco(); @Suppress("DEPRECATION") audio.isBluetoothScoOn = false }
            }
        }
        scoOn = false
        runCatching { focus?.let { audio.abandonAudioFocusRequest(it) } }
        focus = null
        runCatching { audio.mode = prevMode }
        if (keepLive()) LiveService.start(context) else LiveService.stop(context)
    }

    override fun select(route: AudioRoute) {
        // Outside a call the system route is never touched: enter() is handed the route to start on.
        if (inCall) apply(route)
    }

    private fun apply(route: AudioRoute) {
        runCatching {
            if (Build.VERSION.SDK_INT >= 31) {
                val types = when (route.kind) {
                    AudioRouteKind.Earpiece -> setOf(AudioDeviceInfo.TYPE_BUILTIN_EARPIECE)
                    AudioRouteKind.Speaker -> setOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER)
                    AudioRouteKind.Wired -> WIRED
                    AudioRouteKind.Bluetooth -> BLUETOOTH
                }
                val devices = audio.availableCommunicationDevices.filter { it.type in types }
                val d = devices.firstOrNull { route.name == null || it.productName?.toString() == route.name } ?: devices.firstOrNull()
                if (d != null) audio.setCommunicationDevice(d) else audio.clearCommunicationDevice()
            } else {
                @Suppress("DEPRECATION")
                when (route.kind) {
                    AudioRouteKind.Speaker -> {
                        if (scoOn) { audio.stopBluetoothSco(); audio.isBluetoothScoOn = false; scoOn = false }
                        audio.isSpeakerphoneOn = true
                    }
                    AudioRouteKind.Bluetooth -> {
                        audio.isSpeakerphoneOn = false
                        audio.startBluetoothSco(); audio.isBluetoothScoOn = true; scoOn = true
                    }
                    // A plugged-in headset takes the call path by itself once the speaker and SCO are off.
                    AudioRouteKind.Earpiece, AudioRouteKind.Wired -> {
                        if (scoOn) { audio.stopBluetoothSco(); audio.isBluetoothScoOn = false; scoOn = false }
                        audio.isSpeakerphoneOn = false
                    }
                }
            }
        }
    }

    private companion object {
        val WIRED = setOf(AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_USB_HEADSET)
        val BLUETOOTH: Set<Int> = buildSet {
            add(AudioDeviceInfo.TYPE_BLUETOOTH_SCO)
            if (Build.VERSION.SDK_INT >= 31) add(AudioDeviceInfo.TYPE_BLE_HEADSET)
        }
    }
}
