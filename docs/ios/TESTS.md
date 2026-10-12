# Neema iOS — test inventory: every Android test file and its iOS counterpart

The Android app's JVM test suite (`apps/android/app/src/test/java/ke/co/bethanyhouse/neema/`,
177 files) is the reference for what the iOS app must prove. This file maps
every one of them to where the same behaviour is proven on iOS, and says
honestly where it is not. It was written at the end of cycle 8 and is kept
current by later cycles (cycle 9: the keyboard and drop rules) (`docs/ios/PLAN.md` holds the cycle log).

Where the iOS proof lives:

- **`NeemaCore` (Linux)** — `apps/ios/NeemaCore/Tests/NeemaCoreTests/`, run with
  `swift test` on this workstation and on CI's `NeemaCore (Linux)` job. The
  core mirrors Android's `core/*` and every view model one type for one type,
  so every Android test against a view model, the HTTP client, the socket,
  the models or a pure rule ports here. Counts in the iOS column are
  `func test…` in the named file(s).
- **The app's test bundle (macOS CI)** — `apps/ios/NeemaAppTests/`: the four
  shell tests and the screenshot gallery (`ScreenGalleryTests`), which
  renders every screen of the signed-in app and the sign-in screen on a phone
  (light and dark) and an iPad (light) against the recorded backend and
  uploads the PNGs (`ios-screenshots`). This is the iOS twin of Android's
  Paparazzi suites: it proves each screen lays out; it does not pin pixels
  against goldens, and it renders the fixtures' state only (no error, empty,
  restored-form or stress variants yet — those rows say **partial**).
- **The UI tests (macOS CI)** — `apps/ios/NeemaAppUITests/`: XCUITest driving
  the built app on the simulator against the recorded backend (`-neema-canned`):
  sign-in (right and wrong password), the bottom tabs, the drawer to Settings,
  the orders list, sign-out. Android has no instrumented UI tests; these are
  the flows the plan asked CI to drive.

Status vocabulary is the parity matrix's: **verified** (the iOS tests run and
pass here or on CI), **partial** (some of the file's tests have no iOS twin —
the note says which), **platform-restricted** (the Android test proves an
Android-only mechanism; the iOS twin, where one exists, is named),
**gallery** (a screenshot suite covered by the gallery's render of that
screen), **support** (not a test: a helper or fixture file, with its iOS
twin), **missing** (no iOS proof yet).


