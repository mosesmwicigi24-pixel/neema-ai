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
4. A cycle 2 test waited a fixed drain for a refresh that reads two things
   (CI run 18 caught it once); it waits for the spinner to end now.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **918 tests, 0 failures**
  (917 of cycle 2 plus the gallery exporter, which skips unless
  `NEEMA_GALLERY_OUT` is set).
- macOS CI (`Neema app (iOS Simulator)`, XcodeGen → xcodebuild on the
  iPhone 17 simulator): run 17 on `76b6049` **green** — the app and the
  gallery compiled first time, the app tests passed and the
  `ios-screenshots` artifact was uploaded. Runs 15 and 16 (`ce4e1c1`,
  `88f6c8d`) were cancelled by the later pushes before finishing, so the
  one defect they would have caught — the canned transport's private
  `NSLock.sync` twin of NeemaCore's public one — was fixed from reading
  the code (`88f6c8d`), not from a compile error.
- Run 18 (`4f938b7`, the record itself): macOS green again; the Linux core
  job failed once on a cycle 2 test, `CatalogViewModelTests.
  testAnEmptyCatalogueAfterAFailedReadSaysWhyAndRetryLoadsIt`, whose last
  assertion followed one fixed drain while the retry's refresh (catalogue
  AND audit) was still landing on the slow runner. Defect 4 below; the test
  now waits for the flag (`1fdf695`).

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

### Cycle 4 — Business logic & backend integrity

**Features implemented / verified**

