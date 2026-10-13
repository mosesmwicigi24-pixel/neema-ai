# Neema iOS — final report (cycle 10: final verification & production readiness)

The programme that built the Neema iOS app in ten controlled improvement
cycles has ended. This report says what exists, what has been proven and
how, what has not, what is blocked and by what, and how the owner takes it
from here. Every status below uses the parity matrix's vocabulary
(`PARITY_MATRIX.md`: verified / unverified / partial / missing /
platform-restricted / blocked), and the same honesty rule as every cycle:
**nothing in this programme ran on a physical iPhone or iPad, in Xcode's
simulator by hand, or through TestFlight.** The machines were a Linux
workstation with the Swift 6.2 toolchain and GitHub's macOS runners.

## 1. The verdict

| Question | Answer |
|---|---|
| Does the iOS app exist, screen for screen? | Yes. Every Android screen, state, rule, endpoint and socket frame in the matrix has an iOS twin; no row is *missing* or *partial*. |
| Is it proven? | The rules are: 1584 core tests on Linux (0 failures) and, on every pull request, a macOS run that builds the app, renders 54 screenshots, drives 8 UI flows on the simulator and archives the Release configuration. The screens are proven to build, lay out and respond on the simulator; their behaviour on a device is **unverified** (33 matrix rows say so). |
| Is it production-ready? | **Ready to sign and put on TestFlight; not ready to call shipped.** Signing, TestFlight and the store are blocked here (no Apple Developer team in the repository or on the box); the first device run is the owner's, with the checklist in `RELEASE.md` §5. Two features cannot work the way Android's do until the backend sends pushes: alerts and ringing while the app is closed. |

## 2. What was built

