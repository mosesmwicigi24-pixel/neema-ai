import Foundation
import XCTest
@testable import NeemaCore

/// The leads kanban at five hundred leads (Android `LeadsStressTest`): the
/// board's figures from one pass, a hundred card moves in a row, and a read
/// that was already on the wire when a card moved (it must not throw the card back).
final class LeadsStressTests: LeadsTestCase {
    override func setUp() async throws {
        try await super.setUp()
        SalesStressFixtures.install(fake)
    }

    private func stageOf(_ vm: LeadsViewModel, _ id: String) -> String { vm.ui.leads.first { $0.id == id }!.leadStage }
    private func ms(_ block: () -> Void) -> Double {
        let t = DispatchTime.now().uptimeNanoseconds
        block()
        return Double(DispatchTime.now().uptimeNanoseconds - t) / 1e6
    }

    func testTheBoardMatchesTheWebsPerColumnFilters() async {
        let vm = await vm()
        let leads = vm.ui.leads
        XCTAssertEqual(leads.count, 500)
        let stages = vm.ui.stages
        XCTAssertEqual(stages.count, 8, "the custom Measuring column is there")
        let filtered = LeadsRules.filterLeads(leads, filterStage: "all", search: "")
        let board = LeadsRules.buildBoard(leads, filtered: filtered, stages: stages)
        for s in stages {
            // LeadsView: leads.filter(l => l.lead_stage === stage.id), once per pill and once per column.
            XCTAssertEqual(board.counts[s.id], leads.filter { s.matches($0.leadStage) }.count, s.id)
            XCTAssertEqual(board.columns[s.id]!.map { $0.id }, filtered.filter { s.matches($0.leadStage) }.map { $0.id }, s.id)
            XCTAssertEqual(board.columnValue[s.id]!, filtered.filter { s.matches($0.leadStage) }.reduce(0) { $0 + $1.totalSpent }, accuracy: 0.001, s.id)
        }
        XCTAssertEqual(board.columns.values.reduce(0) { $0 + $1.count }, 500, "every lead lands in exactly one column")
        XCTAssertEqual(board.pipelineValue, leads.filter { !["lost", "won"].contains($0.leadStage.lowercased()) }.reduce(0) { $0 + $1.totalSpent }, accuracy: 0.001)
        XCTAssertEqual(board.wonValue, leads.filter { $0.leadStage.lowercased() == "won" }.reduce(0) { $0 + $1.totalSpent }, accuracy: 0.001)
        // A search narrows the columns but not the pills' counts.
        let narrow = LeadsRules.buildBoard(leads, filtered: LeadsRules.filterLeads(leads, filterStage: "all", search: "bishop"), stages: stages)
        XCTAssertEqual(board.counts, narrow.counts)
        let n = narrow.columns.values.reduce(0) { $0 + $1.count }
        XCTAssertTrue(n >= 1 && n < 500)
    }

    func testBuildingTheBoardForFiveThousandLeadsIsFast() async {
        let vm = await vm()
        let base = vm.ui.leads
        var many: [Lead] = []
        for k in 0..<10 { for l in base { var c = Lead(id: "\(l.id)-\(k)", waId: l.waId, name: l.name, leadStage: l.leadStage, totalSpent: l.totalSpent); c.tags = l.tags; many.append(c) } }
        let stages = LeadsRules.buildStages(["Measuring", "Fitting"])
        for _ in 0..<3 { _ = LeadsRules.buildBoard(many, filtered: many, stages: stages) }
        let t = ms {
            let filtered = LeadsRules.filterLeads(many, filterStage: "all", search: "fr.")
            _ = LeadsRules.buildBoard(many, filtered: filtered, stages: stages)
            _ = LeadsRules.buildBoard(many, filtered: many, stages: stages)
        }
        // Android budgets 200 ms on the JVM; an unoptimised Linux debug build gets the same order of magnitude.
        XCTAssertLessThan(t, 400, "5,000 leads, 9 columns in \(t)ms (budget 400)")
    }

