import Foundation

/// One ICE server as the WebRTC SDK wants it (Android `WebRtcMedia.kt` `IceSpec`).
public struct IceSpec: Equatable, Sendable {
    public let urls: [String]
    public let username: String
    public let credential: String
    public init(_ urls: [String], _ username: String, _ credential: String) { self.urls = urls; self.username = username; self.credential = credential }
}

/// GET /admin/calls/ice-config's `ice_servers` (services/wa_calling.py
/// ice_servers()) as the SDK wants them: `urls` is a single string for our
/// coturn and the STUN, a LIST for the openrelay fallback; the STUN entry has no
/// username/credential. Entries without a usable URL are dropped.
public func iceSpecs(_ cfg: IceConfig) -> [IceSpec] {
    cfg.iceServers.compactMap { s in
        var urls: [String] = []
        switch s.urls {
        case .array(let a)?: urls = a.compactMap { $0.content }
        case .string(let u)?: urls = [u]
        default: urls = []
        }
        urls = urls.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        return urls.isEmpty ? nil : IceSpec(urls, s.username ?? "", s.credential ?? "")
    }
}
