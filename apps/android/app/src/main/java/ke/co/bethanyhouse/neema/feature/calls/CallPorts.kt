package ke.co.bethanyhouse.neema.feature.calls

import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallOffer
import ke.co.bethanyhouse.neema.core.model.IceConfig
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
    suspend fun iceConfig(): IceConfig
    suspend fun offer(callId: String): CallOffer
    suspend fun answer(callId: String, sdp: String)
    suspend fun terminate(callId: String)
    suspend fun callback(callId: String)
    /** Returns the new call's id. */
    suspend fun connect(to: String, sdp: String, name: String?): String
    suspend fun requestPermission(to: String)
    /** POST /admin/calls/{id}/recording — pass [UploadFile.of] a File so it streams from disk. */
    suspend fun uploadRecording(callId: String, file: UploadFile)
}

/** [CallApi] over the real HTTP client. */
class NeemaCallApi(private val api: NeemaApi) : CallApi {
    override suspend fun list() = api.calls.list()
    override suspend fun iceConfig() = api.calls.iceConfig()
    override suspend fun offer(callId: String) = api.calls.offer(callId)
    override suspend fun answer(callId: String, sdp: String) { api.calls.answer(callId, sdp) }
    override suspend fun terminate(callId: String) { api.calls.terminate(callId) }
    override suspend fun callback(callId: String) { api.calls.callback(callId) }
    override suspend fun connect(to: String, sdp: String, name: String?) = api.calls.connect(to, sdp, name).callId
    override suspend fun requestPermission(to: String) { api.calls.requestPermission(to) }
    override suspend fun uploadRecording(callId: String, file: UploadFile) { api.calls.uploadRecording(callId, file) }
}

/** What a peer connection reports back (RTCPeerConnection's state-change handlers). */
enum class PeerEvent {
    /** connectionState "connected", or iceConnectionState "connected" / "completed". */
    Connected,
    /** connectionState "failed" / "disconnected" / "closed". */
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
}

/** The ringtone, vibration and the incoming-call notification. */
interface CallRinger {
    fun startRinging()
    fun stopRinging()
    fun postIncoming(callId: String, who: String, from: String?)
    fun cancelIncoming()
}

/** In-call audio routing (communication mode, focus, earpiece/speaker) and the mic foreground service. */
interface CallAudio {
    /** A call is connecting: communication mode, audio focus, the chosen route. */
    fun enter(speaker: Boolean)
    /**
     * The microphone is live on the call (the agent allowed it): keep capturing
     * in the background (the microphone-type foreground service). Never called
     * without the permission — Android 14+ refuses that service type then.
     */
    fun micLive()
    fun leave()
    fun setSpeaker(on: Boolean)
}
