package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallOffer
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.AudioRoute
import ke.co.bethanyhouse.neema.feature.calls.AudioRouteKind
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.feature.calls.CallApi
import ke.co.bethanyhouse.neema.feature.calls.CallAudio
import ke.co.bethanyhouse.neema.feature.calls.CallMedia
import ke.co.bethanyhouse.neema.feature.calls.CallPeer
import ke.co.bethanyhouse.neema.feature.calls.CallRecording
import ke.co.bethanyhouse.neema.feature.calls.CallRinger
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.SdpType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.File

/** An in-memory backend for the softphone: records every call, fails on demand. */
class FakeCallApi : CallApi {
    val log = mutableListOf<String>()
    var calls: List<Call> = emptyList()
    var listError: Exception? = null
    var ice = IceConfig(record = true)
    var iceError: Exception? = null
    var offerSdp = "v=0 caller-offer"
    var offerError: Exception? = null
    var answerError: Exception? = null
    var connectId = "wacid.out1"
    var connectError: Exception? = null
    /** When set, connect() waits for it (to hang up mid-placement). */
    var connectGate: CompletableDeferred<Unit>? = null
    var permissionError: Exception? = null
    /** Failures handed out one per call, in order (then success): terminate / callback / upload. */
    val terminateErrors = ArrayDeque<Exception>()
    val callbackErrors = ArrayDeque<Exception>()
    val uploadErrors = ArrayDeque<Exception>()
    /** When set, answer() waits for it (to reply late, or never). */
    var answerGate: CompletableDeferred<Unit>? = null
    /** When set, terminate() waits for it (a server that answers late, or never). */
    var terminateGate: CompletableDeferred<Unit>? = null
    /** When set, callback() waits for it. */
    var callbackGate: CompletableDeferred<Unit>? = null
    /** callId to (filename, mime type, bytes read from the streamed file). */
    val uploads = mutableListOf<Pair<String, Triple<String, String, Int>>>()
    var lastAnswerSdp: String? = null
    /** The last recording was handed over as a streamed file, not bytes in memory. */
    var lastUploadStreamed: Boolean? = null
    var lastConnect: Triple<String, String, String?>? = null

    override suspend fun list(): List<Call> { log += "list"; listError?.let { throw it }; return calls }
    /** GET /admin/calls/{id}: the row from [calls], else 404 (as the handler). */
    var getError: Exception? = null
    override suspend fun get(callId: String): Call {
        log += "get $callId"; getError?.let { throw it }
        return calls.find { it.callId == callId } ?: throw ApiException(404, "GET", "/admin/calls/$callId", """{"detail":"Call not found"}""")
    }
    /** What GET /calls/permission says for everyone. */
    var permissionStatus = "unknown"
    override suspend fun permission(waId: String): CallPermission { log += "permission $waId"; return CallPermission(waId, permissionStatus) }
    override suspend fun iceConfig(): IceConfig { log += "ice-config"; iceError?.let { throw it }; return ice }
    override suspend fun offer(callId: String): CallOffer {
        log += "offer $callId"; offerError?.let { throw it }
        return CallOffer(callId, offerSdp, "254712345678")
    }
    override suspend fun answer(callId: String, sdp: String) {
        log += "answer $callId"; lastAnswerSdp = sdp; answerGate?.await(); answerError?.let { throw it }
    }
    override suspend fun terminate(callId: String) { log += "terminate $callId"; terminateGate?.await(); terminateErrors.removeFirstOrNull()?.let { throw it } }
    override suspend fun callback(callId: String) { log += "callback $callId"; callbackGate?.await(); callbackErrors.removeFirstOrNull()?.let { throw it } }
    override suspend fun connect(to: String, sdp: String, name: String?): String {
        log += "connect $to"; lastConnect = Triple(to, sdp, name)
        connectGate?.await()
        connectError?.let { throw it }
        return connectId
    }
    override suspend fun requestPermission(to: String): CallPermission? {
        log += "request-permission $to"; permissionError?.let { throw it }; return CallPermission(to, "requested")
    }
    override suspend fun uploadRecording(callId: String, file: UploadFile) {
        log += "recording $callId"; uploadErrors.removeFirstOrNull()?.let { throw it }; lastUploadStreamed = file.bytes == null; uploads += callId to Triple(file.filename, file.mimeType, file.length.toInt())
    }
}

