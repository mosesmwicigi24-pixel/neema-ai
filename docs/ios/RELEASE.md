# Neema iOS — release configuration, versioning, signing and TestFlight

What a release of the iOS app is made of, what CI proves about it on every
pull request, and the steps that need an Apple Developer team — which this
repository does not hold, so those steps are **blocked** here and written
for the owner to run. Statuses use the parity matrix's vocabulary.

## 1. The release configuration

| Item | Where | Value | Status |
|---|---|---|---|
| Bundle identifier | `apps/ios/project.yml` | `ke.co.bethanyhouse.neema` (tests `….tests`, UI tests `….uitests`) | verified (CI builds it) |
| Display name | `project.yml` → `Info.plist` | Neema | verified |
| Deployment target | `project.yml` | iOS 17.0 (iPhone XS / XR and later; raised from 16.0 on 2026-10-30 for the iOS 17 `onChange` and `AVAudioApplication` APIs); iPhone and iPad (`TARGETED_DEVICE_FAMILY` 1,2), no Mac Catalyst | verified |
| Configurations | XcodeGen's defaults | Debug (the simulator job: `build test`) and Release (the archive job: `-O`, whole-module) | verified — both built on CI since cycle 10 |
| Orientations | `Info.plist` | phone: portrait + both landscapes; iPad: all four | verified (declared) |
| Background modes | `Info.plist` | `audio`, `voip`, `remote-notification` — a call that is up when the app leaves the screen; the pushes the backend does not send yet (§25 of the matrix) | declared |
| Usage strings | `Info.plist` | microphone, camera, photo library (`SECURITY_CHECKLIST.md` §3) | verified (declared) |
| Privacy manifest | `NeemaApp/PrivacyInfo.xcprivacy` | no tracking; account and crash data for app functionality; `UserDefaults` reason CA92.1 | verified (declared) |
| Encryption | `Info.plist` | `ITSAppUsesNonExemptEncryption` false (TLS only) | declared |
| App Transport Security | no exception key | the system default: TLS 1.2+, no cleartext | verified |
| URL scheme | `Info.plist` | `neema://` (Universal Links need the host's `apple-app-site-association`: blocked, matrix §25) | verified (the deep-link UI test) |
| Fonts | `NeemaApp/Resources` | Manrope (5 weights), DM Mono (2) — the same files as Android | verified (the gallery renders them) |
| App icon and launch image | `NeemaApp/Assets.xcassets` from `scripts/make_icons.py` | the launcher icon's shapes; `LaunchBackground` / `LaunchIcon` | verified (built) |
| Dependencies | `project.yml` | the local `NeemaCore` package; `stasel/WebRTC` ≥ 155 (binary xcframework, device and simulator slices) | verified (both jobs resolve it) |
| Test-only code | `NeemaApp/App/CannedBackend.swift`, `project.yml` | The recorded backend the UI tests launch (`-neema-canned`) compiles only in Debug; Release gets a stub that ignores the launch arguments, and `fixtures.json` is left out of the Release bundle (`EXCLUDED_SOURCE_FILE_NAMES`). `scripts/release.sh` fails if the archive carries it. | verified from cycle 10's archive run |
| Signing style | `project.yml` | Automatic, no team — CI passes `CODE_SIGNING_ALLOWED=NO` | blocked (needs a team) |
| Backend | `AppContainer` | `https://neema.bethanyhouse.co.ke`, `wss://…/ws` | verified (the core's URL rules) |

## 2. Versioning

Two numbers, the same two Android carries (`versionName` 1.0.0 /
`versionCode` 1 in `apps/android/app/build.gradle.kts`):

| | Build setting | Info.plist key | Now | Rule |
|---|---|---|---|---|
| Version | `MARKETING_VERSION` | `CFBundleShortVersionString` | 1.0.0 | Bumped by hand in `project.yml`, in step with Android's `versionName`, when a release changes what the person sees. |
| Build | `CURRENT_PROJECT_VERSION` | `CFBundleVersion` | 1 | Every upload to App Store Connect needs a higher build for the same version. CI's archive uses the workflow run number (`--build "$GITHUB_RUN_NUMBER"`, as Android tags `android-v<version>-<run>`); a release made by hand passes its own. |

The Profile screen shows "Neema for iOS <version> (<build>)"; crash reports
carry both (`app_version`, `build`), so a report names the build it came from.

Either value can be overridden without editing the project:
`scripts/release.sh --version 1.0.1 --build 42`.

## 3. What CI proves on every pull request (`.github/workflows/ios.yml`)

| Job | Runner | What | Status |
|---|---|---|---|
| NeemaCore (Linux) | ubuntu, Swift 6.2 | `swift test` — the whole core suite | verified |
| Neema app (iOS Simulator) | macos-15, Xcode 16 | XcodeGen → `xcodebuild build test` on an iPhone simulator (Debug): the app tests, the 54-shot gallery, the 8 UI tests against the canned backend | verified |
| Neema release archive (unsigned) | macos-15 | `scripts/release.sh --build <run>`: `xcodebuild archive` of the Release configuration for `generic/platform=iOS`, unsigned; the `.xcarchive` and the log uploaded as `ios-unsigned-archive` | verified from cycle 10's run |

An unsigned archive cannot be installed on any phone; it proves that the
optimised build compiles and links (WebRTC's device slice included) and that
the archive step works, which is everything that can be proven without a
team.

## 4a. On your own iPhone or iPad today — no paid membership

The app declares no entitlements (no push, no associated domains), so a free
Apple ID can sign it. Xcode calls that team your "Personal Team". An app signed
that way runs for 7 days on the devices plugged into that Mac, then needs
installing again. No Mac? §4b. TestFlight and other people's phones need §4.

What you need: a Mac with Xcode 16, a free Apple ID signed in to Xcode
(Xcode → Settings → Accounts → +), and the iPhone or iPad with a cable.

1. On the device: Settings → Privacy & Security → **Developer Mode** on
   (it restarts). Plug it in, unlock it, tap **Trust** for this Mac.
2. Find the team id: Xcode → Settings → Accounts → your Apple ID → the
   Personal Team's **Team ID** (ten characters).
3. Build, install and open it:

   ```bash
   git clone https://github.com/mosesmwicigi24-pixel/neema-ai.git
   cd neema-ai/apps/ios
   brew install xcodegen
   scripts/device-install.sh --team <TEAM_ID>
   ```

   The script generates the project, builds the Release configuration for
   the plugged-in device, signs it with that team, installs it with
   `devicectl` and opens it.
4. If the phone refuses to open it: Settings → General → **VPN & Device
   Management** → your Apple ID → Trust.
5. If Xcode says the bundle id is not available (another team holds
   `ke.co.bethanyhouse.neema`), add `--bundle-id ke.co.bethanyhouse.neema.<yourname>`.

Sign in with your Neema account as on Android. Until the backend sends
pushes (§25 of the matrix), alerts and calls arrive only while the app is
open. The script is untested by this programme (no Mac or device here);
`xcodebuild` and `devicectl` errors print as they come, and the build log is
`build/device.log`.

## 4b. Without a Mac — the .ipa from GitHub, signed with Sideloadly

Every change to the iOS app on `main` publishes a GitHub Release
**Neema iOS 1.0.0 (build N)** with `Neema-iOS-<version>-<sha>-unsigned.ipa`
(the same Release build CI archives; also the `neema-ios-ipa` artifact of
each iOS workflow run). It is unsigned: Apple lets an iPhone install only an
app signed for it, so a sideloading tool signs it with your own Apple ID.
Works for any iPhone on iOS 17 or later — iPhone 17 included.

What you need: a Windows PC or a Mac, the iPhone and its cable, and an Apple
ID (a free one is fine; better a separate one than your main account).

1. On the computer: install **Sideloadly** (sideloadly.io). On Windows also
   install **iTunes** and **iCloud** from apple.com — the web installers, not
   the Microsoft Store versions — so the PC can talk to the iPhone.
2. Download the `.ipa` from the repository's **Releases** page (the newest
   "Neema iOS" release).
3. Plug the iPhone in, unlock it, tap **Trust**.
4. Open Sideloadly: drag the `.ipa` in, pick the iPhone, type your Apple ID,
   **Start**. Enter the Apple ID password (and the two-factor code) when asked.
   If it says the bundle id is taken, open **Advanced options** and change the
   bundle id (e.g. `ke.co.bethanyhouse.neema.moses`).
5. On the iPhone: Settings → Privacy & Security → **Developer Mode** on (it
   restarts; confirm **Turn On**). The switch appears only after the first
   sideloaded app is installed.
6. Settings → General → **VPN & Device Management** → your Apple ID →
   **Trust**. Open Neema and sign in as on Android.

With a free Apple ID the signature lasts **7 days** and at most 3 sideloaded
apps can be on the phone; after 7 days the app won't open until it is
installed again (step 4, the data stays). A paid Apple Developer account
(§4) lifts both limits and opens TestFlight.

## 4. Signing and TestFlight — blocked here, the owner's steps

Needs: an Apple Developer Program membership (the Bethany House team), a
Mac with Xcode 16, and the App Store Connect record. Nothing in this
repository or on the box holds a certificate, a profile or an App Store
Connect key, and none should be committed.

1. **App Store Connect** → My Apps → New App: platform iOS, name "Neema",
   bundle ID `ke.co.bethanyhouse.neema` (register it under Certificates,
   Identifiers & Profiles first, with the capabilities **Push
   Notifications** and **Background Modes**; add **Associated Domains**
   when the host serves the `apple-app-site-association` file).
2. **Signing**: automatic. On the Mac, sign in to Xcode with the team's
   Apple ID (Xcode → Settings → Accounts); Xcode creates the development
   and distribution certificates and the profiles on first archive.
3. **Archive and export**:

   ```bash
   cd apps/ios
   brew install xcodegen && xcodegen generate
   scripts/release.sh --version 1.0.0 --build 1 --team <TEAM_ID>
   ```

   `--team` (or `NEEMA_APPLE_TEAM`) turns on signing with that team
   (`-allowProvisioningUpdates`), archives, and exports with
   `scripts/ExportOptions.plist` (method `app-store-connect`, automatic
   signing, symbols uploaded) into `build/export/Neema.ipa`.
4. **Upload**: open `build/export/Neema.ipa` in **Transporter**, or
   `xcrun altool --upload-app -f build/export/Neema.ipa -t ios --apiKey <key id> --apiIssuer <issuer>`
   with an App Store Connect API key (Users and Access → Integrations),
   or set `destination` to `upload` in the export options and let
   `xcodebuild -exportArchive` upload.
5. **TestFlight**: once the build is processed (minutes), add it to an
   internal group (the team's Apple IDs, up to 100, no review) — testers
   install the TestFlight app and accept the invitation. External groups
   need a short Beta App Review.
6. **The server side that is still blocked** (matrix §25): without APNs
   and PushKit from the backend the app rings and alerts only while open.
   For TestFlight that is acceptable; for the store release the backend
   needs the APNs key (App Store Connect → Keys → APNs) and a device-token
   register / unregister endpoint, and the app a `PKPushRegistry` client
   (`CallKitRinger` already answers `incoming_call` frames as CallKit calls
   when the app is open).

CI could do steps 3–4 itself with these repository secrets, none of which
exist yet: the distribution certificate (`.p12`, base64) and its password,
the App Store Connect API key (`.p8`, its id and issuer), and the team id —
the Android workflow's `ANDROID_KEYSTORE_*` pattern. Add a job that imports
the certificate into a temporary keychain, runs `scripts/release.sh --team`
and uploads with `altool`; until then the unsigned job is the gate.

## 5. Before the first TestFlight build — the owner's checklist

- [ ] Run the app on a real iPhone and an iPad from Xcode (nothing in this
      programme has: `PARITY_MATRIX.md`'s "unverified" rows are the list).
- [ ] Sign in, open a thread, send a text and a photo, receive a WhatsApp
      message while the app is open (the toast and the bell), take a
      WhatsApp call (CallKit's screen, the mic prompt, audio both ways).
- [ ] Background the app during a call (the `audio` / `voip` modes keep it
      up) and return to it.
- [ ] The three permission prompts read as `SECURITY_CHECKLIST.md` §3 says.
- [ ] App Store Connect → App Privacy answered from `PrivacyInfo.xcprivacy`
      (account data, crash data; no tracking).
- [ ] Screenshots for the store from the gallery's phone and iPad sizes
      (the `ios-screenshots` artifact is 2× of 390 × 844 and 1024 × 1366).