- Settings, in NeemaCore (`Settings/`), one rule for one rule with Android's
  `feature/settings`: `SettingsRules` (the local-only Business / AI /
  Integrations models and their copy, crm.py's pipeline constants and
  cleaning, strict ISO dates for the pickers, `offerProblem` — the 422 said
  before the round trip and naming the field, the cards' toasts);
  `SettingsViewModel` — the four live cards read independently with a
  per-card reason and Retry (the standing-orders box stays locked until the
  real text arrives: the web unlocks an empty box whose save would wipe the
  real orders), the translation switch optimistic with the server's truth
  re-read on no answer, the offer with verify-after-no-answer through
  `sameOffer` and the three saved toasts (live / starts later / expired),
  pipeline stages PUT as the whole list with the server's cleaning mirrored
  for the no-answer check, the typed label cleared only once kept, the
  local-only cards toasting and persisting nothing, `saveUi`/`restoreUi`
  with secrets never saved and a pending restore until the card loads, the
  `ScreenLife` re-read on return skipping dirty cards; `CallingSettingsModel`
  — only-the-diff save, every field checked before anything is sent, Meta's
  own words on a refusal, `call_settings` frames reloading unless edits are
  unsaved, the call-request template.
- `ClientCrashReport` and `api.crashes.list/report` (matrix rows 50–51).
- The SwiftUI screen: `SettingsScreen` (one column, two from 720 pt with the
  tall offer under the standing orders; every card; pull-to-refresh; the
  typed state in the scene storage), `OfferCard` (category chips from the
  catalogue, the product picker sheet, UTC date sheets, the End
  confirmation), `CallingSettingsCard` (restrictions, the three call-button
  chips, voicemail, the hours editor with holidays, the template status),
  `CrashReportsCard` (load on tap, expand, Copy report to the clipboard).
  `.settings` is routed; the gallery renders it against the canned settings
  answers (the exporter now drives the model: 29 canned responses).
- Backend integrity: `RouteCoverageTests` reads every `http.*` call in the
  core's sources and matches method and path against the server's route
  table (`ServerRoutes.swift`, 142 routes, generated from `apps/api/app` by
  `apps/ios/scripts/server_routes.py`): 89 distinct client calls (102 call
  sites), all served; the 14 admin routes neither app calls are the web's.
  The no-answer paths of every write, audited: Team (6 writes: refetch and
  compare), Profile (2: `/me` re-read), Customer (6 paths through
  `mayHaveLanded`), Settings (4: the truth re-read), Orders / Deals / Leads
  (status, approve/veto, stage: the list re-read through the feed —
  `mayHaveHappened`), the inbox's sends (its own server check at 0 / 2 / 8 s,
  `RESTORE_CHECK_MS`). The 403 re-read of who this agent is stays in one
  place (`NeemaHTTP.forbidden` → the shell's coalesced refetch) and is pinned
  for settings too (`testARefusedSaveRereadsWhoThisAgentIs`). Permission
  gates: Settings has none (as the web), the calling and crash cards need
  manage_settings (as Android), the rest unchanged from cycle 2's audit.

**Defects corrected**

1. `StagesResponse` read a body whose `stages` was not a list as "no custom
   stages" — a save over that would have replaced the real list with one
   stage. It is now a decoding error the card shows with Retry (Android's
   serializer refuses it the same way).
2. The route matcher escaped the server's `{param}` placeholders before
   turning them into patterns, so every parameterised route read as unserved
   — caught by its own first run, fixed before it shipped.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **1004 tests, 0 failures**,
  1 skipped (the gallery exporter): cycle 3's 918, the 83 settings tests
  (Android's 76 — `SettingsViewModelTests` 24, `SettingsNetworkTests` 22,
  `SettingsContractTests` 19, `SettingsLifecycleTests` 6,
  `CallingSettingsModelTests` 5 — plus the 403 re-read, the Business/AI
  waits, the crash list's contract and 403, the restore-once rule, and the
  calling rules on their own), and the 3 route-coverage tests.
- macOS CI (`Neema app (iOS Simulator)`): green on ccf2ed7 (run
  38287130688: XcodeGen, the simulator build, the app's test bundle with the
  screenshot gallery — no compile defect); every other check green on the
  same head (NeemaCore on Linux, API tests, migrations, web, lint, import
  smoke).

**Remaining parity gaps** (scope of this cycle)

- The settings UI is compile- and gallery-verified only: the pickers, the
  date sheets (a graphical `DatePicker` in UTC where Android opens the
  Material dialog) and the hours editor have not been touched on a device.
- The crash reporter itself (POST /client-crashes from a crashing iOS app)
  is cycle 7's; the card reads what Android has sent.
- The WhatsApp calling card lives in Settings as on Android; calls
  themselves (the log, the softphone) are cycle 5's.
- The crash card says "the app" where Android says "the Android app": the
  server lists every phone's reports once iOS sends them too.

**Blockers** (carried) — no Xcode or device here; backend push; no Apple
credentials.

**Next cycle** — Cycle 5: messaging, communication & real-time — the calls
screen (log, details, transcripts, the call-request flow), the softphone
groundwork (CallKit / PushKit, blocked server-side for pushes), the bell
(notifications list, mute, the wide shell's popup), the live socket under
the iOS lifecycle (background suspension, reconnect on return), the docked
call panel, and the inbox's media round trips on a real device where one
exists.

### Cycle 5 — Messaging, communication & real-time

**Features implemented / verified**

- The softphone's rules, in NeemaCore (`Calls/`), one rule for one rule with
  Android's `feature/calls/CallManager.kt`: `CallManager` behind the same
  five ports (`CallApi`, `CallPeer`, `CallMedia`, `CallRinger`, `CallAudio`)
  — the phases and their side effects, inbound WhatsApp (ring by frame or
  poll, answer through ice-config + offer + mic + non-trickle ICE + `POST
  answer`, the failure table: 409 answered elsewhere, 410/404 missed, mic
  blocked, status 0 back to ringing, the 8 s unconfirmed answer), inbound
  Messenger (reversed SDP, `media_update` highest version only, held until
  ready), outbound WhatsApp (the 1.5 s permission read, PermissionNeeded /
  Requested without a connect, the placed-row lookup, `call_status` →
  RingingOut, `outbound_answer`, the refusal table), outbound Messenger,
  resilience (10 s reconnecting, the connect guard, terminate / callback
  retries, resync on reconnect and foreground, audio-trouble inline errors),
  the second caller, permission requests and the `call_permission` grant
  banner, the caution at two unanswered calls, `endForSignOut`, the
  recording outbox (10 files, 3 days, transient vs permanent errors) and
  every string of the card (`CallState.swift`: status line, outcome words,
  notes, wrap-up actions).
- The console's rules: `CallsViewModel` (one read on the wire at a time, the
  60 s tick while shown and in front, 500 ms after call frames, `call_update`
  merged in place, the transcript panel with its 5 s polling and error
  table, call back through the softphone, follow-up done with the row
  re-read, the deep-link focus with its re-read and "No calls with this
  customer yet" toast, `saveUi` / `restoreUi`).
- The bell and the alerts: `AgentNotifications` (Android's
  `NotificationCenter`: the last 60 persisted, the 3 s exact-repeat drop,
  the per-type table — channel, priority, tap target, the Profile switches —
  the tray through an `AlertSink`, the group summary, read / dismiss / clear
  withdrawing their rows) and `MessageAlerts` (the beep + buzz behind the
  2 s gate and the mute, one tray row per customer in the background,
  cleared on return).
- The SwiftUI layer, screen for screen with Android: `CallsScreen` (the
  night card with its glow, "Calls · WhatsApp [and Messenger] voice calls ·
  N total", All / Follow-ups (N) and the app chips, the restriction,
  readiness and stale-log banners, four skeleton rows, the empty and error
  states, rows under TODAY / YESTERDAY / date with the avatar disc, the
  channel badge, the direction glyph and outcome word in its tone, the
  length, the agent, "Follow up", the Voicemail badge, the time, the
  transcript and call-back round buttons; the transcript panel with the
  summary, the speaker-separated transcript, Transcribe & summarise, Retry
  and the recording player on `AVPlayer`; the details pane — timeline,
  recording line, INSIGHTS, Call back / Open chat / Mark follow-up done,
  the history line and the customer's full panel; a phone replaces the log
  with the details, a window from 840 pt shows both with the newest call
  auto-opened as Android's `detailsPick`), `CallCard` (WhatsApp's dark
  surface, the 120 / 88 pt avatar with the pulse rings — off under Reduce
  Motion — and Messenger's ring, the landscape split, every phase's
  controls, the audio-route menu, the wrap-up pills, the caution and the
  notes), the minimised bar, the waiting banner, the grant banner, the
  docked 420 pt panel from 1000 pt of content with the chat opened beside a
  connected call, the microphone prompt, the bell's panel (the unread badge,
  Mark all read, the mute menu, rows with their emoji tile and time, the
  footer) as the wide shell's 316 pt popup and the phone's sheet, and the
  header / sidebar bells with their counts.
- The platform ports on iOS: `SessionCallAudio` (`AVAudioSession` in
  voice-chat mode, the earpiece / speaker / wired / Bluetooth routes from
  the session's ports, the override on selection), `CallKitRinger` (the
  system's call UI for a ring that leaves the screen, Answer / Decline back
  into the softphone's `handleAction`; in front the alert tone every two
  seconds), `SystemAlertSink` (`UNUserNotificationCenter`: one row per
  alert keyed by the core's id, interruption levels for the priorities, the
  summary row, nothing posted without permission) and `SystemAlertPlayer`.
  The inbox's Call buttons now place calls through the softphone
  (`ShellInboxHost.placeCall` / `placeMessengerCall`); sign-out ends a live
  call first (`endForSignOut`, bounded).
- The gallery renders the Calls view against five canned calls and the
  channels answer (31 canned responses).

**Defects corrected**

1. `CallOutcome` (the softphone's) collided with the inbox's enum of the
   same name: the inbox's is now `PlaceCallOutcome` (placed / shown /
   failed), which is what it was always describing.
2. The contract tests addressed `/admin/calls/<id>/…` with the encoded id
   while the fake matched decoded paths (404s on every call id with a dot):
   the fixtures now carry the raw id and assert the wire form separately.
3. The simulation suite ran 100 random call histories a run (285 s): 30 by
   default, `NEEMA_SIM_RUNS` scales it up for a soak.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **1322 tests, 0
  failures**, 1 skipped (the gallery exporter): cycle 4's 1004 and 318 new —
  the softphone's 239 (Android's suites ported: `CallManagerTests` 59,
  `CallLifecycleTests` 47, `CallResilienceTests` 31, `CallUxTests` 13,
  `CallAcceptanceTests` 48, `CallRingsEverywhereTests` 10,
  `CallNetworkStressTests` 15, `CallApiContractTests` 14,
  `CallSimulationTests` 2), the console's 41 (`CallsViewModelTests`,
  `CallLogLiveTests`) and the 38 notification tests (`NotificationTests`).
