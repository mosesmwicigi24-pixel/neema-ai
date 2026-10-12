import XCTest
@testable import NeemaCore

/// Every CRM-panel action against the fake backend: the endpoint, the body,
/// the optimistic state, the rollback and the toast — each checked against
/// CustomerSidebar.tsx and routers/crm.py (Android `CustomerViewModelTest`).
final class CustomerViewModelTests: CustomerTestCase {
    private let PETER = CustomerFixtures.PETER
    private let MARY = CustomerFixtures.MARY

    // ── Load ────────────────────────────────────────────────────────────────

    func testLoadsTheProfileKeyedOnWaIdWithTheChannel() async {
        let vm = await vm()
        let get = calls("GET", "/admin/customers/\(PETER)")
        XCTAssertEqual(get.count, 1)
        XCTAssertEqual(get.first?.query, "channel=whatsapp")
        XCTAssertFalse(vm.ui.loading)
        let p = vm.profile!
        XCTAssertEqual(p.name, "Fr. Peter Kamau")
        XCTAssertEqual(p.orders?.count, 4)
        XCTAssertEqual(p.tags, ["vip", "clergy", "bulk"])
        XCTAssertEqual(vm.ui.tab, .profile)
    }

    func testNonWhatsAppContactsKeyOnTheirChannelHandle() async {
        // wa_id null (Messenger PSID) — the web uses external_id so edits don't hit /customers/null.
        var conv = CustomerFixtures.conversation("c2")
        conv.waId = nil; conv.externalId = "PSID77"
        fake.on("GET", "/admin/customers/PSID77", body: CustomerFixtures.mary.replacingOccurrences(of: "\"wa_id\":\"\(MARY)\"", with: "\"wa_id\":null"))
        let vm = await vm(conv: conv)
        XCTAssertEqual(calls("GET", "/admin/customers/PSID77").first?.query, "channel=messenger")
        vm.saveContactField("location", "Kisumu"); await drain()
        XCTAssertEqual(calls("PATCH", "/admin/customers/PSID77").count, 1)
    }

