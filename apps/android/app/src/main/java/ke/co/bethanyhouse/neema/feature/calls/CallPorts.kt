package ke.co.bethanyhouse.neema.feature.calls

import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallOffer
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.model.PermissionRequestResponse
import kotlinx.coroutines.flow.StateFlow
import java.io.File

/*
 * The seams around the softphone's logic. [CallManager] holds every rule the
 * web's lib/callContext.tsx has (phases, the re-ring cooldown, the poll
 * cadence, the WebSocket frames, the error mapping); everything that needs a
 * device — WebRTC, the speakers, the ringtone, the notification shade — sits
 * behind these small interfaces so the rules run (and are tested) on the JVM.
 */

/** The backend calls the softphone makes (callsApi in lib/api.ts, NeemaApi.calls here). */
interface CallApi {
    suspend fun list(): List<Call>
    /** GET /admin/calls/{id}: one call's row now (the re-sync after the phone was offline). */
    suspend fun get(callId: String): Call
    suspend fun iceConfig(): IceConfig
    suspend fun offer(callId: String): CallOffer
    suspend fun answer(callId: String, sdp: String)
    suspend fun terminate(callId: String)
    suspend fun callback(callId: String)
    /** Returns the new call's id. */
    suspend fun connect(to: String, sdp: String, name: String?): String
    /** GET /admin/calls/permission: has this customer allowed business calls? */
    suspend fun permission(waId: String): CallPermission
    /**
     * Sends WhatsApp's call-permission request: `{permission, route,
     * already_permitted}`. A refusal is an [ke.co.bethanyhouse.neema.core.net.ApiException]
     * carrying the server's `code` / `action` (template_required, 138009, …).
     */
    suspend fun requestPermission(to: String, name: String? = null): PermissionRequestResponse
    /** POST /admin/calls/{id}/recording — pass [UploadFile.of] a File so it streams from disk. */
    suspend fun uploadRecording(callId: String, file: UploadFile)
}

/** [CallApi] over the real HTTP client. */
class NeemaCallApi(private val api: NeemaApi) : CallApi {
    override suspend fun list() = api.calls.list()
    override suspend fun get(callId: String) = api.calls.get(callId)
    override suspend fun iceConfig() = api.calls.iceConfig()
    override suspend fun offer(callId: String) = api.calls.offer(callId)
    override suspend fun answer(callId: String, sdp: String) { api.calls.answer(callId, sdp) }
    override suspend fun terminate(callId: String) { api.calls.terminate(callId) }
    override suspend fun callback(callId: String) { api.calls.callback(callId) }
    override suspend fun connect(to: String, sdp: String, name: String?) = api.calls.connect(to, sdp, name).callId
    override suspend fun permission(waId: String) = api.calls.permission(waId)
    override suspend fun requestPermission(to: String, name: String?) = api.calls.requestPermission(to, name)
    override suspend fun uploadRecording(callId: String, file: UploadFile) { api.calls.uploadRecording(callId, file) }
}

/** What a peer connection reports back (RTCPeerConnection's state-change handlers). */
enum class PeerEvent {
    /** connectionState "connected", or iceConnectionState "connected" / "completed". */
    Connected,
    /**
     * connectionState "disconnected": the network blipped (a tunnel, a cell
     * handover, Wi-Fi to mobile data). ICE keeps checking and often recovers
     * on its own, so this is not the end of the call yet.
     */
    Interrupted,
    /** connectionState "failed" / "closed": the media path is gone for good. */
    Ended,
}

/** One RTCPeerConnection with the agent's microphone on it. */
interface CallPeer {
    /** getUserMedia + addTrack: the agent's mic (echo cancellation, noise suppression, auto gain). */
    fun addMic(enabled: Boolean)
    /** True once [addMic] has run — the web's `localStreamRef.current`. */
    val hasMic: Boolean
    fun setMicEnabled(enabled: Boolean)
    suspend fun createOffer(): String
    suspend fun createAnswer(): String
    suspend fun setLocal(type: SdpType, sdp: String)
    suspend fun setRemote(type: SdpType, sdp: String)
    /** Resolves when ICE gathering completes (the caller caps the wait at 2.5s). */
    suspend fun awaitGathering()
    /** pc.localDescription.sdp — with the gathered candidates, when there are any. */
    val localSdp: String?
    fun close()
}

enum class SdpType { Offer, Answer }

/** A started call recording (both sides mixed, as the web's Web-Audio mix). */
interface CallRecording {
    var micMuted: Boolean
    /** Stops and returns the encoded file, or null when nothing usable was captured. Blocking. */
    fun stop(): File?
}

/** Builds peer connections and recordings — WebRTC in the app, a fake in tests. */
interface CallMedia {
    /** [onEvent] may be called on any thread. */
    fun createPeer(config: IceConfig, onEvent: (PeerEvent) -> Unit): CallPeer
    /** Starts recording the live call, or returns null when it can't. */
    fun startRecording(micMuted: Boolean): CallRecording?

    /**
     * Deletes what an earlier process killed mid-call left behind (the raw
     * audio tracks of an unfinished recording: an hour of call is hundreds of
     * MB). Called once at start-up, before any call can be live.
     */
    fun sweepLeftovers() {}
}

/** The ringtone, vibration and the incoming-call notification. */
interface CallRinger {
    fun startRinging()
    fun stopRinging()
    fun postIncoming(callId: String, who: String, from: String?)
    fun cancelIncoming()
}

/** Where a call's audio plays: the phone's earpiece, its loudspeaker, a wired headset or a Bluetooth one. */
enum class AudioRouteKind { Earpiece, Speaker, Wired, Bluetooth }

/** One output a call can use ([name]: the Bluetooth device's own name, when the system gives one). */
data class AudioRoute(val kind: AudioRouteKind, val name: String? = null) {
    /** The words on the audio button and in its list. */
    val label: String get() = when (kind) {
        AudioRouteKind.Earpiece -> "Phone"
        AudioRouteKind.Speaker -> "Speaker"
        AudioRouteKind.Wired -> "Headset"
        AudioRouteKind.Bluetooth -> name?.trim()?.takeIf { it.isNotEmpty() } ?: "Bluetooth"
    }
    val isHeadset: Boolean get() = kind == AudioRouteKind.Wired || kind == AudioRouteKind.Bluetooth

    companion object {
        val Earpiece = AudioRoute(AudioRouteKind.Earpiece)
        val Speaker = AudioRoute(AudioRouteKind.Speaker)
    }
}

/**
 * In-call audio (communication mode, focus, the output route) and the mic
 * foreground service. Which route a call uses is [CallManager]'s rule; this
 * port only reports what is plugged in and applies the choice.
 */
interface CallAudio {
    /** A call is starting: communication mode, audio focus, and [route]. */
    fun enter(route: AudioRoute)
    /**
     * The microphone is live on the call (the agent allowed it): keep capturing
     * in the background (the microphone-type foreground service). Never called
     * without the permission — Android 14+ refuses that service type then.
     */
    fun micLive()
    fun leave()
    /** Plays the call through [route] (one of [routes]). */
    fun select(route: AudioRoute)
    /**
     * The outputs a call can use right now, earpiece / speaker first, then any
     * headset — updated as headsets are plugged in, paired or unplugged.
     */
    val routes: StateFlow<List<AudioRoute>>
}