/** A peer connection that does what it's told and remembers it. */
class FakePeer(val onEvent: (PeerEvent) -> Unit) : CallPeer {
    val ops = mutableListOf<String>()
    var micEnabled: Boolean? = null
    var closed = false
    val gathering = CompletableDeferred<Unit>()
    var failSetRemote: Exception? = null
    override var hasMic = false
    override fun addMic(enabled: Boolean) { hasMic = true; micEnabled = enabled; ops += "addMic($enabled)" }
    override fun setMicEnabled(enabled: Boolean) { micEnabled = enabled }
    override suspend fun createOffer(): String { ops += "createOffer"; return "v=0 our-offer" }
    override suspend fun createAnswer(): String { ops += "createAnswer"; return "v=0 our-answer" }
    override suspend fun setLocal(type: SdpType, sdp: String) { ops += "setLocal($type,$sdp)" }
    override suspend fun setRemote(type: SdpType, sdp: String) { failSetRemote?.let { throw it }; ops += "setRemote($type,$sdp)" }
    override suspend fun awaitGathering() = gathering.await()
    override val localSdp: String? get() = ops.lastOrNull { it.startsWith("setLocal") }?.let { "$it+candidates" }
    override fun close() { closed = true }
}

class FakeRecording(bytes: Int, var muted: Boolean) : CallRecording {
    val file: File = File.createTempFile("call", ".m4a").apply { writeBytes(ByteArray(bytes)) }
    var stopped = false
    override var micMuted: Boolean
        get() = muted
        set(v) { muted = v }
    override fun stop(): File { stopped = true; return file }
}

class FakeMedia : CallMedia {
    val peers = mutableListOf<FakePeer>()
    val peer get() = peers.last()
    var configs = mutableListOf<IceConfig>()
    var recordingBytes = 48_000
    var recordings = mutableListOf<FakeRecording>()
    /** Complete ICE gathering immediately (otherwise the 2.5s cap applies). */
    var gatherAtOnce = true
    override fun createPeer(config: IceConfig, onEvent: (PeerEvent) -> Unit): CallPeer {
        configs += config
        return FakePeer(onEvent).also { if (gatherAtOnce) it.gathering.complete(Unit); peers += it }
    }
    override fun startRecording(micMuted: Boolean): CallRecording =
        FakeRecording(recordingBytes, micMuted).also { recordings += it }
}

class FakeRinger : CallRinger {
    var ringing = false
    var ringStarts = 0
    val posted = mutableListOf<Triple<String, String, String?>>()
    var showing = false
    override fun startRinging() { ringing = true; ringStarts++ }
    override fun stopRinging() { ringing = false }
    override fun postIncoming(callId: String, who: String, from: String?) { posted += Triple(callId, who, from); showing = true }
    override fun cancelIncoming() { showing = false }
}

class FakeAudio : CallAudio {
    var inCall = false
    var enters = 0
    /** Where the call's audio is going (null outside a call and before any choice). */
    var route: AudioRoute? = null
    val speakerOn: Boolean get() = route?.kind == AudioRouteKind.Speaker
    /** The microphone foreground service is up (only ever after the mic was allowed). */
    var micService = false
    var micLives = 0
    override val routes = MutableStateFlow(listOf(AudioRoute.Earpiece, AudioRoute.Speaker))
    /** A headset is plugged in / paired. */
    fun plug(r: AudioRoute) { routes.value = routes.value + r }
    /** …and gone again. */
    fun unplug(r: AudioRoute) { routes.value = routes.value - r }
    override fun enter(route: AudioRoute) { if (!inCall) enters++; inCall = true; this.route = route }
    override fun micLive() { micLives++; micService = true }
    override fun leave() { inCall = false; route = null; micService = false }
    override fun select(route: AudioRoute) { this.route = route }
}
