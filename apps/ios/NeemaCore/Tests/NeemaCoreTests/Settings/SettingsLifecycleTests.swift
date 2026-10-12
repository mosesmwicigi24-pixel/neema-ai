import Foundation
import XCTest
@testable import NeemaCore

/// Unsaved standing orders, offer and local fields come back after iOS
/// reclaims the app — into the box once it has loaded, still unsaved so a
/// return to the screen doesn't overwrite them — and secrets never go into
/// saved state (Android `SettingsLifecycleTest`).
final class SettingsLifecycleTests: SettingsTestCase {
    func testUnsavedStandingOrdersSurviveARestart() async {
        let v = await vm()
        v.setDirectives("Push copes this week — Easter is close.")
        let fresh = await fresh()
        fresh.restoreUi(v.saveUi())
        XCTAssertEqual(fresh.ui.directives, "Push copes this week — Easter is close.")
        XCTAssertTrue(fresh.ui.directivesLoaded)
        // Still unsaved: nothing was written for it.
        XCTAssertTrue(writes().isEmpty)
        // Still unsaved after the restart: saved again if iOS reclaims the app a second time.
        XCTAssertTrue(fresh.saveUi().contains("Push copes this week"))
    }

    /// The saved text arrives before the card has loaded (a slow network after the restart): it waits for the load.
    func testUnsavedStandingOrdersWaitForTheCardToLoad() async {
        let first = await vm()
        first.setDirectives("Quote 3-week lead times.")
        let saved = first.saveUi()
        fail("GET", "/admin/settings/directives", 500, "x")
        let fresh = await fresh()
        fresh.restoreUi(saved)
        XCTAssertFalse(fresh.ui.directivesLoaded)
        XCTAssertEqual(fresh.ui.directives, "")
        XCTAssertTrue(fresh.saveUi().contains("Quote 3-week lead times."), "still waiting, it stays in saved state")
        TeamFixtures.settings(fake)
        fresh.retry("directives")
        await settled(fresh)
        XCTAssertTrue(fresh.ui.directivesLoaded)
        XCTAssertEqual(fresh.ui.directives, "Quote 3-week lead times.", "the unsaved typing goes back in the box")
    }

    func testACleanCardSavesNothing() async {
        let v = await vm()
        let saved = v.saveUi()
        XCTAssertFalse(saved.contains("directives"))
        XCTAssertFalse(saved.contains("offer"))
    }

    func testAnUnsavedOfferSurvivesARestart() async {
        let v = await vm()
        v.editDraft { $0.name = "Pentecost 15"; $0.percent = 15 }
        let fresh = await fresh()
        fresh.restoreUi(v.saveUi())
        XCTAssertEqual(fresh.ui.draft.name, "Pentecost 15")
        XCTAssertEqual(fresh.ui.draft.percent, 15)
        XCTAssertEqual(fresh.ui.offer?.campaign?.name, "Easter Sale", "the stored offer is still the server's")
    }

    func testLocalFieldsSurviveButSecretsAreNeverSaved() async {
        let v = await vm()
        v.editBiz { $0.businessName = "Bethany House Kenya" }
        v.editAi { $0.draftApproval = false; $0.escalationKeywords = "refund" }
        v.toggleIntegration("slack")
        v.setConfig("slack", "slack_channel", "#alerts")
        v.setConfig("whatsapp", "token", "EAAx-super-secret")
        v.setNewStage("Sampling")
        let saved = v.saveUi()
        XCTAssertFalse(saved.contains("EAAx-super-secret"), "an access token never goes into saved state")

        let fresh = await fresh()
        fresh.restoreUi(saved)
        XCTAssertEqual(fresh.ui.biz.businessName, "Bethany House Kenya")
        XCTAssertEqual(fresh.ui.ai.draftApproval, false)
        XCTAssertEqual(fresh.ui.ai.escalationKeywords, "refund")
        XCTAssertEqual(fresh.ui.integrations.first { $0.key == "slack" }?.connected, true)
        XCTAssertEqual(fresh.ui.integConfig["slack"]?["slack_channel"], "#alerts")
        XCTAssertNil(fresh.ui.integConfig["whatsapp"]?["token"])
        XCTAssertEqual(fresh.ui.newStage, "Sampling")
    }

    /// The stage box lives in the model: a save that lands after the phone turned still clears it.
    func testAnAddedStageClearsTheBoxEvenAcrossARotation() async {
        let v = await vm()
        v.setNewStage("Sampling")
        let vmRef = Ref<SettingsViewModel?>(v)
        v.addStage(v.ui.newStage) { if vmRef.value?.ui.newStage == "Sampling" { vmRef.value?.setNewStage("") } }
        await settled(v)
        XCTAssertEqual(v.ui.newStage, "")
        XCTAssertEqual(v.ui.stages, ["measuring", "Sampling"])
    }

    /// The screen attaches once per model: a second screen on the same model does not restore stale state over newer typing.
    func testRestoreHappensOncePerModel() async {
        let v = await vm()
        XCTAssertTrue(v.restoreIfFresh(#"{"stage":"Sampling"}"#))
        XCTAssertEqual(v.ui.newStage, "Sampling")
        v.setNewStage("Fitting")
        XCTAssertFalse(v.restoreIfFresh(#"{"stage":"Sampling"}"#))
        XCTAssertEqual(v.ui.newStage, "Fitting")
    }
}
