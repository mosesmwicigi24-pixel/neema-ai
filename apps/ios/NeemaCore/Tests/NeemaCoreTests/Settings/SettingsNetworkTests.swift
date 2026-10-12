import Foundation
import XCTest
@testable import NeemaCore

/// Standing orders, translation, the offer and pipeline stages on a bad phone network (Android `SettingsNetworkTest`).
final class SettingsNetworkTests: SettingsTestCase {
    private let cards = ["directives", "translation", "offer", "pipeline-stages"]

    // ── Loads ────────────────────────────────────────────────────────────────

    func testEveryCardOfflineSaysWhyNoneLoadsForeverAndEachRetriesAlone() async {
        for c in cards { fake.failOffline("GET", "/admin/settings/\(c)") }
        let v = await vm()
        XCTAssertEqual(Set(v.ui.loadErrors.keys), ["directives", "translation", "offer", "stages"])
        XCTAssertTrue(v.ui.loadErrors.values.allSatisfy { $0 == FriendlyErrors.OFFLINE_TEXT }, "\(v.ui.loadErrors)")
        XCTAssertFalse(v.ui.directivesLoaded, "standing orders stay locked: an empty box must not be saved over the real ones")
        XCTAssertNil(v.ui.stages, "no stage list to add to")
        // Adding a stage to a list that never arrived would replace the real one: refused.
        XCTAssertFalse(v.addStage("Sampling"))
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(since.filter { $0.method == "PUT" }.count, 0)

        // Back online: each card's Retry reads only that card.
        TeamFixtures.settings(fake)
        mark()
        v.retry("stages")
        await settled(v)
        XCTAssertEqual(since.map { $0.path }, ["/admin/settings/pipeline-stages"])
        XCTAssertEqual(v.ui.stages, ["measuring"])
        v.retry("directives")
        await settled(v)
        XCTAssertTrue(v.ui.directivesLoaded)
        v.retry("translation"); v.retry("offer")
        await settled(v)
        XCTAssertTrue(v.ui.loadErrors.isEmpty)
    }

    func testGarbledBodiesNoCrashCardSaysWhy() async {
        fake.on("GET", "/admin/settings/offer", body: "<html>captive portal</html>")
        fake.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages": 7}"#)
        let v = await vm()
        XCTAssertEqual(v.ui.loadErrors["offer"], FriendlyErrors.GARBLED_TEXT)
        XCTAssertNotNil(v.ui.loadErrors["stages"], "a stage list that is not a list is an error, never \"no custom stages\"")
        XCTAssertNil(v.ui.stages)
        XCTAssertEqual(v.ui.directives, "Always offer free delivery within Nairobi on orders above KES 10,000.", "the other cards load")
    }

    func testPullToRefreshFailingKeepsEveryCardAsItWas() async {
        let v = await vm()
        for c in cards { fake.failTimeout("GET", "/admin/settings/\(c)") }
        v.refresh()
        await settled(v)
        XCTAssertTrue(v.ui.directivesLoaded)
        XCTAssertEqual(v.ui.stages, ["measuring"])
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Easter Sale")
        XCTAssertTrue(v.ui.loadErrors.isEmpty, "no error over a card already showing")
        XCTAssertFalse(v.ui.refreshing)
    }

    // ── Standing orders ──────────────────────────────────────────────────────

