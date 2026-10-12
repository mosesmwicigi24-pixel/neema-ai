import Foundation

/// The web's `Range`.
public enum ReportRange: String, CaseIterable, Sendable {
    case d7 = "D7", d30 = "D30", d90 = "D90", custom = "Custom"

    public var key: String {
        switch self {
        case .d7: return "7d"
        case .d30: return "30d"
        case .d90: return "90d"
        case .custom: return "custom"
        }
    }

    public var label: String {
        switch self {
        case .d7: return "Last 7 days"
        case .d30: return "Last 30 days"
        case .d90: return "Last 90 days"
        case .custom: return "Custom range"
        }
    }
}

/// The web's `ReportTab`.
public enum ReportTab: String, CaseIterable, Sendable {
    case overview = "Overview", conversations = "Conversations", orders = "Orders", agents = "Agents"
    public var label: String { rawValue }
}

public struct BarPoint: Equatable, Sendable {
    public let label: String
    public let value: Double
    public init(_ label: String, _ value: Double) { self.label = label; self.value = value }
}

public struct AgentStat: Equatable, Sendable {
    public let agent: Agent
    public let handled: Int
    public let revenue: Double
    public init(agent: Agent, handled: Int, revenue: Double) { self.agent = agent; self.handled = handled; self.revenue = revenue }
}

/// Every figure the web's ReportsView computes, for one range.
public struct Report: Equatable, Sendable {
    public let convs: [Conversation]
    public let orders: [Order]
    public let revenue: Double
    public let humanConvs: Int
    public let aiConvs: Int
    public let pending: Int
    public let confirmed: Int
    public let delivered: Int
    public let cancelled: Int
    public let convByDay: [BarPoint]
    public let orderByDay: [BarPoint]
    public let agentStats: [AgentStat]
    public init(convs: [Conversation], orders: [Order], revenue: Double, humanConvs: Int, aiConvs: Int, pending: Int, confirmed: Int, delivered: Int,
                cancelled: Int, convByDay: [BarPoint], orderByDay: [BarPoint], agentStats: [AgentStat]) {
        self.convs = convs; self.orders = orders; self.revenue = revenue; self.humanConvs = humanConvs; self.aiConvs = aiConvs
        self.pending = pending; self.confirmed = confirmed; self.delivered = delivered; self.cancelled = cancelled
        self.convByDay = convByDay; self.orderByDay = orderByDay; self.agentStats = agentStats
    }
}

/// A row with its timestamp parsed once (`NO_DATE` when it has none or it doesn't parse).
public struct Dated<T: Sendable & Equatable>: Sendable, Equatable {
    public let item: T
    public let at: Int64
    public init(_ item: T, _ at: Int64) { self.item = item; self.at = at }
}

public let NO_DATE = Int64.min

/// A badge's tint in a report table (the web's Tailwind -50 tints).
public enum ReportHue: Sendable, Equatable { case emerald, blue, red, amber, open, quiet }

/// A cell of a report table: plain text, a tinted badge, the agent's role chip or their presence.
public enum ReportCell: Sendable, Equatable {
    case text(String)
    case badge(String, ReportHue)
    case role(String)
    case presence(online: Bool)
}

/// A table's rows, with the stable keys their lazy rows take.
public struct TableModel: Sendable, Equatable {
    public let header: String
    public let cols: [String]
    public let rows: [[ReportCell]]
    public let keys: [String]
    public init(header: String, cols: [String], rows: [[ReportCell]], keys: [String]) {
        self.header = header; self.cols = cols; self.rows = rows; self.keys = keys
    }
}

/// A written CSV waiting for the share sheet.
public struct ReadyExport: Equatable, Sendable {
    public let file: URL
    public let range: ReportRange
    public init(file: URL, range: ReportRange) { self.file = file; self.range = range }
}

/// The server answered 200 with something that is not a list of conversations (a captive portal's page).
public struct NotAConversationList: Error, Sendable {}

/// The aggregation maths of ReportsView.tsx (Android `ReportsScreen.kt`'s computation).
public enum ReportsRules {
    /// The web's `mapConversation`: a thread with no messages yet dates from its creation.
    public static func reportAt(_ c: Conversation) -> String? { c.lastMessageAt ?? c.createdAt }

