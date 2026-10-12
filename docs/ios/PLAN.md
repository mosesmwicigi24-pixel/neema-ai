# Neema iOS — the programme and its ten improvement cycles

**Directive.** Build the production-ready Neema iOS app mirroring the Android
app (`apps/android`) screen for screen and feature for feature, in Swift and
SwiftUI with native Apple conventions, against the same backend, APIs and
business logic. Execution order: complete current work → audit Android →
establish feature parity → implement iOS top to bottom → run exactly ten
controlled improvement cycles → verify Android-to-iOS equivalence → validate
production readiness → deliver the final report → stop.

**Anti-loop rules in force.** Ten cycles, no more; one pass per cycle; at
most three correction attempts per issue, then it is logged as a blocker and
the cycle moves on; completed work is never rebuilt; no recursive
improvement; every cycle records measurable progress (below); the scope of a
cycle is what its row says; a critical blocker is documented and the
programme continues around it; after cycle 10 the final report is written
and the programme ends.

**Testing honesty.** Each item is reported as one of: implemented-and-verified
(a test ran here or on CI), implemented-unverified (compiled only, or not
even that), partial, missing, platform-restricted, blocked. Nothing is
reported as tested on a device: no device, simulator session or TestFlight
build has been touched by this programme — the only machines are a Linux
workstation (Swift 6.2 toolchain) and GitHub's macOS runners.

**What exists at the start.** The Android app: 112 Kotlin files, Compose +
Material 3, OkHttp, kotlinx.serialization, Coil, Media3, WebRTC; 170 unit and
screenshot test files pinning its behaviour. No iOS code. The four Android
audits (shell/auth/settings; inbox/thread/customer/socket/models;
calls/notifications/permissions/crash; orders/catalog/deals/leads/API) feed
`PARITY_MATRIX.md`.

---

## The ten cycles

| Cycle | Scope (fixed) | Done when |
|---|---|---|
| 1 | **Architecture & foundation.** The Swift package `NeemaCore` (models, JSON leniency, HTTP client + session rules, auth + refresh, Keychain session store, live socket, API surface, formatting, permissions, single-flight/coalescer, shell rules), the SwiftUI app skeleton (entry, container, sign-in, session-expired, shell with phone chrome, placeholders), XcodeGen project, CI on Linux + macOS, the parity matrix and this plan. | Core tests green on Linux; app builds and its tests pass on macOS CI; matrix and plan committed. |
| 2 | **Screen & feature parity, part 1 (data screens).** `ScreenLife`, snapshots, prefs; Inbox list + thread + composer + dialogs + customer panel (the CRM API wrapper); Orders; Catalog; Deals; Leads (its API wrapper); Analytics; Reports (CSV via the share sheet); Team; Profile. Every screen's strings, states, polls and failure rules from the matrix; the logic of each screen in `NeemaCore` with ported unit tests. | Every row in matrix §3–7, §11–17, §19 is at least "unverified"; the ported logic tests are green. |
| 3 | **UI/UX refinement.** Theme tokens wired (light/dark, three toggles), typography scale, icons, shared components, adaptive layouts (phone / iPad panes, docked sidebar and rail, side sheets), launch screen and app icon, back/sheet ordering, state restoration. Native polish: safe areas, Dynamic Type caps, haptics, SF Symbols where the web icon has a twin. | Matrix §2 chrome rows and §22 rows at "unverified" or better; a screenshot of each screen from the simulator on CI. |
| 4 | **Business logic & backend integrity.** Settings (every card, incl. WhatsApp calling and crash reports), the server contracts re-checked endpoint by endpoint against the OpenAPI (140 routes), every write's uncertain-result reconciliation, 403 → access re-read, permission gates, the price/ordering invariants the Android tests pin. | Matrix §18 and §23 rows at "unverified" or better; the contract tests extended to every endpoint a screen calls. |
| 5 | **Messaging, communication & real-time.** Socket consumers for every frame (inbox, thread, customer panel, Overview, Deals, Settings), notifications (bell, mute, local notifications while running, message alerts), the softphone (`CallManager` port with its 59 tests, WebRTC, CallKit, audio routes, call card, console, details, transcripts), VoIP/APNs client registration (server side documented as blocked). | Matrix §8–10 and §24 rows at "unverified" or better except the blocked backend items. |
| 6 | **Performance.** Off-main decoding and list building, image caching, memory on the 14k-row report, socket burst handling, launch time, polling discipline (only in front), battery (no timers in background), the perf/stress tests ported (`CorePerfStressTest`, `NetworkStressTest`, inbox/customer stress). | Stress tests green on Linux; CI simulator run within the time budget; no main-thread decode. |
| 7 | **Security & permissions.** Keychain accessibility, no secrets in logs or snapshots, TLS-only, App Transport Security, privacy manifest and usage strings, mic/camera/photos/notifications permission flows with native rationale, crash reporting without PII beyond what Android sends, RBAC gates audited screen by screen. | Matrix §20 at "unverified" or better; a written permission/privacy checklist. |
| 8 | **Comprehensive functional & stress testing.** The Android test inventory mapped test-file by test-file; everything portable ported (logic, contracts, lifecycle, stress); UI tests on the simulator for the flows CI can drive (sign-in, nav, inbox, orders, settings); the fake backend with the full fixture set. | A test map in `docs/ios/TESTS.md`; CI green with the full suite. |
| 9 | **Final refinement & cross-platform consistency.** Walk the matrix row by row against Android's screenshot goldens; iPad parity (two-pane, keyboard, drop); wording diffs fixed; a consistency log. | Every matrix row re-verified and its status updated. |
| 10 | **Final verification & production readiness.** Release configuration, versioning, signing/TestFlight instructions (blocked without credentials), the final report with the honest status of every item, the list of blockers and the hand-over. Then stop. | `docs/ios/FINAL_REPORT.md` delivered; programme ended. |

