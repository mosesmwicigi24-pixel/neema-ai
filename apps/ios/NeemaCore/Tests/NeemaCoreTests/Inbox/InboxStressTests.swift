import Foundation
import XCTest
@testable import NeemaCore

/// The inbox at the shop's real scale (Android `InboxStressTest`): 5,000
/// conversations in cursor pages, a 2,000-message thread with photos and
/// voice notes, bursts of 200 socket frames into the list and the open
/// thread, a search typed at speed and a bulk release across 500 rows. Every
/// test asserts correctness under load (order, no duplicates, nothing
/// dropped, bounded memory) and the number of requests made; the pure merges
/// are also timed, with bounds generous enough for a debug build on a slow
/// CI machine.
@MainActor
final class InboxStressTests: XCTestCase {
    var fake: FakeNeema!

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
    }

    override func tearDown() async throws { AppClock.reset(); try await super.tearDown() }

    func vm(live: Bool = false) async -> (TestHost, InboxViewModel) {
        let host = TestHost(fake: fake)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        if live { host.connectLive() }
        await drain()
        return (host, vm)
    }

    func frame(_ host: TestHost, _ text: String) async { host.sockets.last.frame(text); await drain() }
    func gets(_ path: String) -> Int { fake.callsTo("GET", path).count }

    /// Scroll to the end: each page is asked for once the one before it has landed.
    func pageAll(_ vm: InboxViewModel, max: Int = 500) async {
        var n = 0
        while vm.inbox.value.hasMore && n < max {
            n += 1
            vm.loadMore()
            await eventually(timeout: 10) { !vm.inbox.value.loadingMore }
        }
        await drain()
    }

    /// Median of five runs, in ms — a pure function, warmed up first.
    func timeMs(_ block: () -> Void) -> Double {
        for _ in 0..<2 { block() }
        return (0..<5).map { _ -> Double in let t = Date(); block(); return Date().timeIntervalSince(t) * 1000 }.sorted()[2]
    }

    /// Generous for `swift test`'s debug build; the release build is many times faster.
    let budgetMs = 1_500.0

    // ═══════════════ 5,000 conversations ═══════════════

    func testInbox5000PagesThroughInServerOrderNoDuplicatesOnePerPage() async {
        let server = InboxStressFixtures.Inbox(fake)
        let (_, vm) = await vm()
        await pageAll(vm)
        let ids = vm.inbox.value.orderIds
        XCTAssertEqual(ids.count, 5_000)
        XCTAssertEqual(Set(ids).count, 5_000)
        XCTAssertEqual(ids, server.ids)
        // One request per page — page one, then 99 cursors, each asked for exactly once.
        XCTAssertEqual(server.cursors.count, 100)
        XCTAssertEqual(Set(server.cursors.map { $0 ?? "" }).count, server.cursors.count)
        XCTAssertFalse(vm.inbox.value.hasMore)
        // The same people on two channels are one row: 5,000 − 100 pairs.
        let rows = vm.rows
        XCTAssertEqual(rows.count, 4_900)
        XCTAssertEqual(Set(rows.map { $0.key }).count, rows.count)
        // Newest first, all the way down.
        let times = rows.map { Fmt.millis($0.rep.lastMessageAt) ?? 0 }
        XCTAssertTrue(zip(times, times.dropFirst()).allSatisfy { $0 >= $1 })
        // Every cached row is one the list can show (nothing orphaned or doubled).
        XCTAssertEqual(vm.inbox.value.cache.count, 5_000)
    }

    func testInbox5000RefreshWhileScrolledDeepKeepsEveryPageAndPutsPageOneOnTop() async {
        let server = InboxStressFixtures.Inbox(fake)
        let (_, vm) = await vm()
        await pageAll(vm)
        server.bump("s4999", 4_999)
        let before = server.cursors.count
        vm.refresh()
        await eventually(timeout: 10) { vm.inbox.value.orderIds.first == "s4999" }
        XCTAssertEqual(server.cursors.count, before + 1, "one request: page one only")
        let ids = vm.inbox.value.orderIds
        XCTAssertEqual(ids.count, 5_000)
        XCTAssertEqual(Set(ids).count, 5_000)
        XCTAssertEqual(ids.first, "s4999")
        XCTAssertEqual(vm.rows.first?.rep.id, "s4999")
    }

    func testInbox5000SearchTypedAtSpeedIsOneRequest() async {
        let server = InboxStressFixtures.Inbox(fake)
        let (host, vm) = await vm()
        let before = server.queries.count
        let text = "purple cassock"
        for i in 0..<text.count {
            vm.setSearch(String(text.prefix(i + 1)))
            await host.clock.advance(by: 80)
        }
        await host.clock.advance(by: 300)
        XCTAssertEqual(server.queries.dropFirst(before).map { $0 ?? "" }, ["purple cassock"])
    }

    // ═══════════════ A burst of 200 socket frames ═══════════════

    func testSocketBurst200ListAndThreadStayExactOneRefetchOneWindowCheck() async {
        _ = InboxStressFixtures.Inbox(fake)
        let (host, vm) = await vm(live: true)
        await pageAll(vm, max: 4) // 250 rows loaded: every frame below lands on a row on screen
        vm.select("s1"); await drain()
        let listBefore = gets("/admin/conversations")
        let threadBefore = gets("/admin/conversations/s1/messages")
        let windowBefore = gets("/admin/conversations/s1/window")
        var threadIds: [String] = []
        for k in 0..<200 {
            switch k % 4 {
            case 0: await frame(host, InboxStressFixtures.newMessage("s1", "live-\(k)", "burst \(k)")); threadIds.append("live-\(k)")
            case 1: await frame(host, InboxStressFixtures.newMessage("s\(k)", "other-\(k)", "burst \(k)"))
            case 2: await frame(host, InboxStressFixtures.interceptChanged("s\(k)", "human"))
            default: await frame(host, InboxStressFixtures.typing("s1"))
            }
        }
        // A duplicate delivery of a frame already shown changes nothing.
        await frame(host, InboxStressFixtures.newMessage("s1", "live-0", "burst 0"))
        let live = (vm.thread.value.messages["s1"] ?? []).filter { $0.id.hasPrefix("live-") }.map { $0.id }
        XCTAssertEqual(live, threadIds, "every frame, once, in arrival order")
        // The last frame's conversation is on top, and every row moved exactly once.
        XCTAssertEqual(vm.rows.first?.rep.id, "s197")
        XCTAssertEqual(Set(vm.rows.map { $0.key }).count, vm.rows.count)
        XCTAssertEqual(vm.inbox.value.cache["s2"]?.interceptMode, "human")
        // Nothing was fetched during the burst…
        XCTAssertEqual(gets("/admin/conversations"), listBefore)
        XCTAssertEqual(gets("/admin/conversations/s1/messages"), threadBefore)
        // …then one list refetch and one window check for the whole burst.
        await host.clock.advance(by: 1_500)
        XCTAssertEqual(gets("/admin/conversations"), listBefore + 1)
        XCTAssertEqual(gets("/admin/conversations/s1/window"), windowBefore + 1)
    }

    // ═══════════════ A 2,000-message thread ═══════════════

    func testThread2000OlderPagesMergeInOrderNoDuplicatesOnePerPage() async {
        _ = InboxStressFixtures.Inbox(fake)
        let t = InboxStressFixtures.Thread(fake, "s3")
        let (_, vm) = await vm()
        vm.select("s3"); await drain()
        var n = 0
        while vm.thread.value.hasMore["s3"] == true && n < 100 {
            n += 1
            vm.loadOlder()
            await eventually(timeout: 10) { vm.thread.value.olderLoading.isEmpty }
        }
        await drain()
        let msgs = vm.thread.value.messages["s3"] ?? []
        XCTAssertEqual(msgs.count, 2_000 + t.events)
        XCTAssertEqual(Set(msgs.map { $0.id }).count, msgs.count)
        XCTAssertEqual(msgs.filter { !$0.isSystem }.count, 2_000)
        XCTAssertTrue(zip(msgs, msgs.dropFirst()).allSatisfy { $0.millis <= $1.millis })
        // Page one, 39 older pages, and the empty page that says "that's all".
        XCTAssertEqual(t.befores.count, 41)
        XCTAssertEqual(Set(t.befores.map { $0 ?? "" }).count, t.befores.count)
        // The rendered rows: every message accounted for (albums fold photos in).
        let rows = ThreadRows.build(ThreadRows.sort(msgs), unreadSnap: 0)
        XCTAssertEqual(Set(rows.map { $0.key }).count, rows.count)
    }

    func testOpenThreadsKeepABoundedCache() async {
        _ = InboxStressFixtures.Inbox(fake)
        let (_, vm) = await vm()
        await pageAll(vm, max: 2)
        for i in 0..<40 { vm.select("s\(i)"); await drain() }
        let cached = vm.thread.value.messages
        XCTAssertLessThanOrEqual(cached.count, InboxViewModel.MAX_CACHED_THREADS, "cached \(cached.count)")
        XCTAssertNotNil(cached["s39"])
        // Reopening an evicted thread loads it again.
        vm.select("s0"); await drain()
        XCTAssertFalse((vm.thread.value.messages["s0"] ?? []).isEmpty)
    }

    // ═══════════════ Bulk select across hundreds of rows ═══════════════

    func testBulk500SelectAllReleasesEachOnce() async {
        _ = InboxStressFixtures.Inbox(fake, total: 500, pairs: 0, mode: "human")
        fake.on("POST", "/admin/conversations/[^/]+/release", body: #"{"ok":true,"mode":"ai"}"#)
        let (host, vm) = await vm()
        await pageAll(vm)
        vm.enterSelect()
        vm.selectAllOrClear()
        XCTAssertEqual(vm.list.value.selected.count, 500)
        XCTAssertEqual(vm.selectedHeldIds().count, 500)
        vm.toggleRow("s7"); vm.toggleRow("s7")
        XCTAssertEqual(vm.list.value.selected.count, 500)
        vm.releaseSelected()
        await eventually(timeout: 20) { !vm.list.value.bulkBusy && !vm.list.value.selectMode }
        await drain()
        let posts = fake.calls.filter { $0.method == "POST" && $0.path.hasSuffix("/release") }.map { $0.path }
        XCTAssertEqual(posts.count, 500)
        XCTAssertEqual(Set(posts).count, 500)
        XCTAssertEqual(host.toasts.last?.message, "500 conversations released back to Neema")
        XCTAssertFalse(vm.list.value.selectMode)
    }

    // ═══════════════ The open thread off page one: every refresh re-reads its row ═══════════════

    func testRefreshRereadsTheOpenThreadsRowEveryTime() async {
        typealias Contract = InboxFixtures.Contract
        fake.on("GET", "/admin/conversations/summary", body: Contract.summary)
        fake.on("GET", "/admin/conversations", body: Contract.page([Contract.peterWa]))
        fake.on("GET", "/admin/conversations/resolve", body: Contract.resolved)
        let seen = Ref(0)
        fake.on("GET", "/admin/conversations/k2") { _, _ in seen.mutate { $0 += 1 }; return (200, Contract.maryMsgr) }
        let (host, vm) = await vm()
        host.openConvKey.value = "+250788123456|BH-1042"
        await drain()
        XCTAssertEqual(vm.thread.value.activeId, "k2")
        // k2 is open but not on page one: every refresh re-reads its row.
        for _ in 0..<20 {
            let n = seen.value
            vm.refresh(); await drain()
            XCTAssertEqual(seen.value, n + 1, "the open thread's row was re-read by the refresh")
        }
        XCTAssertTrue(vm.inbox.value.orderIds.contains("k2"))
    }

    // ═══════════════ Pure functions, timed ═══════════════

    func conv(_ i: Int) -> String { InboxStressFixtures.row(i, Int64(i + 1)) }

    func testGroupRows5000IsFast() {
        let convs = (0..<5_000).map { Inbox.normalized(Inbox.conversation(of: JSONValue.parse(conv($0))!)!) }
        var s = InboxUi()
        for c in convs { s.cache[c.id] = c }
        s.orderIds = convs.map { $0.id }
        let rows = Inbox.groupRows(s, me: Fixtures.ME_ID)
        XCTAssertEqual(rows.count, 4_900)
        let ms = timeMs { _ = Inbox.groupRows(s, me: Fixtures.ME_ID) }
        XCTAssertLessThan(ms, budgetMs, "grouping 5,000 rows took \(ms) ms")
        // A filter over them too (the Human tab).
        var h = s
        h.filters.tab = "human"
        h.orderKey = Inbox.filterKey(of: h.filters)
        let human = Inbox.groupRows(h, me: Fixtures.ME_ID)
        XCTAssertTrue(!human.isEmpty && human.allSatisfy { g in g.siblings.allSatisfy { $0.interceptMode == "human" } })
    }

    func thread(_ n: Int) -> [ThreadMsg] {
        let f = Fixtures.withFixtures()
        let t = InboxStressFixtures.Thread(f, "x", total: n)
        return t.json.map { try! NeemaJSON.decode(ThreadMsg.self, from: $0) }
    }

    func testMergeThread2000AndAppend200FramesAreFastAndExact() {
        let all = thread(2_050)
        let existing = Array(all.prefix(all.count - 50))
        let incoming = Array(all.suffix(60)) // overlaps 10, adds 50
        let merged = Inbox.mergeThread(existing, incoming)
        XCTAssertEqual(merged.count, all.count)
        XCTAssertEqual(merged.map { $0.id }, all.map { $0.id })
        XCTAssertLessThan(timeMs { _ = Inbox.mergeThread(existing, incoming) }, budgetMs, "merge took")
        XCTAssertLessThan(timeMs { _ = Inbox.mergeServer(existing, incoming) }, budgetMs, "server merge took")
        // 200 socket frames appended one by one onto the 2,000 (each deduped against the thread).
        let frames = (0..<200).map { k in ThreadMsg(id: "live-\(k)", direction: "inbound", sender: "user", text: "burst \(k)", createdAt: Inbox.nowIso()) }
        var out = existing
        let ms = timeMs { var t = existing; for f in frames { t = Inbox.appendWs(t, f) }; out = t }
        XCTAssertEqual(out.count, existing.count + 200)
        XCTAssertLessThan(ms, budgetMs, "200 appends onto 2,000 took \(ms) ms")
    }

    func testThreadRows2000AreFastWithAlbumsAndEvents() {
        let msgs = thread(2_000)
        let ms = timeMs { _ = ThreadRows.build(ThreadRows.sort(msgs), unreadSnap: 12) }
        XCTAssertLessThan(ms, budgetMs, "building 2,000 rows took \(ms) ms")
        let rows = ThreadRows.build(ThreadRows.sort(msgs), unreadSnap: 12)
        XCTAssertTrue(rows.contains { if case .bubble(_, let album) = $0 { return album != nil }; return false })
        XCTAssertEqual(rows.filter { if case .newDivider = $0 { return true }; return false }.count, 1)
    }

    func testWaTextLongMessageIsFastAndKeepsEveryLink() {
        let text = InboxStressFixtures.longMessage(200)
        let out = WaText.format(text)
        XCTAssertFalse(out.plain.contains("*Item"))
        XCTAssertEqual(out.links.count, 400)
        let ms = timeMs { _ = WaText.format(text) }
        XCTAssertLessThan(ms, budgetMs, "formatting \(text.count) chars took \(ms) ms")
    }
}
