# Neema for iOS

The native iOS app for the Neema agent dashboard, mirroring the Android app
(`apps/android`) screen for screen and feature for feature. Swift and SwiftUI,
talking to the same FastAPI backend at `https://neema.bethanyhouse.co.ke`
over REST and the live WebSocket.

Two parts:

| Folder | What | Builds on |
|---|---|---|
| `NeemaCore/` | A Swift package with everything that is not a screen: wire models, the HTTP client and its session rules, sign-in and silent refresh, the live socket, the shell's rules (views, deep links, the way back, toasts, access), formatting and permissions. Mirrors `apps/android/.../core` one type for one type. | Linux, macOS, iOS — `swift test` runs 147 tests anywhere |
| `NeemaApp/` | The SwiftUI app (screens, theme, platform services). The Xcode project is generated from `project.yml` with XcodeGen. | macOS with Xcode 16 |

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

## Where things stand

`docs/ios/PARITY_MATRIX.md` lists every Android feature and the iOS status of
each; `docs/ios/PLAN.md` holds the ten improvement cycles and what each one
did. Two things iOS cannot do the way Android does and that need backend
work before they work at all: alerts and ringing calls while the app is
closed (Android keeps the socket open with a foreground service; iOS needs
APNs and PushKit VoIP pushes from the server) and Universal Links (the host
must serve an `apple-app-site-association` file). Both are tracked in the
matrix.