---

## Cycle log

Each cycle records: features implemented/verified, defects corrected, tests
executed and results, remaining parity gaps, blockers, next cycle.

### Cycle 1 — Architecture & foundation

**Features implemented / verified**

- `NeemaCore` Swift package (`apps/ios/NeemaCore`), Swift 5 language mode,
  platforms iOS 16 / macOS 13, builds and tests on Linux with Swift 6.2:
  - `JSON/`: `JSONValue` tree, `NeemaJSON`, `LenientKeyed` (numbers as
    strings, null as default, lenient string lists, variant attributes) —
    verified.
  - `Models/`: all 52 Android wire types with the same keys and defaults,
    `OrderItem.normalise`, computed twins (`handle`, `recency`, `status`,
    `customerName`, `id/category/isHub`, `permissions`, `insights`,
    `renegotiationSdp`, `urlList`) — verified by contract tests decoding the
    handlers' real shapes (Android's `ApiContractTest` fixtures ported).
  - `Net/`: `ApiError` (detail / field / code / action / timedOut /
    malformed), `ErrorText`, `HTTPTransport` + `URLSessionTransport`
    (no cookie jar, redirects only when asked, hard ceiling, upload from a
    temp file), `MultipartBody`, `NeemaHTTP` (bearer, 30 s / 10 min, 401
    rescue, 403 signal, empty/malformed 2xx, cancellation) — verified with a
    fake transport; the URLSession transport is unverified (no network here).
  - `Auth/`: `Session`, `SessionStore` over `SecureStore` (`KeychainStore`
    on Apple platforms, `MemoryStore` for tests), `AuthRepository` (direct
    mounts → NextAuth bridge with a cookie jar, refresh lock, 3 attempts,
    refusal/timeout final, 30 s cooldown, role kept in nextauth mode) —
    verified (37 tests mirroring Android's `AuthRepositoryTest`).
  - `Live/`: `LiveSocket` (URL, token per attempt, ping 25 s, backoff
    2/4/8/16/30, nudge, reconnected rules, replaced-socket guard, 1,024
    buffer, dropped-frame count) + `URLSessionWebSocketFactory` — the rules
    verified on a virtual clock (24 tests mirroring `LiveSocketTest`); the
    URLSession factory unverified.
  - `Api/NeemaApi`: every endpoint group of Android's `NeemaApi.kt` with the
    same paths, query names (`%20` encoding) and bodies; `UploadFile`,
    `InboxQuery` — verified for the endpoints the contract tests cover.
  - `Util/`: `Perms`, `Fmt`, `AppClock`, `SingleFlight`, `Coalescer`,
    `Signal`/`Watched`/`AsyncLock` — verified.
  - `Shell/`: `ViewId`, `DeepLink` (URL acceptance + action), `NavHistory`,
    `Toast` + `ToastPresenter` (3.5 s in front, ≥ 1.5 s after a return),
    `Access`, `ShellRules.navItems` — verified.
- SwiftUI app skeleton (`apps/ios/NeemaApp`): entry, `AppContainer` (Keychain
  session store, auth, HTTP, API, socket, foreground via `scenePhase`,
  network via `NWPathMonitor`, live-connection policy), `AppModel`
  (sign-in / sign-out, me + agents polls, access, nav, deep links incl. the
  pending link, toasts, session-expired, forbidden re-read), `RootView`,
  `LoginView` (Android's copy and night palette), `SessionExpiredView`,
  `DashboardShell` (phone header + bottom nav + drawer; wide: docked navy
  sidebar), `ToastView`, `ConnectivityBanner`, placeholders per view,
  `NeemaTheme` tokens and fonts (Manrope, DM Mono bundled) — **unverified**
  until the macOS CI job compiles it; see "Blockers".
- XcodeGen `project.yml` (iOS 16 deployment, usage strings, `neema://`
  scheme, background modes audio/voip/remote-notification, fonts),
  `NeemaAppTests` (smoke tests), `.github/workflows/ios.yml` (Linux core job
  in the `swift:6.2` container; macOS job: XcodeGen → xcodebuild build+test
  on the iPhone simulator, log uploaded).
- `docs/ios/PARITY_MATRIX.md` (every Android feature with its iOS status and
  target cycle) and this plan; `apps/ios/README.md`.

**Defects corrected** (found by the ported tests while writing the core)

1. Virtual-clock race in the socket/coalescer tests: a task registered its
   timer after time had moved; the clock now settles before advancing.
2. `ToastPresenter` timer task typed `Task<()?, Never>` — fixed.
3. Test helpers awaiting inside `XCTAssert` autoclosures — hoisted.
4. Two socket tests dropped their `LiveSocket` (weak-self tasks) — the tests
   keep a reference, as the container does in the app.
5. Found by the first macOS CI run: a return to the foreground both opened
   the socket (the live policy) and nudged it, which cancels a socket still
   shaking hands and opens a second one. The nudge is for a socket already
   wanted and mid-backoff, so it is sent only when the foreground state did
   not change (`AppModel.setForeground`).

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux (Swift 6.2): **147 tests,
  0 failures** — ErrorText 7, NeemaHTTP 21, AuthRepository 37, LiveSocket
  24, Fmt 10, Perms 6, Flows 7, ApiContract 27, Shell 7, JSONValue 1.
- macOS CI (pull request #269, `Neema app (iOS Simulator)` job, macOS 15,
  XcodeGen → xcodebuild on the iPhone 17 simulator): run 1 on `27f2cc4` —
  **BUILD SUCCEEDED** on the first compile of the SwiftUI layer, app tests
  3 of 4 (defect 5 above); run 2 on `7a2b7f0` — build and **4 of 4 app
  tests green**. The Linux core job was green on both runs.

**Remaining parity gaps** — everything in `PARITY_MATRIX.md` marked
missing/partial: all screens (cycles 2–5), notifications and the softphone
(5), settings (4), crash reporting (7); the Android-only mechanisms listed
in matrix §25.

**Blockers**

- No Xcode here: SwiftUI is compiled and its tests run only by the macOS CI
  job (green since run 2). The app layer is "implemented-unverified" on a
  device: no simulator session can be driven from here, nothing is signed.
- Backend push (APNs + PushKit VoIP + token endpoints) does not exist: alerts
  and calls to a closed app cannot work on iOS until it does (matrix §25).
- No Apple Developer credentials: nothing can be signed, installed on a
  device or sent to TestFlight.

**Next cycle** — Cycle 2: `ScreenLife`, snapshots, prefs, then the data
screens top to bottom (Inbox → Thread → Composer → Customer panel → Orders →
Catalog → Deals → Leads → Analytics → Reports → Team → Profile) with their
logic in `NeemaCore` and the Android unit tests ported alongside.

### Cycle 2 — Screen & feature parity, part 1 (data screens)

Pull request #270, built up in nine pushes (`694586f` … `68e5aed`), each one
compiled by the macOS job.

**Features implemented / verified**

- Core foundations for every screen (`NeemaCore`): `ScreenLife` (shown ×
  foreground × connected → polls, catch-ups on return and reconnect),
  `SnapshotCache` (per-agent painted-at-sign-in snapshots), `AppPrefs` +
  `AlertSettings` (moved into the core), `InboxMemory`, `NetErrors` /
  `SalesFailures` / `FriendlyErrors` (the fate of a failed request and the
  plain words for it), `Polling`, `LocalDay`, `MuteWords` — verified.
- Inbox (`Inbox/`): `InboxViewModel`, the port of Android's
  `ConversationsViewModel` — the paged list, tabs, search, channel chips,
  filter panel, grouped rows, bulk release, the thread (pages, poll, window,
  activity, drafts), live frames (`new_message` / `message`,
  `intercept_changed`, `ai_draft_ready`, `translations`, `history_cleared`,
  the call frames), the ownership controls and their truth table, the outbox
  with its 2 / 8 / 20 s reconciliation and 401 hold, attachments, Ask /
  Answer / Invite, deep links, per-customer composers — verified (180 tests
  in `Tests/Inbox` + the inbox logic and wrapper suites). SwiftUI:
  `InboxScreen` (phone / two-pane / docked panel), `ConversationListView`,
  `ThreadView` (rows, bubbles, WhatsApp formatting in `WaTextView`, media in
  `MediaViews` with the pinch viewer and album pager, `ThreadCallView`),
  `ComposerView` (AI draft panel, quote strip, window strip, translate
  preview, attach menu, media tray), the dialogs (Transfer, Add Note, Clear
  history, Ask Neema, Neema delivers, Invite), the activity log — unverified
  (compiled on the macOS job).
- Customer panel (`Crm/`): `CrmApi` and `CustomerViewModel` (load, quiet
  reloads, hero, tabs, pipeline, tags, notes with the 3-way merge, identity
  merge / unmerge, enquiry push / decline, invite, template, Ask / Answer,
  every PATCH body and rollback rule) — verified (136 tests). SwiftUI:
  `CustomerPanelView`, `CustomerTabsView`, `CustomerWidgets`,
  `CustomerCallsView` (the calls section renders; the call-request flow is
  cycle 5) — unverified.
- Orders (`Orders/`): `OrdersFeed` (one read on the wire, 90 s poll,
  `order_update` coalesced, reconnect catch-up, snapshot, pending badge),
  `OrderUi` rules, `OrdersViewModel` — verified (75 tests incl. the
  permission-matrix personas). SwiftUI: list, status cards, search, pages,
  row, detail (sheet / side sheet / docked pane), status moves — unverified.
- Catalog (`Catalog/`): `CatalogFeed` (5-minute poll, snapshot),
  `CatalogRules`, `CatalogViewModel` (filter, search, audit) — verified (33
  tests). SwiftUI: grid, source banner, price-audit banner, product sheet —
  unverified.
- Deals (`Deals/`): `DealsRules`, `DealsViewModel` (three reads, 60 s poll,
  `planned_action` / `hub_event` coalesced, guidance / won / lost, approve
  and veto with the lock-until-known settle loop) — verified (58 tests).
  SwiftUI: queue card, three columns, deal card, guidance editor, the
  edit-and-send sheet — unverified.
- Leads (`Leads/`): `LeadsApi`, `LeadsRules` (stages, filter, the sheet's
  diff, `editLanded`, the board in one pass), `LeadsViewModel` (optimistic
  moves, rollback, 404 = gone, lost answers settled by re-reading) —
  verified (54 tests). SwiftUI: kanban columns sized like Android's, cards,
  stage pills, the lead sheet (phone sheet / side sheet) — unverified.
- Analytics (`Overview/`): `OverviewRules` on `LocalDay`, `OverviewViewModel`
  (stats + attribution + the human tab, 30 s poll, coalesced reloads on the
  listed notification types and `intercept_changed`) — verified (30 tests).
  SwiftUI: stat grid, attribution, 7-day revenue, order status, by channel,
  recent activity, top products — unverified.
- Reports (`Reports/`): `ReportsRules` (the report in one pass, tables,
  RFC-4180 CSV to a `.part` file, the unpaged download and its failure
  words), `ReportsViewModel` (one download per visit, off-main rebuilds,
  midnight rollover, the export held until shared) — verified (49 tests
  incl. a 10,000-conversation stress). SwiftUI: range menu, date pickers,
  Export CSV through `UIActivityViewController`, tabs, tiles, tables / cards
  — unverified.
- Team (`Team/`): `PermissionCatalog`, `ROLE_COLORS`, `TeamColors`,
  `TeamForms`, `TeamApi`, `TeamViewModel` (every write under one saving
  flag, verify-after-no-answer, 404 = removed by someone else, masked
  secrets, optimistic availability, per-agent overrides, role CRUD with a
  fixed draft id) — verified (63 tests). SwiftUI: header, tabs, agent grid
  and card, role list, the seven dialogs as sheets with the permission
  picker and the twelve swatches — unverified.
- Profile (`Profile/`): `ProfileViewModel` (forms filled once per agent and
  kept across a reclaim, save profile with the duplicate-email check,
  password change that never echoes the password, availability, the four
  notification switches on the device), the mute words — verified (34
  tests). SwiftUI: profile card and edit form, stat tiles, Availability,
  Password, Appearance, Notifications, Sounds & vibration, Your Permissions,
  Account — unverified.
- Shell: `ShellInboxHost` serves every screen's host protocol; `AppModel`
  owns one model per screen per sign-in and mirrors `me` / `agents` into
  the host; `DashboardShell` routes every view but Calls (cycle 5) and
  Settings (cycle 4). Shared SwiftUI pieces: `StateViews`, `PanelCard`,
  `InboxSupport` (buttons, tints, `FlowLayout`), `TeamDialogs` (form
  pieces); scene state restored per screen (`orders.ui`, `catalog.ui`,
  `deals.ui`, `leads.ui`, `reports.ui`, `team.*`, `profile.*`).

**Defects corrected** (found by the ported tests and the macOS job)

1. Orders: statements inside view-builder bodies and a `tint` helper
   colliding with SwiftUI's modifier (run 7 on `845c7af`) — the thread
   header's actions are built in plain functions; the helper is `tintOf`.
2. Media views: the player's status publisher needs Combine (same run).
3. Deals stress flake (151 vs 150 resolved actions): a lost update between
   two concurrent fake handlers — the test `Ref` gained an atomic `mutate`
   and every counter the handlers bump uses it.
4. Leads stress: the first move raced the board's first read — the test's
   model waits for the read to land.
5. Reports: a test host without orders made the export one line — the
   reports test case reads orders and agents at sign-in, as the dashboard
   does; the `settle` helper shadowed the global one (renamed `landed`).
6. XCTest on Linux aborts test discovery for a synchronous `throws` test in
   a `@MainActor` class — such tests are `async throws`.
7. Team: a raw string holding `"#0891b2"` needs `##"…"##`; main-actor
   isolation inside `quietly { }` closures — a `@MainActor` method instead.
8. macOS job, run 10 on `6218f43`: the brand icon paths were referenced on
   `SVGPath` (the parser) instead of `ChannelIcons`.
9. macOS job, run 11 on `d5df914`: the overview screen redeclared the
   reports' `TopRoundedBar`; a `PanelHeader` name collided with the
   customer panel's private one (renamed `PanelHeadline`).

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux (Swift 6.2): **917 tests, 0
  failures** (154 s) — Inbox 180, Crm 136, Orders 75, Team 63, Deals 58,
  Leads 54, Reports 49, Profile 34, Catalog 33, Overview 30, Calls 8, and
  the 197 foundation tests (cycle 1's 147 plus the FriendlyErrors, inbox
  logic, wrapper and adaptive suites). 770 tests were added this cycle.
- macOS CI (`Neema app (iOS Simulator)`, XcodeGen → xcodebuild on the
  iPhone 17 simulator): run 8 on `e1f9464` and run 9 on `d9c9abb` green;
  runs 7, 10 and 11 failed on the compile errors listed above, each fixed
  in the next push; run 12 on `68e5aed` (the
  final code push: Team + Profile) — **build and app tests green**; the
  Linux core job was green on every run.

**Remaining parity gaps** (scope of this cycle)

- Every SwiftUI screen is "unverified": compiled on the macOS job, never
  seen on a device or driven in a simulator session.
- Composer: the lost-files note after process death (the restore itself is
  in `InboxMemory`) — cycle 3.
- Sheets: `AdaptiveSheet` (the 440 dp end panel on tablets) — cycle 3; the
  inbox's rail widths are re-checked against Android's in cycle 3.
- Customer panel: the call-request flow, the call-button decision sheet and
  the live call frames — cycle 5, with the softphone; the Calls and
  Settings views are still placeholders (cycles 5 and 4).
- Reports: Android's "share target missing" export failure has no iOS twin
  (the share sheet always exists) — platform-equivalent, not a gap.
- Profile: "Stay connected in background" and the battery-saver link are
  platform-restricted (no foreground service on iOS); background delivery
  is the push path, blocked on the backend (matrix §25).
- Notifications: the `notification` frames are consumed by the feeds that
  need them; the bell, toasts and tray are cycle 5.

**Blockers** (carried)

- No Xcode here: the SwiftUI layer is compiled only by the macOS job; no
  device, simulator session or TestFlight build has been touched.
- Backend push (APNs + PushKit VoIP + token endpoints) does not exist.
- No Apple Developer credentials: nothing is signed.
- `aRefusalCorrectsTheNav` (the shell's 403 re-read) lives in `AppModel`
  and cannot be unit-tested on Linux; its host-side coalescing is.

**Next cycle** — Cycle 3: UI/UX refinement — theme tokens and the three
toggles, typography scale, the web's icon paths for the nav, shared
components, adaptive layouts (phone / iPad panes, docked sidebar and rail,
`AdaptiveSheet`), launch screen and app icon, back / sheet ordering, state
restoration for the inbox, Dynamic Type caps, haptics; a screenshot of each
screen from the simulator on CI.

### Cycle 3 — UI/UX refinement

Pull request #271 on `claude/where-are-we-bx9v9w` (restarted from `main`
after cycle 2 merged).

**Features implemented / verified**

- Theme tokens wired: the dim washes (`greenDim` … `indigoDim`), the chrome's
  icon ink, the tones (success / warning / error / info / moss, light and
  dark) now used by the toast and the connectivity banner;
  `NeemaFont.capped(_:maxScale:)` — text that grows with the user's size
  only up to a cap (Android `scaledAtMost`) for the wordmark, tab labels,
  badges and the "Reconnecting…" pill. Three dark-mode toggles (header,
  account card, Profile) drive one `theme` pref; the login is always night,
  the account card always white — unverified (compiled on CI).
- Icons: `WebIcons` — the dashboard's own heroicon paths (nav, bell, sun and
  moon, collapse / expand, chevron, logout, more, menu, search, eye and
  eye-off, wifi-off, check, close, exclamation, alert, warning), stroked
  through `SVGShape` with `OverviewIcons.expandArcFlags`; `NeemaLogo` (the
  amber mark with its glow). The SF Symbol stand-ins are gone from the chrome
  and the login; they remain where the web has no icon of its own.
- Shell chrome by navigation mode (`navMode(for:)` from the window width):
  a drawer under 600 pt, the 60 pt icon rail under 1200 pt, the docked
  208 pt sidebar (× text scale to 130%) beyond, the choice holding until the
  mode changes; the phone drawer as a start-edge panel over a scrim (272 pt,
  rounded end corners, swipe to close); the mobile header (the "Neema ·"
  wordmark yields to the view's name past 150% text, the bell with its red
  "9+" count, the theme switch); the bottom bar (web icons, labels capped,
  the half-width amber indicator, the count 8 pt right of centre); the
  sidebar (logo, wordmark, bell, collapse; the rail's expand button; amber
  pill rows with navy ink; the account row with the online dot, the role
  line, the rotating chevron, the signing-out ring; the account card inline
  or as a popover on the rail, with the role pill, View Profile / Settings,
  the theme row and its pill, Sign out); the three badge sizes with the full
  number; the toast top-end and the "Reconnecting…" pill on wide windows —
  unverified.
- Launch screen and app icon: `Assets.xcassets` with the 1024 px icon and the
  launch image, rendered by `scripts/make_icons.py` from Android's launcher
  shapes (pure Python, so anyone can regenerate them), on the night
  background Android's splash uses; `UILaunchScreen` and the app-icon
  setting in `project.yml` — unverified.
- Adaptive layouts: `AdaptiveSheet` (a phone sheet under 600 pt, an
  end-edge panel beyond, Android `core/ui/AdaptiveSheet`), now what the
  catalog and the leads screens present their detail with; the inbox's
  `inboxPanes` rules and the shell's `navMode` were already the core's,
  verified by `AdaptiveTests`.
- State restoration: the inbox's open panes (customer pane / sheet, activity
  sheet) persist in the scene state, as Android's `rememberSaveable` does;
  every other screen already kept its saved UI (cycle 2).
