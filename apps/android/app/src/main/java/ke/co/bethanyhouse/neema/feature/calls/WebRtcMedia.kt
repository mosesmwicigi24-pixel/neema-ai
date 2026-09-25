package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.notify.LiveService
import kotlinx.coroutines.CompletableDeferred
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
            .setSamplesReadyCallback { s -> recorder?.onMicSamples(s) }
            .setPlaybackSamplesReadyCallback { s -> recorder?.onRemoteSamples(s) }
            .createAudioDeviceModule()
        PeerConnectionFactory.builder().setAudioDeviceModule(adm).createPeerConnectionFactory()
    }

    override fun createPeer(config: IceConfig, onEvent: (PeerEvent) -> Unit): CallPeer = Peer(config, onEvent)

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

        init {
            Log.d(TAG, "ICE servers: ${cfg.iceServers}")
            val rtc = PeerConnection.RTCConfiguration(iceServers(cfg)).apply {
                sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            }
            val observer = object : PeerConnection.Observer {
                override fun onConnectionChange(newState: PeerConnection.PeerConnectionState) {
                    Log.d(TAG, "connectionState: $newState")
                    when (newState) {
                        PeerConnection.PeerConnectionState.CONNECTED -> onEvent(PeerEvent.Connected)
                        PeerConnection.PeerConnectionState.FAILED,
                        PeerConnection.PeerConnectionState.DISCONNECTED,
                        PeerConnection.PeerConnectionState.CLOSED -> onEvent(PeerEvent.Ended)
                        else -> Unit
                    }
                }
                override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) {
                    Log.d(TAG, "iceConnectionState: $newState")
                    if (newState == PeerConnection.IceConnectionState.CONNECTED ||
                        newState == PeerConnection.IceConnectionState.COMPLETED
                    ) onEvent(PeerEvent.Connected)
                }
                override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) {
                    if (newState == PeerConnection.IceGatheringState.COMPLETE) gathered.complete(Unit)
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
            pc = factory.createPeerConnection(rtc, observer) ?: error("Couldn't create the peer connection")
        }

        override val hasMic: Boolean get() = track != null

        override fun addMic(enabled: Boolean) {
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
        }

        override fun setMicEnabled(enabled: Boolean) { track?.setEnabled(enabled) }

        override suspend fun createOffer(): String = create(offer = true)
        override suspend fun createAnswer(): String = create(offer = false)

        private suspend fun create(offer: Boolean): String = suspendCancellableCoroutine { cont ->
            val obs = object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription) { if (cont.isActive) cont.resume(sdp.description) }
                override fun onCreateFailure(error: String?) { if (cont.isActive) cont.resumeWithException(IllegalStateException(error)) }
                override fun onSetSuccess() {}
                override fun onSetFailure(error: String?) {}
            }
            val c = MediaConstraints().apply {
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
            }
            if (offer) pc.createOffer(obs, c) else pc.createAnswer(obs, c)
        }

        override suspend fun setLocal(type: SdpType, sdp: String) = setDesc(type, sdp, local = true)
        override suspend fun setRemote(type: SdpType, sdp: String) = setDesc(type, sdp, local = false)

        private suspend fun setDesc(type: SdpType, sdp: String, local: Boolean): Unit = suspendCancellableCoroutine { cont ->
            val obs = object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription?) {}
                override fun onCreateFailure(error: String?) {}
                override fun onSetSuccess() { if (cont.isActive) cont.resume(Unit) }
                override fun onSetFailure(error: String?) { if (cont.isActive) cont.resumeWithException(IllegalStateException(error)) }
            }
            val desc = SessionDescription(if (type == SdpType.Offer) SessionDescription.Type.OFFER else SessionDescription.Type.ANSWER, sdp)
            if (local) pc.setLocalDescription(obs, desc) else pc.setRemoteDescription(obs, desc)
        }

        override suspend fun awaitGathering() = gathered.await()

        override val localSdp: String? get() = runCatching { pc.localDescription?.description }.getOrNull()

        /** Torn down off the main thread so close() never runs on the thread that delivers events. */
        override fun close() {
            gathered.complete(Unit)
            val t = track; val s = source
            track = null; source = null
            Thread({
                runCatching { pc.close() }
                runCatching { pc.dispose() }
                runCatching { t?.dispose() }
                runCatching { s?.dispose() }
            }, "neema-call-close").start()
        }
    }

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
}

/**
 * Communication-mode audio with focus, earpiece ↔ loudspeaker, and the
 * microphone foreground service that keeps the call alive in the background.
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

    override fun enter(speaker: Boolean) {
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
        if (speaker) setSpeaker(true)
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
        setSpeaker(false)
        runCatching { focus?.let { audio.abandonAudioFocusRequest(it) } }
        focus = null
        runCatching { audio.mode = prevMode }
        if (keepLive()) LiveService.start(context) else LiveService.stop(context)
    }

    override fun setSpeaker(on: Boolean) {
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
}
