import Foundation
import XCTest
@testable import NeemaCore

/// The Deals queue at two hundred planned actions with live updates (Android
/// `DealsStressTest`): sends and vetoes one after another, a load that was
/// already on the wire when a send landed, a burst of notifications, and the
/// board's grouping at size.
final class DealsStressTests: DealsTestCase {
    /// The server's queue: what is still pending after the sends and vetoes it received.
    private let resolved = Ref<Set<String>>([])
    /// When set, the next GET /admin/actions answers this instead (an answer from before a send).
    private let staleOnce = Ref<String?>(nil)

    override func setUp() async throws {
        try await super.setUp()
        SalesStressFixtures.install(fake)
    }

    private func serveTheQueue() {
        let resolved = self.resolved, staleOnce = self.staleOnce
        fake.on("GET", "/admin/actions") { _, _ in
            if let s = staleOnce.value { staleOnce.value = nil; return (200, s) }
            let done = resolved.value
            return (200, SalesStressFixtures.actionsJson((0..<200).filter { !done.contains(SalesStressFixtures.actionId($0)) }.map(SalesStressFixtures.actionRow)))
        }
        fake.on("POST", "/admin/actions/[^/]+/(approve|veto)") { r, _ in
            resolved.mutate { $0.insert(actionIdOf(r)) }
            return (200, #"{"ok":true,"sent":"Hello 🙏"}"#)
        }
    }

    func testTwoHundredActionsLoadInOrder() async {
        serveTheQueue()
        let vm = await vm()
        XCTAssertEqual(ids(vm.ui.actions), (0..<200).map(SalesStressFixtures.actionId))
        XCTAssertEqual(fake.callsTo("GET", "/admin/actions").count, 1, "one read per resource on mount")
    }

    func testSendingAndVetoingFiftyInARowSendsEachExactlyOnce() async {
        serveTheQueue()
        let vm = await vm()
        let picked = (0..<50).map { SalesStressFixtures.actionId($0 * 4) }
        for (i, id) in picked.enumerated() { vm.act(id, i % 2 == 0 ? "approve" : "veto") }
        _ = await eventually(timeout: 15) { vm.ui.acting.isEmpty }
        await drain()
        let posts = fake.calls.filter { $0.method == "POST" && $0.path.hasPrefix("/admin/actions/") }
        XCTAssertEqual(posts.count, 50, "one request per action")
        XCTAssertEqual(Set(posts.map { String($0.path.split(separator: "/")[2]) }), Set(picked))
        XCTAssertEqual(vm.ui.actions?.count, 150)
        XCTAssertFalse(picked.contains { ids(vm.ui.actions).contains($0) })
        XCTAssertTrue(vm.ui.acting.isEmpty, "nothing left locked")
    }

    /// A load was already on the wire when a send landed; its (older) answer
    /// arrives after. The sent follow-up must not come back with a live Send
    /// button — not even for a frame — and the loads never overlap.
    func testALoadFromBeforeASendNeverBringsTheSentActionBack() async {
        serveTheQueue()
        let vm = await vm()
        let seen = Ref<[[String]]>([])
        let sub = vm.state.observe { s in seen.mutate { $0.append((s.actions ?? []).map { $0.id }) } }
        defer { sub.cancel() }
        let target = SalesStressFixtures.actionId(3)
        let before = fake.callsTo("GET", "/admin/actions").count

        let hold = fake.hang("GET", "/admin/actions")
        vm.refresh() // the poll's read, now slow
        await drain()
        XCTAssertEqual(hold.waiting, 1)
        staleOnce.value = SalesStressFixtures.actions(200) // the server answered before the send reached it
        vm.act(target, "approve")
        await drain()
        XCTAssertFalse(ids(vm.ui.actions).contains(target))
        let sentAt = seen.value.count
        XCTAssertEqual(hold.waiting, 1, "the reload after the send waits for the read on the wire")
        hold.release()
        let fake = self.fake!
        _ = await eventually(timeout: 15) { fake.callsTo("GET", "/admin/actions").count >= before + 2 && !vm.ui.refreshing }
        await drain()

        XCTAssertFalse(seen.value.dropFirst(sentAt).contains { $0.contains(target) }, "never shown again after the send")
        XCTAssertFalse(ids(vm.ui.actions).contains(target))
        XCTAssertEqual(vm.ui.actions?.count, 199)
        XCTAssertEqual(fake.callsTo("GET", "/admin/actions").count, before + 2, "the slow read and one after the send — no third")
    }

    func testABurstOfTwoHundredNotificationsIsOneReload() async {
        serveTheQueue()
        host.connectLive()
        await drain()
        _ = await vm()
        let before = fake.callsTo("GET", "/admin/actions").count
        for i in 0..<200 {
            host.sockets.last.frame("{\"event\":\"notification\",\"type\":\"\(i % 2 == 0 ? "planned_action" : "hub_event")\",\"title\":\"Neema\",\"body\":\"#\(i)\"}")
        }
        await advance(ScreenLife.EVENT_WINDOW_MS + 1)
        XCTAssertEqual(fake.callsTo("GET", "/admin/actions").count, before + 1, "200 frames, one reload")
    }

    func testADoubleTapWhileTheSendIsOnTheWireSendsOnce() async {
        serveTheQueue()
        let vm = await vm()
        let id = SalesStressFixtures.actionId(0)
        let hold = fake.hang("POST", "/admin/actions/[^/]+/approve")
        for _ in 0..<5 { vm.act(id, "approve") }
        await drain()
        XCTAssertEqual(hold.waiting, 1)
        XCTAssertTrue(vm.ui.acting.contains(id))
        hold.release()
        _ = await eventually(timeout: 15) { vm.ui.acting.isEmpty }
        await drain()
        XCTAssertEqual(fake.calls.filter { $0.method == "POST" && $0.path == "/admin/actions/\(id)/approve" }.count, 1)
        XCTAssertFalse(ids(vm.ui.actions).contains(id))
    }

    func testGroupingFiveThousandDealsIsOnePassAndKeepsOrder() {
        let deals = (0..<5_000).map { i in Deal(id: "d\(i)", customer: "C\(i)", stage: ["new", "qualified", "proposal", "negotiation", ""][i % 5], status: "open") }
        for _ in 0..<3 { _ = DealsRules.groupByStage(deals) }
        let t = DispatchTime.now().uptimeNanoseconds
        let g = DealsRules.columns(deals)
        let ms = Double(DispatchTime.now().uptimeNanoseconds - t) / 1e6
        XCTAssertLessThan(ms, 200, "grouped in \(ms)ms (budget 200)")
        XCTAssertEqual(g.map { $0.stage.id }, ["new", "qualified", "proposal"])
        XCTAssertEqual(g[0].deals.count, 3_000, "unknown stages land under New")
        XCTAssertEqual(g[1].deals.count, 1_000)
        XCTAssertEqual(g[1].deals.map { $0.id }, (0..<5_000).filter { $0 % 5 == 1 }.map { "d\($0)" })
    }
}