## App shell, dashboard, lifecycle (`app/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `ConnectivityScreenshotTest.kt` | 6 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | the shell's offline / reconnecting banner states are not rendered by the gallery (fixtures only) |
| `DashboardRealtimeTest.kt` | 14 | `Shell/DashboardRulesTests.swift` + `Stress/ShellStressTests.swift` | 36 | **partial** | 9 of 14 (cycle 8): reconnect catch-up, the fresh-orders rule, the alert burst, links while running, alert taps; the five about a link / tap stashed while signed out are the app's `AppModel.applyDeepLink` (now kept in scene storage too) |
| `DashboardStressTest.kt` | 7 | `Shell/DashboardRulesTests.swift` + `Stress/ShellStressTests.swift` | 36 | **partial** | 6 of 7: 3 (cycle 8) + 2 (cycle 7); `anAlertAfterTheRefetchSchedulesAnotherSoNothingIsMissed` is the inbox's own coalescer (`InboxLiveTests`); the per-agent screen store is the app's `AppModel.startScreens` |
| `DashboardViewModelTest.kt` | 24 | `Shell/DashboardRulesTests.swift` | 32 | **partial** | 19 of 24 (cycle 8): access, badges, the bell, frames, the 401 prompt, sign-out, deep links, view names, polls; `theMeRequestRetriesThreeTimes`, the two role-source rules and the 800 ms inbox kick are the app's `AppModel.refetchMe` / the inbox's own refetch |
| `LiveLifecycleTest.kt` | 10 | `Shell/LiveLifecycleTests.swift` | 7 | **partial** | 7 of 10 (cycle 8) with the four-line policy of `AppContainer.applyLivePolicy` applied in the test; the three about Android's foreground service / live mode are platform-restricted (iOS disconnects in the background) |
| `PermissionMatrixTest.kt` | 11 | `Shell/ShellPermissionMatrixTests.swift` + `PermsTests.swift` | 15 | **partial** | 9 of 11 (cycle 8): every persona, Settings' gate, the session role / superuser rules, the poll and the 403 re-read; the 15 s cooldown and the hook's inertness when signed out are the app's `AppModel.onForbidden` |
| `PersonaShellScreenshotTest.kt` | 4 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | one persona (the fixtures' admin); the agent / viewer personas are not rendered |
| `PersonaShellTabletScreenshotTest.kt` | 4 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | iPad light only; one persona |
| `ShellA11yTest.kt` | 4 | `apps/ios/NeemaAppTests/NeemaAppTests.swift` | 4 | **partial** | labels are set on every control (cycle 3) but no automated contrast / touch-target probe runs; `testThemeTokensAndFontsResolve` covers the tokens |
| `ShellBackOrderTest.kt` | 2 | — |  | **platform-restricted** | a Compose back-dispatcher order (drawer before the inbox search); iOS has no system back |
| `ShellLifecycleTest.kt` | 16 | `Shell/ShellLifecycleTests.swift` + `ShellTests.swift` | 15 | **partial** | 8 of 16 (cycle 8): the back walk, history rules, cross-view entries, the Codable round trip, sign-out without a call, the shared orders read; the saved-state and sign-out-with-a-call rules are the app's (`AppModel`: scene storage and the 4 s bound added this cycle); the overlay back order has no iOS twin |
| `ShellMatrixScreenshotTest.kt` | 10 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | phone 390 pt and iPad 1180 pt; the other window classes are pinned by `AdaptiveTests` instead |
| `ShellRestoreScreenshotTest.kt` | 6 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | restored state after a process death is not rendered; `@SceneStorage` restoration is pinned by the inbox / calls model tests |
| `ShellScreenshotTest.kt` | 24 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | every view, light and dark |
| `ShellShots.kt` |  | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **support** | the gallery's render helper |
| `ShellShotsAccess.kt` |  | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **support** |  |
| `ShellStressTest.kt` | 9 | `Stress/ShellStressTests.swift` + `AuthRepositoryTests.swift` + `NeemaHTTPTests.swift` | 62 | **partial** | 2 of 9 by name; the one-prompt-for-many-401s and refresh rules are pinned in `NeemaHTTPTests` / `AuthRepositoryTests`; re-sign-in state and the online flag are the app's (`AppModel`) |
| `ShellTabletScreenshotTest.kt` | 14 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | iPad light |
| `ToastLifecycleTest.kt` | 8 | `Shell/ToastLifecycleTests.swift` | 6 | **partial** | 6 of 8 (cycle 8) against `ToastPresenter`; the two about a toast surviving a process death are the app's (`DashboardShell` scene storage, added this cycle, compiled only) |

## Calls (`calls/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `CallAcceptanceTest.kt` | 53 | `Calls/CallAcceptanceTests.swift` + `Calls/CallsViewModelTests.swift` | 77 | **partial** | 52 of 53: `s20_openChatLandsOnTheCustomersConversation` is the shell's navigation (app layer: `AppModel.openConversationFor`) |
| `CallApiContractTest.kt` | 15 | `Calls/CallApiContractTests.swift` | 15 | **verified** |  |
| `CallDockShellScreenshotTest.kt` | 3 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | the docked call panel is not rendered (no live call in the fixtures); `callDocks` is pinned in `Shell/TabletLayoutTests` |
| `CallFakes.kt` |  | `Calls/CallFakes.swift` + `Calls/CallRig.swift` + `Calls/ConsoleRig.swift` | 0 | **support** | FakeCallApi, FakeMedia / FakePeer / FakeRinger / FakeAudio, the rig |
| `CallLifecycleTest.kt` | 15 | `Calls/CallLifecycleTests.swift` + `Calls/CallsViewModelTests.swift` | 39 | **partial** | 14 of 15: `recorderLeftoversAreSweptButNothingElse` is the Android recorder's (platform-restricted; iOS `sweepLeftovers` is the media layer's) |
| `CallLogLiveTest.kt` | 7 | `Calls/CallLogLiveTests.swift` | 12 | **verified** | 7 of 7 (the file also holds the 5 log stress tests) |
| `CallManagerTest.kt` | 59 | `Calls/CallManagerTests.swift` | 59 | **verified** |  |
| `CallNativeSafetyTest.kt` | 7 | `Calls/CallNativeSafetyTests.swift` | 5 | **partial** | 5 of 7 (cycle 8): the closed-peer races, the mic failure on the card, the contained WebRTC callback; the throwing audio route and the JVM thread-name containment are Android's |
| `CallNetworkStressTest.kt` | 31 | `Calls/CallNetworkStressTests.swift` | 31 | **verified** |  |
| `CallReadinessTest.kt` | 2 | `(apps/ios/NeemaApp/Views/Calls/CallsScreen.swift `CallReadiness`)` | 0 | **platform-restricted** | Android's battery / background-connection / full-screen-intent readiness; iOS asks for notifications and the microphone |
| `CallRecorderTest.kt` | 6 | `(apps/ios/NeemaApp/App/WebRTCMedia.swift)` | 0 | **platform-restricted** | the PCM mixer and the on-device encoder are Android's audio-device module; the outbox the recorder feeds is pinned in `CallNetworkStressTests` |
| `CallResilienceTest.kt` | 13 | `Calls/CallResilienceTests.swift` | 13 | **verified** |  |
| `CallRingsEverywhereTest.kt` | 14 | `Calls/CallRingsEverywhereTests.swift` | 14 | **partial** | 12 of 14: the process restarted by the live service and the lock-screen full-screen notification are Android's (CallKit presents the iOS call) |
| `CallSimulationTest.kt` | 2 | `Calls/CallSimulationTests.swift` | 2 | **verified** |  |
| `CallUxTest.kt` | 47 | `Calls/CallUxTests.swift` | 47 | **verified** |  |
| `CallsMessengerScreenshotTest.kt` | 16 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | the calls console with the fixtures' log; Messenger rows are in the fixtures, the Messenger call card is not |
| `CallsNetworkScreenshotTest.kt` | 16 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | error / offline / retrying states of the console are not rendered |
| `CallsParityTest.kt` | 3 | `Calls/CallsParityTests.swift` | 3 | **verified** | cycle 8: `avatarIndex`, `initialsOf`, `rowWho` moved to the core (`CallVisualsRules.swift`) |
| `CallsPolishScreenshotTest.kt` | 17 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `CallsRefreshScreenshotTest.kt` | 19 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | the refreshing / skeleton states are not rendered |
| `CallsScreenshotTest.kt` | 43 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | the console on phone light / dark and iPad with the first call's details and transcript open |
| `CallsStressTest.kt` | 16 | `Calls/CallLogLiveTests.swift` + `Stress/SoftphoneStressTests.swift` | 23 | **verified** | the 5 log stress tests and the 11 softphone stress tests |
| `CallsViewModelNetworkTest.kt` | 12 | `Calls/CallsViewModelTests.swift` | 29 | **verified** | class `CallsViewModelNetworkTests` in the file |
| `CallsViewModelTest.kt` | 9 | `Calls/CallsViewModelTests.swift` | 29 | **verified** |  |
| `CallsWrapUpScreenshotTest.kt` | 38 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | the wrap-up card's 38 outcome states are not rendered (no live call in the fixtures); the words are pinned by `CallWordsTests` |
| `FrameFuzzTest.kt` | 2 | `Calls/FrameFuzzTests.swift` | 2 | **verified** | cycle 8: 4000 seeded random frames into `CallManager.onFrame` |

