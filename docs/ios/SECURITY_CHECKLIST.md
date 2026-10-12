# Neema iOS — security, permissions and privacy checklist (cycle 7)

What the iOS app does with the agent's credentials, the customers' data and
the phone's capabilities, item by item, with where each rule lives and how
it was checked. Statuses use the parity matrix's vocabulary (verified on
Linux or macOS CI; unverified = compiled only; platform-restricted; blocked).

## 1. Credentials and the session

| Item | Where | Rule | Status |
|---|---|---|---|
| Access and refresh tokens, the NextAuth cookie, the agent's id, email, name, role | `NeemaCore/Auth/SessionStore.swift` → `KeychainStore` | One generic-password item per key in the Keychain, service `ke.co.bethanyhouse.neema.session`, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: readable before the first unlock after a restart (the socket and calls), never carried by a backup to another phone. `MemoryStore` in tests. | verified (store rules, `AuthRepositoryTests`); the Keychain class itself unverified (device code) |
| Sign-out | `SessionStore.clear` | Every item removed; only `last_email` kept for the re-auth prompt (as Android). | verified |
| Session expiry | `NeemaHTTP` → `sessionExpired` → `SessionExpiredView` | Only the server refusing the session (a 401 the refresh cannot rescue, a 403 without a token) signs anyone out; an outage, a timeout or a captive portal is an error message (`NetworkStressTests`, `NeemaHTTPTests`). | verified |
| The token on the wire | `NeemaHTTP` | `Authorization: Bearer` on `/api/*` only; absolute URLs (media) carry no header; the socket's token rides the `ws` URL as the web's does. | verified |
| Tokens in snapshots | `SnapshotCache` | Only response bodies of `me`, `agents`, `orders`, `catalog`, the inbox and the inbox memory are snapshotted (raw text, `Caches/snapshots`); never a session, never a token. | verified by reading every `snapshots.save` site |
| Tokens in logs | the core and the app | No `print` / `os_log` / `Logger` in NeemaCore or NeemaApp. The only log hook is `CallManager.debugLog` (nil in the app; tests only) and it carries call frames, never credentials. | verified (grep) |
| Tokens in crash reports | `CrashVault` | A report holds the kind, the summary (an error's description), the trace, the build and the device. `ApiError`'s description is `METHOD path → status: body[0..500]` — a server body, never the request's headers. | verified by reading; see §4 |

## 2. Transport

| Item | Rule | Status |
|---|---|---|
| App Transport Security | No `NSAppTransportSecurity` key in `project.yml`: the system default (TLS 1.2+, no arbitrary loads, no cleartext). The base URL is `https://neema.bethanyhouse.co.ke`; the socket is `wss://`. | verified (the plist has no exception) |
| Certificates | The system trust store; no pinning (Android pins nothing either). | n/a |
| Redirects | `followRedirects` true by default; the auth flows that must not follow (NextAuth's callback) pass false. | verified (`AuthRepositoryTests`) |

## 3. Permissions and their rationale

iOS shows the system prompt with the app's usage string the first time a
capability is used; the usage strings in `project.yml` are the rationale.

| Capability | When asked | Usage string | What happens on refusal | Status |
|---|---|---|---|---|
| Notifications | Once, right after the first sign-in (`AppModel.askForNotificationsOnce`, pref `asked_post_notifications` — Android `MainActivity.maybeAskForNotifications`); never asked again by the app. | (notifications have no usage string; the prompt is the system's) | The bell and the in-app toast still carry every alert; the calls screen's readiness banner says "Calls can't ring in the background" with Turn on → Settings. | unverified (device code); the readiness banner's rules verified |
| Microphone | Mid-answer, when a call needs it (`CallMicHost`, `AVAudioSession.requestRecordPermission`) — Android asks the same way; the 60 s timeout and the MicBlocked outcome are `CallManager`'s. | `NSMicrophoneUsageDescription`: "Neema uses the microphone to take and place WhatsApp and Messenger calls with customers." | The call ends with "Microphone blocked" and Open settings. | verified (rules, `CallManagerTests`); the prompt unverified |
| Camera | When the composer's camera is opened (`UIImagePickerController`). | `NSCameraUsageDescription`: "Neema uses the camera to photograph an item and send it to a customer." | The picker shows nothing; the photo library remains. | unverified |
| Photo library | Never: `PhotosPicker` runs out of process and needs no permission. | `NSPhotoLibraryUsageDescription` present for the legacy picker path. | n/a | unverified |
| Background modes | `audio`, `voip`, `remote-notification` declared for the call that is up when the app leaves the screen and for the pushes the backend does not send yet (§25 of the matrix). | — | — | declared |

## 4. Crash reporting without more than Android sends

| Item | Rule | Status |
|---|---|---|
| What is captured | `CrashHandlers`: an uncaught `NSException` (name, reason, the call stack) and the fatal signals (SIGABRT, SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGTRAP: the signal's name and the call stack); a non-fatal from an edge (`CrashHooks.recordNonFatal`: WebRTC callbacks through `rtcGuard`). | unverified (device code); the vault's file rules verified (`CrashTests`) |
| What is sent | `POST /admin/client-crashes` `{id, at, kind, thread, summary, trace, app_version, build, device, sdk}` — the same body as Android's (`sdk` = the iOS major version). No agent name (the server adds it from the session), no customer data, no token. | verified (`CrashTests`) |
| Where it waits | `Application Support/crash/`: the newest 10 reports, `last.txt`, `last-fatal.txt`; sent oldest first once signed in, stopping at the first failure. | verified |
| What the person sees | The next launch's "Neema closed unexpectedly" notice with Share / Copy / Close (`CrashNoticeView`); Settings → App crash reports shows the server's list and "On this phone". | unverified |
| PII | A summary is an error's description. For an `ApiError` that is `METHOD path → status: body[0..500]`: a server error body may name a customer (as Android's `ApiException.message` does). Nothing else in a report identifies a person. | same as Android |

## 5. Privacy manifest

`NeemaApp/PrivacyInfo.xcprivacy`: no tracking, no tracking domains; the
data the app sends to the business's own server declared as collected and
linked to the agent (email address and name: the account; crash data), all
for app functionality; the required-reason API in use is `UserDefaults`
(CA92.1: the app's own preferences). File timestamps, disk space and system
boot time are not read.

## 6. Access control (RBAC), screen by screen

The web's `can(PERMS.*)` gates and the app's, side by side (every row read
from the source in cycle 7). The server enforces every permission itself;
the client only hides what a role cannot do.

| Gate | Web | iOS | Status |
|---|---|---|---|
| Nav: Reports, Leads, Analytics, Catalog, Team, Settings | `Sidebar.tsx` `can(VIEW_REPORTS / VIEW_LEADS / VIEW_ANALYTICS / VIEW_CATALOG / MANAGE_AGENTS / MANAGE_SETTINGS)` | `ShellRules.navItems` (`Shell.swift`), the same six | verified (`ShellTests.testNavItemsAreGatedLikeTheWeb`) |
| Settings → WhatsApp calling card, crash reports | `page.tsx` `canManageCalling={can(MANAGE_SETTINGS)}` | `SettingsScreen` (`Perms.MANAGE_SETTINGS`), `calls.canManageSettings` for the card's admin link | verified (`SettingsViewModelTests`) |
| Inbox: reply, intercept / release, close, transfer, notes, clear history | `ConversationsView.tsx` role rules | `InboxPerms` (`InboxPermsTests`), the same rules | verified |
| Orders / Deals / Leads: manage vs view, approve / veto, stage moves | role rules in each view | `SalesPermissionMatrixTests` (11), `OrdersBehaviourTests`, `LeadsBehaviourTests` | verified |
| Team: assign roles, remove, last admin | `AgentsView.tsx` | `TeamViewModelTests.testYouCannotRemoveYourselfOrTheLastAdmin` and the role tests | verified |
| 403 from the server | re-read who the agent is | `NeemaHTTP.forbidden` → the shell's coalesced refetch of `/me` and the team | verified |
| Access before the team row lands | nothing | `ShellRules.access`: nothing until the row decides (`ShellTests`) | verified |

## 7. Data at rest, other than the session

| Data | Where | Protection |
|---|---|---|
| Preferences (theme, alert switches, asked-once flags, the bell's last 60 rows) | `UserDefaults` | The app's container; no secrets. |
| Snapshots | `Caches/snapshots` | Purgeable by the system; no secrets. |
| Crash reports | `Application Support/crash` | The app's container; sent and removed once delivered. |
| Call recordings | `Caches/call-recordings` (the outbox) | Not captured on iOS (platform-restricted); the outbox only ever holds files a recorder produced. |
| Report CSVs | `Caches`, handed to the share sheet | Removed with the cache. |

Every file above lives inside the app's sandbox, under iOS data protection
(`NSFileProtectionCompleteUntilFirstUserAuthentication`, the default).

## 8. Carried blockers

Signing and TestFlight (no Apple credentials), pushes to a closed app
(backend PushKit / APNs), Universal Links (the host's
`apple-app-site-association`) — PARITY_MATRIX §25.
