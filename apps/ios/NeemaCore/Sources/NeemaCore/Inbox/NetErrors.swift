import Foundation

/// What a failed request means for the thing it tried to do (Android
/// `feature/conversations/NetErrors.kt`). A phone on a Nairobi network drops
/// connections mid-request all the time: a send that timed out may well have
/// reached the customer, and saying "failed" then invites a second,
/// duplicate send.
public enum Fate: Sendable, Equatable {
    /// The server never acted on it (refused, or the request never left the phone).
    case notSent
    /// It may have happened: check the server before calling it either way.
    case unknown
    /// It happened — only the answer was unreadable.
    case done
}

public enum NetErrors {
    public static func fate(of e: Error) -> Fate {
        if let api = e as? ApiError {
            // A 2xx whose body didn't decode: the server did it.
            if api.malformed && (200..<300).contains(api.status) { return .done }
            if api.status == 0 { return neverConnected(api) ? .notSent : .unknown }
            // 500: the work may be done and only the bookkeeping failed; a gateway
            // error may have been answered by a proxy after the API had the request.
            if api.status == 500 || (502...504).contains(api.status) { return .unknown }
            return .notSent
        }
        if e is DecodingError { return .done }
        if let t = e as? TransportError {
            if case .cancelled = t { return .notSent }
            return .unknown
        }
        return .notSent
    }

    private static let NEVER_CONNECTED = [
        "unable to resolve host", "no address associated", "failed to connect", "connection refused",
        "network is unreachable", "no route to host", "unknownhost",
        // URLSession's own words for the same (NSURLError descriptions).
        "the internet connection appears to be offline", "could not connect to the server",
        "a server with the specified hostname could not be found", "not connected to the internet",
        "the network connection was lost before",
    ]

    /// The request never reached the server: no DNS, no route, the connection
    /// refused. The HTTP layer folds the cause into the message, so read both.
    public static func neverConnected(_ e: Error) -> Bool {
        var texts: [String] = []
        if let api = e as? ApiError {
            texts.append(api.body)
            if let c = api.cause { texts.append(describe(c)) }
        } else {
            texts.append(describe(e))
        }
        let m = texts.joined(separator: " ").lowercased()
        return NEVER_CONNECTED.contains { m.contains($0) }
    }

    private static func describe(_ e: Error) -> String {
        if let t = e as? TransportError, case .network(let m) = t { return m }
        return (e as? LocalizedError)?.errorDescription ?? String(describing: e)
    }

    public static func timedOut(_ e: Error) -> Bool {
        guard let api = e as? ApiError, api.status == 0 else { return false }
        let b = api.body.lowercased()
        return b.contains("timed out") || b.contains("timeout")
    }

    /// The HTTP status, or -1 for anything that is not an `ApiError`.
    public static func status(of e: Error) -> Int { (e as? ApiError)?.status ?? -1 }

    /// 404 for the conversation itself — someone deleted it — not a route the server lacks ("Not Found").
    public static func conversationGone(_ e: Error) -> Bool {
        guard let api = e as? ApiError, api.status == 404, let d = readableDetail(api) else { return false }
        return d != "Not Found"
    }

    /// The server's `detail` when it is written for people: a plain string from
    /// `HTTPException(detail=…)`. Never a proxy's HTML page, a pydantic error
    /// list, or a bare status phrase.
    public static func readableDetail(_ e: Error) -> String? {
        guard let api = e as? ApiError else { return nil }
        guard let obj = JSONValue.parse(api.body)?.objectValue, let v = obj["detail"], case .string(let raw) = v else { return nil }
        let d = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if d.isEmpty || d.count > 300 || d.hasPrefix("<") || d == "Internal Server Error" { return nil }
        return d
    }

    /// The words for a failure the person can act on. The transport problems get
    /// plain sentences of their own; anything else says `fallback` — the web's
    /// copy for that action — unless `useDetail` and the server explained itself.
    public static func whyFailed(_ e: Error, _ fallback: String, useDetail: Bool = false) -> String {
        if let nd = e as? NotDelivered {
            let m = String(nd.message.prefix(160))
            return m.trimmingCharacters(in: .whitespaces).isEmpty ? fallback : m
        }
        guard let api = e as? ApiError else { return fallback }
        switch api.status {
        case 0 where timedOut(api): return "No answer from the server — the connection is too slow right now."
        case 0 where neverConnected(api): return "No connection — check your internet and try again."
        case 0: return "The connection dropped — try again."
        case 401: return "Your session expired — sign in again."
        case 429: return "Too many requests — wait a moment and try again."
        case 500: return "Something went wrong on the server — try again."
        case 502...504: return "Neema's server is unavailable right now — try again shortly."
        default: return useDetail ? (readableDetail(api) ?? fallback) : fallback
        }
    }

    /// Why the inbox list couldn't load, for the line beside Retry.
    public static func listErrorText(_ e: Error) -> String {
        whyFailed(e, "The server sent an answer the app couldn't read.", useDetail: true)
    }
}