- macOS CI (`Neema app (iOS Simulator)`): green on fd743c5 (run
  38300104256: XcodeGen, the simulator build, the app's test bundle with the
  screenshot gallery — one compile defect on the first push, an unawaited
  `UIApplication.open` in the readiness banner, fixed in one attempt); every
  other check green on the same head (NeemaCore on Linux, API tests,
  migrations, web, lint, import smoke).

**Remaining parity gaps** (scope of this cycle)

- **WebRTC media is not linked**: `DeviceCallMedia` throws
  `DeviceCallError`, so a call that reaches the media step ends on the card
  with "Calling isn't available on this device" (the softphone's own path,
  tested) — no audio flows yet. The WebRTC binary (stasel/WebRTC) is the
  first task of cycle 6, as an SPM dependency with a `CallPeer` over
  `RTCPeerConnection`; the rules above do not change.
- Calls to a closed app stay **blocked** on PushKit VoIP pushes from the
  backend (§25): the app rings only while it runs. The readiness banner says
  "Calls can't ring in the background" when notifications are off, and the
  empty state says "a call rings this phone while the app is open".
- Local two-sided recording is **platform-restricted** (no public audio
  sample hook in the iOS WebRTC SDK): `startRecording` returns nil, the
  outbox and upload rules are ported and tested; Meta's own transcription
  (`meta_transcription`) stands in.
