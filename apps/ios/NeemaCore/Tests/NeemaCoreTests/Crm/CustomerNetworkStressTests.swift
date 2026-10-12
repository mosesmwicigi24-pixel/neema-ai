import XCTest
@testable import NeemaCore

/// Errors and network stress (Android `CustomerNetworkStressTest`). Every load
/// and every action of the CRM panel against a Nairobi phone network: offline
/// (nothing sent), a timeout (it may have landed), a 401 mid-action, each error
/// status, malformed bodies, double taps, leaving mid-request — and, through
/// all of it, what the agent typed survives.
///
/// "In flight" is simulated re-entrantly: a fake handler runs while its request
/// is outstanding, so a second tap made from inside it is exactly a tap made
/// while the first request is still on the wire.
final class CustomerNetworkStressTests: CustomerTestCase {
    private let PETER = CustomerFixtures.PETER
    private var pushPath: String { "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/push" }
    private var declinePath: String { "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/decline" }
    private func last() -> Toast { host.toasts.last! }

    // ── Loading the profile ─────────────────────────────────────────────────

    func testOfflineAtFirstOpenShowsTheChatsFallbackSaysWhyAndRetryRecovers() async {
        fake.on("GET", peterPath) { _, _ in try InboxNetFixtures.offline() }
        let vm = await vm()
        XCTAssertFalse(vm.ui.loading, "the spinner stops")
        XCTAssertEqual(vm.profile?.name, "Fr. Peter Kamau", "the fallback from the chat row")
        XCTAssertEqual(vm.ui.loadError, "Couldn't load the full profile — you're offline. Check your connection and try again. Showing what this chat knows.")
        fake.on("GET", peterPath, body: CustomerFixtures.peter)
        vm.refresh(); await drain()
        XCTAssertNil(vm.ui.loadError)
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk"])
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testAFailedRefreshKeepsTheLastGoodProfileOnScreen() async {
        let vm = await vm()
        fake.on("GET", peterPath, code: 503, body: #"{"detail":"db down"}"#)
        vm.refresh(); await drain()
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk"], "cached data stays")
        XCTAssertEqual(vm.ui.loadError, "Couldn't refresh — the server had a problem. Try again in a moment. Showing the profile as last loaded.")
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testAProxysHtmlPageIsNeverShown() async {
        fake.on("GET", peterPath, code: 502, body: CustomerFixtures.HTML_502)
        let vm = await vm()
        XCTAssertFalse(vm.ui.loadError!.contains("<"), vm.ui.loadError!)
        XCTAssertFalse(vm.ui.loadError!.contains("nginx"))
    }

    func testATimedOutLoadSaysTheServerTookTooLong() async {
        fake.on("GET", peterPath) { _, _ in try InboxNetFixtures.timeout() }
        let vm = await vm()
        XCTAssertFalse(vm.ui.loading)
        XCTAssertTrue(vm.ui.loadError!.contains("the server took too long to answer"), vm.ui.loadError!)
    }

    func testAnEmptyOrMalformedBodyIsNoCrashAndNoBlankProfile() async {
        fake.on("GET", peterPath, body: "")
        let vm = await vm()
        XCTAssertEqual(vm.profile?.waId, PETER, "fallback, not an all-defaults profile")
        XCTAssertTrue(vm.ui.loadError!.contains("couldn't read"), vm.ui.loadError!)
        fake.on("GET", peterPath, body: "{\"id\": 12, \"tags\": ")
        vm.refresh(); await drain()
        XCTAssertEqual(vm.profile?.waId, PETER)
        XCTAssertNotNil(vm.ui.loadError)
    }

    func testACustomerWithNoSavedProfileSaysItMayHaveBeenMerged() async {
        fake.on("GET", peterPath, code: 404, body: #"{"detail":"Customer not found"}"#)
        let vm = await vm()
        XCTAssertEqual(vm.ui.loadError, "No saved profile for this customer — it may have been merged into another. Showing what this chat knows.")
        XCTAssertEqual(vm.profile?.name, "Fr. Peter Kamau")
    }

    func testAReconnectOrForegroundRetriesAFailedLoadByItself() async {
        fake.on("GET", peterPath) { _, _ in try InboxNetFixtures.offline() }
        let vm = await vm()
        vm.onShown()
        fake.on("GET", peterPath, body: CustomerFixtures.peter)
        host.foreground.update(false)
        host.foreground.update(true)
        await advance()
        XCTAssertNil(vm.ui.loadError)
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk"])
    }

    func testATokenThatExpiredMidLoadRefreshesSilently() async {
        let n = Ref(0)
        fake.on("GET", peterPath) { _, _ in
            n.mutate { $0 += 1 }
            return n.value == 1 ? (401, #"{"detail":"Token expired"}"#) : (200, CustomerFixtures.peter)
        }
        let vm = await vm()
        XCTAssertNil(vm.ui.loadError)
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk"])
        XCTAssertEqual(fake.calls.filter { $0.method == "POST" && $0.path.hasSuffix("/refresh") }.count, 1)
        XCTAssertFalse(host.sessionExpired.value)
    }

    func testAFailedStageListIsNotCachedAsNoStagesForTheRestOfTheDay() async {
        fake.on("GET", "/admin/settings/pipeline-stages") { _, _ in try InboxNetFixtures.offline() }
        _ = await vm()
        XCTAssertNil(StageCache.stages, "a failure is not cached")
        fake.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":["measuring"]}"#)
        let vm2 = await vm()
        XCTAssertEqual(vm2.ui.customStages, ["measuring"])
    }

    // ── Field edits (PATCH) ─────────────────────────────────────────────────

    func testAnOfflineSaveRollsBackAndGivesTheTypedTextBack() async {
        let vm = await vm()
        fake.on("PATCH", peterPath) { _, _ in try InboxNetFixtures.offline() }
        vm.saveContactField("email", "fr.peter@parish.ke"); await drain()
        XCTAssertEqual(vm.profile?.email, "peter.kamau@stmarks.or.ke")
        XCTAssertEqual(vm.ui.drafts["email"], "fr.peter@parish.ke", "the editor reopens with it")
        XCTAssertEqual(last().message, "Failed to save — you're offline. Check your connection and try again.")
        XCTAssertEqual(last().type, .error)
        XCTAssertFalse(vm.ui.saving)
        vm.takeDraft("email")
        XCTAssertNil(vm.ui.drafts["email"])
    }

    func testATimedOutSaveIsNeverCalledAFailureAndIsConfirmedByRefetching() async {
        let vm = await vm()
        fake.on("PATCH", peterPath) { _, _ in try InboxNetFixtures.timeout() }
        // It did land: the server now has Mombasa.
        fake.on("GET", peterPath, body: peterWith("\"location\":\"Nyeri\"", "\"location\":\"Mombasa\""))
        vm.saveContactField("location", "Mombasa"); await drain()
        XCTAssertEqual(vm.profile?.location, "Mombasa", "the edit stays while we check")
        XCTAssertEqual(last().message, "Couldn't confirm the save — checking with the server…")
        XCTAssertEqual(last().type, .info)
        let gets = calls("GET", peterPath).count
        await advance()
        XCTAssertEqual(calls("GET", peterPath).count, gets + 1)
        XCTAssertEqual(last().message, "Saved")
        XCTAssertTrue(errors().isEmpty)
        XCTAssertTrue(vm.ui.drafts.isEmpty)
    }

    func testATimedOutSaveThatDidNotLandComesBackToTheEditor() async {
        let vm = await vm()
        fake.on("PATCH", peterPath) { _, _ in try InboxNetFixtures.timeout() }
        vm.saveContactField("location", "Mombasa"); await drain()
        await advance()
        XCTAssertEqual(vm.profile?.location, "Nyeri", "the server's truth")
        XCTAssertEqual(vm.ui.drafts["location"], "Mombasa")
        XCTAssertEqual(last().message, "That change didn't reach the server — it's back in the editor to try again.")
    }

    func testARefusalRollsBackOnlyItsOwnEditNotAnotherInFlight() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let once = Ref(true)
        fake.on("PATCH", peterPath) { _, body in
            if (body ?? "").contains("\"role\"") {
                // While the role save is on the wire, the agent saves the location too (it succeeds).
                if once.value { once.value = false; onMainSync { vmRef.value?.saveContactField("location", "Karatina") } }
                return (500, #"{"detail":"db down"}"#)
            }
            return (200, #"{"ok":true}"#)
        }
        let vm = await vm()
        vmRef.value = vm
        vm.saveContactField("role", "Archdeacon"); await drain(); await drain()
        XCTAssertEqual(vm.profile?.role, "Parish Priest", "the role rolled back")
        XCTAssertEqual(vm.profile?.location, "Karatina", "the location that saved is not undone with it")
        XCTAssertEqual(vm.ui.drafts["role"], "Archdeacon")
    }

    func testADoubleTapOnAStageSendsOnePatchAndAdvanceNeverSkipsAStage() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let busyWhileInFlight = Ref(false)
        fake.on("PATCH", peterPath) { _, _ in
            onMainSync {
                busyWhileInFlight.value = vmRef.value?.ui.stageBusy ?? false
                vmRef.value?.setStage("won")          // the same tap again
                vmRef.value?.setStage("negotiation")  // "Advance" tapped again from the optimistic stage
            }
            return (200, #"{"ok":true}"#)
        }
        let vm = await vm()
        vmRef.value = vm
        vm.setStage("won"); await drain()
        XCTAssertEqual(calls("PATCH", peterPath).count, 1)
        XCTAssertTrue(busyWhileInFlight.value, "the stage buttons disable while it saves")
        XCTAssertFalse(vm.ui.stageBusy)
        XCTAssertEqual(vm.profile?.leadStage, "won")
    }

    func testATokenThatExpiredMidSaveRefreshesAndTheSaveCompletes() async {
        let vm = await vm()
        let n = Ref(0)
        fake.on("PATCH", peterPath) { _, _ in
            n.mutate { $0 += 1 }
            return n.value == 1 ? (401, #"{"detail":"Token expired"}"#) : (200, #"{"ok":true}"#)
        }
        vm.saveContactField("location", "Othaya"); await drain()
        XCTAssertEqual(calls("PATCH", peterPath).count, 2)
        XCTAssertEqual(last().message, "Saved")
        XCTAssertEqual(vm.profile?.location, "Othaya")
        XCTAssertFalse(host.sessionExpired.value)
    }

    func testASessionThatCannotBeRescuedKeepsTheTextForAfterSigningIn() async {
        let vm = await vm()
        fake.on("PATCH", peterPath, code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        vm.saveContactField("email", "fr.peter@parish.ke"); await drain()
        XCTAssertTrue(host.sessionExpired.value, "the session-expired prompt opens")
        XCTAssertEqual(last().message, "Failed to save — your session expired. Sign in again, then retry.")
        XCTAssertEqual(vm.ui.drafts["email"], "fr.peter@parish.ke")

        // Signed in again: the draft is still there and the save goes through.
        fake.on("PATCH", peterPath, body: #"{"ok":true}"#)
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ in (200, Fixtures.tokenResponse()) }
        host.sessionStore.save(Session(accessToken: fakeJwt(), refreshToken: "refresh2", agentId: Fixtures.ME_ID, email: "moses@bethanyhouse.co.ke",
                                       name: "Moses Mwicigi", role: "admin", isSuperuser: true, mode: "direct"))
        host.onReauthenticated()
        let draft = vm.ui.drafts["email"]!
        vm.saveContactField("email", draft); await drain()
        XCTAssertEqual(last().message, "Saved")
        XCTAssertEqual(vm.profile?.email, "fr.peter@parish.ke")
    }

    func testASaveOnACustomerMergedAwayByAColleagueSaysSoAndRefetches() async {
        let vm = await vm()
        fake.on("PATCH", peterPath, code: 404, body: #"{"detail":"Customer not found"}"#)
        let gets = calls("GET", peterPath).count
        vm.saveContactField("location", "Nanyuki"); await drain()
        XCTAssertEqual(last().message, "Failed to save — this customer's profile is gone (it may have been merged into another). Refreshing.")
        await advance()
        XCTAssertEqual(calls("GET", peterPath).count, gets + 1)
        XCTAssertEqual(vm.ui.drafts["location"], "Nanyuki")
    }

    func testAConflictRefetchesTheTruth() async {
        let vm = await vm()
        fake.on("PATCH", peterPath, code: 409, body: #"{"detail":"Profile changed"}"#)
        let gets = calls("GET", peterPath).count
        vm.setStage("won"); await drain()
        XCTAssertEqual(last().message, "Failed to save — it changed meanwhile. Refreshing to show the latest.")
        XCTAssertEqual(vm.profile?.leadStage, "proposal")
        await advance()
        XCTAssertEqual(calls("GET", peterPath).count, gets + 1)
    }

    func testEachErrorStatusGetsItsOwnPlainWords() async {
        let vm = await vm()
        let cases: [(Int, String, String)] = [
            (403, #"{"detail":"Not enough permissions"}"#, "Failed to save — not enough permissions."),
            (422, #"{"detail":[{"loc":["body","age"],"msg":"value is not a valid integer","type":"int"}]}"#, "Failed to save — the server didn't accept that."),
            (429, #"{"detail":"Too Many Requests"}"#, "Failed to save — too many requests. Wait a moment, then try again."),
            (500, "Internal Server Error", "Failed to save — the server had a problem. Try again in a moment."),
            (502, CustomerFixtures.HTML_502, "Failed to save — the server had a problem. Try again in a moment."),
            (503, "", "Failed to save — the server had a problem. Try again in a moment."),
        ]
        for (i, c) in cases.enumerated() {
            fake.on("PATCH", peterPath, code: c.0, body: c.1)
            vm.saveContactField("location", "Town \(i)"); await drain()
            XCTAssertEqual(last().message, c.2, "HTTP \(c.0)")
            XCTAssertEqual(vm.profile?.location, "Nyeri")
        }
    }

    func testAFailedNotesSaveReopensTheEditorOnTheSameDraftAndBase() async {
        let vm = await vm()
        let base = vm.profile!.notes!
        vm.startEditNotes()
        vm.setNoteDraft("\(base)\n\nMeasured for a cassock, size L.")
        fake.on("PATCH", peterPath) { _, _ in try InboxNetFixtures.offline() }
        vm.saveNotes(); await drain()
        XCTAssertTrue(vm.ui.editNotes)
        XCTAssertEqual(vm.ui.noteDraft, "\(base)\n\nMeasured for a cassock, size L.")
        XCTAssertEqual(vm.ui.notesBase, base)
        XCTAssertEqual(vm.profile?.notes, base)
        // Retried when back online: the base is still the snapshot the edit began from.
        fake.on("PATCH", peterPath, body: #"{"ok":true}"#)
        vm.saveNotes(); await drain()
        XCTAssertEqual(lastBody("PATCH", peterPath)["notes_base"]?.content, base)
        XCTAssertFalse(vm.ui.editNotes)
    }

    func testATagThatFailedToSaveGoesBackIntoTheTagBox() async {
        let vm = await vm()
        vm.setTagInput("easter-2027")
        fake.on("PATCH", peterPath) { _, _ in try InboxNetFixtures.offline() }
        vm.addTag(); await drain()
        XCTAssertEqual(vm.ui.tagInput, "easter-2027")
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk"])
        fake.on("PATCH", peterPath, body: #"{"ok":true}"#)
        vm.addTag(); await drain()
        XCTAssertEqual(vm.ui.tagInput, "")
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk", "easter-2027"])
    }

    func testLeavingMidSaveShowsNoConfirmationAndNamesTheCustomerOnFailure() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        fake.on("PATCH", peterPath) { _, _ in onMainSync { vmRef.value?.onHidden() }; return (200, #"{"ok":true}"#) }
        let vm = await vm()
        vmRef.value = vm
        vm.onShown()
        let before = toasts.count
        vm.saveContactField("location", "Nyeri Town"); await drain()
        XCTAssertEqual(toasts.count, before, "no 'Saved' for a panel that is gone")
        XCTAssertEqual(vm.profile?.location, "Nyeri Town")

        fake.on("PATCH", peterPath, code: 500, body: "{}")
        vm.saveContactField("location", "Karatina"); await drain()
        XCTAssertEqual(last().message, "Fr. Peter Kamau: Failed to save — the server had a problem. Try again in a moment.")
    }

    // ── Merge / unmerge ─────────────────────────────────────────────────────

    func testADoubleTapOnMergeSendsOneMerge() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let busy = Ref(false)
        fake.on("POST", "\(peterPath)/merge") { _, _ in
            onMainSync {
                busy.value = vmRef.value?.ui.merging ?? false
                vmRef.value?.merge("254799000222")
            }
            return (200, #"{"ok":true}"#)
        }
        let vm = await vm()
        vmRef.value = vm
        vm.toggleMerge(true); await drain()
        vm.merge("254799000222"); await drain()
        XCTAssertEqual(calls("POST", "\(peterPath)/merge").count, 1)
        XCTAssertTrue(busy.value, "Merge disables while it runs")
        XCTAssertFalse(vm.ui.merging)
    }

    func testAnOfflineMergeKeepsTheTypedTargetAndSaysWhy() async {
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        vm.setMergeQuery("254700999888")
        fake.on("POST", "\(peterPath)/merge") { _, _ in try InboxNetFixtures.offline() }
        vm.merge(); await drain()
        XCTAssertEqual(last().message, "Failed to merge profiles — you're offline. Check your connection and try again.")
        XCTAssertEqual(vm.ui.mergeQuery, "254700999888")
        XCTAssertTrue(vm.ui.showMerge)
        fake.on("POST", "\(peterPath)/merge", body: #"{"ok":true}"#)
        vm.merge(); await drain()
        XCTAssertEqual(vm.ui.mergeQuery, "")
        XCTAssertFalse(vm.ui.showMerge)
    }

    func testATimedOutMergeChecksWhereItStandsInsteadOfFailing() async {
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        vm.setMergeQuery("254799000222")
        fake.on("POST", "\(peterPath)/merge") { _, _ in try InboxNetFixtures.timeout() }
        let gets = calls("GET", peterPath).count
        vm.merge(); await drain()
        XCTAssertEqual(last().message, "Couldn't confirm the merge — refreshing to show where it stands.")
        XCTAssertTrue(errors().isEmpty)
        XCTAssertEqual(calls("GET", peterPath).count, gets + 1)
        XCTAssertEqual(vm.ui.mergeQuery, "254799000222")
    }

    func testMergingAProfileAColleagueAlreadyMergedAwaySaysSoAndRefetches() async {
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        fake.on("POST", "\(peterPath)/merge", code: 404, body: #"{"detail":"Primary customer not found"}"#)
        let gets = calls("GET", peterPath).count
        vm.merge("254799000222"); await drain()
        XCTAssertEqual(last().message, "Failed to merge profiles — this profile is gone (it may already have been merged into another). Refreshing.")
        XCTAssertEqual(calls("GET", peterPath).count, gets + 1)
    }

    func testAFailedDuplicateScanSaysSoAndCanBeRetried() async {
        fake.on("GET", "\(peterPath)/merge_suggestions") { _, _ in try InboxNetFixtures.offline() }
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        XCTAssertEqual(vm.ui.mergeSugs, [])
        XCTAssertEqual(vm.ui.mergeSugsError, "Couldn't scan for duplicates — you're offline. Check your connection and try again.")
        fake.on("GET", "\(peterPath)/merge_suggestions", body: CustomerFixtures.suggestions)
        vm.retryMergeScan(); await drain()
        XCTAssertNil(vm.ui.mergeSugsError)
        XCTAssertEqual(vm.ui.mergeSugs?.count, 2)
    }

    func testUnmergingWhatAColleagueAlreadyUnmergedRefreshesQuietly() async {
        let vm = await vm()
        fake.on("POST", "\(peterPath)/unmerge", code: 404, body: #"{"detail":"No active merge to undo for this pair"}"#)
        let gets = calls("GET", peterPath).count
        vm.unmerge("254799000111"); await drain()
        XCTAssertEqual(last().message, "Already unmerged — refreshed to show where it stands.")
        XCTAssertEqual(last().type, .info)
        XCTAssertEqual(calls("GET", peterPath).count, gets + 1)
    }

    func testADoubleTapOnUnmergeSendsOneAndATimeoutIsChecked() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let wasBusy = Ref(false)
        fake.on("POST", "\(peterPath)/unmerge") { _, _ in
            onMainSync {
                wasBusy.value = vmRef.value?.ui.unmerging.contains("254799000111") ?? false
                vmRef.value?.unmerge("254799000111")
            }
            return try InboxNetFixtures.timeout()
        }
        let vm = await vm()
        vmRef.value = vm
        vm.unmerge("254799000111"); await drain()
        XCTAssertTrue(wasBusy.value)
        XCTAssertEqual(calls("POST", "\(peterPath)/unmerge").count, 1)
        XCTAssertEqual(last().message, "Couldn't confirm the unmerge — refreshing to show where it stands.")
        XCTAssertTrue(vm.ui.unmerging.isEmpty)
    }

    // ── Made-to-order: push to production / dismiss ─────────────────────────

    func testAPushAlreadyMadeByAColleagueShowsTheExistingOrder() async {
        fake.on("POST", pushPath, body: CustomerFixtures.alreadyPushed)
        let vm = await vm()
        vm.pushProduction(); await drain()
        XCTAssertEqual(last().message, "Already in production · BH-2001")
        XCTAssertEqual(vm.ui.enquiry?.status, "pushed")
        XCTAssertEqual(vm.ui.enquiry?.hubOrderNumber, "BH-2001")
    }

    func testAConflictingPushRefetchesAndShowsTheCurrentTruth() async {
        let vm = await vm()
        fake.on("POST", pushPath, code: 409, body: #"{"detail":"Enquiry already pushed"}"#)
        fake.on("GET", "/admin/production/conversation/c1", body: CustomerFixtures.enquiry("pushed", order: "BH-2001"))
        vm.pushProduction(); await drain()
        XCTAssertEqual(last().message, "This request was already handled — showing where it stands.")
        XCTAssertEqual(vm.ui.enquiry?.status, "pushed")
        XCTAssertEqual(vm.ui.enquiry?.hubOrderNumber, "BH-2001")
        XCTAssertFalse(vm.ui.pushing)
    }

    func testATimedOutPushIsCheckedNotFailed() async {
        let vm = await vm()
        fake.on("POST", pushPath) { _, _ in try InboxNetFixtures.timeout() }
        fake.on("GET", "/admin/production/conversation/c1", body: CustomerFixtures.enquiry("pushed", order: "BH-2001"))
        vm.pushProduction(); await drain()
        XCTAssertEqual(last().message, "Couldn't confirm it reached production — checking. Pushing again is safe: it never makes a second order.")
        XCTAssertTrue(errors().isEmpty)
        XCTAssertEqual(vm.ui.enquiry?.status, "pushed")
        XCTAssertFalse(vm.ui.pushing)
    }

    func testAnEnquiryRemovedMeanwhileDisappearsWithAWord() async {
        let vm = await vm()
        fake.on("POST", pushPath, code: 404, body: #"{"detail":"Enquiry not found"}"#)
        vm.pushProduction(); await drain()
        XCTAssertNil(vm.ui.enquiry)
        XCTAssertEqual(last().message, "This made-to-order request no longer exists — someone may have removed it.")
    }

    func testADoubleTapOnPushSendsOneAndDismissWaitsForIt() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        fake.on("POST", pushPath) { _, _ in
            onMainSync { vmRef.value?.pushProduction(); vmRef.value?.declineProduction() }
            return (200, CustomerFixtures.pushed)
        }
        let vm = await vm()
        vmRef.value = vm
        vm.pushProduction(); await drain()
        XCTAssertEqual(calls("POST", pushPath).count, 1)
        XCTAssertTrue(calls("POST", declinePath).isEmpty)
        XCTAssertEqual(last().message, "Sent to production · BH-2001")
    }

    func testANoHubProductPushShowsTheServersAdvice() async {
        let vm = await vm()
        fake.on("POST", pushPath, code: 422, body: #"{"detail":"This enquiry has no linked hub product — create the order in the hub manually."}"#)
        vm.pushProduction(); await drain()
        XCTAssertEqual(last().message, "This enquiry has no linked hub product — create the order in the hub manually.")
        XCTAssertEqual(vm.ui.enquiry?.status, "new")
    }

    func testDismissOfflineRevertsAndATimedOutDismissIsChecked() async {
        let vm = await vm()
        fake.on("POST", declinePath) { _, _ in try InboxNetFixtures.offline() }
        vm.declineProduction(); await drain()
        XCTAssertEqual(vm.ui.enquiry?.status, "new")
        XCTAssertEqual(last().message, "Couldn't dismiss — you're offline. Check your connection and try again.")

        fake.on("POST", declinePath) { _, _ in try InboxNetFixtures.timeout() }
        fake.on("GET", "/admin/production/conversation/c1", body: CustomerFixtures.enquiry("declined"))
        let n = toasts.count
        vm.declineProduction(); await drain()
        XCTAssertEqual(vm.ui.enquiry?.status, "declined")
        XCTAssertEqual(toasts.count, n, "no error for what may have worked")
    }

    func testAnEnquiryThatFailedToLoadArrivesOnTheNextRefresh() async {
        fake.on("GET", "/admin/production/conversation/c1") { _, _ in try InboxNetFixtures.offline() }
        let vm = await vm()
        XCTAssertNil(vm.ui.enquiry)
        fake.on("GET", "/admin/production/conversation/c1", body: CustomerFixtures.enquiry())
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.enquiry?.id, CustomerFixtures.ENQUIRY_ID)
    }

    // ── Pipeline stages ─────────────────────────────────────────────────────

    func testAStageLabelStaysInTheBoxUntilTheServerKeptItAndAddCannotDoubleSend() async {
        let vm = await vm()
        vm.setNewStage("Sampling")
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ in try InboxNetFixtures.offline() }
        vm.addCustomStage(); await drain()
        XCTAssertEqual(vm.ui.newStage, "Sampling")
        XCTAssertEqual(last().message, "Couldn't save pipeline stages — you're offline. Check your connection and try again.")

        let vmRef = Ref<CustomerViewModel?>(vm)
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ in
            onMainSync { vmRef.value?.addCustomStage() }   // tapped again while saving
            return (200, #"{"stages":["measuring","Sampling"]}"#)
        }
        let puts = calls("PUT", "/admin/settings/pipeline-stages").count
        vm.addCustomStage(); await drain()
        XCTAssertEqual(calls("PUT", "/admin/settings/pipeline-stages").count, puts + 1)
        XCTAssertEqual(vm.ui.newStage, "")
        XCTAssertEqual(vm.ui.customStages, ["measuring", "Sampling"])
    }

    func testATimedOutStageSaveRefetchesTheStages() async {
        let vm = await vm()
        vm.setNewStage("Sampling")
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ in try InboxNetFixtures.timeout() }
        fake.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":["measuring","Sampling"]}"#)
        vm.addCustomStage(); await drain()
        XCTAssertEqual(last().message, "Couldn't confirm the stage change — refreshing the stages.")
        XCTAssertEqual(vm.ui.customStages, ["measuring", "Sampling"])
        XCTAssertEqual(vm.ui.newStage, "", "it landed, so the box clears")
    }

    // ── Reach-out: invite, template, call ───────────────────────────────────

    func testATimedOutInviteNeverOpensASecondMessageAndADoubleTapSendsOne() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let opened = Ref<String?>(nil)
        fake.on("POST", "/admin/whatsapp-invite") { _, _ in
            onMainSync { vmRef.value?.inviteToWhatsApp(CustomerFixtures.PETER) { opened.value = $0 } }
            return try InboxNetFixtures.timeout()
        }
        let vm = await vm()
        vmRef.value = vm
        vm.inviteToWhatsApp(PETER) { opened.value = $0 }
        await drain()
        XCTAssertEqual(calls("POST", "/admin/whatsapp-invite").count, 1)
        XCTAssertNil(opened.value, "no wa.me fallback for an invite that may have gone out")
        XCTAssertEqual(last().message, "Couldn't confirm the invite went out — check the WhatsApp thread before sending again.")
        XCTAssertFalse(vm.ui.inviteBusy)
    }

    func testAnOfflineInviteStillOffersTheWaMeFallback() async {
        fake.on("POST", "/admin/whatsapp-invite") { _, _ in try InboxNetFixtures.offline() }
        let vm = await vm()
        let opened = Ref<String?>(nil)
        vm.inviteToWhatsApp(PETER) { opened.value = $0 }
        await drain()
        XCTAssertTrue(opened.value?.hasPrefix("https://wa.me/254712345678?text=") == true)
    }

    func testAnInviteThatFailsAfterThePanelLeftNeverThrowsWhatsAppOpen() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        fake.on("POST", "/admin/whatsapp-invite") { _, _ in onMainSync { vmRef.value?.onHidden() }; return (503, #"{"detail":"WhatsApp sending is not configured."}"#) }
        let vm = await vm()
        vmRef.value = vm
        let opened = Ref<String?>(nil)
        vm.inviteToWhatsApp(PETER) { opened.value = $0 }
        await drain()
        XCTAssertNil(opened.value)
        XCTAssertEqual(last().message, "Fr. Peter Kamau: Couldn't send the WhatsApp invite — the server had a problem. Try again in a moment.")
    }

    func testATemplateCannotBeSentTwiceByADoubleTapAndATimeoutIsNotAFailure() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        fake.on("POST", "/admin/whatsapp-invite") { _, _ in
            onMainSync { vmRef.value?.sendTemplate(CustomerFixtures.PETER) }
            return try InboxNetFixtures.timeout()
        }
        let vm = await vm()
        vmRef.value = vm
        vm.sendTemplate(PETER); await drain()
        XCTAssertEqual(calls("POST", "/admin/whatsapp-invite").count, 1)
        XCTAssertEqual(last().message, "Couldn't confirm the template went out — check the WhatsApp thread before sending again.")
        XCTAssertTrue(errors().isEmpty)
        XCTAssertFalse(vm.ui.templateBusy)
    }

    func testADoubleTapOnCallPlacesOneCall() async {
        let vm = await vm()
        XCTAssertFalse(vm.ui.callBusy)
        vm.call(PETER)
        vm.call(PETER)   // tapped again while dialling
        await drain()
        XCTAssertEqual(host.placedCalls.count, 1)
        XCTAssertFalse(vm.ui.callBusy)
    }

    func testACallWithoutPermissionNeverSendsTheRequestOnAFlakyNetwork() async {
        fake.on("POST", "/admin/calls/request-permission") { _, _ in try InboxNetFixtures.timeout() }
        host.callOutcome = .failed("Customer hasn't granted call permission.")
        let vm = await vm()
        vm.call(PETER); await drain()
        XCTAssertFalse(fake.calls.contains { $0.path.contains("request-permission") })
        XCTAssertEqual(last().message, "Customer hasn't granted call permission.")
    }

    // ── Ask Neema / Answer via Neema ────────────────────────────────────────

    func testAskSaysWhatWentWrongAndNeverAsksTwice() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let n = Ref(0)
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ in n.mutate { $0 += 1 }; onMainSync { vmRef.value?.ask("sizes?") }; return try InboxNetFixtures.offline() }
        let vm = await vm()
        vmRef.value = vm
        vm.setAskDraft("sizes?")
        vm.ask(); await drain()
        XCTAssertEqual(n.value, 1)
        XCTAssertEqual(vm.ui.askAnswer, "You're offline — ask again once you're connected.")
        XCTAssertEqual(vm.ui.askDraft, "sizes?", "the question stays")
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ in try InboxNetFixtures.timeout() }
        vm.ask(); await drain()
        XCTAssertEqual(vm.ui.askAnswer, "Neema took too long to answer — try again.")
        fake.on("POST", "/admin/conversations/c1/ask", code: 429, body: #"{"detail":"rate limited"}"#)
        vm.ask(); await drain()
        XCTAssertEqual(vm.ui.askAnswer, "Neema is busy — wait a moment, then ask again.")
        XCTAssertFalse(vm.ui.askBusy)
    }

    func testATimedOutAnswerIsNeverCalledUnsentAndTheFactsStay() async {
        let vm = await vm()
        vm.setAnswerDraft("yes, KES 3,500, ~5 days")
        fake.on("POST", "/admin/conversations/c1/answer") { _, _ in try InboxNetFixtures.timeout() }
        vm.answerViaNeema(); await drain()
        XCTAssertEqual(vm.ui.answerStatus, "Couldn't confirm Neema sent it — check the thread before sending again.")
        XCTAssertEqual(vm.ui.answerDraft, "yes, KES 3,500, ~5 days")
        XCTAssertFalse(vm.ui.answerBusy)
    }

    func testAnOfflineAnswerKeepsTheFactsAndASentOneClearsThem() async {
        let vmRef = Ref<CustomerViewModel?>(nil)
        let n = Ref(0)
        fake.on("POST", "/admin/conversations/c1/answer") { _, _ in n.mutate { $0 += 1 }; onMainSync { vmRef.value?.answerViaNeema() }; return try InboxNetFixtures.offline() }
        let vm = await vm()
        vmRef.value = vm
        vm.setAnswerDraft("yes, we make it")
        vm.answerViaNeema(); await drain()
        XCTAssertEqual(n.value, 1, "a double tap sends once")
        XCTAssertEqual(vm.ui.answerStatus, "You're offline — your answer is kept; send it once you're connected.")
        XCTAssertEqual(vm.ui.answerDraft, "yes, we make it")
        fake.on("POST", "/admin/conversations/c1/answer", body: #"{"ok":true,"sent":"Yes Father, we make it 🙏"}"#)
        vm.answerViaNeema(); await drain()
        XCTAssertEqual(vm.ui.answerDraft, "")
        XCTAssertEqual(vm.ui.answerStatus, "Neema sent: “Yes Father, we make it 🙏”")
    }
}
