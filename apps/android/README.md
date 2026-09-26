# Neema for Android

The native Android app for the Neema agent dashboard (the web app in
`apps/web`), built with Kotlin and Jetpack Compose. It talks to the same
FastAPI backend at `https://neema.bethanyhouse.co.ke` over REST and the live
WebSocket, so everything an agent does here is what they'd see on the web.

## Build and install

Requirements: JDK 17+ and the Android SDK (platform 36). Android Studio has
both; open this folder (`apps/android`) as the project.

```bash
cd apps/android
echo "sdk.dir=$ANDROID_HOME" > local.properties   # Android Studio writes this for you
./gradlew :app:assembleDebug
```

APKs land in `app/build/outputs/apk/debug/`:

| File | For |
|------|-----|
| `app-arm64-v8a-debug.apk` | almost every phone from the last 7 years |
| `app-armeabi-v7a-debug.apk` | older 32-bit phones |
| `app-universal-debug.apk` | any device (larger) |

Install with `adb install -r app/build/outputs/apk/debug/app-arm64-v8a-debug.apk`,
or copy the APK to the phone and open it (allow "install unknown apps").

`./gradlew :app:assembleRelease` builds a minified release. It is signed with
the debug key until a release keystore is configured in `app/build.gradle.kts`.
Use a real keystore before distributing through Play or MDM.

The backend URL is `NEEMA_BASE_URL` in `app/build.gradle.kts`.

## How it's put together

```
app/src/main/java/ke/co/bethanyhouse/neema/
├── NeemaApplication.kt   process-wide socket lifecycle, foreground tracking
├── MainActivity.kt       theme, login ↔ dashboard, deep links, notification taps
├── app/                  DashboardViewModel (shared state), shell/navigation, login
├── core/
│   ├── api/              NeemaApi — every endpoint in apps/web/src/lib/api.ts
│   ├── auth/             sign-in, token refresh, encrypted session storage
│   ├── model/            wire models (types/index.ts + api.ts interfaces)
│   ├── net/              HTTP client (30s ceiling, refresh-on-401, session expiry)
│   ├── ws/               live WebSocket (/ws/{agent_id}?token=…), ping + reconnect
│   ├── notify/           bell, system notifications, background LiveService
│   ├── perm/ util/ ui/   permissions, formatters, theme, shared components
└── feature/<view>/       one package per dashboard view
```

### Signing in
The web signs in through NextAuth, and on the public origin `/api/auth/*`
belongs to NextAuth. The app therefore tries FastAPI's login at
`/api/agent-auth/login` first (the same router mounted a second time). If that
route isn't deployed yet, it falls back to NextAuth's own credentials flow;
the session it returns already carries the FastAPI tokens.

### Background alerts and calls
The backend has no push service (FCM). The web gets live alerts from an open
browser tab. On Android a small foreground service ("Neema is connected")
keeps the live socket open so escalations and ringing WhatsApp calls arrive
while the app is closed. Agents can turn it off in Profile.
