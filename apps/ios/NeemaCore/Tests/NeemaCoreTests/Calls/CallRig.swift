import Foundation
import XCTest
@testable import NeemaCore

/// Android's `CallManagerTest.Rig`: the manager over the fakes, every delay on
/// one virtual clock, frames pushed straight into the events signal.
@MainActor
final class CallRig {
    static let BASE: Int64 = 1_790_330_400_000   // 2026-09-25T10:00:00Z
    let api: FakeCallApi
    let media = FakeMedia()
    let ringer = FakeRinger()
    let audio = FakeAudio()
    let frames = Signal<JSONValue>(buffer: 64)
    let foreground = Watched<Bool>(true)
    let connected = Watched<Bool>(true)
    let clock = VirtualClock()
    let trouble = Signal<Bool>(buffer: 8)
    var signedIn = true
    var mic = true
    var agentId: String? = nil
    var agentName: String? = nil
    /// Wall-clock time that passed with the main thread asleep (no ticks ran): the clock the manager reads includes it.
    var slept: Int64 = 0
    let outboxDir: URL
    let calls: CallManager

    /// `api`: the fake the manager's API wraps (`wrap` puts a decorator between them); `media`: a stand-in for the fake media.
    init(start: Bool = true, outboxDir: URL? = nil, api: FakeCallApi = FakeCallApi(), wrap: ((FakeCallApi) -> CallApi)? = nil, media: CallMedia? = nil) {
        self.api = api
        self.outboxDir = outboxDir ?? FileManager.default.temporaryDirectory.appendingPathComponent("neema-call-rig-\(UUID().uuidString)")
        let clock = self.clock
        var sleptRef: () -> Int64 = { 0 }
        var signedInRef: () -> Bool = { true }
        var micRef: () -> Bool = { true }
        var idRef: () -> String? = { nil }
        var nameRef: () -> String? = { nil }
        calls = CallManager(api: wrap?(api) ?? api, events: frames, connected: connected, foreground: foreground,
                            signedIn: { signedInRef() }, media: media ?? self.media, ringer: ringer, audio: audio,
                            micGranted: { micRef() }, now: { CallRig.BASE + clock.now + sleptRef() }, sleep: clock.sleeper,
                            outboxDir: self.outboxDir, myAgentId: { idRef() }, myAgentName: { nameRef() }, audioTrouble: trouble)
        signedInRef = { [weak self] in self?.signedIn ?? false }
        micRef = { [weak self] in self?.mic ?? false }
        idRef = { [weak self] in self?.agentId }
        nameRef = { [weak self] in self?.agentName }
        sleptRef = { [weak self] in self?.slept ?? 0 }
        if start { calls.start() }
    }

    /// The end of a test: every timer and observer of the manager is cancelled.
    func stop() { calls.stop() }

    var state: CallUiState { calls.state.value }
    var now: Int64 { CallRig.BASE + clock.now + slept }
    var words: String { state.statusText() }

    /// A frame of string fields, delivered (and handled) at once.
    func frame(_ kv: (String, String)...) {
        var o: [String: JSONValue] = [:]
        for (k, v) in kv { o[k] = .string(v) }
        frames.emit(.object(o))
    }
    func ring(_ id: String = "wacid.1", from: String = "254712345678", name: String? = "Fr. Peter Kamau") {
        if let n = name { frame(("type", "incoming_call"), ("call_id", id), ("from", from), ("name", n)) }
        else { frame(("type", "incoming_call"), ("call_id", id), ("from", from)) }
    }
    /// A frame exactly as routers/whatsapp_webhook.py publishes it (json.dumps), parsed as LiveSocket does.
    func raw(_ json: String) { frames.emit(JSONValue.parse(json)!) }
    /// An ISO instant `ago` ms before now.
    func at(_ ago: Int64) -> String { Fmt.iso(now - ago) }
    /// Lets every queued hop run (Android's `runCurrent()`).
    func settle() async { await drain() }
    /// `advanceTimeBy(ms); runCurrent()`.
    func advance(_ ms: Int64) async { await clock.advance(by: ms); await drain() }
    func listCount() -> Int { api.log.filter { $0 == "list" }.count }
    func count(_ prefix: String) -> Int { api.log.filter { $0.hasPrefix(prefix) }.count }
    /// The files waiting in the recording outbox.
    var outboxFiles: [URL] { (try? FileManager.default.contentsOfDirectory(at: outboxDir, includingPropertiesForKeys: nil)) ?? [] }
    func logged(_ prefix: String) -> Bool { api.log.contains { $0.hasPrefix(prefix) } }
}

extension Fmt {
    /// An ISO-8601 instant with milliseconds, as the server's rows carry (`2026-09-25T10:00:00.000Z`).
    static func iso(_ millis: Int64) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date(timeIntervalSince1970: TimeInterval(millis) / 1000))
    }
}

/// A server refusal of `status` on `method path` with `body`.
func apiError(_ status: Int, _ method: String, _ path: String, _ body: String = "{}") -> ApiError {
    ApiError(status: status, method: method, path: path, body: body)
}
/// No connection at all (status 0, as the transport reports it).
func offlineError(_ method: String, _ path: String) -> ApiError { ApiError(status: 0, method: method, path: path, body: "offline: no route") }
/// The request left but the answer never came (status 0, "timed out").
func timeoutError(_ method: String, _ path: String) -> ApiError { ApiError(status: 0, method: method, path: path, body: "timed out after 30s") }

extension Result {
    var isSuccess: Bool { if case .success = self { return true } else { return false } }
    var isFailure: Bool { !isSuccess }
    var failure: Failure? { if case .failure(let e) = self { return e } else { return nil } }
    /// The user-facing words of a failed call (`CallError.message`), else the error's description.
    var failureMessage: String? {
        guard let e = failure else { return nil }
        if let c = e as? CallError { return c.message }
        return (e as? LocalizedError)?.errorDescription ?? String(describing: e)
    }
}

extension CallUiState {
    /// Android's data-class constructor, for the word tests.
    init(phase: CallPhase = .idle, callId: String? = nil, from: String? = nil, channel: String = CallWords.WHATSAPP, name: String? = nil,
         seconds: Int = 0, outbound: Bool = false, reconnecting: Bool = false, outcome: CallOutcome? = nil, conversationId: String? = nil,
         permission: CallPermission? = nil, refusal: CallRefusal? = nil) {
        self.init()
        self.phase = phase; self.callId = callId; self.from = from; self.channel = channel; self.name = name; self.seconds = seconds
        self.outbound = outbound; self.reconnecting = reconnecting; self.outcome = outcome; self.conversationId = conversationId
        self.permission = permission; self.refusal = refusal
    }
}

/// A JSON string literal for `s` (quotes and backslashes escaped).
func jsonString(_ s: String) -> String {
    "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"").replacingOccurrences(of: "\n", with: "\\n") + "\""
}

/// A structured refusal: `{"detail", "code", "action", …extra}` (CALLING_UX.md §2.1).
func refusal(_ status: Int, _ path: String, _ detail: String, _ code: String, _ action: String, extra: String = "") -> ApiError {
    ApiError(status: status, method: "POST", path: path, body: "{\"detail\":\(jsonString(detail)),\"code\":\"\(code)\",\"action\":\"\(action)\"\(extra)}")
}