    func testDirectivesTimeoutButLandedCountsAsSaved() async {
        let v = await vm()
        let f = fake!
        f.failTimeout("PUT", "/admin/settings/directives") { _ in
            f.on("GET", "/admin/settings/directives", body: #"{"directives":"Push copes this week.","max_chars":600}"#)
        }
        v.setDirectives("Push copes this week.")
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(lastToast()?.message, SettingsWords.DIRECTIVES_SAVED)
    }

    func testDirectivesTimeoutNotLandedKeepsTheText() async {
        let v = await vm()
        fake.failTimeout("PUT", "/admin/settings/directives")
        v.setDirectives("Push copes this week.")
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertEqual(v.ui.directives, "Push copes this week.")
        XCTAssertFalse(v.ui.savingDirectives)
    }

    func testDirectivesStatuses() async {
        let v = await vm()
        v.setDirectives("Push copes this week.")
        let cases: [(Int, String?, String)] = [
            (403, #"{"detail":"Admin only"}"#, "Couldn't save (admin only)"),
            (429, "", FriendlyErrors.BUSY_TEXT),
            (500, "Internal Server Error", "Couldn't save the standing orders — try again."),
            (502, nil, FriendlyErrors.DOWN_TEXT),
        ]
        for (code, body, want) in cases {
            if let b = body { fake.on("PUT", "/admin/settings/directives", code: code, body: b) } else { fake.htmlPage("PUT", "/admin/settings/directives", code: code) }
            v.saveDirectives()
            await settled(v)
            XCTAssertEqual(lastToast()?.message, want, "\(code)")
            XCTAssertEqual(v.ui.directives, "Push copes this week.")
        }
    }

    func testDirectivesDoubleTapSendsOnce() async {
        let v = await vm()
        let vmRef = Ref<SettingsViewModel?>(v)
        fake.on("PUT", "/admin/settings/directives") { _, _ in
            onMainSync { vmRef.value?.saveDirectives() }
            return (200, #"{"ok":true,"directives":"x"}"#)
        }
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(puts("directives"), 1)
    }

    func testDirectivesWithAnExpiredSessionKeepTheText() async {
        let v = await vm()
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        fake.on("PUT", "/admin/settings/directives", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        v.setDirectives("Push copes this week.")
        v.saveDirectives()
        await settled(v)
        XCTAssertTrue(host.sessionExpired.value, "the session-expired dialog")
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.EXPIRED_TEXT)
        XCTAssertEqual(v.ui.directives, "Push copes this week.")
    }

    // ── Translation ──────────────────────────────────────────────────────────

    func testTranslationTimeoutShowsWhatTheServerHas() async {
        let v = await vm()
        let f = fake!
        // It switched off on the server; only the answer was lost.
        f.failTimeout("PUT", "/admin/settings/translation") { _ in
            f.on("GET", "/admin/settings/translation", body: #"{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}"#)
        }
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(v.ui.translation?.enabled, false)
        XCTAssertTrue(toasts.allSatisfy { $0.type != .error }, "no failure claimed for a change that happened")
    }

    func testTranslationTimeoutNotLandedSwitchGoesBackAndSaysSo() async {
        let v = await vm()
        fake.failTimeout("PUT", "/admin/settings/translation")
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(v.ui.translation?.enabled, true)
        XCTAssertEqual(lastToast()?.message, "Couldn't reach the server — translation is still on")
    }

    func testTranslationOfflineSwitchGoesBack() async {
        let v = await vm()
        fake.failOffline("PUT", "/admin/settings/translation")
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(v.ui.translation?.enabled, true)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.OFFLINE_TEXT)
    }

    func testTranslationDoubleTapSendsOnce() async {
        let v = await vm()
        let vmRef = Ref<SettingsViewModel?>(v)
        fake.on("PUT", "/admin/settings/translation") { _, _ in
            onMainSync { vmRef.value?.toggleTranslation() }
            return (200, #"{"ok":true,"enabled":false}"#)
        }
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(puts("translation"), 1)
        XCTAssertEqual(v.ui.translation?.enabled, false)
    }

    // ── Offer ────────────────────────────────────────────────────────────────

    func testOfferTimeoutButLandedCountsAsSaved() async {
        let v = await vm()
        let f = fake!
        f.failTimeout("PUT", "/admin/settings/offer") { _ in
            f.on("GET", "/admin/settings/offer", body: #"{"campaign":{"name":"Harvest","percent":15,"scope":"all","categories":[],"skus":[],"starts_on":null,"ends_on":"2099-01-31"},"running":true,"says":"Harvest — 15% off everything, until 31 January 2099","max_percent":70}"#)
        }
        v.editDraft { $0.name = "Harvest"; $0.percent = 15; $0.scope = "all"; $0.categories = []; $0.endsOn = "2099-01-31" }
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Offer live — Neema will say: Harvest — 15% off everything, until 31 January 2099")
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Harvest")
    }

    func testOfferTimeoutNotLandedKeepsTheDraft() async {
        let v = await vm()
        fake.failTimeout("PUT", "/admin/settings/offer")
        v.editDraft { $0.name = "Harvest"; $0.percent = 15 }
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertEqual(v.ui.draft.name, "Harvest")
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Easter Sale")
    }

    func testEndingTheOfferTimesOutButItEndedCountsAsEnded() async {
        let v = await vm()
        let f = fake!
        f.failTimeout("PUT", "/admin/settings/offer") { _ in TeamFixtures.noOffer(f) }
        v.saveOffer(nil)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, SettingsWords.OFFER_ENDED)
        XCTAssertNil(v.ui.offer?.campaign)
    }

    func testOfferStatuses() async {
        let v = await vm()
        v.editDraft { $0.name = "Harvest" }
        let cases: [(Int, String?, String)] = [
            (403, #"{"detail":"Admin only"}"#, "Couldn't save that offer (admin only)"),
            (422, "{\"detail\":\"\(TeamFixtures.OFFER_422)\"}", "Couldn't save that offer — \(TeamFixtures.OFFER_422)"),
            (429, "", FriendlyErrors.BUSY_TEXT),
            (503, nil, FriendlyErrors.DOWN_TEXT),
        ]
        for (code, body, want) in cases {
            if let b = body { fake.on("PUT", "/admin/settings/offer", code: code, body: b) } else { fake.htmlPage("PUT", "/admin/settings/offer", code: code) }
            v.saveOffer(v.ui.draft)
            await settled(v)
            XCTAssertEqual(lastToast()?.message, want, "\(code)")
            XCTAssertEqual(v.ui.draft.name, "Harvest")
        }
    }

    func testOfferDoubleTapSendsOnce() async {
        let v = await vm()
        let vmRef = Ref<SettingsViewModel?>(v)
        fake.on("PUT", "/admin/settings/offer") { _, _ in
            onMainSync { vmRef.value?.saveOffer(nil) }
            return (200, #"{"ok":true,"campaign":null,"running":false,"says":""}"#)
        }
        v.saveOffer(nil)
        await settled(v)
        XCTAssertEqual(puts("offer"), 1)
    }

    // ── Pipeline stages ──────────────────────────────────────────────────────

    func testAddStageFailingKeepsTheTypedLabel() async {
        let v = await vm()
        fake.failOffline("PUT", "/admin/settings/pipeline-stages")
        var cleared = false
        XCTAssertTrue(v.addStage("Sampling") { cleared = true })
        await settled(v)
        XCTAssertFalse(cleared, "the label stays in the box")
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.OFFLINE_TEXT)
        XCTAssertEqual(v.ui.stages, ["measuring"])
        // Online again: the same label, and now it clears.
        TeamFixtures.settings(fake)
        v.addStage("Sampling") { cleared = true }
        await settled(v)
        XCTAssertTrue(cleared)
        XCTAssertEqual(v.ui.stages, ["measuring", "Sampling"])
    }

    func testAddStageTimeoutButLandedCountsAsAdded() async {
        let v = await vm()
        let f = fake!
        f.failTimeout("PUT", "/admin/settings/pipeline-stages") { _ in
            f.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":["measuring","Sampling"]}"#)
        }
        var cleared = false
        v.addStage("Sampling") { cleared = true }
        await settled(v)
        XCTAssertTrue(cleared)
        XCTAssertEqual(v.ui.stages, ["measuring", "Sampling"])
        XCTAssertTrue(toasts.allSatisfy { $0.type != .error })
    }

    func testAddStageTimeoutNotLandedSaysSoAndShowsTheServersList() async {
        let v = await vm()
        fake.failTimeout("PUT", "/admin/settings/pipeline-stages")
        var cleared = false
        v.addStage("Sampling") { cleared = true }
        await settled(v)
        XCTAssertFalse(cleared)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertEqual(v.ui.stages, ["measuring"])
    }

    func testStageDoubleTapSendsOnce() async {
        let v = await vm()
        let vmRef = Ref<SettingsViewModel?>(v)
        let secondRefused = Ref(false)
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ in
            // A second add while one is on the wire is refused.
            onMainSync { secondRefused.value = !(vmRef.value?.addStage("Fitting") ?? true) }
            return (200, #"{"ok":true,"stages":["measuring","Sampling"]}"#)
        }
        v.addStage("Sampling")
        await settled(v)
        XCTAssertTrue(secondRefused.value)
        XCTAssertEqual(puts("pipeline-stages"), 1)
    }

    func testStageTimeoutMessageIsNotTheGenericOne() async {
        fake.failTimeout("GET", "/admin/settings/pipeline-stages")
        let v = await vm()
        XCTAssertEqual(v.ui.loadErrors["stages"], FriendlyErrors.TIMEOUT_TEXT)
    }

    /// A refused save makes the shell re-read who this agent is (the HTTP layer's `forbidden`), as every screen does.
    func testARefusedSaveRereadsWhoThisAgentIs() async {
        let v = await vm()
        TeamFixtures.settings(fake, admin: false)
        v.setDirectives("Push copes this week.")
        v.saveDirectives()
        await settled(v)
        await host.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 10)
        await drain()
        XCTAssertEqual(host.accessRereads, 1)
    }
}
