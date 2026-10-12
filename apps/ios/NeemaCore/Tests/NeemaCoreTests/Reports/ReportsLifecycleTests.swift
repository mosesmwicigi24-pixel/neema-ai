import Foundation
import XCTest
@testable import NeemaCore

/// What survives the system restarting the app, a CSV export caught by a
/// rotation, the background or a restart, and a report left open overnight
/// (Android `InsightsLifecycleTest` and `ReportsRolloverTest`).
final class ReportsLifecycleTests: ReportsTestCase {
    func testReportChoicesSurviveARestart() async {
        let vm = await vm()
        vm.setTab(.agents)
        vm.setRange(.custom)
        vm.setCustomFrom(LocalDay(2026, 9, 1))
        vm.setCustomTo(LocalDay(2026, 9, 20))
        let saved = vm.saveUi()
        let fresh = await self.vm()
        XCTAssertTrue(fresh.restoreIfFresh(saved))
        XCTAssertEqual(fresh.ui.tab, .agents)
        XCTAssertEqual(fresh.ui.range, .custom)
        XCTAssertEqual(fresh.ui.customFrom, LocalDay(2026, 9, 1))
        XCTAssertEqual(fresh.ui.customTo, LocalDay(2026, 9, 20))
        XCTAssertFalse(fresh.ui.exportInterrupted, "nothing was being exported")
        _ = await eventually(timeout: 10) { fresh.ui.report?.orders.map { $0.id } == ["o5", "o6"] }
        XCTAssertEqual(fresh.ui.report?.orders.map { $0.id }, ["o5", "o6"], "the report is built for the restored range")
        // A model the screen already showed keeps its own (newer) state.
        XCTAssertFalse(fresh.restoreIfFresh(vm.saveUi()))
    }

    func testABrokenSavedStateLeavesTheDefaults() async {
        let fresh = await vm()
        fresh.restoreUi(#"{"tab":"Nope","range":7,"from":"yesterday"}"#)
        XCTAssertEqual(fresh.ui.tab, .overview)
        XCTAssertEqual(fresh.ui.range, .d30)
        XCTAssertNil(fresh.ui.customFrom)
        fresh.restoreUi("not json")
        XCTAssertEqual(fresh.ui.range, .d30)
    }

    /// The CSV finished while no screen was there to open the share sheet (the
    /// phone was turning, or the app was in the background): it waits for the
    /// next screen, and a second tap meanwhile doesn't write another.
    func testAFinishedExportWaitsForTheScreenToShareIt() async throws {
        let vm = await vm()
        let dir = tempDir()
        vm.exportCsv(dir: dir)
        _ = await eventually(timeout: 10) { vm.ui.readyExport != nil }
        let ready = try XCTUnwrap(vm.ui.readyExport)
        XCTAssertFalse(vm.ui.exporting)
        vm.exportCsv(dir: dir)
        await settle(ms: 50)
        XCTAssertEqual(vm.ui.readyExport, ready, "a second tap waits for the first to be shared")
        vm.exportShown(ready)
        XCTAssertNil(vm.ui.readyExport)
        // Shared: the next tap exports again.
        vm.exportCsv(dir: dir)
        _ = await eventually(timeout: 10) { vm.ui.readyExport != nil }
        XCTAssertNotNil(vm.ui.readyExport)
    }

    /// The system closed the app mid-export: the agent is told once, on return, to export again.
    func testAnExportCutOffByARestartIsReportedOnce() async {
        let vm = await vm()
        vm.exportCsv(dir: tempDir()) // written, not yet shared when the process died
        _ = await eventually(timeout: 10) { vm.ui.readyExport != nil }
        let saved = vm.saveUi()
        let fresh = await self.vm()
        fresh.restoreUi(saved)
        XCTAssertTrue(fresh.ui.exportInterrupted)
        fresh.interruptionShown()
        fresh.interruptionShown()
        XCTAssertEqual(host.toasts.filter { $0.message == ReportsViewModel.EXPORT_INTERRUPTED && $0.type == .warning }.count, 1)
        XCTAssertFalse(fresh.ui.exportInterrupted)
        XCTAssertNil(fresh.ui.readyExport, "the new process has nothing to share")
    }

    // ── Overnight: the report rolls over to the new day ──────────────────────

    /// 23:59 in Nairobi on Friday 25 September, as a Date.
    private func nairobi(_ day: LocalDay, hour: Int, minute: Int) -> Date {
        Date(timeIntervalSince1970: TimeInterval(day.startMillis(zone: Self.NAIROBI) + Int64(hour) * 3_600_000 + Int64(minute) * 60_000) / 1000)
    }

    func testReportRollsOverAtLocalMidnight() async {
        let start = nairobi(LocalDay(2026, 9, 25), hour: 23, minute: 59)
        AppClock.pin(to: start)
        let vm = await vm()
        vm.setRange(.d7)
        _ = await eventually(timeout: 10) { vm.ui.report?.convByDay.count == 7 }
        XCTAssertEqual(vm.ui.today, LocalDay(2026, 9, 25))
        XCTAssertEqual(vm.ui.report?.convByDay.last?.label, "Fri")
        let builds = vm.builds

        // Two minutes later it is Saturday: the next midnight check rebuilds the report.
        AppClock.pin(to: start.addingTimeInterval(120))
        await advance(61_000)
        _ = await eventually(timeout: 10) { vm.ui.today == LocalDay(2026, 9, 26) && vm.ui.report?.convByDay.last?.label == "Sat" }
        XCTAssertEqual(vm.ui.today, LocalDay(2026, 9, 26))
        XCTAssertEqual(vm.ui.report?.convByDay.last?.label, "Sat")
        XCTAssertEqual(vm.ui.report?.convByDay.count, 7)
        XCTAssertEqual(vm.builds, builds + 1)

        // Nothing else changed the inputs: no rebuild before the next midnight.
        await advance(3_600_000)
        await settle(ms: 50)
        XCTAssertEqual(vm.builds, builds + 1)
    }

    func testReportRollsOverOnReturnToTheApp() async {
        let start = nairobi(LocalDay(2026, 9, 25), hour: 22, minute: 0)
        AppClock.pin(to: start)
        let vm = await vm()
        XCTAssertEqual(vm.ui.today, LocalDay(2026, 9, 25))
        host.foreground.update(false)
        await drain()
        // In the pocket overnight (no tick while in the background)…
        AppClock.pin(to: start.addingTimeInterval(10 * 3600))
        await advance(3_600_000)
        XCTAssertEqual(vm.ui.today, LocalDay(2026, 9, 25), "nothing ticks in the background")
        host.foreground.update(true)
        await drain()
        // …and back: the date is read at once.
        XCTAssertEqual(vm.ui.today, LocalDay(2026, 9, 26))
        _ = await eventually(timeout: 10) { vm.ui.report?.convByDay.last?.label == "Sat" }
        XCTAssertEqual(vm.ui.report?.convByDay.last?.label, "Sat")
    }

    /// Each return to the screen re-reads the list once (joining a download in flight); a return to the app does not.
    func testAReturnToTheScreenRereadsTheListOnce() async {
        let vm = await vm()
        XCTAssertEqual(downloads(), 1)
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        _ = await eventually(timeout: 10) { self.downloads() == 2 }
        XCTAssertEqual(downloads(), 2)
        host.foreground.update(false)
        host.foreground.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        await settle(ms: 50)
        XCTAssertEqual(downloads(), 2, "the web doesn't reload on returning to the app either")
    }
}