    func testAFailedLoadFallsBackToAMinimalProfileFromTheConversation() async {
        fake.on("GET", "/admin/customers/\(PETER)", code: 500, body: #"{"detail":"boom"}"#)
        let vm = await vm()
        let p = vm.profile!
        XCTAssertEqual(p.name, "Fr. Peter Kamau")
        XCTAssertEqual(p.waId, PETER)
        XCTAssertEqual(p.phone, PETER)
        XCTAssertEqual(p.leadStage, "new")
        XCTAssertEqual(p.leadScore, 0)
        XCTAssertEqual(p.channels.count, 1)
        XCTAssertEqual(p.channels[0].channel, "whatsapp")
        XCTAssertEqual(p.channels[0].conversationCount, 1)
        XCTAssertEqual(p.countryIso, "KE")
        XCTAssertFalse(vm.ui.loading)
    }

    func testANewMessageOrRenameOnTheRowReloadsQuietly() async {
        var conv = CustomerFixtures.conversation("c1")
        let vm = await vm(conv: conv)
        let path = "/admin/customers/\(PETER)"
        vm.sync(conv); await advance()
        XCTAssertEqual(calls("GET", path).count, 1)
        conv.lastMessageAt = Fixtures.ago(0)
        vm.sync(conv); await advance()
        XCTAssertEqual(calls("GET", path).count, 2)
        conv.name = "Fr. Peter K."
        vm.sync(conv); await advance()
        XCTAssertEqual(calls("GET", path).count, 3)
        XCTAssertFalse(vm.ui.loading, "a quiet reload never blanks the panel")
    }

    // ── PATCH edits ─────────────────────────────────────────────────────────

    func testEditingAFieldPatchesItOptimisticallyAndToastsSaved() async {
        let vm = await vm()
        vm.saveContactField("role", "Archdeacon"); await drain()
        let path = "/admin/customers/\(PETER)"
        XCTAssertEqual(calls("PATCH", path).count, 1)
        XCTAssertEqual(calls("PATCH", path).first?.query, "channel=whatsapp")
        XCTAssertEqual(calls("PATCH", path).first?.body, #"{"role":"Archdeacon"}"#)
        XCTAssertEqual(vm.profile?.role, "Archdeacon")
        XCTAssertEqual(lastToast()?.message, "Saved")
        XCTAssertFalse(vm.ui.saving)
    }

    func testEveryContactFieldSendsItsOwnKey() async {
        let vm = await vm()
        let path = "/admin/customers/\(PETER)"
        for f in ["organization", "email", "phone", "country", "location"] {
            vm.saveContactField(f, "x-\(f)"); await drain()
            XCTAssertEqual(lastBody("PATCH", path)[f]?.content, "x-\(f)")
        }
    }

    func testAFailedSaveRollsBackAndToastsAnError() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/customers/.*", code: 500, body: #"{"detail":"db down"}"#)
        vm.saveContactField("location", "Mombasa"); await drain()
        XCTAssertEqual(vm.profile?.location, "Nyeri")
        XCTAssertEqual(lastToast()?.message, "Failed to save — the server had a problem. Try again in a moment.")
        XCTAssertEqual(lastToast()?.type, .error)
        XCTAssertFalse(vm.ui.saving)
    }

    func testRenamingTellsTheInboxOnlyAfterTheServerAccepts() async {
        let vm = await vm()
        let renamed = Ref<[(String, String)]>([])
        vm.saveName("Fr. Peter M. Kamau") { id, n in renamed.mutate { $0.append((id, n)) } }
        await drain()
        XCTAssertEqual(renamed.value.count, 1)
        XCTAssertEqual(renamed.value.first?.0, PETER)
        XCTAssertEqual(renamed.value.first?.1, "Fr. Peter M. Kamau")
        XCTAssertEqual(calls("PATCH", "/admin/customers/\(PETER)").last?.body, #"{"name":"Fr. Peter M. Kamau"}"#)

        fake.on("PATCH", "/admin/customers/.*", code: 500, body: "{}")
        vm.saveName("Oops") { id, n in renamed.mutate { $0.append((id, n)) } }
        await drain()
        XCTAssertEqual(renamed.value.count, 1)
        XCTAssertEqual(vm.profile?.name, "Fr. Peter M. Kamau")
    }

    func testClearingTheNameSavesButDoesNotRenameTheInboxRow() async {
        let vm = await vm()
        let told = Ref(false)
        vm.saveName("") { _, _ in told.value = true }
        await drain()
        XCTAssertEqual(calls("PATCH", "/admin/customers/\(PETER)").last?.body, #"{"name":""}"#)
        XCTAssertFalse(told.value)
    }

    func testAgeFollowsParseIntOrNull() async {
        let vm = await vm()
        let path = "/admin/customers/\(PETER)"
        vm.saveAge("35 yrs"); await drain()
        XCTAssertEqual(lastBody("PATCH", path)["age"]?.content, "35")
        XCTAssertEqual(vm.profile?.age, 35)
        vm.saveAge("abc"); await drain()
        XCTAssertEqual(lastBody("PATCH", path)["age"], .null)
        vm.saveAge("0"); await drain()
        XCTAssertEqual(lastBody("PATCH", path)["age"], .null)
    }

    func testMovingTheStagePatchesLeadStageAndClearsTheAiHint() async {
        let vm = await vm()
        XCTAssertEqual(vm.profile?.leadStageSource, "auto")
        vm.setStage("negotiation"); await drain()
        XCTAssertEqual(calls("PATCH", "/admin/customers/\(PETER)").last?.body, #"{"lead_stage":"negotiation"}"#)
        XCTAssertEqual(vm.profile?.leadStage, "negotiation")
        XCTAssertEqual(vm.profile?.leadStageSource, "manual")
    }

    func testMovingToACustomStageSendsItsLabel() async {
        let vm = await vm()
        vm.setStage("measuring"); await drain()
        XCTAssertEqual(lastBody("PATCH", "/admin/customers/\(PETER)")["lead_stage"]?.content, "measuring")
    }

    func testTagsAreSentAsTheWholeNewList() async {
        let vm = await vm()
        let path = "/admin/customers/\(PETER)"
        vm.addTag("  choir  "); await drain()
        XCTAssertEqual(lastBody("PATCH", path)["tags"]?.arrayValue?.compactMap { $0.content }, ["vip", "clergy", "bulk", "choir"])
        XCTAssertEqual(vm.profile?.tags, ["vip", "clergy", "bulk", "choir"])
        vm.removeTag("clergy"); await drain()
        XCTAssertEqual(lastBody("PATCH", path)["tags"]?.arrayValue?.compactMap { $0.content }, ["vip", "bulk", "choir"])
        let before = calls("PATCH", path).count
        vm.addTag("   "); await drain()
        XCTAssertEqual(calls("PATCH", path).count, before, "a blank tag sends nothing")
    }

    func testRemovingTheLastTagSendsAnEmptyList() async {
        fake.on("GET", "/admin/customers/\(PETER)", body: peterWith("\"tags\":[\"vip\",\"clergy\",\"bulk\"]", "\"tags\":[\"vip\"]"))
        let vm = await vm()
        vm.removeTag("vip"); await drain()
        XCTAssertEqual(lastBody("PATCH", "/admin/customers/\(PETER)")["tags"], .array([]))
    }

    func testNotesCarryTheBaseTheEditStartedFromSoTheServerCanMerge() async {
        let vm = await vm()
        let base = vm.profile!.notes!
        vm.saveNotes("\(base)\nCall back Friday."); await drain()
        let body = lastBody("PATCH", "/admin/customers/\(PETER)")
        XCTAssertEqual(body["notes"]?.content, "\(base)\nCall back Friday.")
        XCTAssertEqual(body["notes_base"]?.content, base)
        XCTAssertEqual(vm.profile?.notes, "\(base)\nCall back Friday.")
    }

    func testNotesOnAProfileWithNoneSendAnEmptyBase() async {
        let vm = await vm("c2")
        vm.saveNotes("Wants a quote for 3 cassocks"); await drain()
        let body = lastBody("PATCH", "/admin/customers/\(MARY)")
        XCTAssertEqual(body["notes_base"]?.content, "")
        XCTAssertEqual(calls("PATCH", "/admin/customers/\(MARY)").last?.query, "channel=messenger")
    }

    // ── Custom pipeline stages ──────────────────────────────────────────────

    func testCustomStagesAreFetchedOncePerProcess() async {
        let a = await vm()
        XCTAssertEqual(a.ui.customStages, ["measuring"])
        _ = await vm()
        XCTAssertEqual(calls("GET", "/admin/settings/pipeline-stages").count, 1)
    }

    func testSavingStagesPutsTheListAndAdoptsTheServersCleanedCopy() async {
        signIn(role: "admin", superuser: true)
        fake.on("PUT", "/admin/settings/pipeline-stages", body: #"{"ok":true,"stages":["measuring","Sampling"]}"#)
        let vm = await vm()
        vm.saveCustomStages(["measuring", "Sampling", "sampling"]); await drain()
        XCTAssertEqual(lastBody("PUT", "/admin/settings/pipeline-stages")["stages"]?.arrayValue?.compactMap { $0.content }, ["measuring", "Sampling", "sampling"])
        XCTAssertEqual(vm.ui.customStages, ["measuring", "Sampling"])
        XCTAssertEqual(StageCache.stages, ["measuring", "Sampling"])
    }

    func testARefusedStageSaveExplainsItIsAdminOnly() async {
        let vm = await vm()
        fake.on("PUT", "/admin/settings/pipeline-stages", code: 403, body: #"{"detail":"Admin only"}"#)
        vm.saveCustomStages(["measuring", "x"]); await drain()
        XCTAssertEqual(lastToast()?.message, "Only an admin can change pipeline stages.")
        XCTAssertEqual(vm.ui.customStages, ["measuring"])
        // crm.py put_pipeline_stages' own words for the cap are shown as they are…
        fake.on("PUT", "/admin/settings/pipeline-stages", code: 422, body: #"{"detail":"At most 4 custom stages"}"#)
        vm.saveCustomStages(["a", "b", "c", "d", "e"]); await drain()
        XCTAssertEqual(lastToast()?.message, "At most 4 custom stages.")
        // …anything else (a pydantic list, a 500) says what kind of failure it was, in plain words.
        fake.on("PUT", "/admin/settings/pipeline-stages", code: 422, body: #"{"detail":[{"loc":["body"],"msg":"field required","type":"missing"}]}"#)
        vm.saveCustomStages(["a"]); await drain()
        XCTAssertEqual(lastToast()?.message, "Couldn't save pipeline stages — the server didn't accept that.")
        fake.on("PUT", "/admin/settings/pipeline-stages", code: 500, body: "Internal Server Error")
        vm.saveCustomStages(["a"]); await drain()
        XCTAssertEqual(lastToast()?.message, "Couldn't save pipeline stages — the server had a problem. Try again in a moment.")
        XCTAssertEqual(vm.ui.customStages, ["measuring"])
    }

    func testTheStageEditorIsShownExactlyToWhomTheServerAdmits() {
        XCTAssertTrue(InboxPerms.canEditPipelineStages(agent: Agent(id: "a", role: "admin", isSuperuser: false)))
        XCTAssertTrue(InboxPerms.canEditPipelineStages(agent: Agent(id: "a", role: "agent", isSuperuser: true)), "superusers may edit stages")
        XCTAssertFalse(InboxPerms.canEditPipelineStages(agent: Agent(id: "a", role: "agent", isSuperuser: false)), "plain agents do not get the stage editor")
        XCTAssertFalse(InboxPerms.canEditPipelineStages(agent: nil), "hidden until a record has loaded")
    }

    // ── Merge / unmerge ─────────────────────────────────────────────────────

    func testOpeningMergeScansForDuplicatesAndClosingForgetsThem() async {
        let vm = await vm()
        XCTAssertNil(vm.ui.mergeSugs)
        vm.toggleMerge(); await drain()
        XCTAssertTrue(vm.ui.showMerge)
        let get = calls("GET", "/admin/customers/\(PETER)/merge_suggestions")
        XCTAssertEqual(get.count, 1)
        XCTAssertEqual(get.first?.query, "channel=whatsapp")
        XCTAssertEqual(vm.ui.mergeSugs?.map { $0.mergeWith }, ["254799000222", "17840000000000077"])
        XCTAssertEqual(vm.ui.mergeSugs?[0].strength, "strong")
        vm.toggleMerge()
        XCTAssertFalse(vm.ui.showMerge)
        XCTAssertNil(vm.ui.mergeSugs)
    }

    func testAFailedScanShowsNoSuggestionsRatherThanSpinningForever() async {
        fake.on("GET", "/admin/customers/[^/]+/merge_suggestions", code: 500, body: "{}")
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        XCTAssertEqual(vm.ui.mergeSugs, [])
    }

    func testMergingPostsTheTrimmedTargetThenClosesAndReloads() async {
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        let cleared = Ref(false)
        vm.merge("  254799000222 ") { cleared.value = true }
        await drain()
        let path = "/admin/customers/\(PETER)/merge"
        XCTAssertEqual(calls("POST", path).count, 1)
        XCTAssertEqual(calls("POST", path).first?.body, #"{"merge_with":"254799000222"}"#)
        XCTAssertEqual(calls("POST", path).first?.query, "channel=whatsapp")
        XCTAssertEqual(lastToast()?.message, "Profiles merged successfully")
        XCTAssertFalse(vm.ui.showMerge)
        XCTAssertTrue(cleared.value)
        XCTAssertEqual(calls("GET", "/admin/customers/\(PETER)").count, 2)
    }

    func testABlankMergeTargetDoesNothing() async {
        let vm = await vm()
        vm.merge("   "); await drain()
        XCTAssertTrue(calls("POST", "/admin/customers/\(PETER)/merge").isEmpty)
    }

    func testARefusedMergeKeepsTheFormOpen() async {
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        fake.on("POST", "/admin/customers/[^/]+/merge", code: 404, body: #"{"detail":"Secondary customer not found"}"#)
        vm.merge("254700000000"); await drain()
        XCTAssertEqual(lastToast()?.message, "Failed to merge profiles — no customer found for that phone / wa_id")
        XCTAssertEqual(lastToast()?.type, .error)
        XCTAssertTrue(vm.ui.showMerge)
        fake.on("POST", "/admin/customers/[^/]+/merge", code: 422, body: #"{"detail":"Cannot merge a profile into itself"}"#)
        vm.merge(PETER); await drain()
        XCTAssertEqual(lastToast()?.message, "Failed to merge profiles — that's this same profile")
        fake.on("POST", "/admin/customers/[^/]+/merge", code: 500, body: "Internal Server Error")
        vm.merge("254700000000"); await drain()
        XCTAssertEqual(lastToast()?.message, "Failed to merge profiles — the server had a problem. Try again in a moment.")
        XCTAssertTrue(vm.ui.showMerge)
    }

    func testUnmergePostsTheMergedIdAndReloads() async {
        let vm = await vm()
        vm.unmerge("254799000111"); await drain()
        let path = "/admin/customers/\(PETER)/unmerge"
        XCTAssertEqual(calls("POST", path).count, 1)
        XCTAssertEqual(calls("POST", path).first?.body, #"{"merge_with":"254799000111"}"#)
        XCTAssertEqual(lastToast()?.message, "Unmerged")
        XCTAssertEqual(calls("GET", "/admin/customers/\(PETER)").count, 2)
        fake.on("POST", "/admin/customers/[^/]+/unmerge", code: 409, body: "{}")
        vm.unmerge("254799000111"); await drain()
        XCTAssertEqual(lastToast()?.message, "Failed to unmerge — it changed meanwhile. Refreshing.")
    }

    // ── Made-to-order enquiry ───────────────────────────────────────────────

    func testTheConversationsEnquiryLoadsAndAThreadWithoutOneShowsNothing() async {
        let a = await vm()
        XCTAssertEqual(a.ui.enquiry?.id, CustomerFixtures.ENQUIRY_ID)
        XCTAssertFalse(calls("GET", "/admin/production/conversation/c1").isEmpty)
        let b = await vm("c2")
        XCTAssertNil(b.ui.enquiry)
    }

    func testPushingSendsToProductionAndShowsTheHubOrder() async {
        fake.on("POST", "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/push", body: #"{"ok":true,"hub_order_id":88,"hub_order_number":"BH-2001"}"#)
        let vm = await vm()
        vm.pushProduction(); await drain()
        XCTAssertEqual(calls("POST", "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/push").count, 1)
        XCTAssertEqual(vm.ui.enquiry?.status, "pushed")
        XCTAssertEqual(vm.ui.enquiry?.hubOrderNumber, "BH-2001")
        XCTAssertEqual(lastToast()?.message, "Sent to production · BH-2001")
        XCTAssertFalse(vm.ui.pushing)
    }

    func testAPushWithoutAnOrderNumberStillConfirms() async {
        let vm = await vm()
        vm.pushProduction(); await drain()
        XCTAssertEqual(lastToast()?.message, "Sent to production")
        XCTAssertNil(vm.ui.enquiry?.hubOrderNumber)
    }

    func testARejectedPushLeavesTheEnquiryNew() async {
        fake.on("POST", "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/push", code: 502, body: #"{"detail":"Hub rejected the order"}"#)
        let vm = await vm()
        vm.pushProduction(); await drain()
        XCTAssertEqual(vm.ui.enquiry?.status, "new")
        XCTAssertEqual(lastToast()?.message, "Couldn't send to production — the hub didn't accept it. Try again in a moment.")
        XCTAssertFalse(vm.ui.pushing)
    }

    func testDismissIsOptimisticAndRevertsOnFailure() async {
        let vm = await vm()
        vm.declineProduction(); await drain()
        XCTAssertEqual(calls("POST", "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/decline").count, 1)
        XCTAssertEqual(vm.ui.enquiry?.status, "declined")
        XCTAssertFalse(toasts.contains { $0.message.contains("dismiss") }, "a dismiss that worked is silent")

        let vm2 = await self.vm()
        fake.on("POST", "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/decline", code: 500, body: "{}")
        vm2.declineProduction(); await drain()
        XCTAssertEqual(vm2.ui.enquiry?.status, "new")
        XCTAssertEqual(lastToast()?.message, "Couldn't dismiss — the server had a problem. Try again in a moment.")
    }

    // ── Reach-out: invite, template, call ───────────────────────────────────

    func testInviteSendsTheTemplateToTheProfilePhone() async {
        let vm = await vm()
        let opened = Ref<String?>(nil)
        vm.inviteToWhatsApp(PETER) { opened.value = $0 }
        await drain()
        let body = lastBody("POST", "/admin/whatsapp-invite")
        XCTAssertEqual(body["phone"]?.content, "+\(PETER)")
        XCTAssertEqual(body["name"]?.content, "Fr. Peter Kamau")
        XCTAssertEqual(lastToast()?.message, "WhatsApp invite sent ✓")
        XCTAssertNil(opened.value)
    }

    func testAFailedInviteOpensWhatsAppWithAWarmPrefilledMessage() async {
        fake.on("POST", "/admin/whatsapp-invite", code: 503, body: #"{"detail":"template not configured"}"#)
        let vm = await vm()
        let opened = Ref<String?>(nil)
        let before = toasts.count
        vm.inviteToWhatsApp(PETER) { opened.value = $0 }
        await drain()
        XCTAssertEqual(opened.value, "https://wa.me/254712345678?text=Hello%20Fr.%2C%20this%20is%20Bethany%20House.%20Continuing%20our%20chat%20here%20on%20WhatsApp%20so%20we%20can%20finalise%20your%20order.")
        XCTAssertEqual(toasts.count, before, "no error toast — the fallback is the answer")
    }

    func testSendTemplateToastsAndClearsBusy() async {
        let vm = await vm()
        vm.sendTemplate(PETER); await drain()
        XCTAssertEqual(calls("POST", "/admin/whatsapp-invite").count, 1)
        XCTAssertEqual(lastToast()?.message, "Template sent ✓")
        XCTAssertFalse(vm.ui.templateBusy)
        fake.on("POST", "/admin/whatsapp-invite", code: 500, body: "{}")
        vm.sendTemplate(PETER); await drain()
        XCTAssertEqual(lastToast()?.message, "Couldn't send the template — the server had a problem. Try again in a moment.")
        XCTAssertEqual(lastToast()?.type, .error)
        XCTAssertFalse(vm.ui.templateBusy)
    }

    func testAConnectedCallNeedsNoToast() async {
        let vm = await vm()
        let before = toasts.count
        vm.call(PETER); await drain()
        XCTAssertEqual(host.placedCalls.count, 1)
        XCTAssertEqual(host.placedCalls.first?.waId, PETER)
        XCTAssertEqual(host.placedCalls.first?.name, "Fr. Peter Kamau")
        XCTAssertEqual(host.placedCalls.first?.convId, "c1")
        XCTAssertEqual(toasts.count, before)
    }

    func testNoCallPermissionIsNeverAskedForByItself() async {
        // The call screen says it and offers "Send call request" (it messages the customer): the panel neither sends it nor toasts over the card.
        host.callOutcome = .shown
        let vm = await vm()
        let before = toasts.count
        vm.call(PETER); await drain()
        XCTAssertTrue(calls("POST", "/admin/calls/request-permission").isEmpty)
        XCTAssertEqual(toasts.count, before)
        XCTAssertFalse(vm.ui.callBusy)
    }

    func testAnyOtherCallFailureIsToastedAsIs() async {
        host.callOutcome = .failed("Already in a call")
        let vm = await vm()
        vm.call(PETER); await drain()
        XCTAssertEqual(lastToast()?.message, "Already in a call")
        XCTAssertEqual(lastToast()?.type, .error)
        host.callOutcome = .failed("")
        vm.call(PETER); await drain()
        XCTAssertEqual(lastToast()?.message, "Couldn't place the call")
    }

    // ── Ask Neema / Answer via Neema ────────────────────────────────────────

    func testAskNeemaPostsTheQuestionAndShowsTheAnswer() async {
        let vm = await vm()
        vm.ask("  what were his sizes?  "); await drain()
        XCTAssertEqual(calls("POST", "/admin/conversations/c1/ask").count, 1)
        XCTAssertEqual(calls("POST", "/admin/conversations/c1/ask").first?.body, #"{"question":"what were his sizes?"}"#)
        XCTAssertEqual(vm.ui.askAnswer, "16 inch collar, size L cassock.")
        XCTAssertFalse(vm.ui.askBusy)
        vm.ask("   "); await drain()
        XCTAssertEqual(calls("POST", "/admin/conversations/c1/ask").count, 1)
        fake.on("POST", "/admin/conversations/c1/ask", code: 500, body: "{}")
        vm.ask("again?"); await drain()
        XCTAssertEqual(vm.ui.askAnswer, "Couldn't check right now — try again.")
    }

    func testAnswerViaNeemaReportsWhatWasSentAndClearsTheBox() async {
        fake.on("POST", "/admin/conversations/c1/answer", body: #"{"ok":true,"sent":"Yes Father, we make it — KES 3,500, about 5 days 🙏"}"#)
        let vm = await vm()
        let cleared = Ref(false)
        vm.setAnswerDraft("yes, KES 3,500, ~5 days")
        vm.answerViaNeema("yes, KES 3,500, ~5 days") { cleared.value = true }
        await drain()
        XCTAssertEqual(calls("POST", "/admin/conversations/c1/answer").first?.body, #"{"facts":"yes, KES 3,500, ~5 days"}"#)
        XCTAssertEqual(vm.ui.answerStatus, "Neema sent: “Yes Father, we make it — KES 3,500, about 5 days 🙏”")
        XCTAssertEqual(vm.ui.answerDraft, "")
        XCTAssertTrue(cleared.value)
    }

    func testAnswerViaNeemaExplainsAClosedWindow() async {
        let vm = await vm()
        let cleared = Ref(false)
        fake.on("POST", "/admin/conversations/c1/answer", code: 409, body: #"{"detail":"Outside the 24h window"}"#)
        vm.answerViaNeema("facts") { cleared.value = true }
        await drain()
        XCTAssertEqual(vm.ui.answerStatus, "Outside the messaging window — reply yourself when they next write.")
        fake.on("POST", "/admin/conversations/c1/answer", code: 500, body: #"{"detail":"boom"}"#)
        vm.answerViaNeema("facts") { cleared.value = true }
        await drain()
        XCTAssertEqual(vm.ui.answerStatus, "Couldn't send right now — try again.")
        XCTAssertFalse(cleared.value)
    }

    // ── Web-chat visitors (`web_<sha1>` keys) and channel labels ────────────

    func testAWebVisitorsKeyIsNeverReadAsAPhone() {
        // The hash holds 11 digits: the web's digits rule alone would call it a phone.
        XCTAssertEqual(CustomerFixtures.WEB.filter { $0.isNumber }.count, 11)
        XCTAssertNil(Crm.realPhoneDigits(CustomerFixtures.WEB))
        XCTAssertNil(Crm.realPhoneDigits(" \(CustomerFixtures.WEB)"))
        XCTAssertEqual(Crm.realPhoneDigits("+254 712 345 678"), "254712345678")
        XCTAssertNil(Crm.realPhoneDigits("12345"), "too short")
        XCTAssertNil(Crm.realPhoneDigits("25898765432101234"), "a Meta PSID")
        XCTAssertNil(Crm.realPhoneDigits(nil))
        XCTAssertEqual(Crm.badgeKey("whatsapp", identifier: CustomerFixtures.WEB), "web")
        XCTAssertEqual(Crm.badgeKey("whatsapp", identifier: PETER), "whatsapp")
    }

    func testChannelsReadAsTheirBrandNamesAndAWebVisitorAsWebChat() {
        XCTAssertEqual(Crm.channelLabel("whatsapp", identifier: PETER), "WhatsApp")
        XCTAssertEqual(Crm.channelLabel("whatsapp"), "WhatsApp")
        XCTAssertEqual(Crm.channelLabel("messenger"), "Messenger")
        XCTAssertEqual(Crm.channelLabel("facebook"), "Facebook")
        XCTAssertEqual(Crm.channelLabel("instagram"), "Instagram")
        XCTAssertEqual(Crm.channelLabel("email"), "Email")
        XCTAssertEqual(Crm.channelLabel("sms"), "SMS")
        XCTAssertEqual(Crm.channelLabel("tiktok"), "TikTok")
        XCTAssertEqual(Crm.channelLabel("whatsapp", identifier: CustomerFixtures.WEB), "Web chat")
    }

    func testAWebVisitorsProfileLoadsOnItsKeyAndHasNoPhone() async {
        let vm = await vm("c7")
        XCTAssertEqual(calls("GET", "/admin/customers/\(CustomerFixtures.WEB)").first?.query, "channel=whatsapp")
        XCTAssertNil(vm.profile?.phone)
    }

    func testAWebVisitorsFallbackProfileNeverTakesTheKeyAsItsPhone() async {
        fake.on("GET", "/admin/customers/\(CustomerFixtures.WEB)", code: 500, body: #"{"detail":"boom"}"#)
        let p = await vm("c7").profile!
        XCTAssertEqual(p.waId, CustomerFixtures.WEB)
        XCTAssertNil(p.phone)
        // A real WhatsApp contact's fallback still carries the wa_id as its phone, as on the web.
        fake.on("GET", "/admin/customers/\(PETER)", code: 500, body: #"{"detail":"boom"}"#)
        let q = await vm("c1").profile!
        XCTAssertEqual(q.phone, PETER)
    }

    func testNothingIsEverSentToAWebVisitorsHash() async {
        fake.on("GET", "/admin/customers/\(CustomerFixtures.WEB)", code: 500, body: #"{"detail":"boom"}"#)
        let vm = await vm("c7")
        let hashDigits = CustomerFixtures.WEB.filter { $0.isNumber }
        let opened = Ref<String?>(nil)
        vm.inviteToWhatsApp(hashDigits) { opened.value = $0 }
        vm.sendTemplate(hashDigits)
        vm.call(hashDigits)
        await drain()
        XCTAssertTrue(calls("POST", "/admin/whatsapp-invite").isEmpty)
        XCTAssertFalse(fake.calls.contains { $0.path.contains("permission") })
        XCTAssertTrue(host.placedCalls.isEmpty)
        XCTAssertNil(opened.value)
        XCTAssertFalse(vm.ui.templateBusy)
    }

    func testAWebVisitorWhoLeftARealNumberIsInvitedOnThatNumber() async {
        fake.on("GET", "/admin/customers/\(CustomerFixtures.WEB)", body: CustomerFixtures.webVisitor(phone: "+256772123456", name: "Br. Joseph"))
        let vm = await vm("c7")
        vm.inviteToWhatsApp("256772123456") { _ in }
        await drain()
        let body = lastBody("POST", "/admin/whatsapp-invite")
        XCTAssertEqual(body["phone"]?.content, "+256772123456")
        XCTAssertEqual(body["name"]?.content, "Br. Joseph")
    }
}