- The ringtone and vibration Profile switches cannot be honoured exactly
  (CallKit rings the device's own ringtone); the in-front tone is the
  system alert sound.
- Android's readiness banners for "Stay connected in background", battery
  optimisation and full-screen intents have no iOS equivalent; the
  notifications and microphone ones remain.
- Not ported: Android's `CallRecorderTests` and `CallAlertTests` (device
  code), and the recorder sweep tests (no recorder).
- The SwiftUI layer is compile- and gallery-verified only; no call has been
  placed from a device.

**Blockers** (carried) — no Xcode or device here; backend push (PushKit /
APNs); no Apple credentials.

**Next cycle** — Cycle 6: performance — the WebRTC dependency and the real
`CallPeer`, the inbox list and thread under a thousand rows, image
decoding off the main thread, the catalogue's search, the socket's
reconnect budget, memory under the gallery's three sizes, and a sweep of
every `Task` for cancellation on sign-out.

### Cycle 6 — Performance

**Features implemented / verified**

- **WebRTC linked.** `project.yml` takes stasel/WebRTC (Google's libwebrtc
  as an xcframework, M155) as a package; `App/WebRTCMedia.swift` is the
  `CallMedia` / `CallPeer` port of Android's `WebRtcMedia.kt` over
  `RTCPeerConnection` — audio only, Unified Plan, the ICE servers from
  ice-config through `iceSpecs`, the AEC / NS / AGC / highpass constraints,
  `OfferToReceiveAudio`, non-trickle gathering handed to `CallManager`'s cap,
  every SDK callback through `rtcGuard`, and a close that never touches the
  native object twice (`live`, the teardown off the delivering thread).
  `makeCallMedia()` picks it when the framework is present
  (`#if canImport(WebRTC)`), else the port that ends a call honestly.
- **Images cached as Android caches them**: `URLCache.shared` is sized to
  64 MB memory / 256 MB disk at start (Coil's defaults), which every
  `AsyncImage` in the app (avatars, catalogue, thread media) goes through.
- **Nothing derived per frame on the calls screen**: the filtered rows, the
  follow-up count and the Messenger switch are derived once per change in
  `CallsScreenModel`, not in the view's body (a thousand rows under a
  scrubber ticking four times a second).
- **Off-main decoding, confirmed**: every `api.*` call decodes in
  `NeemaHTTP` (a nonisolated async function — the cooperative pool, never
  the main actor); the inbox's row grouping, the thread's row building and
  the report's build run in their view models' tasks; the 14k-row report
  builds off the screen (`ReportsStressTests`).
- **Polling discipline and battery**: every screen's tick runs through
  `ScreenLife` (only while shown and in front; a return reads once); the
  feeds' polls pause in the background; the softphone's fallback poll is a
  sleep loop that iOS suspends with the app. No timer runs in the
  background. **Socket bursts**: `LiveSocket.EVENT_BUFFER` (1024) with
  `droppedFrames` accounting, pinned by `LiveSocketTests`.
- **Sign-out cancels everything**: `AppModel.logout` stops the polls, closes
  every screen model (each cancels its jobs), stops the feeds and the
  notifications, and ends a live call first.
