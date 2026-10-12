import XCTest
@testable import NeemaCore

/// The customer panel stays current while it is open, as CustomerSidebar.tsx's
/// loadProfile effect keeps the web's — and catches up on what a phone misses
/// that a browser tab would not: a socket that dropped, an app that went to
/// the background, an order that landed (Android `CustomerLiveTest`). Driven
/// through the real socket, the host's orders feed and the fake backend, on
/// virtual time.
final class CustomerLiveTests: CustomerTestCase {
    private var row: Conversation { CustomerFixtures.conversation("c1") }
    private var path: String { peterPath }
    /// One fixed copy: the fixture's timestamps follow the wall clock, the server's do not.
    private var baseOrders = ""

    override func setUp() async throws {
        try await super.setUp()
        baseOrders = Fixtures.orders
        host.orders.update(try NeemaJSON.decode([Order].self, from: baseOrders))
        host.connectLive()
        await drain()
    }

    private func gets(_ p: String? = nil) -> Int { calls("GET", p ?? path).count }

    private func peter(_ edit: (String) -> String = { $0 }) -> CustomerProfile {
        try! NeemaJSON.decode(CustomerProfile.self, from: edit(CustomerFixtures.peter))
    }

    /// A panel on screen for `conv`; `fetch` replaces the GET when a test must hold or reorder answers.
    private func shown(_ conv: Conversation? = nil, fetch: ((String, String?) async throws -> CustomerProfile)? = nil) async -> CustomerViewModel {
        let v = CustomerViewModel(host: host, conversation: conv ?? row, fetchProfile: fetch, sleep: host.clock.sleeper)
        vms.append(v)
        v.onShown()
        await drain()
        return v
    }

    /// Answers that wait until the test releases them, in request order.
    private final class Held: @unchecked Sendable {
        private let lock = NSLock()
        private var conts: [CheckedContinuation<CustomerProfile, Error>] = []
        var count: Int { lock.sync { conts.count } }
        func fetch(_ key: String, _ channel: String?) async throws -> CustomerProfile {
            try await withCheckedThrowingContinuation { c in lock.sync { conts.append(c) } }
        }
        func complete(_ i: Int, _ p: CustomerProfile) { lock.sync { conts[i] }.resume(returning: p) }
    }

    private func ordersWith(_ extra: String) throws -> [Order] {
        try NeemaJSON.decode([Order].self, from: withRows(baseOrders, [extra]))
    }

    // ── Row changes (the web's loadProfile deps) ────────────────────────────

