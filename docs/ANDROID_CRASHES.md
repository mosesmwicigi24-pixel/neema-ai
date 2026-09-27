# Android crash reports

When the Android app closes unexpectedly, it records why.

- **Where a report is saved:** the phone saves it in the app's private `files/crash/` folder at the moment of the crash (`core/crash/CrashVault.kt`).
- **When it's sent:** the next time someone is signed in, the phone sends it to `POST /api/admin/client-crashes` (`CrashReporter.kt`).
- **Where to read it:** the web dashboard, **Settings → App crash reports** (admins only). Each report has a **Copy** button.

## What gets recorded

| Kind | Label in Settings | What happened |
|---|---|---|
| `crash` | App closed | An uncaught exception on any thread. The app still closes afterwards. |
| `nonfatal` | Background error | An error escaped a background job of the app scope, a socket frame the call code couldn't handle, or a failed session read. The app kept running. |
| `native` | App closed (native) | A native crash, for example in WebRTC. The system's exit record reports it at the next start (Android 11+). |
| `anr` | App froze | The system killed the app because it stopped responding (Android 11+). |

Every report carries:
- the full stack trace
- the thread
- the CI build number (`BuildConfig.BUILD_NUMBER`, the `N` in `android-v1.0.0-N`)
- the device and its Android API level
- the agent who was signed in

The server logs each report once, as `android <kind> from <agent> …`, and keeps one row per report id.

## Reading a release trace

Release builds are shrunk by R8, so class and method names in a trace are obfuscated. Line numbers are kept (`proguard-rules.pro`). Each GitHub release publishes the matching mapping next to its APKs, named `neema-1.0.0-N-mapping.txt`.

To restore the real names:
1. Save the copied trace as `trace.txt`.
2. Run:
   ```
   $ANDROID_HOME/cmdline-tools/latest/bin/retrace neema-1.0.0-N-mapping.txt trace.txt
   ```

## Crash fixes from 2026-09-27

A phone showed "Neema closed because this app has a bug" (build 61), and there was no trace to go on. Three audits of the app found these crash paths, now fixed:

- **Calls screen:** a live update for an older call went to the top of the log. The same day heading then appeared twice, and a repeated lazy-list key crashes Compose. Updates are now placed by time, and day keys are unique.
- **Session storage:** the encrypted session could open but fail to read (a lost Keystore key, seen on Samsung). That threw in `Application.onCreate` on every start. The file is now wiped, and the agent signs in again.
- **Stopping the background service** between `startForegroundService` and `startForeground` ("did not then call Service.startForeground()"). This could happen when a call failed just as its audio started. The stop now waits for the start.
- **Background coroutine errors** killed the whole app. The app scope now has an exception handler that records the error, and the call-event listener survives a bad frame.
- **Smaller fixes:** a link tapped with no browser installed, a `null` buffer in the recorder, and lead stage and report table keys that could repeat.
