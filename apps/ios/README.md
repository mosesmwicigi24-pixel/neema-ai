# Neema for iOS

The native iOS app for the Neema agent dashboard, mirroring the Android app
(`apps/android`) screen for screen and feature for feature. Swift and SwiftUI,
talking to the same FastAPI backend at `https://neema.bethanyhouse.co.ke`
over REST and the live WebSocket.

Two parts:

| Folder | What | Builds on |
|---|---|---|
| `NeemaCore/` | A Swift package with everything that is not a screen: wire models, the HTTP client and its session rules, sign-in and silent refresh, the live socket, the shell's rules (views, deep links, the way back, toasts, access), formatting and permissions, and every screen's logic (inbox, customer panel, orders, catalog, deals, leads, analytics, reports, team, profile, settings, WhatsApp calling, the calls console, the softphone's rules behind its ports, the bell and the message alerts). Mirrors `apps/android/.../core` and `feature/*` one rule for one rule. | Linux, macOS, iOS — `swift test` runs 1570 tests anywhere |
| `NeemaApp/` | The SwiftUI app (screens, theme, platform services). The Xcode project is generated from `project.yml` with XcodeGen. | macOS with Xcode 16 |
| `NeemaAppTests/` | The app's test bundle: the shell's four tests and the screenshot gallery below. | macOS, the simulator |
| `NeemaAppUITests/` | XCUITest driving the built app on the simulator against the recorded backend (`-neema-canned`): sign-in right and wrong, the bottom tabs, the drawer to Settings, the orders list, a thread by a tap and by a deep link (`-neema-open <key>`), sign-out. | macOS, the simulator |

## Build and test

```bash
cd apps/ios/NeemaCore && swift test          # the core, anywhere

cd apps/ios && brew install xcodegen && xcodegen generate
open Neema.xcodeproj                         # or:
xcodebuild -project Neema.xcodeproj -scheme Neema \
  -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO build test
```

CI (`.github/workflows/ios.yml`) runs both on every pull request that touches
`apps/ios`: the core on Linux, the app on a macOS runner against the iPhone
simulator. Nothing is signed in CI: shipping to a device or TestFlight needs
an Apple Developer team, which lives outside this repository.

## Screenshots of every screen

The macOS job also renders the sign-in screen and every view of the signed-in
app on a phone (light and dark) and an iPad, against a canned backend, and
uploads the PNGs as the `ios-screenshots` artifact of each run — the only look
at the SwiftUI layer the programme gets without a device. The pieces:

- `NeemaAppTests/Gallery/ScreenGalleryTests.swift` renders each view through
  `ImageRenderer` and writes to `$NEEMA_SCREENSHOTS` (set by the workflow as
  `TEST_RUNNER_NEEMA_SCREENSHOTS`); locally, `xcodebuild … test` attaches the
  images to the result bundle.
- `NeemaAppTests/Gallery/fixtures.json` is what the canned backend serves:
  the answers the core's fixtures gave every screen's model. Regenerate it
  after the fixtures or a screen's requests change:

  ```bash
  NEEMA_GALLERY_OUT=/tmp/gallery swift test --package-path apps/ios/NeemaCore --filter GalleryFixtureExport
  cp /tmp/gallery/fixtures.json apps/ios/NeemaAppTests/Gallery/fixtures.json
  ```

## The UI tests and the recorded backend

Launched with `-neema-canned`, the app runs on `CannedBackend`
(`NeemaApp/App/CannedBackend.swift`): the gallery's `fixtures.json`, bundled
with the app too, answers every GET, sign-in is answered as FastAPI's auth
router would for the fixtures' agent (any email, password `neema`), and the
live socket is dead on arrival. `NeemaAppUITests/NeemaUITests.swift` drives
that app as a person would, finding controls by the accessibility labels the
screens carry for VoiceOver and the sign-in form by its identifiers
(`login.email`, `login.password`, `login.submit`); `-neema-open <key>` hands
the app a deep link at launch, as a notification tap would. The canned app
runs in its own wiped preferences suite and snapshot folder and restores no
saved scene state, so one test leaves nothing for the next. The scheme runs
them with the unit tests, so the CI job above runs them on every pull request.

The gallery (`ScreenGalleryTests`) hosts each view in a window of the shot's
size and draws it as it is on screen — lists and scroll views included — and
after the eleven views renders the states Android's screenshot suites pin
(the drawer, the bell, toasts, offline, the session-expired card, a ringing
call, a missed call's wrap-up). `docs/ios/CONSISTENCY_LOG.md` is the walk of
those shots against Android's goldens.

`docs/ios/TESTS.md` maps every Android test file to where the same behaviour
is proven on iOS.

## The routes the server serves

`NeemaCore/Tests/NeemaCoreTests/RouteCoverageTests.swift` reads every
`http.get/post/put/patch/delete`, `http.raw` and `http.multipart` call in the
core's sources and checks, method and path, that `apps/api/app` serves it —
so a renamed handler or a typo fails on Linux before the macOS job. The
server's table is `Support/ServerRoutes.swift`; regenerate it after a backend
route changes: `python3 apps/ios/scripts/server_routes.py`.

## The app icon and launch image

`scripts/make_icons.py` renders `NeemaApp/Assets.xcassets` (the 1024 px app
icon and the launch image) from the same shapes as Android's launcher icon —
pure Python, no image library needed: `python3 apps/ios/scripts/make_icons.py`.

## Where things stand

`docs/ios/PARITY_MATRIX.md` lists every Android feature and the iOS status of
each; `docs/ios/PLAN.md` holds the ten improvement cycles and what each one
did. Two things iOS cannot do the way Android does and that need backend
work before they work at all: alerts and ringing calls while the app is
closed (Android keeps the socket open with a foreground service; iOS needs
APNs and PushKit VoIP pushes from the server) and Universal Links (the host
must serve an `apple-app-site-association` file). Both are tracked in the
matrix.