    func testAStageTheAiSetsWhileThePanelIsOpenShowsUpWithoutReopening() async {
        let vm = await shown()
        XCTAssertEqual(vm.profile?.leadStage, "proposal")
        // The AI advanced the lead; the inbox's refetch hands the panel the moved row.
        fake.on("GET", path, body: peterWith("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"negotiation\""))
        var moved = row; moved.leadStage = "negotiation"
        vm.sync(moved); await drain()
        XCTAssertEqual(gets(), 1, "coalesced: nothing leaves at once")
        await advance()
        XCTAssertEqual(gets(), 2)
        XCTAssertEqual(vm.profile?.leadStage, "negotiation")
        XCTAssertFalse(vm.ui.loading, "a live reload never blanks the panel")
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testANewMessageRenameOrNewKeyOnTheRowEachReload() async {
        let vm = await shown()
        var r = row
        r.lastMessageAt = "2026-09-26T09:00:00Z"; vm.sync(r); await advance()
        r.name = "Fr. P. Kamau"; vm.sync(r); await advance()
        r.ordersCount = 4; vm.sync(r); await advance()
        XCTAssertEqual(gets(), 4)
    }

    func testABurstOfRowUpdatesCostsOneRequest() async {
        let vm = await shown()
        // Twelve moves of the row 50 ms apart (a chatty customer, the inbox poll, a rename).
        for i in 0..<12 {
            var r = row; r.lastMessageAt = "2026-09-26T09:00:\(10 + i)Z"
            vm.sync(r)
            await advance(50)
        }
        XCTAssertEqual(gets(), 1)
        await advance()
        XCTAssertEqual(gets(), 2)
    }

    func testAnUnchangedRowOrAnotherThreadsRowCostsNothing() async {
        let vm = await shown()
        for _ in 0..<5 { vm.sync(row) }
        vm.sync(CustomerFixtures.conversation("c2"))
        await advance()
        XCTAssertEqual(gets(), 1)
    }

    func testARowThatGainsAWaIdReloadsAgainstTheNewKey() async {
        var psid = row; psid.waId = nil; psid.externalId = "PSID77"; psid.channel = "messenger"
        fake.on("GET", "/admin/customers/PSID77", body: CustomerFixtures.mary)
        let vm = await shown(psid)
        XCTAssertEqual(gets("/admin/customers/PSID77"), 1)
        var gained = psid; gained.waId = CustomerFixtures.MARY
        vm.sync(gained)
        await advance()
        XCTAssertEqual(gets("/admin/customers/\(CustomerFixtures.MARY)"), 1)
    }

    func testAQuietReloadThatFailsKeepsWhatIsPainted() async {
        let vm = await shown()
        fake.on("GET", path, code: 502, body: #"{"detail":"hub down"}"#)
        var r = row; r.lastMessageAt = "2026-09-26T09:00:00Z"
        vm.sync(r); await advance()
        XCTAssertEqual(gets(), 2)
        XCTAssertEqual(vm.profile?.name, "Fr. Peter Kamau")
        XCTAssertEqual(vm.profile?.totalOrders, 24, "the real profile, not the fallback")
        XCTAssertFalse(vm.ui.refreshing)
    }

    // ── Out-of-order answers ────────────────────────────────────────────────

    func testTheNewestAnswerWinsWhenAnOlderOneLandsLate() async {
        let held = Held()
        let vm = await shown(fetch: held.fetch)
        held.complete(0, peter()); await drain()
        vm.load(showSpinner: false); await drain()            // answer 1: slow
        vm.load(showSpinner: false); await drain()            // answer 2: the newest
        XCTAssertEqual(held.count, 3)
        held.complete(2, peter { $0.replacingOccurrences(of: "\"lead_stage\":\"proposal\"", with: "\"lead_stage\":\"won\"") }); await drain()
        held.complete(1, peter { $0.replacingOccurrences(of: "\"lead_stage\":\"proposal\"", with: "\"lead_stage\":\"contacted\"") }); await drain()
        XCTAssertEqual(vm.profile?.leadStage, "won")
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testAnAnswerThatLeftBeforeAnEditIsNotPaintedOverIt() async {
        let held = Held()
        let vm = await shown(fetch: held.fetch)
        held.complete(0, peter()); await drain()
        vm.load(showSpinner: false); await drain()            // a live reload in flight…
        vm.addTag("choir"); await drain()                     // …the agent adds a tag (PATCH accepted)
        XCTAssertTrue(vm.profile!.tags.contains("choir"))
        held.complete(1, peter()); await drain()              // the pre-edit answer lands: no "choir"
        XCTAssertTrue(vm.profile!.tags.contains("choir"), "the optimistic edit survives the stale answer")
        // …and the reload runs again, now that the edit has settled.
        await advance()
        XCTAssertEqual(held.count, 3)
        held.complete(2, peter { $0.replacingOccurrences(of: "\"tags\":[\"vip\",\"clergy\",\"bulk\"]", with: "\"tags\":[\"vip\",\"clergy\",\"bulk\",\"choir\"]") }); await drain()
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk", "choir"])
    }

    func testAReloadAskedForMidSaveWaitsForTheSave() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let getsDuringSave = Ref(-1)
        fake.on("PATCH", path) { _, _ in
            // A pull-to-refresh and a row move land while the stage is being saved.
            onMainSync {
                vmRef.value?.load(showSpinner: false)
                var r = CustomerFixtures.conversation("c1"); r.lastMessageAt = "2026-09-26T09:00:00Z"
                vmRef.value?.sync(r)
            }
            getsDuringSave.value = self.gets()
            return (200, #"{"ok":true}"#)
        }
        let vm = await shown()
        vmRef.value = vm
        vm.setStage("won"); await drain()
        XCTAssertEqual(getsDuringSave.value, 1, "nothing is fetched over an unsettled save")
        XCTAssertEqual(vm.profile?.leadStage, "won")
        await advance()
        XCTAssertEqual(gets(), 2, "one catch-up fetch once it settled")
    }

    // ── Typing is never clobbered ───────────────────────────────────────────

    func testTheNotesDraftSurvivesALiveReloadAndKeepsItsBase() async {
        let vm = await shown()
        let base = vm.profile!.notes!
        vm.startEditNotes()
        vm.setNoteDraft("\(base)\n\nWants gold thread on the stole.")
        // A call summary is appended server-side while the agent types; the row moves.
        let summary = "Call summary: asked about delivery to Nyeri."
        fake.on("GET", path, body: peterWith("Ask about the Easter order in March.", "Ask about the Easter order in March.\\n\\n\(summary)"))
        var r = row; r.lastMessageAt = "2026-09-26T09:00:00Z"
        vm.sync(r); await advance()
        XCTAssertTrue(vm.profile!.notes!.hasSuffix(summary))
        XCTAssertTrue(vm.ui.editNotes, "still editing")
        XCTAssertEqual(vm.ui.noteDraft, "\(base)\n\nWants gold thread on the stole.")
        XCTAssertEqual(vm.ui.notesBase, base)

        vm.saveNotes(); await drain()
        let body = lastBody("PATCH", path)
        XCTAssertEqual(body["notes"]?.content, "\(base)\n\nWants gold thread on the stole.")
        XCTAssertEqual(body["notes_base"]?.content, base, "the snapshot the edit STARTED from, so the server keeps the summary")
        XCTAssertFalse(vm.ui.editNotes)
        XCTAssertNil(vm.ui.notesBase)
        // The server merged the summary back in: fetch what it kept.
        await advance()
        XCTAssertEqual(gets(), 3)
    }

    func testCancellingTheNotesEditDropsTheDraftAndBase() async {
        let vm = await shown()
        vm.startEditNotes()
        vm.setNoteDraft("scratch")
        vm.cancelEditNotes()
        XCTAssertFalse(vm.ui.editNotes)
        XCTAssertNil(vm.ui.notesBase)
        XCTAssertTrue(calls("PATCH", path).isEmpty)
        vm.startEditNotes()
        XCTAssertEqual(vm.ui.noteDraft, vm.profile?.notes, "a fresh edit starts from the notes, not the old draft")
    }

    // ── Missed frames: foreground, reconnect ────────────────────────────────

    func testComingBackToTheForegroundCatchesUp() async {
        let vm = await shown()
        host.foreground.update(false)
        await advance()
        XCTAssertEqual(gets(), 1)
        host.foreground.update(true)
        await advance()
        XCTAssertEqual(gets(), 2)
        XCTAssertFalse(vm.ui.loading)
    }

    func testASocketReconnectCatchesUpOnFramesItMissed() async {
        _ = await shown()
        host.sockets.last.fail()
        await drain()
        XCTAssertFalse(host.socket.connected.value)
        await advance(2_001)                          // LiveSocket retries after 2 s
        XCTAssertEqual(host.sockets.sockets.count, 2)
        host.sockets.last.open()
        await advance()
        XCTAssertEqual(gets(), 2)
    }

    func testAForegroundReturnThatAlsoReconnectsCostsOneRequest() async {
        _ = await shown()
        host.foreground.update(false)
        host.sockets.last.fail()
        await advance(2_001)
        host.foreground.update(true)
        host.sockets.last.open()
        await advance()
        XCTAssertEqual(gets(), 2)
    }

    // ── Orders ──────────────────────────────────────────────────────────────

    func testAnOrderUpdateForThisCustomerRefreshesTheProfile() async throws {
        let vm = await shown()
        fake.on("GET", path, body: peterWith("\"total_orders\":24", "\"total_orders\":25"))
        // The dashboard's `order_update` handling refetches /admin/orders; the host's feed then carries the new row.
        host.orders.update(try ordersWith(Fixtures.orderRow("o9", CustomerFixtures.PETER, "[]", "5000.0", "confirmed", "whatsapp", 1)))
        await drain()
        XCTAssertEqual(gets(), 1)
        await advance()
        XCTAssertEqual(gets(), 2)
        XCTAssertEqual(vm.profile?.totalOrders, 25)
    }

    func testAnOrderForSomeoneElseCostsNothing() async throws {
        _ = await shown()
        host.orders.update(try ordersWith(Fixtures.orderRow("o9", CustomerFixtures.MARY, "[]", "5000.0", "confirmed", "messenger", 1)))
        await advance()
        XCTAssertEqual(gets(), 1)
    }

    func testAnOrdersPollThatChangesNothingCostsNothing() async {
        _ = await shown()
        host.orders.update(host.orders.value); host.orders.update(host.orders.value)
        await advance()
        XCTAssertEqual(gets(), 1)
    }

    // ── On screen or not ────────────────────────────────────────────────────

    func testAHiddenPanelMakesNoRequests() async throws {
        let vm = await shown()
        var r = row; r.lastMessageAt = "2026-09-26T09:00:00Z"
        vm.sync(r)
        vm.onHidden()                           // closed before the coalesced reload left
        host.foreground.update(false)
        host.foreground.update(true)
        host.sockets.last.fail(); await advance(2_001); host.sockets.last.open()
        host.orders.update(try ordersWith(Fixtures.orderRow("o9", CustomerFixtures.PETER, "[]", "5000.0", "confirmed", "whatsapp", 1)))
        await advance()
        XCTAssertEqual(gets(), 1)
    }

    func testReopeningThePanelRefetchesQuietly() async {
        let vm = await shown()
        vm.onHidden()
        vm.onShown()
        XCTAssertNotNil(vm.profile, "the last profile stays painted meanwhile")
        await advance()
        XCTAssertEqual(gets(), 2)
        XCTAssertFalse(vm.ui.loading)
    }

    func testSwitchingConversationsNeverShowsTheOldProfile() async {
        let first = await shown()
        XCTAssertEqual(first.profile?.name, "Fr. Peter Kamau")
        first.onHidden()
        // The next thread's profile is slow; its panel must never paint Peter meanwhile.
        let held = Held()
        let next = await shown(CustomerFixtures.conversation("c2"), fetch: held.fetch)
        let seen = Ref<[String?]>([next.profile?.name])
        let sub = next.state.observe { s in seen.value.append(s.profile?.name) }
        defer { sub.cancel() }
        XCTAssertTrue(next.ui.loading)
        XCTAssertNil(next.profile)
        // Peter's panel answering late changes nothing for Mary's.
        first.load(showSpinner: false); await drain()
        held.complete(0, try! NeemaJSON.decode(CustomerProfile.self, from: CustomerFixtures.mary)); await drain()
        XCTAssertEqual(Set(seen.value.map { $0 ?? "nil" }), ["nil", "Rev. Mary Achieng"])
        XCTAssertEqual(next.profile?.name, "Rev. Mary Achieng")
        XCTAssertFalse(next.ui.loading)
    }
}