- Native polish: haptics (a light tap on sends, moves, status changes and
  availability switches; the system's notice on an error toast); Dynamic
  Type caps on dense chrome; safe areas handled by the shell (the navy top
  edge under the status bar on wide windows, the drawer's background under
  the bars); the status bar follows the theme and the night login through
  `preferredColorScheme`.
- The screenshot gallery — the cycle's "done when": `GalleryFixtureExportTests`
  (NeemaCore, on demand) drives every screen's model against the full
  fixture set and records the 24 answers the screens ask for;
  `NeemaAppTests/Gallery` serves them from `fixtures.json` through
  `CannedTransport` to a real `AppModel` and renders the sign-in screen and
  every view (phone light and dark, iPad) through `ImageRenderer`, attaching
  each PNG and writing it to `$NEEMA_SCREENSHOTS`, which the macOS job sets
  and uploads as the `ios-screenshots` artifact.

**Defects corrected**

1. The nav badge on the phone bar and the rail showed "9+" where the web
   prints the full number (only the bell's red count abbreviates) — fixed
   with the badge rewrite.
2. The wide shell's "Reconnecting…" indicator was a bare dot; Android and the
   web show the pill with its words — fixed.
3. The connectivity banner drew its icon in the tone's accent colour over
   the tint (under 3:1 by day); it is now the solid 24 pt badge Android
   draws.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **918 tests, 0 failures**
  (917 of cycle 2 plus the gallery exporter, which skips unless
  `NEEMA_GALLERY_OUT` is set).
- macOS CI (`Neema app (iOS Simulator)`): the run on `88f6c8d` was in
  progress when this record was first committed; its result (and any
  compile defect it found) is added below once known.

**Remaining parity gaps** (scope of this cycle)

- The bell's list, its mute control and the wide shell's bell popup — cycle 5
  (the bell button and its count are in place with a count of 0).
- The docked call panel at ≥ 1000 pt of content and the call bar — cycle 5.
- Keyboard shortcuts (Ctrl+1…9, Ctrl+B, Escape through the in-app history)
  and drag-and-drop — cycle 9.
- A pixel comparison of the gallery against Android's Paparazzi goldens —
  cycle 9; the gallery renders through `ImageRenderer`, which does not draw
  presented sheets or UIKit-backed views, so dialogs and the media viewer
  are not in it.
- Every SwiftUI change remains "unverified" on a device; the gallery is the
  first rendered evidence.

**Blockers** (carried) — no Xcode or device here; backend push; no Apple
credentials.

**Next cycle** — Cycle 4: business logic & backend integrity — the Settings
screen (every card, incl. WhatsApp calling and crash reports), the server
contracts re-checked endpoint by endpoint against the OpenAPI, every write's
uncertain-result reconciliation, 403 → access re-read, permission gates, the
price/ordering invariants the Android tests pin.
