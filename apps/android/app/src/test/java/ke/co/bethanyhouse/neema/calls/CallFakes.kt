package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallOffer
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
    /** callId to (filename, mime type, bytes read from the streamed file). */
    val uploads = mutableListOf<Pair<String, Triple<String, String, Int>>>()
    var lastAnswerSdp: String? = null
    var lastConnect: Triple<String, String, String?>? = null

    override suspend fun list(): List<Call> { log += "list"; listError?.let { throw it }; return calls }
    override suspend fun iceConfig(): IceConfig { log += "ice-config"; iceError?.let { throw it }; return ice }
    override suspend fun offer(callId: String): CallOffer {
        log += "offer $callId"; offerError?.let { throw it }
        return CallOffer(callId, offerSdp, "254712345678")
    }
    override suspend fun answer(callId: String, sdp: String) { log += "answer $callId"; lastAnswerSdp = sdp; answerError?.let { throw it } }
    override suspend fun terminate(callId: String) { log += "terminate $callId" }
    override suspend fun callback(callId: String) { log += "callback $callId" }
    override suspend fun connect(to: String, sdp: String, name: String?): String {
        log += "connect $to"; lastConnect = Triple(to, sdp, name)
        connectGate?.await()
        connectError?.let { throw it }
        return connectId
    }
    override suspend fun requestPermission(to: String) { log += "request-permission $to"; permissionError?.let { throw it } }
    override suspend fun uploadRecording(callId: String, file: File, filename: String, mimeType: String) {
        log += "recording $callId"; uploads += callId to Triple(filename, mimeType, file.length().toInt())
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
    var speakerOn = false
    /** The microphone foreground service is up (only ever after the mic was allowed). */
    var micService = false
    var micLives = 0
    override fun enter(speaker: Boolean) { if (!inCall) enters++; inCall = true; if (speaker) speakerOn = true }
    override fun micLive() { micLives++; micService = true }
    override fun leave() { inCall = false; speakerOn = false; micService = false }
    override fun setSpeaker(on: Boolean) { speakerOn = on }
}