    /// Conversations dated as the web's `mapConversation` dates them (last message, else creation).
    public static func datedConversations(_ all: [Conversation]) -> [Dated<Conversation>] {
        all.map { Dated($0, Fmt.millis(reportAt($0)) ?? NO_DATE) }
    }

    public static func datedOrders(_ orders: [Order]) -> [Dated<Order>] {
        orders.map { Dated($0, Fmt.millis($0.createdAt) ?? NO_DATE) }
    }

    /// Every figure the web's ReportsView computes, for one range. Custom ranges
    /// cover whole local days, "to" inclusive — a deliberate fix: the web parses
    /// `new Date("2026-09-01")` as UTC midnight, which silently drops the whole
    /// "to" day (and starts "from" at 03:00 in Nairobi).
    public static func buildReport(_ all: [Conversation], orders: [Order], agents: [Agent], range: ReportRange,
                                   customFrom: LocalDay?, customTo: LocalDay?, now: Int64 = AppClock.now(), zone: TimeZone = Fmt.timeZone) -> Report {
        buildReportDated(datedConversations(all), orders: datedOrders(orders), agents: agents, range: range,
                         customFrom: customFrom, customTo: customTo, now: now, zone: zone)
    }

    /// `buildReport` over rows whose dates are already parsed: one pass per
    /// figure, per-day buckets by binary search over the day boundaries, and
    /// agent performance from per-agent / per-customer indexes instead of a scan
    /// of every conversation and order for each agent — 10,000 conversations,
    /// 1,000 orders and 200 agents build in a few milliseconds.
    public static func buildReportDated(_ all: [Dated<Conversation>], orders: [Dated<Order>], agents: [Agent], range: ReportRange,
                                        customFrom: LocalDay?, customTo: LocalDay?, now: Int64, zone: TimeZone) -> Report {
        let day: Int64 = 86_400_000
        // Date range (the web's daysAgo(): same time of day, n days back).
        let from: Int64, to: Int64
        switch range {
        case .d7: from = now - 7 * day; to = now
        case .d90: from = now - 90 * day; to = now
        case .custom where customFrom != nil && customTo != nil:
            // Inclusive of the whole "to" day.
            from = customFrom!.startMillis(zone: zone)
            to = customTo!.plusDays(1).startMillis(zone: zone) - 1
        default: from = now - 30 * day; to = now
        }
        func inRange(_ at: Int64) -> Bool { at != NO_DATE && at >= from && at <= to }

        let datedConvs = all.filter { inRange($0.at) }
        let datedFOrders = orders.filter { inRange($0.at) }
        let convs = datedConvs.map { $0.item }
        let fOrders = datedFOrders.map { $0.item }
        let revenue = fOrders.filter { $0.status != "cancelled" }.reduce(0.0) { $0 + $1.total }

        // Per-day charts: at most 14 bars ending on the range's last day. Each
        // row lands in its local day by binary search over the days' start
        // instants (DST-safe, no per-row calendar maths).
        let days: Int
        switch range { case .d7: days = 7; case .d30: days = 14; default: days = 30 }
        let n = min(days, 14)
        let toDay = LocalDay.of(millis: to, zone: zone)
        let dayList = (0..<n).map { i in toDay.minusDays(n - 1 - i) }
        var starts = [Int64](repeating: 0, count: n + 1)
        for i in 0...n { starts[i] = (i < n ? dayList[i] : toDay.plusDays(1)).startMillis(zone: zone) }
        func bucket(_ at: Int64) -> Int {
            if at < starts[0] || at >= starts[n] { return -1 }
            // The last start ≤ at.
            var lo = 0, hi = n
            while hi - lo > 1 {
                let mid = (lo + hi) / 2
                if starts[mid] <= at { lo = mid } else { hi = mid }
            }
            return lo
        }
        var convCounts = [Int](repeating: 0, count: n)
        for d in datedConvs { let b = bucket(d.at); if b >= 0 { convCounts[b] += 1 } }
        // Summed in list order per day, exactly as the web's reduce adds them.
        var orderSums = [Double](repeating: 0, count: n)
        for d in datedFOrders { let b = bucket(d.at); if b >= 0 { orderSums[b] += d.item.total } }
        let convByDay = dayList.enumerated().map { i, d in BarPoint(d.weekdayShort, Double(convCounts[i])) }
        let orderByDay = dayList.enumerated().map { i, d in BarPoint(d.weekdayShort, orderSums[i]) }

        // Agent performance: threads they hold, and orders from those customers.
        // Indexed once — never every conversation and order scanned per agent.
        var byAgent: [String: [Conversation]] = [:]
        for conv in convs { if let a = conv.assignedAgentId { byAgent[a, default: []].append(conv) } }
        var ordersByCustomer: [String: [Int]] = [:]
        for (i, o) in fOrders.enumerated() where !o.waId.isEmpty { ordersByCustomer[o.waId, default: []].append(i) }
        let agentStats = agents.map { a -> AgentStat in
            let mine = byAgent[a.id] ?? []
            var waIds = Set<String>()
            for c in mine { if let w = c.waId { waIds.insert(w) } }
            // The same orders the web's filter keeps, added in the same (list) order.
            let idx = waIds.flatMap { ordersByCustomer[$0] ?? [] }.sorted()
            var rev = 0.0
            for i in idx { rev += fOrders[i].total }
            return AgentStat(agent: a, handled: mine.count, revenue: rev)
        }
        // A stable sort by handled, descending: ties keep the team's order.
        .enumerated().sorted { a, b in a.element.handled != b.element.handled ? a.element.handled > b.element.handled : a.offset < b.offset }
        .map { $0.element }

        var human = 0, ai = 0
        for c in convs { if c.interceptMode == "human" { human += 1 } else if c.interceptMode == "ai" { ai += 1 } }
        var pending = 0, confirmed = 0, delivered = 0, cancelled = 0
        for o in fOrders {
            switch o.status {
            case "pending": pending += 1
            case "confirmed": confirmed += 1
            case "delivered": delivered += 1
            case "cancelled": cancelled += 1
            default: break
            }
        }
        return Report(convs: convs, orders: fOrders, revenue: revenue, humanConvs: human, aiConvs: ai,
                      pending: pending, confirmed: confirmed, delivered: delivered, cancelled: cancelled,
                      convByDay: convByDay, orderByDay: orderByDay, agentStats: agentStats)
    }

