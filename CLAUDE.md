# Neema AI — working notes

## Android: two APKs for every change

Whenever anything changes (app code, server, web — any change the owner will
test), build and send **two APKs**:

| File | For |
|---|---|
| `Neema-Android-<version>-<sha>.apk` | every Android phone, ARM 64- and 32-bit (~22 MB: the universal build without x86, which only emulators use — the full universal is over the 30 MB send limit) |
| `Neema-TabS9Ultra-<version>-<sha>.apk` | the Samsung Galaxy Tab S9 Ultra (arm64-v8a build) |

```sh
cd apps/android && scripts/two-apks.sh      # builds assembleRelease, then packages both
```

They land in `apps/android/app/build/outputs/two-apks/`. Both are the same app
with the same signing key (the tablet layouts switch on from the window size),
so each installs over the previous build. CI (`.github/workflows/android.yml`)
attaches the same two files to every run and to the GitHub Release on `main`.

Before building, run the gate:
`./gradlew :app:testDebugUnitTest verifyPaparazziDebug :app:assembleRelease`.
Screenshot goldens that change on purpose are re-recorded with the whole suite
(`recordPaparazziDebug`, not a filtered subset) so they match CI's test order.
