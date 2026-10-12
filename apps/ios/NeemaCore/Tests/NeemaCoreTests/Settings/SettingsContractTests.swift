import Foundation
import XCTest
@testable import NeemaCore

/// Settings against crm.py's real handlers (TeamFixtures.settings re-implements
/// each one): exact requests, the server's cleaning echoed back, every error
/// (Android `SettingsContractTest`).
final class SettingsContractTests: SettingsTestCase {

    // ── /admin/settings/directives ───────────────────────────────────────────

    func testDirectivesRoundTrip() async {
        let v = await vm()
        XCTAssertEqual(v.ui.maxChars, TeamFixtures.DIRECTIVES_MAX)
        v.setDirectives("  Push copes this week.\n")
        v.saveDirectives()
        await settled(v)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PUT"); XCTAssertEqual(w.first?.path, "/admin/settings/directives")
        XCTAssertEqual(json(w[0]), el(#"{"directives":"  Push copes this week.\n"}"#))
        XCTAssertEqual(v.ui.directives, "Push copes this week.", "set_directives strips; the box shows what was stored")
    }

    func testDirectivesNeverExceedTheServersCap() async {
        let v = await vm()
        v.setDirectives(String(repeating: "y", count: 900))
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0])?["directives"]?.stringValue?.count, 600)
    }

    func testDirectivesTolerateAMissingMaxChars() async {
        fake.on("GET", "/admin/settings/directives", body: #"{"directives":null}"#)
        let v = await vm()
        XCTAssertEqual(v.ui.directives, "")
        XCTAssertEqual(v.ui.maxChars, 600)
        XCTAssertTrue(v.ui.directivesLoaded)
    }

    func testDirectivesRefusedForANonAdmin() async {
        TeamFixtures.settings(fake, admin: false)
        let v = await vm()
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Couldn't save (admin only)")
    }

    /// No answer and the server still holds the old text: say it may not have saved, and keep what was typed.
    func testDirectivesOfflineSaysSo() async {
        let v = await vm()
        fake.on("PUT", "/admin/settings/directives") { _, _ in throw TransportError.network("Connection reset") }
        v.setDirectives("Push copes this week.")
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertEqual(v.ui.directives, "Push copes this week.")
    }

    // ── /admin/settings/pipeline-stages ──────────────────────────────────────

    func testStagesShowWhatTheServerKept() async {
        let v = await vm()
        // The server trims and cuts to 18; the list shows its answer, not what was typed.
        v.addStage("  Awaiting the deposit money ")
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"stages":["measuring","Awaiting the depos"]}"#))
        XCTAssertEqual(v.ui.stages, ["measuring", "Awaiting the depos"])
    }

    func testStagesRefusedForANonAdmin() async {
        TeamFixtures.settings(fake, admin: false)
        let v = await vm()
        v.addStage("Sampling")
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Only an admin can change pipeline stages.")
        XCTAssertEqual(v.ui.stages, ["measuring"])
    }

    func testTheServersFourStageLimitIsShownVerbatim() async {
        let v = await vm()
        // Another admin filled the list meanwhile: the local count said 1, the server says no.
        fake.on("PUT", "/admin/settings/pipeline-stages", code: 422, body: #"{"detail":"At most 4 custom stages"}"#)
        v.addStage("Sampling")
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "At most 4 custom stages")
    }

    // ── /admin/settings/translation ──────────────────────────────────────────

    func testTranslationDecodesTheSpendAsANumber() async {
        let v = await vm()
        XCTAssertEqual(v.ui.translation?.spend30dUsd ?? 0, 3.4187, accuracy: 0.000001)
        XCTAssertEqual(v.ui.translation?.calls30d, 812)
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"enabled":false}"#))
        XCTAssertEqual(v.ui.translation?.enabled, false)
    }

    func testTranslationToleratesAStringSpendAndMissingKeys() async {
        fake.on("GET", "/admin/settings/translation", body: #"{"enabled":true,"spend_30d_usd":"0.0042"}"#)
        let v = await vm()
        XCTAssertEqual(v.ui.translation?.spend30dUsd ?? 0, 0.0042, accuracy: 0.000001)
        XCTAssertEqual(v.ui.translation?.calls30d, 0)
    }

    func testTranslationRefusedForANonAdminRevertsTheSwitch() async {
        TeamFixtures.settings(fake, admin: false)
        let v = await vm()
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(v.ui.translation?.enabled, true)
        XCTAssertEqual(lastToast()?.message, "Couldn't change that (admin only)")
    }

    // ── /admin/settings/offer ────────────────────────────────────────────────

    func testOfferDecodesTheStoredCampaign() async {
        let v = await vm()
        let o = v.ui.offer!
        XCTAssertEqual(o.maxPercent, 70)
        XCTAssertTrue(o.running)
        XCTAssertEqual(o.says, TeamFixtures.EASTER_SAYS)
        XCTAssertEqual(o.campaign?.percent, 10)
        XCTAssertNil(o.campaign?.startsOn)
        XCTAssertEqual(o.campaign?.categories, ["Vestments"])
    }

    func testOfferToleratesMissingOptionalKeys() async {
        fake.on("GET", "/admin/settings/offer", body: #"{"campaign":{"name":"X","percent":5,"ends_on":"2099-01-01"},"running":true}"#)
        let v = await vm()
        XCTAssertEqual(v.ui.offer?.campaign?.scope, "all")
        XCTAssertEqual(v.ui.offer?.campaign?.skus, [])
        XCTAssertEqual(v.ui.offer?.says, "")
    }

    func testOfferPutSendsTheWholeCampaignAndShowsTheServersVersion() async {
        let v = await vm()
        v.editDraft { $0.name = "  Harvest Offer  "; $0.percent = 20; $0.scope = "all"; $0.categories = []; $0.endsOn = "2099-10-25" }
        v.saveOffer(v.ui.draft)
        await settled(v)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PUT"); XCTAssertEqual(w.first?.path, "/admin/settings/offer")
        let c = sentCampaign(w[0]) ?? [:]
        XCTAssertEqual(Set(c.keys).subtracting(["starts_on"]), ["name", "percent", "scope", "categories", "skus", "ends_on"])
        // The encoder drops a nil starts_on; parse() reads c.get("starts_on") → None either way.
        XCTAssertTrue(c["starts_on"] == nil || c["starts_on"] == .null)
        // parse() trims the name and stores percent as an int.
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Harvest Offer")
        XCTAssertEqual(v.ui.draft.name, "Harvest Offer")
        XCTAssertEqual(v.ui.offer?.running, true)
        XCTAssertEqual(lastToast()?.message, "Offer live — Neema will say: Harvest Offer — 20% off everything in the catalogue, until 25 October 2099")
    }

    func testAnOfferThatStartsLaterIsSavedNotLive() async {
        let v = await vm()
        // "Later" by the server's calendar (the real date): the app's clock is pinned to
        // 25 Sep 2026, and the fake's is_running reads the real today in UTC.
        let start = LocalDay.of(millis: Int64(Date().timeIntervalSince1970 * 1000), zone: TimeZone(identifier: "UTC")!).plusDays(10).description
        v.editDraft { $0.startsOn = start }
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(v.ui.offer?.running, false)
        XCTAssertEqual(v.ui.offer?.says, "")
        XCTAssertEqual(lastToast()?.message, "Offer saved — Neema starts mentioning it on \(Fmt.date(start))")
        XCTAssertEqual(lastToast()?.type, .success)
    }

    func testAnOfferWhoseLastDayHasPassedIsSavedNotLive() async {
        let v = await vm()
        v.editDraft { $0.endsOn = "2026-01-31" }
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(v.ui.offer?.running, false)
        XCTAssertEqual(lastToast()?.message, SettingsWords.OFFER_EXPIRED)
    }

    func testEndingTheOfferSendsNull() async {
        let v = await vm()
        v.saveOffer(nil)
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"campaign":null}"#))
        XCTAssertNil(v.ui.offer?.campaign)
        XCTAssertEqual(lastToast()?.message, SettingsWords.OFFER_ENDED)
    }

    func testOfferRefusedForANonAdmin() async {
        TeamFixtures.settings(fake, admin: false)
        let v = await vm()
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Couldn't save that offer (admin only)")
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Easter Sale")
    }

    func testWhatTheClientLetsThroughTheServerAccepts() async {
        let v = await vm()
        // Every campaign offerProblem() passes, parse() must accept (no surprise 422s).
        let base = v.ui.draft
        var products = base; products.scope = "products"; products.skus = ["CS-BLK-16"]; products.categories = []
        var later = base; later.scope = "all"; later.percent = 70; later.startsOn = "2099-01-01"
        var one = base; one.percent = 1
        for c in [base, products, later, one] {
            mark()
            v.saveOffer(c)
            await settled(v)
            XCTAssertEqual(lastToast()?.type, .success, "\(c)")
            XCTAssertEqual(toasts.count, 1, "\(c)")
        }
    }

    // ── /admin/client-crashes (admin.py client_crash_list) ───────────────────

    func testCrashReportsDecodeNewestFirst() async throws {
        let list = try await host.api.crashes.list(limit: 20)
        XCTAssertEqual(fake.callsTo("GET", "/admin/client-crashes").first?.query, "limit=20")
        XCTAssertEqual(list.map { $0.id }, ["crash-7f3a", "anr-20c1"])
        XCTAssertEqual(list[0].kind, "crash"); XCTAssertEqual(list[1].kind, "anr")
        XCTAssertEqual(list[0].agentName, "Grace Wanjiru")
        XCTAssertEqual(list[0].sdk, 34); XCTAssertEqual(list[0].build, "142"); XCTAssertEqual(list[0].device, "samsung SM-S918B")
        XCTAssertTrue(list[0].trace.contains("Composer.kt:214"))
        XCTAssertEqual(Fmt.timeAgo(list[0].at), "42m ago")
    }

    func testCrashReportsRefusedWithoutManageSettings() async {
        fake.on("GET", "/admin/client-crashes", code: 403, body: #"{"detail":"Missing permission: manage_settings"}"#)
        let e = await expectApi { try await self.host.api.crashes.list() }
        XCTAssertEqual(e?.status, 403)
        XCTAssertEqual(FriendlyErrors.text(of: e!), "Missing permission: manage_settings")
    }
}
