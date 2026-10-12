import Foundation

/// Where the call on this phone is (docs/CALLING_UX.md §3). Exactly one at a
/// time; the words on screen are always the phase's own (`statusText`).
/// "Reconnecting" is `CallUiState.reconnecting` on a live call (the timer keeps
/// the call's true length through it); "ending" never shows — hang-up ends the
/// call on this phone at once and the terminate follows in the background.
/// Android `feature/calls/CallManager.kt`.
public enum CallPhase: Equatable, Sendable {
    case idle
    /// Ringing this phone (inbound).
    case ringing
    /// Outbound: building the offer, asking Meta to place the call ("Calling…").
    case placing
    /// Outbound: Meta is ringing the customer ("Ringing…").
    case ringingOut
    /// Answered, the media not flowing yet ("Connecting…").
    case connecting
    /// Media flowing; the timer runs from here.
    case inCall
    /// The wrap-up card: the `CallUiState.outcome` and what to do next.
    case ended
}

public enum CallbackSave: Equatable, Sendable { case saved, retrying, notSaved }

/// How a call ended, as the wrap-up card says it (the §3 table).
public enum CallOutcome: Equatable, Sendable {
    case completed
    /// Another agent took it (`agent`, their name), or this agent on another
    /// device (`mine`: "Answered on your other device").
    case answeredElsewhere(agent: String?, mine: Bool = false)
    /// Declined for the whole team; `agent` nil when it was this agent.
    case declined(agent: String? = nil)
    /// The caller gave up while it rang (`note`: why, when the server said more — a line under "Missed call").
    case missed(note: String? = nil)
    /// Saved to call back (`agent`: the colleague who did, nil when it was this agent).
    case callback(saved: CallbackSave, agent: String? = nil)
    /// Our call rang out unanswered.
    case noAnswer
    /// The customer declined OUR call (Meta's REJECTED): "{First} declined the call".
    case rejected
    /// The agent hung up our call before the customer answered.
    case cancelled
    /// The media dropped and did not come back.
    case connectionLost
    /// The server's reason, and its `action` (CALLING_UX.md §2.1): retry (or
    /// nil — an older server) offers Try again; wait / admin / none never do.
    /// `until`: when a `wait` may end, if the server said.
    case failed(reason: String, action: String? = nil, until: String? = nil)
    /// The customer hasn't allowed business calls: the agent may send WhatsApp's call request.
    case permissionNeeded
    /// The call request found they had already allowed calls permanently: "Call now".
    case alreadyAllowed
    /// Nothing more is owed here: the "{First} allowed calls" banner follows when they tap Allow.
    case permissionRequested
    case micBlocked

    /// How long the wrap-up stays by itself. Nil: until the agent acts or
    /// dismisses it — the team still owes the customer something.
    public var autoCloseMs: Int64? {
        switch self {
        case .completed: return 8_000
        case .answeredElsewhere: return 4_000
        case .declined: return 5_000
        case .callback(let saved, _): return saved == .notSaved ? nil : 4_000
        case .cancelled: return 2_000
        case .permissionRequested: return 6_000
        default: return nil
        }
    }

    public var isDeclined: Bool { if case .declined = self { return true } else { return false } }
    public var isCallback: Bool { if case .callback = self { return true } else { return false } }
    public var isFailed: Bool { if case .failed = self { return true } else { return false } }
}

/// What the wrap-up card offers (in this order; the first is the primary one).
public enum WrapAction: String, Equatable, Sendable, CaseIterable {
    case openChat = "Open chat", callAgain = "Call again", callBack = "Call back", tryAgain = "Try again",
         message = "Message", sendCallRequest = "Send call request", openSettings = "Open settings",
         callNow = "Call now", callingSettings = "Open WhatsApp calling settings",
         done = "Done", cancel = "Cancel"
    public var label: String { rawValue }
}

/// A second caller while this phone is on a call: a banner, never a take-over. `from`: wa_id, or the PSID on Messenger.
public struct WaitingCall: Equatable, Sendable {
    public let callId: String
    public let from: String?
    public let name: String?
    public let channel: String
    public init(callId: String, from: String?, name: String?, channel: String = CallWords.WHATSAPP) {
        self.callId = callId; self.from = from; self.name = name; self.channel = channel
    }
    public var who: String {
        if let n = name?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty { return n }
        if channel == CallWords.MESSENGER { return CallWords.MESSENGER_CALLER }
        if let f = from, !f.isEmpty { return "+\(f)" }
        return "Someone"
    }
}

/// A customer this phone asked allowed calls: "{First} allowed calls — Call now".
/// `waId`: their handle on `channel` (the PSID on Messenger).
public struct PermissionGrant: Equatable, Sendable {
    public let waId: String
    public let name: String?
    public let channel: String
    public init(waId: String, name: String?, channel: String = CallWords.WHATSAPP) { self.waId = waId; self.name = name; self.channel = channel }
}