- **The stress suites ported** (`Tests/NeemaCoreTests/Stress/`):
  `CorePerfStressTests` (Android `CorePerfStressTest`: a thousand requests,
  the bell under a storm of 500, 10,000 coalescer kicks from eight threads,
  the immediate coalescer, 5k phones + timestamps under 500 ms, a 2 MB error
  page bounded and quick, 5,000 call row keys under 200 ms),
  `NetworkStressTests` (Android `NetworkStressTest`, all 17: parallel 401s
  sharing one refresh, a refused refresh asked once, timeouts and outages
  that never sign anyone out, the captive portal, the outage cool-down, 429
  with Retry-After, offline vs timeout, a dropped connection retried, empty /
  HTML / cut-off / 5 MB bodies, the fake's delays and holds on virtual time,
  sign-in against outages, rate limits and a half-broken NextAuth),
  `SoftphoneStressTests` (Android `SoftphoneStressTest`, all 11: a burst of
  200 frames rings once, ended calls stay bounded at `ENDED_MAX`, polls never
  overlap on a slow network, and every way a call ends — hang-up, decline, a
  failed answer, the media dropping, a blip that never recovers, the caller
  giving up, sign-out mid-call, ten calls in a row — releases the peer, the
  recording, the ring and the audio), `ShellStressTests` (the core-testable
  rows of Android's `ShellStressTest` / `DashboardStressTest`: an answer that
  lands after sign-out is dropped, a sign-out mid-poll abandons the held
  request, 200 order alerts cost one fetch, 200 non-alert frames cost
  nothing).

**Defects corrected**

1. The calls screen filtered its rows inside the view body on every render.
   Derived once per change in the model now.
2. Images had the system's default 4 MB URL cache: avatars and catalogue
   thumbnails were re-fetched on every scroll back. Sized as Android's.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **1362 tests, 0
  failures**, 1 skipped: cycle 5's 1322 and the 40 stress tests above.
- macOS CI (`Neema app (iOS Simulator)`): green on 23420fe (run
  38306420400: XcodeGen, the WebRTC package resolved, the simulator build
  against it, the app's test bundle with the screenshot gallery — no
  compile defect); every other check green on the same head (NeemaCore on
  Linux, API tests, migrations, web, lint, import smoke).

**Remaining parity gaps** (scope of this cycle)

- WebRTC is linked and compiled, not exercised: no call's audio has flowed
  on a device. The first real call is cycle 8's device checklist (blocked
  without a device here).
- Local two-sided recording stays platform-restricted (`startRecording`
  returns nil); Meta's transcription stands in.
- Android's `CallRecorderTests`, the screenshot stress tests (Paparazzi) and
  the app-layer rows of `ShellStressTest` / `DashboardStressTest` (one
  session-expired prompt, re-authenticating keeps the view, another agent
  starts clean, the per-agent screen store) are not ported to Linux: the
  app-layer rules live in `AppModel` and are only exercised by the app's
  own tests on macOS CI.
- Launch time and memory under the gallery's three sizes are not measured
  (no Instruments here); the gallery run's wall time on CI is the only
  budget watched.

**Blockers** (carried) — no Xcode or device here; backend push (PushKit /
APNs); no Apple credentials.

**Next cycle** — Cycle 7: security & permissions — Keychain accessibility
classes, no secrets in logs or snapshots, App Transport Security and the
privacy manifest, the usage strings, the mic / camera / photos /
notifications flows with native rationale, crash reporting from the iOS app
without PII beyond Android's, the RBAC gates audited screen by screen, and
a written permission / privacy checklist.

### Cycle 7 — Security & permissions

**Features implemented / verified**

- **Crash reporting from the iOS app**, Android's `core/crash` one rule for
  one rule: `NeemaCore/Crash/CrashVault.swift` (a report per file in
  `Application Support/crash`, the newest 10, `last.txt`, `last-fatal.txt`,
  500 characters of summary and 48k of trace, `asText` capped at 60k, the
  non-fatal that never raises the notice), `CrashReporter.swift` (sent
  oldest first once signed in — at start, on sign-in, after a non-fatal —
  stopping at the first failure), `App/CrashHandlers.swift` (the uncaught
  `NSException` handler and the fatal signals, written first, then the
  process ends as it would have), `CrashHooks` wired to the vault
  (`rtcGuard` and every edge that records a non-fatal), the next-launch
  "Neema closed unexpectedly" notice with Share / Copy / Close
  (`CrashNoticeView`), and Settings → App crash reports showing "On this
  phone" with Copy.