## Catalog (`catalog/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `CatalogFilterTest.kt` | 11 | `Catalog/CatalogRulesTests.swift` + `Catalog/CatalogViewModelTests.swift` | 29 | **verified** |  |
| `CatalogMatrixScreenshotTest.kt` | 2 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `CatalogScreenshotTest.kt` | 18 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |

## Inbox and thread (`conversations/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `ConversationsScreenshotTest.kt` | 55 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | the list and the first thread; the 55 Android states (media kinds, tombstones, drafts) are pinned by the model tests, not rendered |
| `ConversationsViewModelTest.kt` | 32 | `Inbox/ConversationsViewModelTests.swift` | 32 | **partial** | 31 of 32: `rows_areReadyTheMomentTheViewModelIs_noWaiting` is a Compose state-read timing test |
| `InboxBusyServerTest.kt` | 3 | `Inbox/InboxLiveTests.swift` | 22 | **verified** | the three tests by name |
| `InboxContractTest.kt` | 40 | `Inbox/InboxContractTests.swift` | 40 | **verified** |  |
| `InboxDarkContrastTest.kt` | 1 | `apps/ios/NeemaAppTests/NeemaAppTests.swift` | 4 | **partial** | the dark tokens resolve (`testThemeTokensAndFontsResolve`); no contrast ratio is computed |
| `InboxDeviceMatrixScreenshotTest.kt` | 21 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | phone and iPad; the other sizes are pinned by `AdaptiveTests` |
| `InboxErrorScreenshotTest.kt` | 12 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | error states are not rendered |
| `InboxLifecycleScreenshotTest.kt` | 6 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | restored / returning states are not rendered |
| `InboxLifecycleTest.kt` | 20 | `Inbox/InboxLifecycleTests.swift` | 20 | **partial** | 19 of 20: `viewerSaver_roundTripsEveryKind` is the media viewer's Android `Saver` |
| `InboxLiveTest.kt` | 19 | `Inbox/InboxLiveTests.swift` | 22 | **verified** |  |
| `InboxLogicTest.kt` | 24 | `InboxLogicTests.swift` | 26 | **partial** | 23 of 24: `waText_codeIsDmMonoAtWebSize` asserts a Compose font span; the iOS `WaStyle.code` parse is pinned, the font is the view's |
| `InboxNetworkStressTest.kt` | 50 | `Inbox/InboxNetworkStressTests.swift` | 50 | **partial** | 49 of 50 by name (`ownership_404_403_409` is split across three iOS tests) |
| `InboxPermissionsTest.kt` | 12 | `Inbox/InboxPermsTests.swift` + `Inbox/InboxPermissionsTests.swift` | 12 | **verified** | 4 (cycle 2) + 8 (cycle 8); the 403 re-read is driven through the host's re-read hook |
| `InboxStressTest.kt` | 12 | `Inbox/InboxStressTests.swift` | 12 | **partial** | 11 of 12: `refresh_finishesOnTheCallersThread_beforeReturning` is a dispatcher rule |

