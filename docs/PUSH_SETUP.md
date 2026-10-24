# Calls ring with the app closed — push setup (Firebase Cloud Messaging)

Owner, 2026-10-24: *"The calls should come through even the app is not open.
When any phone is on, route the call there. Also, the app should remain active
in the background to receive calls."*

## How it works

- Every call event (the ring, "answered", "ended") already goes to every
  **running** app over the live socket. The server now also sends it to every
  **signed-in phone** as a high-priority Firebase data message
  (`apps/api/app/services/push.py`, hooked into `call_log.publish`).
- Android wakes the app for it (`NeemaPushService`). The app rings exactly as
  for the socket frame (`CallManager.onPush`), with the full-screen call screen
  on a locked phone. It also restarts the background connection, which the
  answer and the audio need.
- **Every phone rings, and the first one to answer takes the call.** The others
  stop at once (`call_answered`). A ring that reaches a phone after the caller
  has given up (the phone was off) is not rung.
- A phone is registered when someone signs in (`POST /api/admin/push/register`),
  moves to whoever signs in on it next, and is removed at sign-out. If Firebase
  says a phone's token is dead (app uninstalled), the server deletes it.
- Until the Firebase values below are set, nothing changes: calls ring only
  while the app is running, as before.

## One-time setup (owner, about 15 minutes)

1. **Create the project.** Go to https://console.firebase.google.com → **Add
   project** → name it `Neema`. Google Analytics is not needed.
2. **Add the Android app.** In the project, click **Add app** → **Android**:
   - Package name: `ke.co.bethanyhouse.neema`
   - Click **Register app**, then **Download google-services.json**. You don't
     need to add it to the code; four values from it are enough (next step).
3. **Give the four app values to the build.** Add them in GitHub → the
   repository → Settings → Secrets and variables → **Actions** → New repository
   secret. Or send them to Claude to commit; none of them is secret, since
   every installed APK carries them.

   | Secret | Where it is in google-services.json |
   |---|---|
   | `NEEMA_FCM_PROJECT_ID` | `project_info.project_id` |
   | `NEEMA_FCM_SENDER_ID` | `project_info.project_number` |
   | `NEEMA_FCM_APP_ID` | `client[0].client_info.mobilesdk_app_id` |
   | `NEEMA_FCM_API_KEY` | `client[0].api_key[0].current_key` |

   For a local build, put the same four in `~/.gradle/gradle.properties`.
4. **Give the server its key. This one IS secret.**
   - In Firebase, go to Project settings → **Service accounts** → **Generate
     new private key**. A `.json` file downloads.
   - On the VPS, add this line to the API's `.env`:
     `FCM_SERVICE_ACCOUNT_JSON=<the output of: base64 -w0 that-file.json>`
   - Restart the API.
   - Never commit this file or paste it in chat.
5. **Build and install** the new APKs (CI does it on the next merge), and sign
   in on each phone once.

## Checking it

- Close Neema completely: swipe it away from recent apps. Then call the
  business WhatsApp number. Every signed-in phone should ring with the call
  screen.
- Answer on one phone. The others stop within a moment.
- The API log shows a line like `push: incoming_call wacid… → sent N, failed 0`.

## Still needed on each phone

Push wakes a closed app. Android still decides how aggressively to save
battery:
- In Neema, tap **Allow** on the yellow battery box on the Calls screen. This
  sets Battery to Unrestricted.
- On Samsung, also go to Settings → Battery → Background usage limits →
  **Never sleeping apps** → add Neema.
- An app that was **Force stopped** from Settings gets no push until it is
  opened again (an Android rule for every app).

## Not covered

- **iPhone:** needs Apple push (APNs), which needs the paid Apple Developer
  account. Until then the iOS app rings only while it is open.
- **Web dashboard:** rings while a tab is open, as before.