| Part | Files | Lines | What |
|---|---|---|---|
| `apps/ios/NeemaCore` (Swift package; Linux, macOS, iOS) | 84 | 21 068 | Everything that is not a screen: the 52 wire models with Android's leniency, the HTTP client and its session rules, sign-in and silent refresh, the Keychain session store, the live socket, the API surface (81 endpoints, each checked against the server's router on Linux), formatting, permissions, the shell's rules (views, deep links, history, toasts, access, keyboard, docking), and every screen's logic: inbox, thread, composer, customer panel, orders, catalog, deals, leads, analytics, reports, team, profile, settings (every card), the softphone (`CallManager` behind ports), the calls console, the bell and message alerts, crash reporting. |
| `apps/ios/NeemaApp` (SwiftUI) | 67 | 19 197 | The screens, the theme (light / dark, the three toggles, Manrope and DM Mono, the web's icon paths), the adaptive shell (phone chrome, iPad sidebar / rail, side sheets, docked call panel), the platform services (URLSession, Keychain, CallKit, WebRTC, AVAudioSession, notifications, haptics, the share sheet, pickers, drop), scene restoration, the canned backend for tests. |
| `apps/ios/NeemaCore/Tests` | 132 | 29 539 | 1584 tests: the Android suites ported one by one (`TESTS.md` maps all 177 Android test files). |
| `apps/ios/NeemaAppTests`, `NeemaAppUITests` | 3 | — | The shell's 4 app tests, the 54-shot gallery, 8 XCUITest flows. |
| CI (`.github/workflows/ios.yml`) | 3 jobs | — | Core on Linux; Debug build + tests + gallery + UI tests on the iPhone simulator; unsigned Release archive for a real iPhone. |
| Docs (`docs/ios/`) | 7 | — | `PLAN.md` (the ten cycles' records), `PARITY_MATRIX.md`, `TESTS.md`, `SECURITY_CHECKLIST.md`, `CONSISTENCY_LOG.md`, `RELEASE.md`, this report. |

## 3. Status of every area

The matrix's 155 status rows at the end of cycle 10 (each row's own text
says what "verified" covers — most app rows read "verified (rules) · UI
unverified", counted here as verified because the behaviour is pinned by
a test and the view compiles and renders on CI):

| Status | Rows | What it means here |
|---|---|---|
| verified | 115 | A Linux test or a green macOS run exercises it. |
| unverified | 33 | Implemented and compiled on CI, sometimes rendered in the gallery; not exercised by a test. These are the device-run list (§6). |
| platform-restricted | 7 | Android relies on something iOS does not have; the row names what iOS does instead. |
| partial / missing | 0 | — |
| blocked (§25 of the matrix) | 3 | Apple credentials; backend pushes; the host's `apple-app-site-association`. |

By area (the matrix's sections):

| Area | Status |
|---|---|
| 1 Platform foundation (models, JSON, HTTP, auth, Keychain rules, socket, API, permissions, formatting, clocks, single-flight, screen life, prefs, snapshots, saved state, contact names) | all verified; the Keychain and URLSession classes themselves unverified (device code) |
| 2 Bootstrap, shell, navigation | rules verified (views, access, deep links, history, 403 re-read, logout, toasts, keyboard); the chrome's look unverified beyond the gallery and the 8 UI flows; back-press order platform-restricted (no system back) |
| 3–7 Inbox, thread, composer, dialogs, customer panel | logic verified (paging, polling, frames, drafts, translations, media, intercept, release, call request, the "call on WhatsApp instead" sheet, lost files); the sheets and viewers unverified |
| 8 Softphone | `CallManager` verified frame by frame (the 59 Android tests and the fuzz / native-safety suites); CallKit, WebRTC audio and the mic prompt unverified; ringing, the lock-screen takeover and local recording platform-restricted (CallKit rings; no WebRTC audio tap on iOS — Meta's transcription stands in) |
| 9 Calls console, details, transcript, settings card | rules verified; the console's rendering unverified (gallery only) |
| 10 Notifications and alerts | bell, tray, mute, alerts verified; channels and the background connection platform-restricted (categories; pushes needed) |
| 11–17 Orders, catalog, deals, leads, overview, reports, team | verified (logic and contracts); the CSV share sheet and the deals board's drag unverified |
| 18 Settings (every card incl. WhatsApp calling, crash reports) | verified (rules) |
| 19 Profile | verified (rules); the rows unverified |
| 20 Crash reporting | vault and upload verified; the signal handlers unverified; tombstones platform-restricted (MetricKit not read) |
| 21 Local persistence | verified; the restore after process death unverified |
| 22 Design tokens, typography, icons | tokens verified; the rendering checked by eye against Android's goldens (`CONSISTENCY_LOG.md`), not by pixel |
| 23 Endpoints (81) | verified — every path the core calls exists on the server (`RouteCoverageTests`) |
| 24 Socket frames | verified — every frame Android consumes has its consumer |
| 25 Platform-restricted and backend gaps | see §5 |

## 4. How it was verified

| Evidence | Where | Result |
|---|---|---|
| The core suite on Linux | `swift test` in `apps/ios/NeemaCore`; CI job `NeemaCore (Linux)` | **1584 tests, 0 failures**, 1 skipped (the gallery fixture export, which runs only with `NEEMA_GALLERY_OUT` set) — run in cycle 10 on this workstation and on the pull request; CI doubles the tests' fixed waits (`NEEMA_TEST_WAIT_SCALE=2`) because its shared runner is slower than a workstation |
| The app on the simulator | CI job `Neema app (iOS Simulator)` (Debug, iPhone 17 simulator, Xcode 16): the 4 shell tests, the gallery, the 8 UI tests | green on cycle 9's head and on cycle 10's (the run is named in `PLAN.md`'s cycle 10 record) |
| The gallery | 54 PNGs per run (`ios-screenshots`): sign-in, the eleven views on phone light / dark and iPad, the drawer, the account menu, the bell, three toasts, offline, session expired, a ringing call, a missed call's wrap-up | rendered as on screen (window-hosted); walked against Android's 902 Paparazzi goldens in `CONSISTENCY_LOG.md` (17 screens and states, 7 defects found and fixed in cycle 9) |
| The UI flows | `NeemaAppUITests` against the canned backend: sign-in right and wrong, the bottom tabs, the drawer to Settings, the orders list, a thread by a tap and by a deep link, sign-out | 8 / 8 passing on the simulator |
| The Release configuration | CI job `Neema release archive (unsigned)`: `xcodebuild archive` for `generic/platform=iOS`, build number = run number | green from cycle 10 (the `.xcarchive` is the run's `ios-unsigned-archive` artifact) |
| Endpoint contracts | `ApiContractTests` and the per-screen contract suites decode the handlers' real shapes; `RouteCoverageTests` checks every call against `apps/api/app`'s routes | green |
| The Android test inventory | `TESTS.md`: 177 Android test files / 2277 tests mapped — 66 files verified by a port, 44 partial (the rule ported, the Paparazzi state not), 28 covered by the gallery, 6 platform-restricted, 33 fixtures | — |
| Wording | 1202 Android literals against 1194 iOS; the 135 without a verbatim twin read in context in cycle 9 | all accounted for (Android-only by design, template fragments, or code) |
| Security and privacy | `SECURITY_CHECKLIST.md`: Keychain accessibility, no secrets in logs or snapshots (grep), ATS default, privacy manifest, usage strings, RBAC screen by screen | written and checked in cycle 7, re-read in cycle 10 |

## 5. Blockers — carried through every cycle, still open

| Blocker | Effect | What unblocks it | Owner |
|---|---|---|---|
| No Xcode, simulator or device on the workstation | Every SwiftUI, UIKit, CallKit, WebRTC, Keychain and notification line was compiled and run only by CI's macOS runner; nothing was seen or touched by hand | A Mac with Xcode 16 and an iPhone: `RELEASE.md` §5 | owner |
| No Apple Developer team / credentials | No signing, no TestFlight, no store, no push certificates, no associated domains | Enrol the team; `RELEASE.md` §4 (and the CI secrets it names) | owner |
| The backend sends no APNs / PushKit pushes | Alerts and incoming calls reach the app only while it is open (Android's foreground service has no iOS equivalent) | An APNs key, a device-token endpoint, pushes for notification and call frames; then `PKPushRegistry` in the app | backend + owner |
| The host serves no `apple-app-site-association` | `https://neema.bethanyhouse.co.ke/dashboard…` links open Safari, not the app; `neema://` links work | The file on the host and the associated-domains entitlement | host + owner |
| No audio tap in the iOS WebRTC SDK | Local two-sided call recording is not possible; Meta's transcription stands in | — (platform) | decided |
| `openConversationFor` hangs inside the gallery's in-process host | The gallery renders no open-thread state; the UI tests prove the thread instead | unknown cause; the app itself is unaffected | noted |

## 6. The device-run list (what "unverified" means in practice)

The 33 unverified rows are, grouped: the chrome's look and motion (header,
drawer, bottom bar, sidebar and rail, account card, connectivity banner,
status-bar style, dark mode); the sheets and viewers (customer profile and
activity log sheets, `AdaptiveSheet`, media viewer, the dialogs); the
softphone's platform half (CallKit's screen, audio routes, the mic prompt,
WebRTC audio both ways); the console and details renderings; the Profile
rows; the crash signal handlers and the notice on the next launch; the
restore after process death; the keyboard and drop wiring on iPad; the
notification permission prompt; the CSV share sheet; the Keychain and
URLSession classes. Each is a line in `RELEASE.md` §5's checklist or a
matrix row with the file to look at.

## 7. The ten cycles

| Cycle | Scope | PR | Measured progress |
|---|---|---|---|
| 1 | Architecture & foundation | #269 | `NeemaCore` + app skeleton + XcodeGen + CI (Linux + macOS); matrix and plan |
| 2 | Data screens | #270 | inbox, thread, composer, customer panel, orders, catalog, deals, leads, analytics, reports, team, profile with their logic and ported tests |
| 3 | UI/UX refinement | #271 | theme, typography, icons, adaptive layouts, launch screen and icon, state restoration, the first gallery |
| 4 | Business logic & backend integrity | #272 | Settings (every card), 140 routes re-checked, reconciliation and 403 audits, `RouteCoverageTests` |
| 5 | Messaging, calls & real-time | #273 | every socket consumer, the bell and alerts, `CallManager` + CallKit + WebRTC + the call card and console |
| 6 | Performance | #274 | off-main decoding, image caching, list budgets, reconnect budget, stress suites ported |
| 7 | Security & permissions | #275 | Keychain accessibility, ATS, privacy manifest, usage strings, permission flows, RBAC audit, `SECURITY_CHECKLIST.md` |
| 8 | Functional & stress testing | #276 | `TESTS.md` (177 files mapped), 193 more ported tests (suite 1570), fixtures for every route, the first UI tests |
| 9 | Refinement & consistency | #277 | the window-hosted gallery with Android's named states, the walk against the goldens (`CONSISTENCY_LOG.md`, 7 fixes), wording diff, keyboard and drop on iPad (suite 1584, 8 UI tests) |
| 10 | Final verification & production readiness | see `PLAN.md` | the unsigned Release archive on CI, the test backend and fixtures kept out of Release, `RELEASE.md`, the matrix's last stale rows set straight, this report |

Anti-loop rules held: one pass per cycle, no cycle rebuilt another's work,
no issue took more than three correction attempts (the gallery's open-thread
state took three and was logged as the blocker above), and the programme
stops here.

## 8. Hand-over

- **Build and test**: `apps/ios/README.md`. The core anywhere with
  `swift test`; the app on a Mac with `xcodegen generate` and Xcode 16.
- **Release**: `docs/ios/RELEASE.md` — configuration, versioning (1.0.0,
  build 1; CI archives with the run number), signing and TestFlight steps,
  the CI secrets that would let the workflow sign and upload.
- **What each screen must do**: `docs/ios/PARITY_MATRIX.md`, row by row with
  the Android file it mirrors and the iOS file that does it.
- **What each test proves**: `docs/ios/TESTS.md`.
- **Security and privacy**: `docs/ios/SECURITY_CHECKLIST.md`.
- **What the screens look like next to Android's**: `docs/ios/CONSISTENCY_LOG.md`
  and every run's `ios-screenshots` artifact.
- **The history**: `docs/ios/PLAN.md` — every cycle's features, defects,
  tests, gaps and blockers.
- **First things to do**: enrol the Apple team; run `scripts/release.sh --team`
  on a Mac; install the TestFlight build on an iPhone and an iPad; walk
  `RELEASE.md` §5; then give the backend its push work (matrix §25) so the
  app rings when closed.

The programme ended with this report.