## Core: HTTP, auth, socket, notifications, crash (`core/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `ApiContractTest.kt` | 23 | `ApiContractTests.swift` | 27 | **partial** | 22 of 23: `orderItemsSurviveTheSnapshotCacheRoundTrip` — the snapshot round trip is pinned in `CatalogRulesTests.CatalogSnapshotRoundTrips` for the catalogue, not for orders |
| `AuthRepositoryTest.kt` | 31 | `AuthRepositoryTests.swift` | 37 | **verified** |  |
| `CoreA11yRound9Test.kt` | 1 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | a screenshot probe of the inbox's touch targets; iOS controls carry the 44 pt minimum by construction (cycle 3), not yet probed |
| `CoreLogicTest.kt` | 6 | `Core/CoreLogicTests.swift` | 6 | **verified** | cycle 8: `isPhoneLike` moved to the core (`Util/PhoneLike.swift`), `Perms.of`, the mappers |
| `CorePerfStressTest.kt` | 13 | `Stress/CorePerfStressTests.swift` + `Stress/NetworkStressTests.swift` | 25 | **partial** | 5 of 13 by name; the OkHttp cancellation-cause tests are Android's, the 200-frame burst / buffer backlog / coalescer overlap are pinned in `LiveSocketTests` and `FlowsTests` under other names |
| `CoreRound2Test.kt` | 6 | `Core/CoreRound2Tests.swift` | 6 | **verified** | cycle 8: en-KE "Sept", dashes for broken dates, the visitor glyph, uncapped badges, the nav order |
| `CoreRound9Test.kt` | 7 | `Core/CoreRound9Tests.swift` | 7 | **verified** | cycle 8: the coalescer under a slow run, `SingleFlight.cancel`, initials with emoji and combining marks |
| `CrashHardeningTest.kt` | 7 | `Crash/CrashTests.swift` | 15 | **partial** | 6 of 7: `dayHeadingsNeverRepeatAKeyEvenOutOfOrder` needs the day-heading builder, which is the app's (`CallsScreenModel.logItems`); the core's `rowKeys` half is pinned |
| `ErrorTextTest.kt` | 5 | `ErrorTextTests.swift` | 7 | **verified** |  |
| `LiveSocketTest.kt` | 23 | `LiveSocketTests.swift` | 24 | **verified** |  |
| `MessageAlertsTest.kt` | 15 | `Notify/NotificationTests.swift` | 38 | **verified** |  |
| `NeemaHttpTest.kt` | 15 | `NeemaHTTPTests.swift` | 21 | **partial** | 13 of 15: the OkHttp call-timeout-vs-cancel distinction is Android's; blank-body decoding is pinned in `ApiContractTests.AnEmptySuccessIsASuccess` |
| `NetworkStressTest.kt` | 17 | `Stress/NetworkStressTests.swift` | 17 | **verified** |  |
| `NotificationAlertsTest.kt` | 14 | `Notify/NotificationTests.swift` | 38 | **verified** |  |
| `NotificationCenterTest.kt` | 9 | `Notify/NotificationTests.swift` | 38 | **verified** |  |
| `TombstoneTextTest.kt` | 3 | — |  | **platform-restricted** | parses Android's debuggerd protobuf tombstones; iOS crash records are the vault's own JSON (`CrashTests`) |