- **Permissions**: notifications asked once, right after the first sign-in
  (`asked_post_notifications`, as Android's MainActivity); the microphone
  mid-answer (cycle 5); the camera when opened; the photo library never
  (`PhotosPicker`). The usage strings are the rationale iOS shows.
- **The privacy manifest** (`NeemaApp/PrivacyInfo.xcprivacy`): no tracking;
  email, name and crash data declared as collected for app functionality;
  `UserDefaults` (CA92.1) the one required-reason API.
- **Audits written down** in `docs/ios/SECURITY_CHECKLIST.md`: the Keychain
  class and what it holds, sign-out, no tokens in snapshots, logs or crash
  reports (no `print` / `os_log` anywhere in the core or the app), App
  Transport Security at the system default (no exceptions in the plist),
  every permission's prompt and refusal path, and the RBAC gates screen by
  screen against the web's `can(PERMS.*)` (the six nav gates, the calling
  card, the inbox's role rules, the sales permission matrix, the team's
  last-admin rule, the 403 re-read) — every one already pinned by a test.

**Defects corrected**

1. `rtcGuard` labelled a WebRTC callback's non-fatal `rtc:<name>`; Android's
   vault reads `webrtc-<name>`. Aligned.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **1377 tests, 0
  failures**, 1 skipped: cycle 6's 1362 and the 15 crash tests
  (`CrashTests`: Android's `CrashHardeningTest` — the call log's update for
  an old call, keys that look like their own suffix, lead stages, the
  reporter's two — and the vault's file rules).
- macOS CI (`Neema app (iOS Simulator)`): green on b67ff6b (run
  38309732605: XcodeGen, the simulator build with the crash handlers, the
  notice and the privacy manifest, the app's test bundle with the screenshot
  gallery — no compile defect); every other check green on the same head.

**Remaining parity gaps** (scope of this cycle)