public struct CallUiState: Equatable, Sendable {
    public var phase: CallPhase = .idle
    public var callId: String? = nil
    /// Customer wa_id (digits, no +) — on Messenger their PSID, which is never shown.
    public var from: String? = nil
    /// "whatsapp" | "messenger": where the call is (the card's look and words follow it).
    public var channel: String = CallWords.WHATSAPP
    public var name: String? = nil
    public var muted: Bool = false
    public var seconds: Int = 0
    /// Said inline on a live card ("No connection — can't answer yet"); the wrap-up says `outcome`.
    public var error: String? = nil
    /// True while we placed the call (ringing THEM).
    public var outbound: Bool = false
    /// The network blipped mid-call: ICE is trying to recover (see `CallManager.ICE_GRACE_MS`).
    public var reconnecting: Bool = false
    /// A request the card is waiting on (saving a callback, sending a call request): its buttons are disabled.
    public var busy: Bool = false
    /// Set in `.ended`.
    public var outcome: CallOutcome? = nil
    /// The customer's WhatsApp conversation (from the ring or a `call_update`), for "Open chat".
    public var conversationId: String? = nil
    public var personId: String? = nil
    /// Where the call's audio plays, and what it could play through.
    public var route: AudioRoute = .earpiece
    public var routes: [AudioRoute] = [.earpiece, .speaker]
    /// A recording is really running (the only time "● Recording" shows).
    public var recording: Bool = false
    /// After the call: "Recording saved — …", or nil when nothing was recorded.
    public var recordingNote: String? = nil
    /// The call shrank to the bar at the top of the app (§6).
    public var minimised: Bool = false
    public var waiting: WaitingCall? = nil
    /// Whether the customer allowed calls, as the server read it before this
    /// call was placed (and as `call_permission` frames update it): the
    /// wrap-up says it honestly, the card warns about unanswered calls.
    public var permission: CallPermission? = nil
    /// A refused call request (see `CallRefusal`).
    public var refusal: CallRefusal? = nil
    /// WhatsApp records and transcribes this call itself (ice-config `meta_transcription`).
    public var metaTranscription: Bool = false

    public init() {}

    public var speaker: Bool { route.kind == .speaker }
    /// A Messenger call (CALLING_UX.md §2.0): Messenger's look, never the PSID on screen.
    public var messenger: Bool { channel == CallWords.MESSENGER }
    /// "WhatsApp" / "Messenger".
    public var app: String { channelLabel(channel) }
    /// Their number to show under the name (never a PSID).
    public var number: String? {
        guard let f = from, !f.isEmpty, !messenger else { return nil }
        return f
    }
    /// Ringing, placing, connecting or on a call — anything but idle and the wrap-up.
    public var live: Bool { phase != .idle && phase != .ended }
    /// Name, else +number ("Messenger caller" on Messenger), else "Unknown caller".
    public var who: String {
        if let n = name?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty { return n }
        if messenger { return CallWords.MESSENGER_CALLER }
        if let n = number { return "+\(n)" }
        return "Unknown caller"
    }
    /// The key "Open chat" / "Message" opens: the wa_id (the inbox matches it),
    /// else the conversation. On Messenger the conversation first, else the PSID.
    public var chatKey: String? {
        let conv = conversationId.flatMap { $0.isEmpty ? nil : $0 }
        let f = from.flatMap { $0.isEmpty ? nil : $0 }
        return messenger ? (conv ?? f) : (f ?? conv)
    }
    /// A headset or Bluetooth is there: the audio button opens a list instead of toggling the speaker.
    public var routeChoice: Bool { routes.contains { $0.isHeadset } }
}

public extension CallUiState {
    /// The status line under the name — the §3 words for every phase and outcome.
    func statusText() -> String {
        switch phase {
        case .idle: return ""
        case .ringing: return "Incoming…"
        case .placing: return "Calling…"
        case .ringingOut: return "Ringing…"
        case .connecting: return reconnecting ? "Reconnecting…" : "Connecting…"
        case .inCall: return reconnecting ? "Reconnecting…" : mmss(seconds)
        case .ended: return outcome.map { outcomeText($0) } ?? "Call ended"
        }
    }

    /// The wrap-up's words for `o` (a table row of CALLING_UX.md §3).
    func outcomeText(_ o: CallOutcome) -> String {
        // Addressed by first name (titles skipped); no name: their number, as the web's firstName() (never a PSID).
        let first = firstNameOf(name) ?? number.map { "+\($0)" }
        switch o {
        case .completed: return seconds > 0 ? "Call ended · \(callLength(seconds))" : "Call ended"
        case .answeredElsewhere(let agent, let mine):
            return mine ? "Answered on your other device" : "Answered by \(agentFirst(agent) ?? "a colleague")"
        case .declined(let agent): return agentFirst(agent).map { "Declined by \($0)" } ?? "Call declined"
        case .missed: return "Missed call"
        case .callback(let saved, let agent):
            switch saved {
            case .saved: return agentFirst(agent).map { "\($0) saved it to call back — find it under Calls" } ?? CallManager.CALLBACK_SAVED
            case .retrying: return CallManager.CALLBACK_RETRYING
            case .notSaved: return CallManager.CALLBACK_FAILED
            }
        case .noAnswer: return "No answer"
        case .rejected: return "\(first ?? "The customer") declined the call"
        case .alreadyAllowed: return "\(first ?? "This customer") already allows calls — call now"
        case .cancelled: return "Call cancelled"
        case .connectionLost:
            return seconds > 0 ? "Call dropped · \(callLength(seconds)) — the connection was lost" : "Call dropped — the connection was lost"
        case .failed(let reason, _, _): return reason
        case .permissionNeeded: return "\(first ?? "This customer") hasn't allowed \(app) calls yet"
        case .permissionRequested: return "Call request sent — you'll be told when \(first ?? "they") tap\(first == nil ? "" : "s") Allow"
        case .micBlocked: return CallManager.MIC_BLOCKED_WRAP
        }
    }

