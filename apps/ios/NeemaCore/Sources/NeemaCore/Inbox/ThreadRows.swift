import Foundation

/// One rendered line of the thread (the web's thread JSX, Android's `TRow`).
public enum ThreadRow: Equatable, Hashable, Sendable, Identifiable {
    case newDivider(n: Int)
    case postHead(PostContext, key: String)
    case escalated(ThreadMsg, reason: String)
    case flag(ThreadMsg)
    case pill(ThreadMsg)
    /// A WhatsApp call where it happened: the pill, and its summary card when there is one.
    case call(ThreadMsg)
    case note(ThreadMsg)
    case bubble(ThreadMsg, album: [ThreadMsg]?)

    public var key: String {
        switch self {
        case .newDivider: return "new-divider"
        case .postHead(_, let key): return key
        case .escalated(let m, _), .flag(let m), .pill(let m), .call(let m), .note(let m), .bubble(let m, _): return m.id
        }
    }

    public var id: String { key }
}

public enum ThreadRows {
    /// Escalation-style events sort just after the inbound message that caused them.
    public static func sort(_ list: [ThreadMsg]) -> [ThreadMsg] {
        func key(_ m: ThreadMsg) -> Int64 {
            m.millis + ((m.isSystem && (m.eventKind == "escalated" || (m.eventKind == "intercept" && m.agentName == nil))) ? 1 : 0)
        }
        return list.enumerated().sorted { a, b in
            let ka = key(a.element), kb = key(b.element)
            return ka != kb ? ka < kb : a.offset < b.offset
        }.map { $0.element }
    }

    /// The thread as the web renders it: handoff pills stay in the activity
    /// log, only the FIRST escalation shows, a comment run is headed by its
    /// post once, consecutive photos collapse into an album, and the "N new"
    /// divider sits before the first message that was unread on open.
    public static func build(_ sorted: [ThreadMsg], unreadSnap: Int) -> [ThreadRow] {
        var rows: [ThreadRow] = []
        rows.reserveCapacity(sorted.count + 8)
        var dividerIdx = -1
        if unreadSnap > 0 {
            let inbound = sorted.indices.filter { sorted[$0].inbound && !sorted[$0].isSystem }
            if inbound.count >= unreadSnap { dividerIdx = inbound[inbound.count - unreadSnap] }
            else if let f = inbound.first { dividerIdx = f }
            else { dividerIdx = max(0, sorted.count - unreadSnap) }
        }

        // A comment thread reads like Facebook: the POST once, the comments under it.
        var postHeadFor: [String: PostContext] = [:]
        var lastPostKey = ""
        for m in sorted {
            guard let c = m.commentContext, c.replyTo == nil else { continue }
            let key = c.postId ?? c.permalink ?? c.title ?? ""
            if key.isEmpty { continue }
            if key != lastPostKey { postHeadFor[m.id] = c; lastPostKey = key }
        }

        // WhatsApp-style albums: runs of ≥2 consecutive photos from the same side.
        var albumOf: [String: (first: Bool, items: [ThreadMsg])] = [:]
        var run: [ThreadMsg] = []
        func flush() {
            if run.count >= 2 { for (i, m) in run.enumerated() { albumOf[m.id] = (i == 0, run) } }
            run = []
        }
        for m in sorted {
            let isImg = !m.isSystem && !m.isNote && m.mediaType == "image" && m.mediaUrl != nil
            if isImg, run.last.map({ $0.direction == m.direction && $0.sender == m.sender }) ?? true {
                run.append(m)
            } else {
                flush()
                if isImg { run.append(m) }
            }
        }
        flush()

        var escalationShown = false
        for (idx, msg) in sorted.enumerated() {
            let showDivider = idx == dividerIdx
            let album = albumOf[msg.id]
            var row: ThreadRow? = nil
            if let a = album, !a.first {
                row = nil
            } else if msg.isSystem {
                let kind = msg.eventKind ?? ""
                let agentPickup = kind == "intercept" && msg.agentName != nil
                if kind == "release" || kind == "transfer" || kind == "approve_draft" || agentPickup {
                    row = nil // handoffs live in the Activity Log only
                } else if kind == "escalated" {
                    if !escalationShown {
                        escalationShown = true
                        row = .escalated(msg, reason: msg.eventReason ?? "AI could not continue — agent needed")
                    }
                } else if kind == "flag" {
                    row = .flag(msg)
                } else if kind == "call" {
                    row = .call(msg)
                } else if kind == "intercept" {
                    if !escalationShown {
                        escalationShown = true
                        let hasInboundMedia = sorted[0..<idx].contains { $0.inbound && $0.mediaType != nil }
                        row = .escalated(msg, reason: msg.eventReason ?? (hasInboundMedia ? "Media received — AI cannot process" : "AI could not continue — agent needed"))
                    }
                } else {
                    row = .pill(msg)
                }
            } else if msg.isNote {
                row = .note(msg)
            } else {
                row = .bubble(msg, album: album?.items)
            }
            if showDivider && unreadSnap > 0 { rows.append(.newDivider(n: unreadSnap)) }
            if case .bubble? = row, let head = postHeadFor[msg.id] { rows.append(.postHead(head, key: "post-\(msg.id)")) }
            if let r = row { rows.append(r) }
        }
        // Each row keys the list: a message delivered twice under one id draws once.
        var keys: Set<String> = []
        return rows.filter { keys.insert($0.key).inserted }
    }
}
