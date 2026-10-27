import Foundation
import XCTest
@testable import NeemaCore

/// SettingsView.tsx's live cards (+ the pipeline stage list): endpoints, bodies, validation, failures (Android `SettingsViewModelTest`).
final class SettingsViewModelTests: SettingsTestCase {
    func testLoadsEveryCard() async {
        let v = await vm()
        for card in ["directives", "translation", "offer", "pipeline-stages"] {
            XCTAssertTrue(fake.called("GET", "/admin/settings/\(card)"), card)
        }
        XCTAssertEqual(v.ui.directives, "Always offer free delivery within Nairobi on orders above KES 10,000.")
        XCTAssertEqual(v.ui.maxChars, 600)
        XCTAssertTrue(v.ui.directivesLoaded)
        XCTAssertEqual(v.ui.translation?.enabled, true)
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Easter Sale")
        XCTAssertEqual(v.ui.draft.name, "Easter Sale")
        XCTAssertEqual(v.ui.stages, ["measuring"])
    }

    func testOneCardFailingLeavesTheOthers() async {
        fail("GET", "/admin/settings/directives", 500, "x")
        fail("GET", "/admin/settings/translation", 500, "x")
        let v = await vm()
        // Deliberate fix: the web unlocks an empty box here, and saving it would
        // wipe the real standing orders. The box stays locked and the card says why.
        XCTAssertFalse(v.ui.directivesLoaded, "the box stays locked until the real text arrives")
        XCTAssertNil(v.ui.translation, "translation has no switch to show")
        XCTAssertEqual(Set(v.ui.loadErrors.keys), ["directives", "translation"])
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Easter Sale")
    }

    // ── Standing orders ──────────────────────────────────────────────────────

    func testDirectivesAreCappedAtMaxChars() async {
        let v = await vm()
        v.setDirectives(String(repeating: "x", count: 2500))
        XCTAssertEqual(v.ui.directives.count, 600)
    }

