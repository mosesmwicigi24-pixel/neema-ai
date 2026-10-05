package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallChannels
import ke.co.bethanyhouse.neema.core.model.CallOffer
import ke.co.bethanyhouse.neema.core.model.CallSdpResponse
import ke.co.bethanyhouse.neema.core.model.ChannelCalling
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.model.PermissionRequestResponse
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
    /** The whole answer of GET /calls/permission (overrides [permissionStatus] when set). */
    var permission: CallPermission? = null
    /** When set, permission() waits for it (a slow Meta read). */
    var permissionGate: CompletableDeferred<Unit>? = null
    var permissionReadError: Exception? = null
    override suspend fun permission(waId: String): CallPermission {
        log += "permission $waId"; permissionGate?.await(); permissionReadError?.let { throw it }
        return permission ?: CallPermission(waId, permissionStatus)
    }
    override suspend fun iceConfig(): IceConfig { log += "ice-config"; iceError?.let { throw it }; return ice }
    /** Messenger calls (CALLING_UX.md §2.0): which call ids ring on Messenger (their offer route says offer_required). */
    val messengerCalls = mutableSetOf<String>()
    /** What Meta answers our Messenger offer with (accept / connect): the answer SDP and the renegotiation. */
    var messengerAnswer: String? = "v=0 meta-answer"
    var messengerRenegotiation: kotlinx.serialization.json.JsonElement? = null
    /** GET /calls/channels (null: Messenger off — the server's switch). */
    var channels = CallChannels()
    var channelsError: Exception? = null
    var messengerConnectId = "c_msg.out1"
    var lastMessengerConnect: Triple<String, String, String?>? = null

    override suspend fun offer(callId: String): CallOffer {
        log += "offer $callId"; offerError?.let { throw it }
        if (callId in messengerCalls) return CallOffer(callId, null, "7788990011", "messenger", offerRequired = true)
        return CallOffer(callId, offerSdp, "254712345678")
    }
    override suspend fun answer(callId: String, sdp: String): CallSdpResponse {
        log += "answer $callId"; lastAnswerSdp = sdp; answerGate?.await(); answerError?.let { throw it }
        return if (callId in messengerCalls) CallSdpResponse(callId = callId, channel = "messenger", sdp = messengerAnswer,
            sdpType = "answer", renegotiation = messengerRenegotiation)
        else CallSdpResponse(callId = callId)
    }
    /** GET /calls/channels reads (kept out of [log]: the softphone reads it at start and on every reconnect). */
    var channelsReads = 0
    override suspend fun channels(): CallChannels { channelsReads++; channelsError?.let { throw it }; return channels }
    override suspend fun connectMessenger(psid: String, sdp: String, name: String?): CallSdpResponse {
        log += "connect-messenger $psid"; lastMessengerConnect = Triple(psid, sdp, name)
        connectGate?.await()
        connectError?.let { throw it }
        return CallSdpResponse(callId = messengerConnectId, channel = "messenger", sdp = messengerAnswer, sdpType = "answer",
            renegotiation = messengerRenegotiation)
    }
    override suspend fun messengerPermission(psid: String): CallPermission {
        log += "permission messenger $psid"; permissionGate?.await(); permissionReadError?.let { throw it }
        return (permission ?: CallPermission(null, permissionStatus)).copy(waId = null, channel = "messenger", externalId = psid)
    }
    override suspend fun requestMessengerPermission(psid: String): PermissionRequestResponse {
        log += "request-permission messenger $psid"; permissionError?.let { throw it }
        return requestResponse ?: PermissionRequestResponse(
            permission = CallPermission(null, "requested", channel = "messenger", externalId = psid), route = "calling_optin",
        )
    }
    override suspend fun terminate(callId: String) { log += "terminate $callId"; terminateGate?.await(); terminateErrors.removeFirstOrNull()?.let { throw it } }
    override suspend fun callback(callId: String) { log += "callback $callId"; callbackGate?.await(); callbackErrors.removeFirstOrNull()?.let { throw it } }
    override suspend fun connect(to: String, sdp: String, name: String?): String {
        log += "connect $to"; lastConnect = Triple(to, sdp, name)
        connectGate?.await()
        connectError?.let { throw it }
        return connectId
    }
    /** What POST /calls/request-permission answers (default: sent free-form, now "requested"). */
    var requestResponse: PermissionRequestResponse? = null
    override suspend fun requestPermission(to: String, name: String?): PermissionRequestResponse {
        log += "request-permission $to"; permissionError?.let { throw it }
        return requestResponse ?: PermissionRequestResponse(permission = CallPermission(to, "requested"), route = "free_form")
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
    /**
     * Every native step asked of this peer after close(): on a phone that is a
     * PeerConnection used after dispose() — a native crash no catch can stop.
     */
    val usedAfterClose = mutableListOf<String>()
    /** When set, the SDP steps wait for it (a hang-up can land while WebRTC works). */
    var sdpGate: CompletableDeferred<Unit>? = null
    override var hasMic = false
    override fun addMic(enabled: Boolean) { if (closed) usedAfterClose += "addMic"; hasMic = true; micEnabled = enabled; ops += "addMic($enabled)" }
    override fun setMicEnabled(enabled: Boolean) { micEnabled = enabled }
    override suspend fun createOffer(): String { if (closed) usedAfterClose += "createOffer"; ops += "createOffer"; sdpGate?.await(); return "v=0 our-offer" }
    override suspend fun createAnswer(): String { if (closed) usedAfterClose += "createAnswer"; ops += "createAnswer"; sdpGate?.await(); return "v=0 our-answer" }
    override suspend fun setLocal(type: SdpType, sdp: String) { if (closed) usedAfterClose += "setLocal"; ops += "setLocal($type,$sdp)"; sdpGate?.await() }
    override suspend fun setRemote(type: SdpType, sdp: String) {
        if (closed) usedAfterClose += "setRemote"
        failSetRemote?.let { throw it }; ops += "setRemote($type,$sdp)"; sdpGate?.await()
    }
    override suspend fun awaitGathering() = gathering.await()
    override val localSdp: String? get() { if (closed) usedAfterClose += "localSdp"; return ops.lastOrNull { it.startsWith("setLocal") }?.let { "$it+candidates" } }
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
    /** Handed to each new peer: its SDP steps wait on it. */
    var sdpGate: CompletableDeferred<Unit>? = null
    /** Complete ICE gathering immediately (otherwise the 2.5s cap applies). */
    var gatherAtOnce = true
    override fun createPeer(config: IceConfig, onEvent: (PeerEvent) -> Unit): CallPeer {
        configs += config
        return FakePeer(onEvent).also { if (gatherAtOnce) it.gathering.complete(Unit); it.sdpGate = sdpGate; peers += it }
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
    /** The app each posted notification named ("WhatsApp" / "Messenger"). */
    val postedApps = mutableListOf<String>()
    override fun postIncoming(callId: String, who: String, from: String?, app: String) { posted += Triple(callId, who, from); postedApps += app; showing = true }
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