    /// The wrap-up's second line, under the outcome: why a call was missed when
    /// the server said more, and what "Send call request" does (CallStage.tsx).
    /// Nil when the outcome says it all — or when `error` says something more
    /// pressing in its place.
    func outcomeNote(now: Int64 = AppClock.now()) -> String? {
        if phase != .ended || error != nil { return nil }
        guard let o = outcome else { return nil }
        switch o {
        case .missed(let note): return note
        case .permissionNeeded:
            // Where their permission stands (declined, revoked, asked already), then what the button does —
            // or why it can't be pressed yet.
            var lines: [String] = []
            if let p = permission, p.status == "denied" || p.status == "requested",
               let line = permissionLine(p, first: firstNameOf(name) ?? "them", now: now) { lines.append(line) }
            lines.append(sendRequestBlocked(now: now) ?? (messenger ? CallManager.PERMISSION_EXPLAINED_MESSENGER : CallManager.PERMISSION_EXPLAINED))
            return lines.joined(separator: "\n")
        case .failed(_, let action, let until):
            switch action {
            case "admin": return CallManager.ADMIN_MUST_ACT
            case "wait": return until.map { "You can try again \(untilText($0, now: now))" } ?? CallManager.WAIT_A_MOMENT
            case "none": return CallManager.MESSAGE_INSTEAD
            default: return nil
            }
        default: return nil
        }
    }

    /// "You can ask again in 5 h": Send call request can't be pressed yet — Meta's
    /// limit (1 a day, 2 a week) is used up. Nil when a request may be sent.
    func sendRequestBlocked(now: Int64 = AppClock.now()) -> String? {
        let p = permission
        let limited = refusal?.code == "138009" || refusal?.code == "request_limit"
            || (p != nil && p!.canRequest == false && p!.status != "granted" && p!.status != "requested")
        if !limited { return nil }
        return p?.requestAvailableAt.map { "You can ask again \(untilText($0, now: now))" } ?? "You can ask again later"
    }

    /// The line shown on the card before the call goes through, when this customer
    /// left our last calls unanswered — WhatsApp removes the permission after 4 in
    /// a row. A caution, never a block.
    func callCaution() -> String? {
        if !outbound || (phase != .placing && phase != .ringingOut) { return nil }
        // WhatsApp's rule: Messenger has no unanswered-call revoke to warn about.
        if channel != CallWords.WHATSAPP { return nil }
        let n = permission?.unansweredStreak ?? 0
        if n < 2 { return nil }
        return "\(firstNameOf(name) ?? "This customer") missed your last \(n) calls — WhatsApp removes call permission after 4 in a row. Consider a message first."
    }

    /// What the wrap-up card offers for its outcome, the primary action first.
    /// Chat actions need someone to write to; call actions a number to call.
    func wrapActions() -> [WrapAction] {
        guard let o = outcome else { return [.done] }
        let chat = chatKey != nil
        let dial = !(from ?? "").isEmpty
        func list(_ a: WrapAction?...) -> [WrapAction] { a.compactMap { $0 } }
        switch o {
        case .completed: return list(chat ? .openChat : nil, dial ? .callAgain : nil, .done)
        case .answeredElsewhere, .callback, .cancelled: return [.done]
        case .declined: return list(chat ? .message : nil, .done)
        case .missed: return list(dial ? .callBack : nil, chat ? .message : nil, .done)
        case .noAnswer: return list(dial ? .callAgain : nil, chat ? .message : nil, .done)
        case .rejected: return list(chat ? .message : nil, .done)
        case .alreadyAllowed: return list(dial ? .callNow : nil, chat ? .message : nil, .done)
        case .connectionLost: return list(dial ? .callAgain : nil, chat ? .openChat : nil, .done)
        // Only a retryable failure offers another go (wait / admin / none: trying again won't help).
        case .failed(_, let action, _):
            let again: WrapAction? = dial && (action == nil || action == "retry") ? (outbound ? .tryAgain : .callBack) : nil
            return list(again, chat ? .message : nil, .done)
        // No template outside the 24 h window: asking again can't work — an admin can fix it in Settings.
        case .permissionNeeded:
            if refusal?.code == "template_required" {
                return list(refusal?.adminCanFix == true ? .callingSettings : nil, chat ? .message : nil, .cancel)
            }
            return list(dial ? .sendCallRequest : nil, chat ? .message : nil, .cancel)
        case .permissionRequested: return list(chat ? .message : nil, .done)
        case .micBlocked: return [.openSettings, .done]
        }
    }
}
