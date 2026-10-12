import Foundation
import XCTest
@testable import NeemaCore

/// Reports under a real shop's load (the reports rows of Android
/// `InsightsStressTest`): 10,000 conversations, 1,000 orders, 200 agents.
/// Asserts the figures stay exact against a straightforward re-implementation
/// of the web's maths, that the heavy work is bounded in time and in requests,
/// and that nothing stacks. Time bounds are generous (an unoptimised Linux
/// debug build) so they only catch an O(n²) slip.
final class ReportsStressTests: ReportsTestCase {
    private var convs: [Conversation] = []
    private var orders: [Order] = []
    private var agents: [Agent] = []

    override func setUp() async throws {
        try await super.setUp()
        convs = InsightsStressFixtures.conversations()
        orders = InsightsStressFixtures.orders()
        agents = InsightsStressFixtures.agents()
    }

    private func ms(_ block: () -> Void) -> Double {
        let t = DispatchTime.now().uptimeNanoseconds
        block()
        return Double(DispatchTime.now().uptimeNanoseconds - t) / 1e6
    }

    // ── The web's maths, written the obvious way ─────────────────────────────

    private func naive(_ all: [Conversation], _ orders: [Order], _ agents: [Agent], _ range: ReportRange, _ cf: LocalDay?, _ ct: LocalDay?,
                       _ now: Int64, _ zone: TimeZone) -> Report {
        let day: Int64 = 86_400_000
        let from: Int64, to: Int64
        switch range {
        case .d7: from = now - 7 * day; to = now
        case .d90: from = now - 90 * day; to = now
        case .custom where cf != nil && ct != nil: from = cf!.startMillis(zone: zone); to = ct!.plusDays(1).startMillis(zone: zone) - 1
        default: from = now - 30 * day; to = now
        }
        func inRange(_ iso: String?) -> Bool { Fmt.millis(iso).map { $0 >= from && $0 <= to } ?? false }
        func localDay(_ iso: String?) -> LocalDay? { LocalDay.of(iso, zone: zone) }
        let c = all.filter { inRange(ReportsRules.reportAt($0)) }
        let o = orders.filter { inRange($0.createdAt) }
        let n = min(range == .d7 ? 7 : (range == .d30 ? 14 : 30), 14)
        let toDay = LocalDay.of(millis: to, zone: zone)
        let days = (0..<n).map { toDay.minusDays(n - 1 - $0) }
        var cd: [LocalDay: Int] = [:]
        for x in c { if let d = localDay(ReportsRules.reportAt(x)) { cd[d, default: 0] += 1 } }
        var od: [LocalDay: [Order]] = [:]
        for x in o { if let d = localDay(x.createdAt) { od[d, default: []].append(x) } }
        let stats = agents.map { a -> AgentStat in
            let mine = c.filter { $0.assignedAgentId == a.id }
            let wa = Set(mine.compactMap { $0.waId })
            return AgentStat(agent: a, handled: mine.count, revenue: o.filter { !$0.waId.isEmpty && wa.contains($0.waId) }.reduce(0) { $0 + $1.total })
        }.enumerated().sorted { a, b in a.element.handled != b.element.handled ? a.element.handled > b.element.handled : a.offset < b.offset }.map { $0.element }
        return Report(convs: c, orders: o, revenue: o.filter { $0.status != "cancelled" }.reduce(0) { $0 + $1.total },
                      humanConvs: c.filter { $0.interceptMode == "human" }.count, aiConvs: c.filter { $0.interceptMode == "ai" }.count,
                      pending: o.filter { $0.status == "pending" }.count, confirmed: o.filter { $0.status == "confirmed" }.count,
                      delivered: o.filter { $0.status == "delivered" }.count, cancelled: o.filter { $0.status == "cancelled" }.count,
                      convByDay: days.map { BarPoint($0.weekdayShort, Double(cd[$0] ?? 0)) },
                      orderByDay: days.map { d in BarPoint(d.weekdayShort, (od[d] ?? []).reduce(0) { $0 + $1.total }) },
                      agentStats: stats)
    }