    // ── Tables ────────────────────────────────────────────────────────────

    /// `keys` made unique (a repeated id gets its position appended), so lazy rows never collide.
    public static func uniqueKeys(_ keys: [String]) -> [String] {
        var seen = Set<String>(minimumCapacity: keys.count * 2)
        return keys.enumerated().map { i, k in
            if seen.insert(k).inserted { return k }
            var n = 0
            while true {
                let candidate = n == 0 ? "\(k)#\(i)" : "\(k)#\(i).\(n)"
                if seen.insert(candidate).inserted { return candidate }
                n += 1
            }
        }
    }

    /// The table for `tab` (nil for Overview): the web's first 50 conversations, first 20 orders, every agent.
    public static func tableFor(_ tab: ReportTab, _ r: Report, agents: [Agent], now: Int64) -> TableModel? {
        switch tab {
        case .overview: return nil
        case .conversations:
            // `agents.find(...)`: the first agent with the id, as the web picks it.
            var names: [String: String] = [:]
            for a in agents where names[a.id] == nil { names[a.id] = a.name }
            let shown = Array(r.convs.prefix(50))
            return TableModel(header: "\(r.convs.count) conversations in period",
                              cols: ["Customer", "Channel", "Status", "Mode", "Last Activity", "Agent"],
                              rows: shown.map { conversationRow($0, names, now) },
                              keys: uniqueKeys(shown.map { "c:\($0.id)" }))
        case .orders:
            let shown = Array(r.orders.prefix(20))
            return TableModel(header: "\(r.orders.count) orders · \(Fmt.currency(r.revenue)) total",
                              cols: ["Customer", "Phone", "Amount", "Status", "Date"],
                              rows: shown.map(orderRow), keys: uniqueKeys(shown.map { "o:\($0.id)" }))
        case .agents:
            return TableModel(header: "Agent Performance", cols: ["Agent", "Role", "Conversations", "Revenue", "Status"],
                              rows: r.agentStats.map(agentRow), keys: uniqueKeys(r.agentStats.map { "a:\($0.agent.id)" }))
        }
    }