## Customer panel (`customer/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `CustomerContractTest.kt` | 21 | `Crm/CustomerContractTests.swift` | 22 | **verified** |  |
| `CustomerLiveTest.kt` | 20 | `Crm/CustomerLiveTests.swift` | 20 | **verified** |  |
| `CustomerNetworkStressTest.kt` | 48 | `Crm/CustomerNetworkStressTests.swift` | 48 | **verified** |  |
| `CustomerPanelScreenshotTest.kt` | 47 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | the panel for the first thread is rendered; its 47 states are not |
| `CustomerViewModelTest.kt` | 49 | `Crm/CustomerViewModelTests.swift` | 46 | **partial** | 46 of 49: `superusersMayEditStages`, `plainAgentsDoNotGetTheStageEditor` (pinned in `InboxPermsTests.pipelineStageEditor`), `aBlockedMicrophoneIsTheAgentsProblemNotTheCustomers` (the softphone's card, `CallUxTests`) |

## Deals (`deals/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `DealsBehaviourTest.kt` | 12 | `Deals/DealsBehaviourTests.swift` | 13 | **verified** |  |
| `DealsContractTest.kt` | 13 | `Deals/DealsContractTests.swift` | 13 | **verified** |  |
| `DealsNetworkTest.kt` | 26 | `Deals/DealsNetworkTests.swift` | 26 | **verified** |  |
| `DealsScreenshotTest.kt` | 14 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `DealsStressTest.kt` | 6 | `Deals/DealsStressTests.swift` | 6 | **verified** |  |

## Screen freshness (`freshness/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `ScreenFreshnessTest.kt` | 23 | `Freshness/ScreenFreshnessTests.swift` + `Overview/OverviewLifecycleTests.swift` + `Catalog/CatalogViewModelTests.swift` + `FlowsTests.swift` | 45 | **verified** | 17 (cycle 8) + 6 already pinned elsewhere by name |

## Leads (`leads/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `LeadsBehaviourTest.kt` | 11 | `Leads/LeadsBehaviourTests.swift` | 11 | **verified** |  |
| `LeadsContractTest.kt` | 11 | `Leads/LeadsContractTests.swift` | 11 | **verified** |  |
| `LeadsNetworkTest.kt` | 21 | `Leads/LeadsNetworkTests.swift` | 21 | **verified** |  |
| `LeadsScreenshotTest.kt` | 11 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `LeadsStressTest.kt` | 6 | `Leads/LeadsStressTests.swift` | 6 | **verified** |  |

## Orders and sales (`orders/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `NetFaults.kt` |  | `Support/FakeNeema.swift` | 0 | **support** | drop / timeout / delay / hang faults are `FakeNeema`'s |
| `OrderPhoneLineTest.kt` | 5 | `Orders/OrderPhoneLineTests.swift` | 6 | **verified** |  |
| `OrdersBehaviourTest.kt` | 14 | `Orders/OrdersBehaviourTests.swift` | 15 | **verified** |  |
| `OrdersContractTest.kt` | 13 | `Orders/OrdersContractTests.swift` | 14 | **verified** |  |
| `OrdersNetworkTest.kt` | 14 | `Orders/OrdersNetworkTests.swift` | 15 | **verified** |  |
| `OrdersScreenshotTest.kt` | 16 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `OrdersStressTest.kt` | 8 | `Orders/OrdersStressTests.swift` | 7 | **partial** | 7 of 8: `callersDuringAReadShareTheNextOneAndNothingStacks` has no twin by name (the feed's single-flight is pinned in `OrdersNetworkTests`) |
| `SalesLifecycleTest.kt` | 17 | `Orders/OrdersLifecycleTests.swift` + `Leads/LeadsLifecycleTests.swift` + `Deals/DealsBehaviourTests.swift` | 25 | **partial** | 12 of 17 by intent (the deals three are one iOS test); the five `restored*` rows are Paparazzi snapshots |
| `SalesNetworkScreenshotTest.kt` | 17 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | error states are not rendered |
| `SalesPermissionMatrixTest.kt` | 14 | `Orders/SalesPermissionMatrixTests.swift` + `Orders/SalesPermissionExtraTests.swift` | 15 | **verified** | 11 (cycle 4) + 4 (cycle 8) |
| `SalesPolishScreenshotTest.kt` | 27 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `SalesStressScreenshotTest.kt` | 8 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | the thousand-row lists are pinned by the stress tests, not rendered |
| `SalesTestSupport.kt` |  | `Orders/OrdersTestSupport.swift` + `Support/SalesFixtures.swift` | 0 | **support** |  |
| `TouchAudit.kt` |  | — |  | **platform-restricted** | a Compose semantics walk; no SwiftUI equivalent without a device |

## Analytics / overview (`overview/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `OverviewMathTest.kt` | 12 | `Overview/OverviewMathTests.swift` | 14 | **partial** | 10 of 12 by name: the unnamed-buyer activity line and the seven-day revenue marking today are not pinned by name |
| `OverviewScreenshotTest.kt` | 14 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |

## Profile (`profile/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `ProfileDeviceMatrixScreenshotTest.kt` | 14 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `ProfileLifecycleTest.kt` | 5 | `Profile/ProfileLifecycleTests.swift` | 6 | **verified** |  |
| `ProfileNetworkTest.kt` | 13 | `Profile/ProfileNetworkTests.swift` | 13 | **verified** |  |
| `ProfileScreenshotTest.kt` | 19 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `ProfileViewModelTest.kt` | 13 | `Profile/ProfileViewModelTests.swift` | 15 | **verified** |  |

## Reports and insights (`reports/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `AnalyticsDeviceMatrixTest.kt` | 31 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` + `AdaptiveTests.swift` | 15 | **partial** | screenshot matrix (font 13 / 20, fold, tablet landscape); phone and iPad rendered, the column rules pinned by `AdaptiveTests` |
| `ApiContractTest.kt` | 26 | `ApiContractTests.swift` + `Reports/ReportsViewModelTests.swift` + `Overview/OverviewViewModelTests.swift` + `Catalog/CatalogViewModelTests.swift` | 69 | **partial** | 5 of 26 by name; the orders / catalog / audit / attribution shapes are pinned in `ApiContractTests` under its own names, the stats fallback and audit-hidden rules in the view-model tests; not re-checked row by row |
| `AreaPermissionMatrixTest.kt` | 12 | `Reports/AreaPermissionMatrixTests.swift` + `Overview/OverviewPermissionTests.swift` + `Reports/ReportsViewModelTests.swift` | 33 | **verified** | 8 (cycle 8) + 4 already pinned |
| `AreaPersonaScreenshotTest.kt` | 5 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | one persona |
| `AreaViewModelTest.kt` | 10 | `Reports/ReportsViewModelTests.swift` + `Overview/OverviewViewModelTests.swift` + `Catalog/CatalogViewModelTests.swift` + `Reports/AreaViewModelTests.swift` | 43 | **verified** | 9 already pinned + 1 (cycle 8: the audit read never writes) |
| `InsightsLifecycleTest.kt` | 6 | `Reports/ReportsLifecycleTests.swift` + `Catalog/CatalogViewModelTests.swift` + `Overview/OverviewLifecycleTests.swift` | 28 | **verified** | all six already pinned by intent |
| `InsightsNetworkTest.kt` | 21 | `Reports/ReportsViewModelTests.swift` + `Reports/InsightsNetworkTests.swift` + `Catalog/CatalogViewModelTests.swift` + `Catalog/FriendlyErrorsTests.swift` | 46 | **partial** | 20 of 21: 14 already pinned + 6 (cycle 8); `export_noShareTarget_saysWhatToInstall` is Android's ActivityNotFoundException |
| `InsightsStressScreenshotTest.kt` | 12 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | stress states not rendered |
| `InsightsStressTest.kt` | 13 | `Reports/ReportsStressTests.swift` + `Reports/InsightsStressTests.swift` | 13 | **verified** | 7 (cycle 6) + 6 (cycle 8: analytics over 5 000 orders, the catalogue index over 2 000 products) |
| `ReportMathTest.kt` | 12 | `Reports/ReportMathTests.swift` | 14 | **verified** |  |
| `ReportsRolloverTest.kt` | 4 | `Reports/ReportsLifecycleTests.swift` + `Reports/ReportMathTests.swift` + `Reports/ReportsRolloverTests.swift` | 22 | **verified** | 3 already pinned + 1 (cycle 8) |
| `ReportsScreenshotTest.kt` | 25 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `RestoredInsightsScreenshotTest.kt` | 3 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | restored state not rendered |

## Settings (`settings/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `CallingSettingsModelTest.kt` | 5 | `Settings/CallingSettingsModelTests.swift` | 7 | **verified** |  |
| `SettingsContractTest.kt` | 19 | `Settings/SettingsContractTests.swift` | 21 | **verified** |  |
| `SettingsDeviceMatrixScreenshotTest.kt` | 26 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `SettingsLifecycleTest.kt` | 6 | `Settings/SettingsLifecycleTests.swift` | 7 | **verified** |  |
| `SettingsNetworkTest.kt` | 22 | `Settings/SettingsNetworkTests.swift` | 23 | **verified** |  |
| `SettingsScreenshotTest.kt` | 28 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `SettingsViewModelTest.kt` | 24 | `Settings/SettingsViewModelTests.swift` | 25 | **verified** |  |

## Tablet layouts and input (`tablet/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `TabS9UltraScreenshotTest.kt` | 10 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** | iPad 1180 × 820 stands in for the Tab S9 Ultra |
| `TabletInputTest.kt` | 12 | `Shell/TabletInputTests.swift` | 15 | **verified** | cycle 9: the keyboard and drop rules moved into the core (`Shell/Shortcuts.swift`) — `KeyboardRulesTests` 11 + `stepping` 1 |
| `TabletLayoutTest.kt` | 23 | `Shell/TabletLayoutTests.swift` + `AdaptiveTests.swift` + `Shell/TabletInputTests.swift` | 49 | **verified** | the 13 Tab S9 Ultra widths, call docking (`DockRules.swift`), the 6 details-pick rules, the 3 Esc-key rules (`EscapeKeyTests`, cycle 9) |

## Team (`team/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `AgentsViewModelTest.kt` | 29 | `Team/TeamViewModelTests.swift` | 31 | **verified** | every one of the 29 by name |
| `AreaHarness.kt` |  | `Support/TestHost.swift` | 0 | **support** |  |
| `AreaShots.kt` |  | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **support** |  |
| `LegibilityTest.kt` | 4 | `Team/TeamLegibilityTests.swift` | 5 | **verified** |  |
| `NetworkErrorScreenshotTest.kt` | 16 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | error states not rendered |
| `PermissionMatrixTest.kt` | 8 | `Team/TeamPermissionMatrixTests.swift` | 8 | **verified** | cycle 8 |
| `RestoreShots.kt` |  | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **support** |  |
| `RestoredFormsScreenshotTest.kt` | 4 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **partial** | restored forms not rendered |
| `TeamContractTest.kt` | 20 | `Team/TeamContractTests.swift` + `Team/TeamViewModelTests.swift` | 47 | **verified** | 16 (cycle 8) + 4 already pinned |
| `TeamDeviceMatrixScreenshotTest.kt` | 20 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |
| `TeamLifecycleTest.kt` | 7 | `Team/TeamLifecycleTests.swift` + `Team/TeamViewModelTests.swift` | 37 | **verified** | 6 (cycle 8) + 1 already pinned |
| `TeamNetworkTest.kt` | 27 | `Team/TeamNetworkTests.swift` | 27 | **verified** |  |
| `TeamScreenshotTest.kt` | 32 | `apps/ios/NeemaAppTests/Gallery/ScreenGalleryTests.swift` | 1 | **gallery** |  |

## Test support and fixtures (`testing/`)

| Android test file | tests | iOS counterpart | tests | status | note |
|---|---|---|---|---|---|
| `A11yProbe.kt` | 1 | — |  | **platform-restricted** | a Compose semantics probe |
| `DeviceMatrix.kt` | 1 | `AdaptiveTests.swift` | 14 | **support** | the window classes the gallery and `AdaptiveTests` use |
| `FakeNeema.kt` |  | `Support/FakeNeema.swift` | 0 | **support** |  |
| `FakeSocket.kt` |  | `Support/FakeSocket.swift` | 0 | **support** |  |
| `Fixtures.kt` |  | `Support/Fixtures.swift` | 0 | **support** |  |
| `Harness.kt` |  | `Support/TestHost.swift` + `Support/Support.swift` | 0 | **support** |  |
| `MainDispatcherRule.kt` |  | `Support/Support.swift` | 0 | **support** | `drain()`, `eventually`, `settle` and the `VirtualClock` stand in for the dispatcher rule |
| `MemoryPrefs.kt` |  | `Support/Support.swift` | 0 | **support** | `MemoryStore` + `AppPrefs(store:)` |
| `Personas.kt` |  | `Support/TestHost.swift` | 0 | **support** | `TestHost(role:superuser:)` |
| `PinnedClock.kt` |  | `Support/Support.swift` | 0 | **support** | `PINNED`, `AppClock.pin` |
| `AreaPersonaFixtures.kt` |  | `Support/ReportsFixtures.swift` | 0 | **support** |  |
| `CallsFixtures.kt` |  | `Support/CallsFixtures.swift` | 0 | **support** |  |
| `CustomerFixtures.kt` |  | `Support/CustomerFixtures.swift` | 0 | **support** |  |
| `InboxFixtures.kt` |  | `Support/InboxFixtures.swift` | 0 | **support** |  |
| `InboxNetFixtures.kt` |  | `Support/InboxFixtures.swift` | 0 | **support** |  |
| `InboxPersonaFixtures.kt` |  | `Support/InboxFixtures.swift` | 0 | **support** |  |
| `InboxPolishFixtures.kt` |  | `Support/InboxFixtures.swift` | 0 | **support** |  |
| `InboxStressFixtures.kt` |  | `Support/InboxStressFixtures.swift` | 0 | **support** |  |
| `InsightsStressFixtures.kt` |  | `Support/InsightsStressFixtures.swift` | 0 | **support** |  |
| `NetStressFixtures.kt` |  | `Support/FakeNeema.swift` | 0 | **support** |  |
| `ReportsFixtures.kt` |  | `Support/ReportsFixtures.swift` | 0 | **support** |  |
| `SalesFixtures.kt` |  | `Support/SalesFixtures.swift` | 0 | **support** |  |
| `SalesPersonaFixtures.kt` |  | `Support/SalesFixtures.swift` | 0 | **support** |  |
| `SalesPolishFixtures.kt` |  | `Support/SalesFixtures.swift` | 0 | **support** |  |
| `SalesStressFixtures.kt` |  | `Support/SalesFixtures.swift` | 0 | **support** |  |
| `TeamFixtures.kt` |  | `Support/TeamFixtures.swift` | 0 | **support** |  |

## Totals

| status | Android files | Android tests |
|---|---|---|
| verified | 66 | 1006 |
| partial | 44 | 755 |
| gallery | 28 | 501 |
| platform-restricted | 6 | 14 |
| support | 33 | 1 |
| **all** | **177** | **2277** |

iOS test functions: **1584** in `NeemaCore` (Linux), **5** in the app's test bundle (macOS CI, one of them the gallery's render of every screen), **6** UI tests (macOS CI).

## How the ports were made (cycle 8)

Every Android test was matched to the iOS suites by name and, where the
names differ, by intent; the matcher's output drove the table above. What
had no twin was ported in this order: the softphone (`FrameFuzzTests`,
`CallNativeSafetyTests`, `CallsParityTests`), the core rules
(`Core/CoreLogicTests`, `CoreRound2Tests`, `CoreRound9Tests`), the inbox's
permissions (`InboxPermissionsTests`), screen freshness
(`Freshness/ScreenFreshnessTests`), the shell (`Shell/TabletLayoutTests`
with `CallsDetailsPickTests`, `TabletInputTests`, `ToastLifecycleTests`,
`LiveLifecycleTests`, `ShellLifecycleTests`, `DashboardRulesTests`,
`ShellPermissionMatrixTests`), sales and insights
(`Orders/SalesPermissionExtraTests`, `Reports/ReportsRolloverTests`,
`AreaViewModelTests`, `AreaPermissionMatrixTests`, `InsightsNetworkTests`,
`InsightsStressTests`) and the team (`Team/TeamContractTests`,
`TeamLifecycleTests`, `TeamPermissionMatrixTests`).

Four pure helpers moved from the app into the core so Linux can test them,
with the app now calling the core's: `avatarIndex`, `initialsOf`,
`DetailsPick` / `detailsPick` (`Calls/CallVisualsRules.swift`),
`isPhoneLike` (`Util/PhoneLike.swift`), `CALL_PANEL_WIDTH` / `callDocks`
(`Shell/DockRules.swift`).

Android tests that only the app layer can answer on iOS (`AppModel`,
`DashboardShell`) are marked **platform-restricted** with the iOS file that
holds the behaviour, so the parity matrix can cite it. A test harness gap
to know about: `TestHost`'s 403 re-read counts itself and fetches `/admin/me`
and `/admin/agents` but does not store the rows, so "the nav corrected itself"
is asserted on the list the re-read fetched, not on a live nav (the app's
`AppModel.onForbidden` does store them).

## What the screenshot suites cover that the gallery does not

Android's Paparazzi suites (the **gallery** and **partial** rows) pin 600-odd
named states: every call card phase and wrap-up outcome, offline and
server-down banners on every screen, restored forms after a process death,
large-text and small-phone layouts, three personas' navigation. The iOS
gallery renders each screen once per shot in the fixtures' state. Rendering
the named states needs either a device run or a gallery that drives each
screen model into the state first; the rules behind the states (the words,
the phases, the gating) are pinned by the Linux suites instead.