    private func assertSame(_ expected: Report, _ actual: Report, _ label: String = "") {
        XCTAssertEqual(expected.convs.map { $0.id }, actual.convs.map { $0.id }, label)
        XCTAssertEqual(expected.orders.map { $0.id }, actual.orders.map { $0.id }, label)
        XCTAssertEqual(expected.revenue, actual.revenue, accuracy: 0.0, label)
        XCTAssertEqual([expected.humanConvs, expected.aiConvs, expected.pending, expected.confirmed, expected.delivered, expected.cancelled],
                       [actual.humanConvs, actual.aiConvs, actual.pending, actual.confirmed, actual.delivered, actual.cancelled], label)
        XCTAssertEqual(expected.convByDay, actual.convByDay, label)
        XCTAssertEqual(expected.orderByDay, actual.orderByDay, label)
        XCTAssertEqual(expected.agentStats.map { "\($0.agent.id):\($0.handled):\($0.revenue)" }, actual.agentStats.map { "\($0.agent.id):\($0.handled):\($0.revenue)" }, label)
    }

    private func build(_ range: ReportRange, _ f: LocalDay? = nil, _ t: LocalDay? = nil) -> Report {
        ReportsRules.buildReport(convs, orders: orders, agents: agents, range: range, customFrom: f, customTo: t, now: Self.NOW_MS, zone: Self.NAIROBI)
    }

    // ── Aggregation ──────────────────────────────────────────────────────────

    func testTenThousandConversationsReportExactlyWhatTheWebWouldForEveryRange() {
        XCTAssertEqual(convs.count, 10_000)
        XCTAssertEqual(orders.count, 1_000)
        XCTAssertEqual(agents.count, 200)
        let cases: [(ReportRange, LocalDay?, LocalDay?)] = [
            (.d7, nil, nil), (.d30, nil, nil), (.d90, nil, nil),
            (.custom, LocalDay(2026, 6, 1), LocalDay(2026, 9, 25)),
            (.custom, LocalDay(2026, 9, 25), LocalDay(2026, 9, 25)),
        ]
        for (range, f, t) in cases {
            let want = naive(convs, orders, agents, range, f, t, Self.NOW_MS, Self.NAIROBI)
            assertSame(want, build(range, f, t), "\(range)")
        }
        // The load is real: most agents hold threads, the 90-day report spans thousands.
        let r90 = build(.d90)
        XCTAssertGreaterThan(r90.convs.count, 7_000)
        XCTAssertGreaterThan(r90.agentStats.filter { $0.handled > 0 }.count, 150)
    }

    func testBuildingTheReportForTenThousandRowsIsFast() {
        for _ in 0..<2 { _ = build(.d90) } // warm up
        let t = ms { _ = build(.d90) }
        // Android budgets 500 ms on the JVM; an unoptimised Linux debug build gets the same order of magnitude.
        XCTAssertLessThan(t, 1_500, "report over 10k conversations took \(t)ms")
    }

    // ── The model ────────────────────────────────────────────────────────────

    func testTheModelDownloadsTheFullListOnceAndBuildsTheReportOffTheScreen() async throws {
        fake = Fixtures.withFixtures()
        InsightsStressFixtures.install(fake)
        let h = TestHost(fake: fake, ordersFeed: true)
        hosts.append(h)
        await drain()
        _ = await eventually(timeout: 30) { !(h.feed?.reading ?? false) && !h.orders.value.isEmpty }
        try await h.refreshAgents()
        let vm = await vm(h)
        XCTAssertEqual(downloads(), 1, "one full-list download")
        let r = try XCTUnwrap(vm.ui.report)
        XCTAssertEqual(vm.ui.allConvs?.count, 10_000)
        XCTAssertEqual(h.orders.value.count, 1_000)
        XCTAssertEqual(h.agents.value.count, 200)
        // The same numbers the pure function gives for the loaded lists.
        assertSame(ReportsRules.buildReport(vm.ui.allConvs!, orders: h.orders.value, agents: h.agents.value, range: .d30, customFrom: nil, customTo: nil,
                                            now: Self.NOW_MS, zone: Self.NAIROBI), r)

        // A range change rebuilds from the parsed rows — no second download.
        vm.setRange(.d90)
        _ = await eventually(timeout: 30) { (vm.ui.report?.convs.count ?? 0) > r.convs.count }
        XCTAssertGreaterThan(vm.ui.report?.convs.count ?? 0, r.convs.count)
        vm.setRange(.d7)
        _ = await eventually(timeout: 30) { (vm.ui.report?.convs.count ?? Int.max) < r.convs.count }
        XCTAssertLessThan(vm.ui.report?.convs.count ?? Int.max, r.convs.count)
        XCTAssertEqual(downloads(), 1)
    }