- The crash handlers, the notice and the permission prompts are device code,
  compiled only. MetricKit diagnostics (hangs, the system's own crash
  records — Android's `ApplicationExitInfo`) are not read: platform-restricted
  until a device run shows what MetricKit delivers.
- No certificate pinning (Android pins nothing either).
- Signing, TestFlight and the App Store listing's privacy answers stay
  blocked without Apple credentials; the manifest is written for them.

**Blockers** (carried) — no Xcode or device here; backend push (PushKit /
APNs); no Apple credentials.

**Next cycle** — Cycle 8: comprehensive functional & stress testing — the
Android test inventory mapped file by file in `docs/ios/TESTS.md`, everything
portable ported, UI tests on the simulator for the flows CI can drive
(sign-in, navigation, inbox, orders, settings), the fake backend with the
full fixture set.

### Cycle 8 — Comprehensive functional & stress testing

**Features implemented / verified**

- **The test inventory** (`docs/ios/TESTS.md`): every one of the Android
  suite's 177 files mapped to the iOS file(s) that prove the same behaviour,
  with the status vocabulary of the matrix, generated from a name-and-intent
  match of all 2 277 Android tests against the iOS tree and then checked
  file by file. Totals: 64 files verified, 46 partial (the note names the
  missing tests), 28 screenshot suites covered by the gallery, 6
  platform-restricted, 33 support files mapped to their iOS twins.
- **Ported this cycle** (193 new tests, all green on Linux): the softphone
  (`FrameFuzzTests` 2 — 4 000 seeded random frames into the manager;
  `CallNativeSafetyTests` 5; `CallsParityTests` 3), the core rules
  (`CoreLogicTests` 6, `CoreRound2Tests` 6, `CoreRound9Tests` 7), the
  inbox's permissions (`InboxPermissionsTests` 8), screen freshness across
  deals / orders / leads / reports / team / settings
  (`ScreenFreshnessTests` 17), the shell (`TabletLayoutTests` 14 at the Tab
  S9 Ultra widths + `CallsDetailsPickTests` 6, `TabletInputTests` 1,
  `ToastLifecycleTests` 6, `LiveLifecycleTests` 7, `ShellLifecycleTests` 8,
  `DashboardRulesTests` 32, `ShellPermissionMatrixTests` 9), sales and
  insights (`SalesPermissionExtraTests` 4, `ReportsRolloverTests` 1,
  `AreaViewModelTests` 1, `AreaPermissionMatrixTests` 8,
  `InsightsNetworkTests` 6, `InsightsStressTests` 6 — analytics over 5 000
  orders, the catalogue index over 2 000 products) and the team
  (`TeamContractTests` 16, `TeamLifecycleTests` 6,
  `TeamPermissionMatrixTests` 8).
- **Helpers moved into the core** so Linux can test them, the app now
  calling the core's: `avatarIndex`, `initialsOf`, `DetailsPick` /
  `detailsPick` (`Calls/CallVisualsRules.swift`), `isPhoneLike`
  (`Util/PhoneLike.swift`), `CALL_PANEL_WIDTH` / `callDocks`
  (`Shell/DockRules.swift`).
- **UI tests on the simulator** (`NeemaAppUITests`, 6, in the scheme so CI
  runs them): the app launched with `-neema-canned` runs on
  `CannedBackend` — the gallery's fixtures bundled with the app, sign-in
  answered as FastAPI's auth router would (any email, password `neema`),
  dead sockets — and XCUITest drives sign-in right and wrong, the bottom
  tabs, the drawer to Settings, the orders list and sign-out, by the
  accessibility labels the screens already carry and three identifiers on
  the sign-in form.
- **The recorded backend regenerated by the exporter** (33 answers, was 28
  with two hand-made rows): the exporter now drives the calls console (the
  log with every fixture row, the channels, the first call's transcript)
  and the crash list, so Settings' crash card and the console render from
  the fixtures rather than an error state.

**Defects corrected** (the ports found them; none of the ported assertions
failed against the core)

1. A notification frame landed in the bell without the toast Android and the
   web show ("{title}: {body}"): nothing consumed `AgentNotifications.incoming`.
   `AppModel` now toasts each one.
2. The view, its history, a pending deep link and the toast on screen did not
   survive a process death (Android's `SavedStateHandle`): `@SceneStorage`
   in `DashboardShell` / `RootView` now keeps them, with Android's owner rule
   (another agent restored into the same scene starts on the inbox) and an
   expired toast not restored.
3. Sign-out mid-call awaited `endForSignOut` with no outer cap; Android caps
   the wait at 4 s (`SIGN_OUT_CALL_MS`) in case the terminate ever hangs.
   Added.
4. The app's `isPhoneLike` returned true for a blank name where Android's
   returns false (the caller handles blanks). The core's version is
   Android's; the avatar's caller checks the blank itself.

**Tests executed**

- `swift test` in `apps/ios/NeemaCore` on Linux: **1570 tests, 0
  failures**, 1 skipped, twice in a row (cycle 7's 1377 + the 193 above).
- macOS CI (`Neema app (iOS Simulator)`): see the line below once the run
  is in.

**Remaining parity gaps** (scope of this cycle)

- The Android screenshot suites pin some 600 named states (every call card
  phase and wrap-up outcome, offline / server-down banners, restored forms,
  large-text and small-phone layouts, three personas' navigation); the iOS
  gallery renders each screen once per shot in the fixtures' state. The rules
  behind the states are pinned by the Linux suites; the states themselves
  are **partial** until a gallery drives each model into them or a device
  run looks.
- Android-only mechanisms with no iOS twin, by design: hardware-keyboard
  rules (Enter sends, Ctrl-digits, Esc-is-back), the back-dispatcher order
  of overlays, the foreground service's live mode, the on-device PCM
  recorder, debuggerd tombstones, the OkHttp cancellation causes.
- `TestHost`'s 403 re-read counts itself and fetches `/admin/me` and
  `/admin/agents` but does not store the rows; the nav-correction tests
  assert on the list the re-read fetched (the app's `AppModel.onForbidden`
  does store them).
- The three fixes above are app-layer code: compiled on CI, not driven by a
  test (the UI tests do not kill the process).

**Blockers** (carried) — no Xcode or device here; backend push (PushKit /
APNs); no Apple credentials.

**Next cycle** — Cycle 9: final refinement — the matrix and the test inventory
re-read against the app as it stands, every **unverified** row either driven
by a UI test or a gallery state or named as needing a device, the consistency
pass (copy, spacing, icons, dark mode) across screens, and the loose ends the
cycles left (forms' saved state, the gallery's named states).