    func testAHundredMovesInARowEachSaveOnceAndNeverReloadTheBoard() async {
        let vm = await vm()
        let before = gets()
        let moved = (0..<100).map { SalesStressFixtures.leadId($0 * 5) }
        for id in moved { vm.moveTo(vm.ui.leads.first { $0.id == id }!, "won") }
        _ = await eventually(timeout: 15) { vm.ui.saving.isEmpty }
        await drain()
        XCTAssertEqual(fake.calls.filter { $0.method == "PATCH" && $0.path.hasPrefix("/admin/leads/") }.count, 100, "one PATCH per card")
        XCTAssertTrue(moved.allSatisfy { stageOf(vm, $0) == "won" })
        XCTAssertEqual(gets(), before, "a stage move needs no re-read of 500 leads")
        XCTAssertTrue(vm.ui.saving.isEmpty)
    }

    /// A read of the board was on the wire (a pull) when the operator moved a
    /// card; the read's answer — from before the move — lands after it. The
    /// card stays where it was moved; the next read is the server's truth.
    func testAReadFromBeforeAMoveDoesNotThrowTheCardBack() async {
        let vm = await vm()
        let id = SalesStressFixtures.leadId(7)
        let lead = vm.ui.leads.first { $0.id == id }!
        let before = lead.leadStage
        let hold = fake.hang("GET", "/admin/leads")
        vm.refresh()
        await drain()
        vm.moveTo(lead, "won")
        await drain()
        XCTAssertEqual(stageOf(vm, id), "won")
        hold.release() // the answer from before the move
        _ = await eventually(timeout: 15) { !vm.ui.refreshing && vm.ui.saving.isEmpty }
        await drain()
        XCTAssertEqual(stageOf(vm, id), "won")
        XCTAssertNotEqual(before, "won")
        XCTAssertEqual(hold.caught, 1, "the slow read plus nothing else")
        // A read that starts after the move is the server's truth again (this
        // fake never stores a move, so the card goes back to what it says).
        vm.refresh()
        _ = await eventually(timeout: 15) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(stageOf(vm, id), before)
    }

    func testASecondTapWhileAMoveIsSavingIsIgnored() async {
        let vm = await vm()
        let lead = vm.ui.leads.first { $0.id == SalesStressFixtures.leadId(12) }!
        let hold = fake.hang("PATCH", "/admin/leads/.+")
        vm.moveTo(lead, "won")
        vm.moveTo(lead, "lost")
        await drain()
        XCTAssertEqual(hold.waiting, 1)
        XCTAssertEqual(stageOf(vm, lead.id), "won")
        hold.release()
        _ = await eventually(timeout: 15) { vm.ui.saving.isEmpty }
        await drain()
        XCTAssertEqual(fake.calls.filter { $0.method == "PATCH" && $0.path == "/admin/leads/\(lead.id)" }.count, 1)
        XCTAssertEqual(stageOf(vm, lead.id), "won")
    }

    func testOverlayKeepsOnlyTheProtectedRowsAndIsLinear() async {
        let vm = await vm()
        let server = vm.ui.leads
        let onScreen = server.map { l -> Lead in var c = l; if l.id == "u0003" { c.leadStage = "won" }; return c }.filter { $0.id != "u0009" }
        let out = LeadsRules.overlayLocal(server, onScreen: onScreen, keepLocal: ["u0003", "u0009"])
        XCTAssertEqual(out.first { $0.id == "u0003" }?.leadStage, "won")
        XCTAssertFalse(out.contains { $0.id == "u0009" }, "a lead deleted here stays gone")
        XCTAssertEqual(out.count, server.count - 1)
        XCTAssertEqual(out.map { $0.id }, server.filter { $0.id != "u0009" }.map { $0.id })
        var many: [Lead] = []
        for k in 0..<10 { for l in server { many.append(Lead(id: "\(l.id)-\(k)", waId: l.waId, name: l.name, leadStage: l.leadStage)) } }
        let keep = Set(many.map { $0.id }.enumerated().filter { $0.offset % 7 == 0 }.map { $0.element })
        for _ in 0..<3 { _ = LeadsRules.overlayLocal(many, onScreen: many, keepLocal: keep) }
        let t = ms { _ = LeadsRules.overlayLocal(many, onScreen: many, keepLocal: keep) }
        XCTAssertLessThan(t, 400, "5,000 rows overlaid in \(t)ms (budget 400)")
    }
}