    func testTheAgentsTableKeepsEveryAgentWithUniqueKeysAndIndexedNames() async throws {
        let r = build(.d90)
        let agentsTable = try XCTUnwrap(ReportsRules.tableFor(.agents, r, agents: agents, now: Self.NOW_MS))
        XCTAssertEqual(agentsTable.rows.count, 200)
        XCTAssertEqual(Set(agentsTable.keys).count, 200)
        let convTable = try XCTUnwrap(ReportsRules.tableFor(.conversations, r, agents: agents, now: Self.NOW_MS))
        XCTAssertEqual(convTable.rows.count, 50, "the web's first 50")
        XCTAssertEqual(Set(convTable.keys).count, 50)
        XCTAssertEqual(ReportsRules.tableFor(.orders, r, agents: agents, now: Self.NOW_MS)?.rows.count, 20)
        XCTAssertNil(ReportsRules.tableFor(.overview, r, agents: agents, now: Self.NOW_MS))
        // Building all three tables for a 10k report is cheap enough to do per tab switch.
        let t = ms { for _ in 0..<20 { for tab in ReportTab.allCases { _ = ReportsRules.tableFor(tab, r, agents: agents, now: Self.NOW_MS) } } }
        XCTAssertLessThan(t, 1_500, "tables took \(t)ms")
    }

    func testDuplicateIdsNeverCollideAsRowKeys() {
        XCTAssertEqual(ReportsRules.uniqueKeys(["a", "b", "a", "c", "b"]), ["a", "b", "a#2", "c", "b#4"])
        let many = ReportsRules.uniqueKeys([String](repeating: "same", count: 5_000))
        XCTAssertEqual(Set(many).count, 5_000)
    }

    // ── CSV export ───────────────────────────────────────────────────────────

    func testTenThousandOrdersExportStreamedToAFileMatchingTheCsv() async throws {
        let big = InsightsStressFixtures.orders(10_000)
        let dir = tempDir("stress")
        var file: URL? = nil
        let t = ms { file = try? ReportsRules.writeReportCsv(dir: dir, orders: big, range: .d90) }
        let url = try XCTUnwrap(file)
        XCTAssertLessThan(t, 6_000, "export of 10k rows took \(t)ms")
        let text = try String(contentsOf: url, encoding: .utf8)
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        XCTAssertEqual(lines.count, 10_001)
        XCTAssertEqual(lines.first, "Date,Customer,Amount,Status")
        XCTAssertEqual(text, ReportsRules.reportCsv(big))
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent(url.lastPathComponent + ".part").path), "no half-written file is left behind")
    }

    func testTheExportWritesOffTheScreenAndHandsTheFileBack() async throws {
        fake = Fixtures.withFixtures()
        InsightsStressFixtures.install(fake)
        let h = TestHost(fake: fake, ordersFeed: true)
        hosts.append(h)
        await drain()
        _ = await eventually(timeout: 30) { !(h.feed?.reading ?? false) && !h.orders.value.isEmpty }
        let vm = await vm(h)
        vm.setRange(.d90)
        _ = await eventually(timeout: 30) { (vm.ui.report?.convs.count ?? 0) > 7_000 }
        let dir = tempDir("stress-export")
        vm.exportCsv(dir: dir)
        _ = await eventually(timeout: 30) { vm.ui.readyExport != nil }
        let ready = try XCTUnwrap(vm.ui.readyExport)
        XCTAssertEqual(ready.range, .d90)
        let lines = try String(contentsOf: ready.file, encoding: .utf8).split(separator: "\n", omittingEmptySubsequences: false)
        XCTAssertEqual(lines.count, vm.ui.report!.orders.count + 1)
        XCTAssertFalse(vm.ui.exporting, "the button is free again")
        vm.exportShown(ready)
        XCTAssertNil(vm.ui.readyExport)
    }
}
