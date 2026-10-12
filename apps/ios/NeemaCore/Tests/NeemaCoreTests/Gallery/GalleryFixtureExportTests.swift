import Foundation
import XCTest
@testable import NeemaCore

/// Not a test of behaviour: the generator for the app's screenshot gallery
/// (`NeemaAppTests/Gallery`). Run with `NEEMA_GALLERY_OUT=<dir>` to drive
/// every screen's model against the full fixture set and write the answers
/// the app will be served — `fixtures.json`: one entry per distinct GET the
/// screens made (method, path, query, status, body), plus the signed-in agent.
///
///     NEEMA_GALLERY_OUT=/tmp/gallery swift test --filter GalleryFixtureExport
///     cp /tmp/gallery/fixtures.json apps/ios/NeemaAppTests/Gallery/fixtures.json
@MainActor
final class GalleryFixtureExportTests: XCTestCase {
    func testExportGalleryFixtures() async throws {
        guard let out = ProcessInfo.processInfo.environment["NEEMA_GALLERY_OUT"], !out.isEmpty else {
            throw XCTSkip("set NEEMA_GALLERY_OUT=<dir> to export the gallery fixtures")
        }
        AppClock.pin(to: PINNED)
        defer { AppClock.reset() }
        let fake = Fixtures.withFixtures()
        // Later registrations win: the calls log first (its customer profile is the small one), then the reports' full set,
        // the inbox page, the customers, the sales screens, the team.
        CallsFixtures.install(fake)
        ReportsFixtures.install(fake)
        InboxFixtures.install(fake)
        CustomerFixtures.install(fake)
        SalesFixtures.install(fake)
        TeamFixtures.install(fake)
        TeamFixtures.settings(fake)
        fake.on("GET", "/admin/calls/channels", body: #"{"whatsapp":{"inbound":true,"outbound":true,"video":false,"sdp":"answer"},"messenger":{"inbound":false,"outbound":false,"video":false},"instagram":{"inbound":false,"outbound":false,"video":false}}"#)
        let host = TestHost(fake: fake, ordersFeed: true, catalogFeed: true)
        _ = try? await host.refreshAgents()
        host.refetchMe()
        await drain()
        _ = await eventually(timeout: 5) { host.me.value != nil }

        // Every screen, as the app opens it.
        let inbox = InboxViewModel(host: host)
        let orders = OrdersViewModel(host: host)
        let catalog = CatalogViewModel(host: host)
        let deals = DealsViewModel(host: host)
        let leads = LeadsViewModel(host: host)
        let overview = OverviewViewModel(host: host)
        let reports = ReportsViewModel(host: host)
        let team = TeamViewModel(host: host)
        let profile = ProfileViewModel(host: host)
        let settings = SettingsViewModel(host: host)
        settings.calling.start()
        // The calls console (the log, the channels, the first row's transcript) and Settings' crash reports card.
        host.calls.start()
        let calls = CallsViewModel(host: host)
        calls.load()
        _ = try? await host.api.crashes.list(limit: 20)
        for life in [orders.life, catalog.life, deals.life, leads.life, overview.life, reports.life, team.life] { life?.shown.update(true) }
        await drain()
        await settle(ms: 300)
        // The first thread, and its customer panel.
        if let firstId = JSONValue.parse(InboxFixtures.conversations[0])?.objectValue?["id"]?.stringValue,
           let first = try? await host.api.conversations.get(id: firstId) {
            inbox.select(first.id)
            await drain()
            await settle(ms: 300)
            let customer = CustomerViewModel(host: host, conversation: first)
            await drain()
            await settle(ms: 300)
            customer.close()
        }
        _ = await eventually(timeout: 10) { reports.ui.report != nil && !overview.ui.statsLoading && !team.ui.rolesLoading && !settings.busy && !settings.calling.ui.loading && calls.calls.value != nil }
        if let first = calls.calls.value?.first { calls.select(first); calls.toggleTranscript(first.callId) }
        await drain()
        await settle(ms: 300)
        await drain()
        await settle(ms: 300)
        _ = (profile, leads)

        // Replay every distinct GET through the fake and write what it answered.
        var seen = Set<String>()
        var responses: [JSONValue] = []
        for call in fake.calls where call.method == "GET" {
            let key = "\(call.path)?\(call.query ?? "")"
            if !seen.insert(key).inserted { continue }
            let url = URL(string: "https://neema.test/api\(call.path)\(call.query.map { "?\($0)" } ?? "")")!
            let reply = try await fake.send(HTTPRequest(method: "GET", url: url))
            responses.append(.object([
                "method": .string("GET"), "path": .string(call.path), "query": .string(call.query ?? ""),
                "status": .number(Double(reply.status)), "body": .string(String(decoding: reply.body, as: UTF8.self)),
            ]))
        }
        let me = host.me.value!
        let doc = JSONValue.object([
            "agent": .object(["id": .string(me.id), "email": .string(me.email), "name": .string(me.name), "role": .string(me.role), "isSuperuser": .bool(me.isSuperuser)]),
            "pinnedMillis": .number(Double(AppClock.now())),
            "responses": .array(responses),
        ])
        try FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
        let file = URL(fileURLWithPath: out).appendingPathComponent("fixtures.json")
        try Data(doc.text.utf8).write(to: file)
        print("gallery fixtures: \(responses.count) responses → \(file.path)")
        for v in [inbox as AnyObject, orders, catalog, deals, leads, overview, reports, team, profile] { _ = v }
        inbox.close(); orders.close(); catalog.close(); deals.close(); leads.close(); overview.close(); reports.close(); team.close(); profile.close(); settings.close(); calls.close()
        host.logout()
        XCTAssertGreaterThan(responses.count, 10)
    }
}