    static func conversationRow(_ conv: Conversation, _ agentNames: [String: String], _ now: Int64) -> [ReportCell] {
        let mode: ReportHue = conv.interceptMode == "human" ? .amber : (conv.interceptMode == "ai" ? .blue : .quiet)
        let agent = conv.assignedAgentId.flatMap { agentNames[$0] }.flatMap { $0.isEmpty ? nil : $0 } ?? "—"
        return [
            .text(Fmt.displayName(conv.name, conv.waId)),
            // `<span className="capitalize">{c.channel || "whatsapp"}</span>`
            .text(OverviewRules.capitalizeWords(conv.channel.isEmpty ? "whatsapp" : conv.channel)),
            .badge(conv.status, conv.status == "open" ? .open : .quiet),
            .badge(conv.interceptMode, mode),
            .text(Fmt.timeAgo(reportAt(conv), now: now)),
            // `?.name || "—"`: an agent with a blank name reads "—" too.
            .text(agent),
        ]
    }

    public static func orderStatusHue(_ status: String) -> ReportHue {
        switch status {
        case "delivered": return .emerald
        case "confirmed": return .blue
        case "cancelled": return .red
        default: return .amber
        }
    }

    /// The web's `displayName(o.contact_name, o.contact_phone || o.wa_id)` after
    /// mapOrder(), which makes `contact_name` fall back to the wa_id: an unnamed
    /// buyer reads as their bare number ("254712345678"), in the table and the CSV.
    public static func reportCustomer(_ o: Order) -> String { Fmt.displayName(o.customerName, reportPhone(o)) }

    /// mapOrder() sets `contact_phone` to the wa_id.
    public static func reportPhone(_ o: Order) -> String { (o.contactPhone?.isEmpty == false) ? o.contactPhone! : o.waId }

    static func orderRow(_ o: Order) -> [ReportCell] {
        [.text(reportCustomer(o)), .text(Fmt.formatPhone(reportPhone(o))), .text(Fmt.currency(o.total)),
         .badge(o.status, orderStatusHue(o.status)), .text(Fmt.date(o.createdAt))]
    }

    static func agentRow(_ s: AgentStat) -> [ReportCell] {
        [.text(s.agent.name), .role(OverviewRules.capitalizeWords(s.agent.role)), .text(String(s.handled)),
         .text(Fmt.currency(s.revenue)), .presence(online: s.agent.isAvailable)]
    }

    // ── CSV export ────────────────────────────────────────────────────────

    /// "1500" not "1500.0" — the web prints the raw number.
    public static func plain(_ v: Double) -> String {
        if v.isFinite && v == v.rounded(.down) && abs(v) < 9.2e18 { return String(Int64(v)) }
        return String(v)
    }

