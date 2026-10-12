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
