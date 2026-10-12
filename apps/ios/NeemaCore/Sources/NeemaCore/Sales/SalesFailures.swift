import Foundation

/// What kind of failure a request met — how the Orders, Deals and Leads
/// screens read it (Android `feature/orders/SalesFailures.kt`).
public enum FailKind: String, Sendable, Equatable {
    case offline, timeout, sessionExpired, forbidden, notFound, conflict, invalid, rateLimited, serverError, unavailable, garbled
}

/// A failed request, read for people. `status` is the HTTP code (0 = no
/// answer), `detail` the server's own words when they are meant for a person
/// (FastAPI's `detail` string, never an HTML page or a stack trace).
public struct SalesFailure: Equatable, Sendable {
    public let kind: FailKind
    public let status: Int
    public let detail: String?
    /// A connection that was never made: refused, no route, no DNS — nothing reached the server.
    public let neverSent: Bool

    public init(_ kind: FailKind, _ status: Int, _ detail: String? = nil, neverSent: Bool = false) {
        self.kind = kind; self.status = status; self.detail = detail; self.neverSent = neverSent
    }

    /// The request may have reached the server and done its work even though no
    /// good answer came back: a timeout, a dropped connection mid-request, a
    /// gateway (502/504) that forwarded it, or a 2xx whose body could not be
    /// read. An action that failed this way must be reconciled by re-reading,
    /// never reported as "failed" (it may have sent the message).
    public var mayHaveHappened: Bool {
        kind == .timeout || kind == .garbled || status == 502 || status == 504 || (kind == .offline && !neverSent)
    }

    /// The words for a toast or an inline error; `gone` is what a 404 means on this screen.
    public func message(gone: String = "It no longer exists — someone may have deleted it") -> String {
        switch kind {
        case .offline: return "No connection — check your internet and try again"
        case .timeout: return "The server took too long to answer — try again"
        case .sessionExpired: return "Your session expired — sign in again to continue"
        case .forbidden: return detail ?? "Your role doesn't allow that"
        case .notFound: return gone
        case .conflict: return detail ?? "That changed meanwhile — showing the latest"
        case .invalid: return detail ?? "The server didn't accept that"
        case .rateLimited: return "Too many requests — wait a moment and try again"
        case .serverError: return detail ?? "The server hit an error — try again"
        case .unavailable: return "The server is unavailable right now — try again shortly"
        case .garbled: return "The server sent an answer the app couldn't read"
        }
    }
}

public enum SalesErrors {
    /// Server `detail`s that are FastAPI's defaults, not words written for a person.
    static let GENERIC_DETAILS: Set<String> = ["not found", "internal server error", "bad gateway", "service unavailable", "method not allowed"]

    /// The server's `detail` when it is a short sentence for a person; nil for pages, dumps and defaults.
    public static func humanDetail(_ body: String) -> String? {
        guard let d = JSONValue.parse(body)?.objectValue?["detail"] else { return nil }
        let raw: String?
        switch d {
        case .string(let s): raw = s
        case .array(let items):
            let msgs = items.compactMap { $0.objectValue?["msg"]?.content }
            raw = msgs.isEmpty ? nil : msgs.joined(separator: "; ")
        default: raw = nil
        }
        guard let t = raw?.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
        if t.isEmpty || t.count > 200 || t.contains("<") || GENERIC_DETAILS.contains(t.lowercased()) { return nil }
        return t
    }

    /// The work was given up, not refused: never a failure to report.
    public static func isCancellation(_ e: Error) -> Bool {
        if e is CancellationError { return true }
        if let t = e as? TransportError, case .cancelled = t { return true }
        if let api = e as? ApiError, api.status == 0, let c = api.cause as? TransportError, case .cancelled = c { return true }
        return false
    }

    /// Read any error from an API call as a `SalesFailure`. Check `isCancellation` first: a cancellation is not a failure.
    public static func failure(of e: Error) -> SalesFailure {
        if e is DecodingError { return SalesFailure(.garbled, 200) }
        guard let api = e as? ApiError else { return SalesFailure(.garbled, 200) }
        // The core flags an unreadable body and a timeout explicitly — trust them first.
        if api.malformed { return SalesFailure(.garbled, api.status) }
        if api.timedOut { return SalesFailure(.timeout, 0) }
        let detail = humanDetail(api.body)
        let s = api.status
        switch s {
        case 0:
            if api.body.range(of: "timed out", options: .caseInsensitive) != nil { return SalesFailure(.timeout, 0) }
            return SalesFailure(.offline, 0, neverSent: NetErrors.neverConnected(api))
        case 401: return SalesFailure(.sessionExpired, s)
        case 403: return SalesFailure(.forbidden, s, detail)
        case 404, 410: return SalesFailure(.notFound, s, detail)
        case 409: return SalesFailure(.conflict, s, detail)
        case 400, 422: return SalesFailure(.invalid, s, detail)
        case 429: return SalesFailure(.rateLimited, s, detail)
        case 502, 503, 504: return SalesFailure(.unavailable, s)
        default: return s >= 500 ? SalesFailure(.serverError, s, detail) : SalesFailure(.invalid, s, detail)
        }
    }

    /// "No connection — …" → "no connection — …", for the tail of a sentence.
    public static func lowerFirst(_ s: String) -> String {
        guard let f = s.first else { return s }
        return f.lowercased() + s.dropFirst()
    }
}