    func testSaveDirectivesPutsTheText() async {
        let v = await vm()
        v.setDirectives("Push copes this week.")
        v.saveDirectives()
        await settled(v)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PUT"); XCTAssertEqual(w.first?.path, "/admin/settings/directives")
        XCTAssertEqual(json(w[0]), el(#"{"directives":"Push copes this week."}"#))
        XCTAssertEqual(lastToast()?.message, SettingsWords.DIRECTIVES_SAVED)
    }

    func testSaveDirectivesShowsWhatTheServerKept() async {
        let v = await vm()
        fake.on("PUT", "/admin/settings/directives", body: #"{"ok":true,"directives":"Trimmed by server"}"#)
        v.setDirectives("  Trimmed by server  ")
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(v.ui.directives, "Trimmed by server")
    }

    func testSaveDirectivesFailure() async {
        let v = await vm()
        fail("PUT", "/admin/settings/directives")
        v.saveDirectives()
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Couldn't save (admin only)")
        XCTAssertFalse(v.ui.savingDirectives)
    }

    // ── Translation (optimistic) ─────────────────────────────────────────────

    func testTranslationFlipsBeforeTheServerAnswers() async {
        let v = await vm()
        let vmRef = Ref<SettingsViewModel?>(v)
        let seenDuringRequest = Ref<Bool?>(nil)
        fake.on("PUT", "/admin/settings/translation") { _, _ in
            onMainSync { seenDuringRequest.value = vmRef.value?.ui.translation?.enabled }
            return (200, #"{"ok":true,"enabled":false}"#)
        }
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(seenDuringRequest.value, false, "switch moved before the reply")
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"enabled":false}"#))
        XCTAssertEqual(v.ui.translation?.enabled, false)
        XCTAssertEqual(lastToast()?.message, SettingsWords.TRANSLATION_OFF)
    }

    func testTranslationRevertsWhenTheSaveFails() async {
        let v = await vm()
        fail("PUT", "/admin/settings/translation")
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(v.ui.translation?.enabled, true)
        XCTAssertEqual(lastToast()?.message, "Couldn't change that (admin only)")
        XCTAssertEqual(lastToast()?.type, .error)
    }

    func testTranslationOnToast() async {
        fake.on("GET", "/admin/settings/translation", body: #"{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}"#)
        let v = await vm()
        v.toggleTranslation()
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"enabled":true}"#))
        XCTAssertEqual(lastToast()?.message, SettingsWords.TRANSLATION_ON)
    }

    func testTranslationDoesNothingBeforeItLoads() async {
        fail("GET", "/admin/settings/translation", 500, "x")
        let v = await vm()
        v.toggleTranslation()
        await settled(v)
        XCTAssertTrue(writes().isEmpty)
    }

    // ── Offer ────────────────────────────────────────────────────────────────

    func testStartOfferFromBlank() async {
        TeamFixtures.noOffer(fake)
        fake.on("PUT", "/admin/settings/offer", body: #"{"ok":true,"campaign":{"name":"Harvest Offer","percent":20,"scope":"all","categories":[],"skus":[],"starts_on":null,"ends_on":"2026-10-25"},"running":true,"says":"Harvest Offer — 20% off everything"}"#)
        let v = await vm()
        // A new offer ends a month from today.
        XCTAssertEqual(v.ui.draft.endsOn, SettingsViewModel.today().plusMonths(1).description)
        XCTAssertEqual(v.ui.draft.percent, 10)
        v.editDraft { $0.name = "Harvest Offer"; $0.percent = 20; $0.endsOn = "2026-10-25" }
        v.saveOffer(v.ui.draft)
        await settled(v)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PUT"); XCTAssertEqual(w.first?.path, "/admin/settings/offer")
        let c = sentCampaign(w[0])
        XCTAssertEqual(c?["name"], .string("Harvest Offer"))
        XCTAssertEqual(c?["percent"]?.doubleValue, 20)
        XCTAssertEqual(c?["scope"], .string("all"))
        XCTAssertEqual(c?["ends_on"], .string("2026-10-25"))
        XCTAssertEqual(v.ui.offer?.running, true)
        XCTAssertEqual(lastToast()?.message, "Offer live — Neema will say: Harvest Offer — 20% off everything")
    }

    func testUpdateOfferSendsTheEditedCampaign() async {
        let v = await vm()
        v.editDraft { $0.percent = 25; $0.scope = "products"; $0.skus = ["CS-BLK-16"]; $0.startsOn = "2026-10-01" }
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        let c = sentCampaign(writes()[0])
        XCTAssertEqual(c?["scope"], .string("products"))
        XCTAssertEqual(c?["skus"], el(#"["CS-BLK-16"]"#))
        XCTAssertEqual(c?["starts_on"], .string("2026-10-01"))
        XCTAssertEqual(c?["ends_on"], .string("2099-04-30"))
    }

    func testEndOfferSendsNull() async {
        let v = await vm()
        fake.on("PUT", "/admin/settings/offer", body: #"{"ok":true,"campaign":null,"running":false,"says":""}"#)
        v.saveOffer(nil)
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0])?["campaign"], JSONValue.null)
        XCTAssertNil(v.ui.offer?.campaign)
        XCTAssertEqual(v.ui.draft.name, "")
        XCTAssertEqual(lastToast()?.message, SettingsWords.OFFER_ENDED)
    }

    func testOfferTheServerWouldRefuseIsNotSent() async {
        let v = await vm()
        let pct = "The discount must be a whole number from 1 to 70%"
        v.editDraft { $0.percent = 0 }
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, pct)
        v.editDraft { $0.percent = 71 } // promotions.MAX_PERCENT is 70
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, pct)
        v.editDraft { $0.percent = 12.5 } // the server would keep int(12.5) = 12
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, pct)
        v.editDraft { $0.percent = 70; $0.name = " " }
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, "Give the offer a name")
        v.editDraft { $0.name = "Easter"; $0.endsOn = "" }
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, "Pick the offer's last day")
        v.editDraft { $0.endsOn = "30/04/2099" } // not YYYY-MM-DD: date.fromisoformat refuses it
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, "Pick the offer's last day")
        v.editDraft { $0.endsOn = "2099-04-30"; $0.scope = "category"; $0.categories = [] }
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, "Pick at least one category for the offer")
        v.editDraft { $0.scope = "products"; $0.skus = [" "] }
        v.saveOffer(v.ui.draft)
        XCTAssertEqual(lastToast()?.message, "Pick at least one product for the offer")
        await settled(v)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(toasts.count, 8)
        XCTAssertTrue(toasts.allSatisfy { $0.type == .error })
    }

    func testOfferRangeBoundaries() {
        let c = Campaign(name: "X", percent: 1, endsOn: "2026-12-01")
        XCTAssertTrue(offerIsValid(c, maxPercent: 30))
        var d = c; d.percent = 30
        XCTAssertTrue(offerIsValid(d, maxPercent: 30))
        d.percent = 0.5
        XCTAssertFalse(offerIsValid(d, maxPercent: 30))
        d.percent = 30.5
        XCTAssertFalse(offerIsValid(d, maxPercent: 30))
        d.percent = 10.5
        XCTAssertFalse(offerIsValid(d, maxPercent: 30), "a whole number only")
    }

    func testOfferServerRefusal() async {
        let v = await vm()
        fail("PUT", "/admin/settings/offer", 422, TeamFixtures.OFFER_422)
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Couldn't save that offer — \(TeamFixtures.OFFER_422)")
        XCTAssertFalse(v.ui.savingOffer)
        fail("PUT", "/admin/settings/offer", 403, "Admin only")
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Couldn't save that offer (admin only)")
        fake.on("PUT", "/admin/settings/offer", code: 500, body: "Internal Server Error")
        v.saveOffer(v.ui.draft)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, OFFER_SAVE_FAILED)
        XCTAssertEqual(v.ui.offer?.campaign?.name, "Easter Sale")
    }

    func testDatePickerRoundTripsInUtc() {
        let ms = isoDateToUtcMillis("2026-04-30")!
        XCTAssertEqual(utcMillisToIsoDate(ms), "2026-04-30")
        XCTAssertNil(isoDateToUtcMillis(nil))
        XCTAssertNil(isoDateToUtcMillis("not a date"))
        XCTAssertNil(isoDateToUtcMillis("2026-4-30"), "date.fromisoformat wants two-digit months")
    }

    // ── Pipeline stages ──────────────────────────────────────────────────────

    func testAddStagePutsTheWholeList() async {
        let v = await vm()
        fake.on("PUT", "/admin/settings/pipeline-stages", body: #"{"ok":true,"stages":["measuring","Sampling"]}"#)
        XCTAssertTrue(v.addStage("  Sampling "))
        await settled(v)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PUT"); XCTAssertEqual(w.first?.path, "/admin/settings/pipeline-stages")
        XCTAssertEqual(json(w[0]), el(#"{"stages":["measuring","Sampling"]}"#))
        XCTAssertEqual(v.ui.stages, ["measuring", "Sampling"])
    }

    func testStageLabelsAreCappedAt18() async {
        let v = await vm()
        v.addStage("A very long stage label indeed")
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        let sent = json(writes()[0])?["stages"]?.arrayValue?.compactMap { $0.stringValue } ?? []
        XCTAssertTrue(sent.contains("A very long stage"), "\(sent)")
        XCTAssertEqual(PIPELINE_LABEL_MAX, 18)
    }

    func testDuplicateAndBuiltInStagesAreRefused() async {
        let v = await vm()
        XCTAssertFalse(v.addStage("MEASURING"))
        XCTAssertEqual(lastToast()?.message, "“MEASURING” is already a stage")
        XCTAssertFalse(v.addStage("Won"))
        XCTAssertEqual(lastToast()?.message, "“Won” is already a built-in stage")
        XCTAssertFalse(v.addStage("   "))
        await settled(v)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertTrue(toasts.allSatisfy { $0.type == .warning })
    }

    func testAtMostFourStages() async {
        fake.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":["a","b","c","d"]}"#)
        let v = await vm()
        XCTAssertFalse(v.addStage("e"))
        XCTAssertEqual(lastToast()?.message, "At most 4 custom stages")
        await settled(v)
        XCTAssertTrue(writes().isEmpty)
    }

    func testRemoveStage() async {
        let v = await vm()
        fake.on("PUT", "/admin/settings/pipeline-stages", body: #"{"ok":true,"stages":[]}"#)
        v.removeStage("measuring")
        await settled(v)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"stages":[]}"#))
        XCTAssertEqual(v.ui.stages, [])
    }

    func testStageErrors() async {
        let v = await vm()
        fail("PUT", "/admin/settings/pipeline-stages", 403)
        v.addStage("Sampling")
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Only an admin can change pipeline stages.")
        fail("PUT", "/admin/settings/pipeline-stages", 422, "At most 4 custom stages")
        v.addStage("Sampling")
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "At most 4 custom stages")
        fail("PUT", "/admin/settings/pipeline-stages", 500, "x")
        v.addStage("Sampling")
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Couldn't save pipeline stages.")
        XCTAssertEqual(v.ui.stages, ["measuring"])
    }

    // ── Local-only cards (no API on the web either) ───────────────────────────

    func testLocalCardsNeverCallTheApi() async {
        let v = await vm()
        v.toggleIntegration("slack")
        XCTAssertEqual(lastToast()?.message, "Slack Notifications connected")
        XCTAssertEqual(v.ui.integrations.first { $0.key == "slack" }?.connected, true)
        v.toggleIntegration("whatsapp")
        XCTAssertEqual(lastToast()?.message, "WhatsApp Business API disconnected")
        v.setConfig("slack", "slack_channel", "#alerts")
        v.saveIntegConfig("slack")
        XCTAssertEqual(lastToast()?.message, "Slack Notifications settings saved")
        v.dangerAction()
        XCTAssertEqual(lastToast()?.message, "Requires confirmation — coming soon")
        XCTAssertEqual(lastToast()?.type, .warning)
        await settled(v)
        XCTAssertTrue(writes().isEmpty)
    }

    /// The Business and AI cards "save" with a short wait and a toast, nothing on the wire (the web's setTimeout).
    func testBusinessAndAiSavesToastAfterTheirWait() async {
        let v = await vm()
        v.editBiz { $0.businessName = "Bethany House Kenya" }
        v.saveBiz()
        XCTAssertTrue(v.ui.savingBiz)
        await host.clock.advance(by: 600)
        await settled(v)
        XCTAssertFalse(v.ui.savingBiz)
        XCTAssertEqual(lastToast()?.message, "Business settings saved")
        v.saveAi()
        await host.clock.advance(by: 600)
        await settled(v)
        XCTAssertEqual(lastToast()?.message, "Neema settings saved")
        XCTAssertTrue(writes().isEmpty)
    }
}