    public static func csvField(_ s: String) -> String {
        if s.contains(",") || s.contains("\"") || s.contains("\n") || s.contains("\r") {
            return "\"" + s.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        return s
    }

    /// The web's CSV: `Date,Customer,Amount,Status`, one line per order in range.
    /// Fields are RFC-4180 quoted when they need it — the web writes them bare, so
    /// a customer called "Kamau, Peter" split into two columns there.
    public static func reportCsv(_ orders: [Order]) -> String {
        var out = ""
        writeCsv(into: { out += $0 }, orders)
        return out
    }

    /// The CSV handed to `sink` a row at a time (10,000 orders never become one string).
    public static func writeCsv(into sink: (String) -> Void, _ orders: [Order]) {
        sink("Date,Customer,Amount,Status\n")
        for (i, o) in orders.enumerated() {
            var line = i > 0 ? "\n" : ""
            line += csvField(Fmt.date(o.createdAt)) + "," + csvField(reportCustomer(o)) + "," + csvField(plain(o.total)) + "," + csvField(o.status)
            sink(line)
        }
    }

    /// The web downloads `neema-report-<range>.csv`; on a phone the same file is
    /// written to the cache and handed to the share sheet (Mail, Drive, WhatsApp…).
    public static func csvFileName(_ range: ReportRange) -> String { "neema-report-\(range.key).csv" }

    /// Streams the CSV into `dir` (created if needed) in 64 KB pieces; throws
    /// when the phone can't store it. Written to a temporary name first, so a
    /// failure halfway never leaves a truncated report to share.
    public static func writeReportCsv(dir: URL, orders: [Order], range: ReportRange) throws -> URL {
        let fm = FileManager.default
        var isDir: ObjCBool = false
        if !(fm.fileExists(atPath: dir.path, isDirectory: &isDir) && isDir.boolValue) {
            try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        let file = dir.appendingPathComponent(csvFileName(range))
        let part = dir.appendingPathComponent(csvFileName(range) + ".part")
        defer { try? fm.removeItem(at: part) }
        guard fm.createFile(atPath: part.path, contents: nil) else { throw CocoaError(.fileWriteUnknown) }
        let handle = try FileHandle(forWritingTo: part)
        var buffer = ""
        buffer.reserveCapacity(64 * 1024)
        var failure: Error? = nil
        func flush() {
            guard failure == nil, !buffer.isEmpty else { return }
            if let data = buffer.data(using: .utf8) {
                do { try handle.write(contentsOf: data) } catch { failure = error }
            }
            buffer.removeAll(keepingCapacity: true)
        }
        writeCsv(into: { piece in
            buffer += piece
            if buffer.utf8.count >= 64 * 1024 { flush() }
        }, orders)
        flush()
        try handle.close()
        if let e = failure { throw e }
        if fm.fileExists(atPath: file.path) { try fm.removeItem(at: file) }
        try fm.moveItem(at: part, to: file)
        return file
    }

    /// Why an export didn't reach the share sheet, in words that say what to do.
    public static func exportFailureText(_ e: Error) -> String {
        if e is CocoaError || (e as NSError).domain == NSCocoaErrorDomain || (e as NSError).domain == NSPOSIXErrorDomain {
            return "Couldn't save the report file — free up some storage on this phone and try again."
        }
        return "Couldn't export the report — try again."
    }

    // ── The download ──────────────────────────────────────────────────────

    /// GET /admin/conversations with no `limit`: the legacy full list the API keeps
    /// for Reports (admin.py `list_conversations` → `_conversation_rows()`).
    ///
    /// The server does NOT cap it: every conversation, ~14,000 rows / 13 MB in
    /// production. The shared 30-second ceiling suits every other call but would
    /// cut this download short on a phone link and the report would read zero,
    /// so it runs with the long ceiling (the one uploads use). Decoded straight
    /// from the text, and tolerant of the paged `{items, next_cursor}` envelope
    /// should the server ever answer with it.
    public static func fetchEveryConversation(_ http: NeemaHTTP) async throws -> [Conversation] {
        let body = try await http.raw("GET", "/admin/conversations", upload: true)
        let text = body.drop(while: { $0.isWhitespace })
        if text.hasPrefix("[") { return try NeemaJSON.decode([Conversation].self, from: String(text)) }
        if text.hasPrefix("{") { return try NeemaJSON.decode(ConversationPage.self, from: String(text)).items }
        // An empty 2xx is an empty list; anything else (a captive portal's HTML
        // page answering 200) is not a list of conversations, and reading it
        // as one would report zeros as if they were true.
        if text.isEmpty { return [] }
        throw NotAConversationList()
    }

    /// Why the full list didn't arrive. It is the largest download in the app, so
    /// the two phone-network failures get their own words: the long ceiling
    /// passed, or the connection died mid-download.
    public static func loadErrorText(_ e: Error) -> String {
        if let api = e as? ApiError {
            if api.status == 0 && FriendlyErrors.isTimeout(api) {
                return "The download timed out — this report needs every conversation, a large download. Try again on a stronger connection."
            }
            if api.status == 0 && !FriendlyErrors.neverSent(api) {
                return "The download was cut off partway — try again on a stronger connection."
            }
            if api.status == 403 {
                // The web's words, and why: the server refused this agent the full list.
                if let d = FriendlyErrors.readableDetail(api), d.caseInsensitiveCompare("Not authenticated") != .orderedSame,
                   d.caseInsensitiveCompare("Forbidden") != .orderedSame { return d }
                return "Could not load conversations for this report — you don't have permission to see them."
            }
        }
        if e is DecodingError || e is NotAConversationList {
            return "The download arrived incomplete — try again on a stronger connection."
        }
        if let t = e as? TransportError {
            if case .timedOut = t {
                return "The download timed out — this report needs every conversation, a large download. Try again on a stronger connection."
            }
            return "The download was cut off partway — try again on a stronger connection."
        }
        return FriendlyErrors.text(of: e, fallback: "Could not load conversations for this report.")
    }
}
