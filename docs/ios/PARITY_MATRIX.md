# Neema iOS — Android-to-iOS feature parity matrix

The Android app (`apps/android`, Kotlin + Jetpack Compose, 112 files / ~39k
lines) is the definitive reference. This matrix lists every screen, feature,
rule, endpoint and socket frame it implements, and where the iOS app
(`apps/ios`) stands against each. It is updated at the end of every
improvement cycle (`docs/ios/PLAN.md` holds the cycle log).

Sources: the four audits of the Android code (shell/auth/settings; inbox,
thread, customer panel, socket, models; calls, notifications, permissions,
crash reporting; orders, catalog, deals, leads, the full API surface), read
against the Kotlin itself. Android file paths are relative to
`apps/android/app/src/main/java/ke/co/bethanyhouse/neema/`; iOS paths to
`apps/ios/`.

## Status vocabulary

| Status | Meaning |
|---|---|
| **verified** | Implemented on iOS and proven by a test that runs in this environment (`swift test` on Linux for `NeemaCore`) or by a green macOS CI run that exercises it. |
| **unverified** | Implemented, but the only check available was a compile (SwiftUI builds only on macOS CI) or none at all; device behaviour has not been seen. |
| **partial** | Some of the Android behaviour is there; the gap is named in the row. |
| **missing** | Not started. |
| **platform-restricted** | Android relies on something iOS does not have (a foreground service, a full-screen intent, a boot receiver…). The iOS equivalent, or the reason there is none, is named. |
| **blocked** | Needs something outside this repository (Apple credentials, a backend push service, a device). |

Verification environments, honestly: this programme runs on a Linux
workstation with the Swift 6.2 toolchain, so the platform-independent core
is built and tested here. SwiftUI, UIKit, CallKit, WebRTC, PushKit and the
Keychain compile only with Xcode: the repository is public, so GitHub's
macOS runners (`.github/workflows/ios.yml`) are the compiler and simulator.
Nothing has run on a physical iPhone or iPad. No App Store / TestFlight
signing exists (no Apple Developer credentials in the repo or on the box).

---

## 1. Platform foundation (`core/*` → `apps/ios/Sources/NeemaCore`)

| Feature | Android | iOS | Status | Cycle |
|---|---|---|---|---|
| JSON leniency: numbers as strings, nulls as defaults, unknown keys ignored, bools as 0/1/"true" | `NeemaJson` (kotlinx) | `JSON/JSONValue.swift`, `JSON/NeemaJSON.swift` (`LenientKeyed`) | verified | 1 |
| Wire models: 52 types in `Models.kt` (Conversation, ConversationPage, InboxSummary, CommentContext, ReplyTo, Message, ActivityEvent, ConversationWindow, Deal*, PlannedAction, Campaign, OfferSetting, TranslationSetting, Agent, CustomRole, Catalog*, PriceAudit*, Order*, Stats, ChannelCount, Attribution*, Call, CallInsights, CallPermission, PermissionRequestResponse, CallTranscript, IceServer/IceConfig, ChannelCalling/CallChannels, CallSdpResponse, CallingSettings (+hours/holiday/voicemail), PermissionTemplate, CallOffer, 19 envelopes) | `core/model/Models.kt` | `Models/*.swift` (same names, snake_case keys, same defaults) | verified (contract tests decode the handlers' real shapes) | 1 |
| `OrderItemsSerializer` rules (qty/quantity, unit/unit_price/price, total = qty×unit, non-objects dropped) | `Models.kt` | `Models/Orders.swift` `OrderItem.normalise` | verified | 1 |
| Lenient string lists (`tags`, `aliases`), variant attributes (`[]` → {}), `isNote` camelCase key, `status` open→pending, `CatalogItem.id/category/isHub`, `Agent.permissions` | `Models.kt` | same | verified | 1 |
| `ApiException` → status, detail (string / pydantic list / object), `field()`, `code` (body or `X-Neema-Reason`), `action`, `timedOut`, `malformed`, `looksLikeHtml` | `core/net/NeemaHttp.kt` | `Net/ApiError.swift` | verified | 1 |
| `ErrorText`: one voice for every failure (12 strings, stock-phrase filter, Retry-After wording) | `core/net/ErrorText.kt` | `Net/ErrorText.swift` | verified | 1 |
| HTTP client: `${BASE}/api`, bearer on every call, `Accept: application/json`, bodiless POST/PATCH/PUT send an empty JSON body, 30 s ceiling, 10-min upload client, absolute URLs as is | `NeemaHttp.kt` | `Net/NeemaHTTP.swift` over `Net/HTTPTransport.swift` (`URLSession`, no cookie jar, redirects only when asked) | verified (fake transport); URLSession transport itself **unverified** (needs a network) | 1 |
| 401 (or 403 with no token) → `onRejected`, one `forceRefresh`, one retry, then `sessionExpired`; a refresh outage fails only that request | `NeemaHttp.kt` | `NeemaHTTP.raw` | verified | 1 |
| 403 with a token → `forbidden` signal except GET `/admin/me` / `/admin/agents` | `NeemaHttp.kt` | same | verified | 1 |
| Empty 2xx reads as nil / `{}` / `[]`; malformed 2xx → `ApiError(200, malformed)` | `NeemaHttp.decode` | `NeemaHTTP.decode` | verified | 1 |
| Cancelling the caller ends as cancelled, never a network error | `InFlight` | `Task` cancellation + `TransportError.cancelled` | verified | 1 |
| Streamed multipart uploads re-read the file on the post-refresh retry; a missing file is a status-0 error | `UploadFile`, `RequestBody` | `MultipartBody` (temp file for `uploadTask(fromFile:)`), `UploadFile.of(file:)` | verified (fake); upload task **unverified** | 1 |
| Sign-in: `agent-auth/login` → `auth/login` → NextAuth csrf/callback/session (cookie jar, chunked cookies); 401/422 final; 429 / 5xx / offline / timeout wording | `core/auth/AuthRepository.kt` | `Auth/AuthRepository.swift`, `CookieJar` | verified (37 tests mirror Android's) | 1 |
| Silent refresh: 5-min buffer, one refresh for everyone (lock), 3 attempts × backoff, refusal final, timeout final, refused token remembered, 30 s outage cooldown, NextAuth "same token" is no rescue, role kept from `/admin/me` in nextauth mode | `AuthRepository.kt` | same | verified | 1 |
| `jwtExp` / `jwtSub` read without verifying | same | same | verified | 1 |
| Session store: encrypted prefs; unreadable store wiped, not a crash; `last_email` kept across sign-out | `core/auth/SessionStore.kt` | `Auth/SessionStore.swift` (`KeychainStore` on Apple, `MemoryStore` in tests) | verified (memory); Keychain **unverified** | 1 |
| Live socket: `wss://…/ws/{agent}?token=`, token re-read per attempt, ping 25 s, backoff 2/4/8/16/30 s, `nudge`, `reconnected` signal rules, replaced-socket frames ignored, 1,024-frame buffer, `droppedFrames` | `core/ws/LiveSocket.kt` | `Live/LiveSocket.swift` (+ `URLSessionWebSocketFactory`) | verified (24 tests on a virtual clock); URLSession factory **unverified** | 1 |
| Endpoint surface (`NeemaApi`: conversations, deals, actions, settings, agents, catalog, orders, stats, calls, profile, roles, ask/answer, invite, attribution) with the same paths, query names and bodies | `core/api/NeemaApi.kt` | `Api/NeemaApi.swift` | verified for the endpoints the contract tests cover; the rest compile and share the same helpers | 1 |
| `Perms`: 21 keys, superuser → all, custom ?: role ?: legacy defaults | `core/perm/Permissions.kt` | `Util/Perms.swift` | verified | 1 |
| `Fmt`: ISO parsing (offset, naive = UTC, SQL space, date-only = local midnight), `timeAgo`, grapheme initials, en-US numbers, "5 Sept 2026", `HH:mm`, day labels, `mm:ss`, phones per country, Messenger IDs, web visitors, flags, country names | `core/util/Format.kt` | `Util/Fmt.swift` | verified | 1 |
| `AppClock` (pinned in tests) | `core/util/AppClock.kt` | `Util/AppClock.swift` | verified | 1 |
| `SingleFlight` (one read on the wire; late callers share the next read; cancel) | `core/util/SingleFlight.kt` | `Util/SingleFlight.swift` | verified | 1 |
| `Coalescer` (one run per burst, never overlapping, one run after a slow run) and the 500 / 800 ms windows | `core/util/ScreenLife.kt` | `Util/SingleFlight.swift` (`Coalescer`) | verified | 1 |
| `ScreenLife` (shown × foreground × connected → catch-up, poll) | `ScreenLife.kt` | — | missing (Cycle 2, with the first screens) | 2 |
| `AppPrefs` (theme, background_live, alert settings, mute) | `core/util/AppPrefs.kt` | — | missing (UserDefaults-backed; `background_live` is platform-restricted, see §24) | 2 |
| `SnapshotCache` (per-agent JSON files for me/agents/orders/catalog, inbox page one, inbox memory) | `core/util/SnapshotCache.kt` | — | missing (Cycle 2; will store the raw response text so no model needs to be Encodable) | 2 |
| `UiRestore` / saved state across process death | `core/util/UiRestore.kt`, `rememberSaveable` | — | missing (SwiftUI `@SceneStorage` / state restoration, Cycle 2–3) | 2 |
| `ContactNames` (LRU of 2,000 names for notifications) | `core/notify/MessageAlerts.kt` | `NeemaApi.onConversationsSeen` hook only | partial | 5 |

## 2. App bootstrap, shell and navigation (`app/`)

| Feature | Android | iOS | Status | Cycle |
|---|---|---|---|---|
| Single entry, splash (night #070D1C, moss icon), then the app | `MainActivity`, `Theme.Neema.Starting` | `NeemaApp/App/NeemaApp.swift`, launch screen | unverified — `UILaunchScreen` with the night background and the moss tile (`Assets.xcassets`, rendered from Android's launcher shapes by `scripts/make_icons.py`); the app icon likewise | 1/3 |
| Hand-rolled DI: prefs, session store, auth, http, api, socket, foreground, online, snapshots, notifications, message alerts, calls, crash reporter | `app/AppContainer.kt` | `NeemaApp/App/AppContainer.swift` | unverified (skeleton: store, auth, http, api, socket, foreground, online) | 1 |
| Foreground tracking + network callback that nudges the socket | `NeemaApplication` | `scenePhase` + `NWPathMonitor` | unverified | 1 |
| `ViewId` (11 views, labels, web names), start on Inbox | `app/DashboardViewModel.kt` | `NeemaCore/Shell/ViewId.swift` | verified | 1 |
| `navigate` history (each view once, cap 10), `back` → previous, Inbox, leave | same | `NeemaCore/Shell/NavHistory.swift` | verified | 1 |
| Deep links `?open=<key>[&ref=]`, `?view=calls&caller=`, `?view=<name>`, `https://neema.bethanyhouse.co.ke/dashboard*`, `neema://`; stashed while signed out and replayed once; newest wins; dropped on sign-out | `applyDeepLink`, manifest filters | `NeemaCore/Shell/DeepLink.swift` (+ `onOpenURL`, Universal Links need an AASA file on the host) | verified (parsing); routing **unverified**; AASA **blocked** (host file + entitlement) | 1 |
| Cross-view requests: `openConvKey`, `callsFocusKey`, `composerPrefill`, `inboxRefresh`, `immersive` | `DashboardViewModel` | `DashboardModel` | unverified (`AppModel` + `ShellInboxHost`; `callsFocusKey` is consumed by the calls screen in cycle 5) | 2 |
| Toasts: one at a time, 3.5 s while in front, ≥1.5 s after a return, survives process death; ✓ / ! / ✕ pill | `DashboardViewModel`, `ToastView` | `NeemaCore/Shell/Toast.swift` + `ToastView` | partial (rules verified; view unverified) | 1 |
| Snapshots painted on sign-in; `refetchMe` (3 tries, no retry on 401); polls agents 180 s / catalog 300 s / orders 90 s only in front, refetch on return | `DashboardViewModel` | `DashboardModel` | verified (the feeds and `refetchMe` rules) · shell unverified | 2 |
| Notification frames → toast "{title}: {body}", inbox refetch (types), orders refetch on `order_update` (800 ms) | same | — | missing | 5 |
| `socket.reconnected` → orders refetch unless < 5 s ago; `sessionExpired` → dialog; `forbidden` → re-read me + agents (1 s coalesce, 15 s cooldown) | same | — | verified (the feed and the host) · shell unverified | 2 |
| Access: team row by id then email; `permissions()` empty until it lands; `isAdmin` rule; nav gates | `access`, `Sidebar.buildNavItems` | `NeemaCore/Shell/Access.swift` | verified | 1 |
| Logout: ignore repeats, stop polls, end a live call (3 s / 4 s caps) before the token goes, clear store (keep `last_email`), clear notifications, clear agent state, drop pending link; late answers dropped | `logout()`, `forCurrentAgent` | — | missing (call part: Cycle 5) | 2 |
| Session expired dialog: not dismissable, "Signed in as", password, "Continue"/"Signing in…", "Sign out", errors | `LoginScreen.kt` `SessionExpiredDialog` | `Views/Auth/SessionExpiredView.swift` | unverified | 1 |
| Login screen: night palette, brand panel ≥1024 dp, exact copy, email prefilled from `last_email`, eye toggle, validation and error strings | `LoginScreen.kt` | `Views/Auth/LoginView.swift` | unverified | 1 |
| Phone chrome: header (☰, amber logo, "Neema · {view}", reconnecting pill, bell with "9+" badge, theme toggle), bottom nav (first 4 + More, amber indicator), drawer 272 dp navy | `DashboardShell.kt`, `Sidebar.kt` | `Views/Shell/*` | unverified — the web's icon paths, the wordmark that yields at 150% text, the bell with its red count, the theme switch, the bottom bar's half-width indicator and capped labels, the 272 pt start-edge drawer | 1/3 |
| Wide chrome: navy docked sidebar 208 dp / rail 60 dp, collapse rule (<1200 dp), bell popup 316 dp, toast top-end, offline dot, docked call panel 420 dp at ≥1000 dp | same | `NavigationSplitView` / custom sidebar | unverified — `navMode(for:)`: rail under 1200 pt (the choice holds until the mode changes), docked 208 pt × text scale beyond; toast top-end; the "Reconnecting…" pill; the bell popup is cycle 5 and the docked call panel cycle 5 | 3 |
| Sidebar items, badges (Inbox = human, Orders = pending), account card (profile, settings, dark mode switch, sign out), signing-out spinner | `Sidebar.kt` | — | unverified — amber pill rows with navy ink, the three badge sizes with the full number, the account row (online dot, role line, rotating chevron, signing-out ring), the account card inline or as a popover on the rail | 3 |
| Bell panel: header, mute control (1 h / 8 h / until), mark all read, rows by kind with emoji tiles, dismiss, footer "Clear all", mute status strings | `ShellParts.kt` | — | missing | 5 |
| Connectivity banner (offline / back online 2.5 s) | `ShellParts.kt` | — | unverified (the solid badge, the two wordings, 2.5 s fold) | 3 |
| Back-press order: bell popup → account menu → drawer → the view → history → Inbox → exit | `ShellBack.kt` | — | platform-restricted — iOS has no system back; the shell's overlays (drawer, account card, sheets) dismiss by swipe, scrim tap or ✕, and the in-app history (`NavHistory`) stays for the keyboard's Escape in cycle 9 | 3 |
| Keyboard shortcuts: Ctrl+1…9, Ctrl+B, Alt+↑/↓, Ctrl+[ ], Ctrl+F/K, Esc, Enter/Shift+Enter in the composer | `core/ui/Shortcuts.kt` | `.keyboardShortcut` | missing | 9 |
| Drag-and-drop of files onto the thread | `DropFiles.kt` | `.dropDestination` (iPad) | missing | 9 |
| System bar icon colours by theme / signed-out | `MainActivity` | `.preferredColorScheme`, status bar style | unverified — `.preferredColorScheme`: dark over the night login and the dark theme, light otherwise (the wide shell's navy top edge is drawn under the status bar) | 3 |
| Dark mode: app-controlled (`theme` pref), three toggles, always-night login, always-light cards | `AppPrefs`, `NeemaTheme` | `NeemaTheme` | unverified — the `theme` pref drives the environment; three toggles (header, account card pill, Profile); the login is always night; the account card always white | 3 |
| Notification permission asked once after first sign-in | `MainActivity.maybeAskForNotifications` | `UNUserNotificationCenter.requestAuthorization` | missing | 5/7 |

## 3. Inbox list (`feature/conversations/ConversationList.kt`, `ConversationsViewModel.kt`)

| Feature | Status | Cycle |
|---|---|---|
| Pane rules: one pane < 801 dp (thread full-screen, chrome hidden); two panes ≥ 801 (list 30%, 320–400 dp); customer panel docks when the thread keeps ≥ 480 dp + 32 dp rail; activity pane 16% (196–292 dp); `roomyThread` ≥ 540 dp; auto-open first row; placeholder "💬 Select a conversation" | unverified (phone / two-pane / docked customer panel; the rail widths are re-checked in cycle 3) | 2 |
| Header "Chats" / "{n} selected", "{human} live" pill, select mode (checklist icon), filter icon | logic verified · UI unverified | 2 |
| Tabs All · Unread · Read · Human · Yours with server-summary counts ("999+"), local fallback before the summary | logic verified · UI unverified | 2 |
| Search: placeholder, 300 ms debounce, server `q`, ✕ | logic verified · UI unverified | 2 |
| Channel chips All · WA · FB · MSG · IG with `unread_messages` badges | logic verified · UI unverified | 2 |
| Filter panel: tags from the summary, mode pills All / "Ai" / Human / Paused | logic verified · UI unverified | 2 |
| Rows grouped by `person_id` (newest representative, sibling chips), sorted by `lastMessageAt ?: createdAt`; edge colour, avatar + flag + unread dot, name rules ("Website visitor"), repeat-buyer badge, time ago, chips (channels, stage, country, Human/Paused, Yours/🔒, unread pill), preview, hover, long-press select | logic verified · UI unverified | 2 |
| Bulk release bar and parallel `POST …/release` with 404 handling and toasts | logic verified · UI unverified | 2 |
| States: Loading… / Couldn't load + Retry / No conversations found; stale strip; paging footer; pull-to-refresh only with rows; snapshot `inbox_v2` paint | logic verified · UI unverified | 2 |
| Paging `limit=50`, cursor, "all" keys omitted, legacy bare array, newest request wins, join an in-flight refresh, page-one replace vs prepend, revealed rows stay, open-thread row kept fresh | verified (logic) · UI unverified | 2 |
| Summary fetched on every refresh (newest wins, failure keeps badges) → nav badge | logic verified · UI unverified | 2 |
| List poll 60 s in front; frames coalesce 1.5 s; quiet refresh 2 s after a local patch | logic verified · UI unverified | 2 |
| Open-conversation key resolution (cache → `resolve` → `get`), toasts, offline retry on reconnect | logic verified · UI unverified | 2 |
| Keyboard stepping Alt+↓/↑ | missing | 9 |

## 4. Thread (`ThreadView.kt`, `ConversationsScreen.ThreadPane`, `MediaViews.kt`, `ThreadCall.kt`)

| Feature | Status | Cycle |
|---|---|---|
| Header: back (phone), avatar, name, handle line (mono phone / "Web chat" / hidden), 📞 "Call on WhatsApp" (7–15 digits), 👤 profile, ⋮ menu (actions, Ask Neema, Neema delivers, Invite, Activity log) | logic verified · UI unverified | 2 |
| Second row: Intercept badge AI/Human/Paused, "→ {agent}" (wide), 🔒 lock, sibling chips, inline actions on roomy tablets, pinned primary on phones | logic verified · UI unverified | 2 |
| `threadControls()` truth table (admin / agent-type / readonly × c1/c2/c3/c6/h) and the busy-lock rule | verified (logic; the truth table ported with its tests) · UI unverified | 2 |
| Footer: Composer when allowed; "🔒 Handled by …" banner; nothing for AI/paused | logic verified · UI unverified | 2 |
| Row builder: "N new messages" divider, post head card, hidden handoff events, first-escalation pill with default reasons, flag pill, live pills by kind, call pill + summary card ("Use as reply"), internal note card, albums (2+ images) | logic verified · UI unverified | 2 |
| Bubbles: inbound/AI/human colours, widths (75% / 65%, 520 / 360 dp), labels, quote strip (CUSTOMER / NEEMA / YOU + thumbnail), WhatsApp formatting (*bold* _italic_ ~strike~ `code` ```mono```), links, translation line, footer (time / Sending… / Not sent / ↩ Reply), swipe-to-reply ≥ 55 dp, failed line with Retry · Edit | logic verified · UI unverified | 2 |
| Body variants: public comment reply "↳", `[comment]` prefix stripped, media fallback card ("Recover from Meta"), unsupported type text, image (viewer, "Show image analysis"), sticker 120 dp, video poster + player, audio player (seek, mm:ss, transcript toggle, AI caption box), document tile, comment-post card (post-video fetch, "View on Facebook ↗") | logic verified · UI unverified | 2 |
| Dedupe/merge rules for live bubbles (same id, media echo 15 s, optimistic match, id-less 10 s / 120 s, inbound only by id, server page replaces `optimistic-`/`ws-` within 10 min, `live-evt-` yields) | verified (logic) · UI unverified | 2 |
| States: spinner, load error + Try again, "No messages yet", top progress bar, older-page spinner / retry / hint, deleted conversation toast | logic verified · UI unverified | 2 |
| Open-thread requests: messages (50), window, activity, latest-draft (human), translate preview, customer reach; per-person composer keys; 8 cached threads | logic verified · UI unverified | 2 |
| Actions + wording table: intercept / pick up / release / resume / pause / transfer / note / clear history / recover media / call / Ask / Answer / Invite / other-channel identity; 409 and unknown-result settling | logic verified · UI unverified | 2 |
| Live: silent reload 20 s, call frames reload 700 ms, window re-check 1 s, activity 60 s | logic verified · UI unverified | 2 |
| Scroll position per thread; auto-scroll within 2 rows / own bubble; `sortThread` 1 ms rule | logic verified · UI unverified | 2 |

## 5. Composer (`Composer.kt`)

| Feature | Status | Cycle |
|---|---|---|
| AI draft pill and panel (Edit/Preview, ✓ Send, Edit & send manually, Dismiss), "Generate AI draft" | logic verified · UI unverified | 2 |
| Quote strip (incl. cross-channel "REPLYING TO {CHANNEL}") | logic verified · UI unverified | 2 |
| Window strip: open / 24h closed (human agent for {left}) / closed reason, ticking per minute | logic verified · UI unverified | 2 |
| Translate pill + preview ("THEY WILL RECEIVE — {LANG}") with 700 ms debounce | logic verified · UI unverified | 2 |
| Lost-files note after process death | partial — the restore is `InboxMemory`'s; the note itself lands in cycle 3 | 3 |
| Box row: attach menu (Camera / Photos & videos / Document), 44–132 dp box, placeholders, send button rules, hardware-keyboard rules | logic verified · UI unverified | 2 |
| Media tray: thumbnails, captions, per-file errors, add-more, Send N / Retry N / Cancel, "Images up to 5 MB each" | logic verified · UI unverified | 2 |
| Outbox: optimistic bubble, translate step, reply body keys, `{ok:false,error}` = not delivered, refused vs no-answer (2 / 8 / 20 s reconcile), 401 hold + auto-resend after re-auth, Retry checks, Edit, restore after death | verified (logic) · UI unverified | 2 |
| AI drafts: latest-draft, generate (toasts incl. held toast), approve (null = server's draft), `ai_draft_ready` frame | logic verified · UI unverified | 2 |
| Attachments: sources (camera, picker, documents, drop), allowed MIME list, size limits, JPEG re-encode ladder (2048 px, q 85→40), sequential upload with per-file toasts, unknown-result check, 401 keeps the file | logic verified · UI unverified | 2 |
| No template picker, no voice-note recorder, no reactions/edit/delete/mark-unread (parity = also absent) | n/a | — |

## 6. Dialogs, sheets, viewers

| Feature | Status | Cycle |
|---|---|---|
| Transfer (available agents minus assignee, "{n} active conversations"), Add Note, Clear Chat History, Ask Neema, Neema delivers, Invite to WhatsApp (phone prefill, 7–15 digits) — all with the exact strings; Ask/Answer/Invite remember their thread | logic verified · UI unverified | 2 |
| Viewer: image pinch 1–5×, double-tap 2.5×, video player, album pager "{i} / {n}" | unverified | 2 |
| Activity log pane/sheet with kind-coloured dots and the empty line; collapsed rails ACTIVITY (20+) / CUSTOMER | unverified | 2 |
| Phone bottom sheets "Customer Profile" / "ACTIVITY LOG"; tablet `SideSheet` (28% scrim, 220/180 ms) and `AdaptiveSheet` (< 600 dp sheet, else 440 dp end panel) | partial — the phone sheets and the tablet `SideSheet` are in; `AdaptiveSheet` (the 440 dp end panel) is cycle 3 | 3 |

## 7. Customer panel (`feature/conversations/customer/*`)

| Feature | Status | Cycle |
|---|---|---|
| Placement (docked / slide-over / sheet; reused in Calls as `call:{id}`), one model per conversation, load `GET /admin/customers/{key}?channel=` + production enquiry + pipeline stages, quiet 400 ms reloads on the listed triggers, hidden = silent, failure banners (three wordings) + Retry, pull-to-refresh | logic verified · UI unverified | 2 |
| Hero: avatar, name (+ ✓), flag + phone, stage pill, country chip, lead score bar, tier badge + tooltips, cadence / Overdue, channel chips, Invite chip, "+N merged", Call button (WhatsApp green / Messenger #0066D6), "Send template" | logic verified · UI unverified | 2 |
| Quick stats; tabs PROFILE · INSIGHTS · ACTIVITY with every section and string (contact fields, ad ref, parish, pipeline stepper + admin custom stages, tags, notes with 3-way merge note, cross-channel identity + merge form + suggestions, purchase summary, buying rhythm, top products, score breakdown, recent orders incl. hub-linked line, channel history) | logic verified · UI unverified | 2 |
| Pinned footer: made-to-order request (push / dismiss / not pushable) and quick actions (Mark Won / Lost / Advance Stage) | logic verified · UI unverified | 2 |
| CALLS section: 3 recent calls (wa_id + psid), permission lines, Send call request flow (138009 / template_required / errors), live frames | partial — the section renders (`CustomerCallsView`: recent calls, permission lines); the call-request flow and the live frames land with the softphone | 5 |
| Call button decision + "call on WhatsApp instead" sheet (Messenger off / Instagram), composer prefill question | missing | 5 |
| PATCH bodies per field, age rule, stage, tags, notes + `notes_base`, custom stages PUT, merge / unmerge, push / decline enquiry, invite, template, Ask / Answer (panel wording), save-failure wording and rollback rules | verified (logic) · UI unverified | 2 |

## 8. Calls — softphone (`feature/calls/CallManager.kt`, `WebRtcMedia.kt`, `CallStage.kt`, `CallAlert.kt`)

| Feature | Android mechanism | iOS plan | Status | Cycle |
|---|---|---|---|---|
| `CallManager` rules: phases (Idle, Ringing, Placing, RingingOut, Connecting, InCall, Ended), `CallUiState`, outcomes, derived `who/number/chatKey/app/live/routeChoice`, phase side effects, timers (12 s cooldown, 90 s freshness, 120 s ring timeout, 2.5 s ICE cap, 60 s mic prompt, 10 s ICE grace, 20 s connect guard, 8 s answer wait, 1.8 s error, 1.5 s permission cap, terminate/callback retries 2 s / 5 s, 3 s sign-out wait) | Kotlin with ports (`CallApi`, `CallPeer`, `CallMedia`, `CallRinger`, `CallAudio`) | `NeemaCore/Calls/CallManager.swift` with the same ports, tested on Linux with fakes (the 59 CallManager tests ported) | verified | 5 |
| Inbound WhatsApp: ring (frame or poll), answer (ice-config + offer, mic, non-trickle ICE, `POST answer`), failure table (409 answered elsewhere, 410/404 missed, mic blocked, status 0 back to Ringing, unconfirmed answer 8 s), decline, call back later, colleague answered, caller hung up, end | same | same | verified (rules, Linux) | 5 |
| Inbound Messenger: reversed SDP (we offer, Meta answers, renegotiation applied and never sent), `media_update` highest version only, held until ready | same | same | verified (rules, Linux) | 5 |
| Outbound WhatsApp: permission read (1.5 s cap), PermissionNeeded/Requested without connect, offer, `POST connect`, placed-row lookup on timeout (2 × 3 s), `call_status` → RingingOut, `outbound_answer`, outcomes, refusals (409 / action / 502 code) | same | same | verified (rules, Linux) | 5 |
| Outbound Messenger (never retried, never looked up) | same | same | verified (rules, Linux) | 5 |
| Resilience: 10 s reconnecting, FAILED/CLOSED rules, connect guard, hang-up retries, resync on reconnect/foreground, audio-failure inline errors | same | same | verified (rules, Linux) | 5 |
| Second caller: waiting banner, Decline / Call back later / End & answer, re-check after the live call ends | same | same | verified (rules); banner unverified | 5 |
| Permission requests (`request-permission`), responses (already_permitted, 138009 / request_limit with `request_available_at`, template_required + admin link), `call_permission` frame → card + grant banner, caution at `unanswered_streak ≥ 2` | same | same | verified (rules); banner unverified | 5 |
| Sign-out mid-call (`endForSignOut`) | same | same (`AppModel.logout` waits for it) | verified (rules) | 5 |
| Outcome → card table (status line, note, actions, auto-close times, icons, tint) and every other string on the card (§4.5 of the calls audit) | `CallStage.kt`, `CallWords.kt` | `Views/Calls/CallCard.swift` + `NeemaCore/Calls/CallState.swift` (strings tested on Linux) | verified (strings); card unverified | 5 |
| Call card UI: WhatsApp dark surface, 120/88 dp avatar with pulse rings (reduced motion), Messenger ring, landscape split, per-phase controls, audio route menu, minimised bar, waiting banner, grant banner, tablet docking 420 dp + auto-open chat | Compose | SwiftUI (`CallCard.swift`, `CallDockHost` in the shell) | unverified (compile-only; the gallery shows no live call) | 5 |
| WebRTC: audio only, Unified Plan, ICE servers from ice-config (string or list urls), constraints (AEC/NS/AGC/highpass), `OfferToReceiveAudio`, gathering cap 2.5 s, event mapping, guarded callbacks, closed-peer safety | `io.github.webrtc-sdk:android` | `WebRTC` SPM binary (stasel/WebRTC M155) in `project.yml`; `App/WebRTCMedia.swift` over `RTCPeerConnection` behind the `CallPeer` port (audio only, Unified Plan, ice-config servers, the constraints, non-trickle gathering, guarded callbacks, closed-peer safety); without the framework `DeviceCallMedia` ends the call honestly | unverified (linked and compiled on macOS CI; no call's audio has flowed on a device) | 6 |
| Audio: `MODE_IN_COMMUNICATION`, focus, routes (earpiece / speaker / wired / Bluetooth), route rules ("never the loudspeaker while an earpiece exists"), mute | `AndroidCallAudio` | `SessionCallAudio`: `AVAudioSession` `.playAndRecord` / `.voiceChat`, the routes from the session's ports, `overrideOutputAudioPort` / `setPreferredInput`; the route rules live in `CallManager` (verified) | unverified (device code) | 5 |
| Ringing: ringtone loop + vibration pattern, Profile switches, mute never applies | `CallAlert` | `CallKitRinger`: in front the system alert tone every 2 s; in the background CallKit rings the device's ringtone; the two switches cannot be honoured exactly | platform-restricted (implemented) | 5 |
| Incoming-call notification (`CallStyle`, full-screen intent, Answer / Decline actions, 120 s timeout), lock-screen takeover (`setShowWhenLocked`, `setTurnScreenOn`), `USE_FULL_SCREEN_INTENT` readiness banner | `CallAlert`, `CallStage` | CallKit `CXProvider` / `CXCallUpdate` / `CXAnswerCallAction` / `CXEndCallAction` / `CXCallEndedReason` in `CallKitRinger`, Answer / Decline into `handleAction`; no full-screen-intent concept | platform-restricted (CallKit replaces all of it; unverified on a device) | 5 |
| Calls to a closed app (foreground service keeps the socket) | `LiveService`, `BootReceiver`, `START_STICKY` | PushKit VoIP pushes + `reportNewIncomingCall`; needs backend APNs + token endpoints | **blocked** (backend + Apple push credentials) — documented in §24 | 5 (client side) |
| Mic permission: prompted mid-answer, MicBlocked outcome, 60 s timeout | `CallMicHost` | `CallMicHost` asks `AVAudioSession.requestRecordPermission` when the softphone raises `micRequest`; the 60 s timeout and MicBlocked are the core's (verified); a CallKit answer from the lock screen cannot prompt | partial (asked mid-answer as Android; onboarding prompt is cycle 7's) | 5/7 |
| Local two-sided recording (16 kHz mono, AAC-LC 32 kbps `.m4a`, ≥ 2000 bytes), upload queue (10 files, 3 days, oldest first, transient vs permanent errors), raw-file sweep | `CallRecorder`, `RecordingOutbox` | `RecordingOutbox` (queue, drain, prune, transient vs permanent) ported and verified; `startRecording` returns nil — no public sample hook in the iOS WebRTC SDK; Meta transcription stands in | platform-restricted (capture); verified (queue) | 5 |
| Transcripts, insights, voicemail badge, follow-ups (`follow-up-done`) | REST | same | verified (rules); UI unverified | 5 |

## 9. Calls — console, details, transcript, settings card (`CallsScreen.kt`, `CallsViewModel.kt`)

| Feature | Status | Cycle |
|---|---|---|
| Header "Calls" + "WhatsApp [and Messenger] voice calls · N total"; chips All / Follow-ups (N) / app chips; restriction banner; readiness banners (notifications → background → battery → full screen; one at a time) | unverified (gallery-rendered); the notifications and microphone banners port, background / battery / full-screen are platform-restricted (none on iOS) | 5 |
| States: 4 skeleton rows, load error + Retry, empty copy, follow-ups empty copy, stale "Showing the last call log" | unverified (compile-only; the rules behind them verified) | 5 |
| Rows under TODAY / YESTERDAY / date: avatar, who, channel badge, direction icon + outcome word + " · m:ss · Agent" + " · Follow up", Voicemail badge, HH:mm, transcript button, call-back button | unverified (gallery-rendered; words verified) | 5 |
| Load 60 s in front; 500 ms after call frames; reconnect / foreground / pull; `call_update` merged in place; 50 newest (follow-ups filter client-side, as Android) | verified (`CallsViewModelTests`, `CallLogLiveTests`) | 5 |
| Details: Close, "{word} · m:ss · date", voicemail line, timeline (Rang / Called by / Answered by / On the call now / Ended), recording line variants, INSIGHTS, transcript panel (strings, 5 s polling, error table), player (play/pause/seek, "Couldn't play the recording."), Call back / Open chat / Mark follow-up done, history line, embedded customer panel; tablet ≥ 840 dp side-by-side with newest auto-opened | unverified (UI); transcript rules and `detailsPick` verified | 5 |
| Deep-link focus `?view=calls&caller=` + "No calls with this customer yet — showing the full call log." | verified (rules) | 5 |
| Settings → WhatsApp calling card (controls, validation strings, changed-fields POST, `call_settings` frame, template status lines, "Saved — customers may take up to 7 days…") | missing | 4 |
| Recording playback (`recording_url` without auth header) | `AVPlayer` in `RecordingPlayer`; `/api/admin/media/*` access still to confirm on a device | unverified | 5 |

## 10. Notifications and alerts (`core/notify/*`, `app/ShellParts.kt`)

| Feature | Android | iOS | Status | Cycle |
|---|---|---|---|---|
| Notification frames → bell entries (last 60 persisted, 3 s exact-repeat drop), in-app toast when in front, tray row in background per Profile switch, tap → conversation / Orders / app | `NotificationCenter` | `NeemaCore/Notify/AgentNotifications.swift` + `SystemAlertSink` (`UNUserNotificationCenter`) while the app runs | verified (rules, 38 tests); the tray unverified | 5 |
| Customer messages: beep + buzz (2 s gate), tray row per customer (title name / phone / "{App} customer", body text or media words), cleared on foreground, DND/silent rules | `MessageAlerts`, `DeviceAlertPlayer` | `MessageAlerts` + `SystemAlertPlayer` (`AudioServicesPlaySystemSound`, the vibrate sound id) + the sink | verified (rules); DND / vibrate-mode detection platform-restricted | 5 |
| Channels (alerts, messages, updates, calls, live) and their importance | `Notifier.createChannels` | `UNNotificationCategory` + interruption levels | platform-restricted (no channels UI; categories instead) | 5 |
| Per-type table (channel, content, tap, switch, beep, side effects) | `NotificationCenter.alertFor` | `AgentNotifications.alertFor` | verified | 5 |
| Mute (1 h / 8 h / until), status strings, never silences calls | `AppPrefs`, `MuteControl` | same (`AppPrefs.muteFor`, the bell panel's menu) | verified (rules); menu unverified | 5 |
| Profile switches (`notif_*`, defaults), Sounds & vibration switches, "Try the message alert" | `ProfileScreen` | same (vibrate switches map to haptics) | missing | 5/6 |
| Background delivery when the app is closed | `LiveService` foreground service | APNs alert pushes (backend) | **blocked** (backend) | — |
| "Stay connected in background", battery link, boot receiver, live-connection notification | Android only | none | platform-restricted (dropped; documented in Profile copy) | 5 |

## 11. Orders (`feature/orders/*`)

| Feature | Status | Cycle |
|---|---|---|
| Shared `dash.orders` (snapshot + 90 s poll), ScreenLife catch-up, SingleFlight reads, `initialLoading`, no gate, server order kept | logic verified · UI unverified | 2 |
| Layout by width (< 600 sheet / 600–840 side sheet 440 / ≥ 840 pane 440; compact rows < 480 dp) | logic verified · UI unverified | 2 |
| Header "Orders", "{n} total · {pending} pending" / Loading… / Not loaded, revenue card (always KES) | logic verified · UI unverified | 2 |
| Status cards Pending / Confirmed / Delivered / Cancelled (tones, counts, revenue, columns rule, toggle filter) | logic verified · UI unverified | 2 |
| Search "Search by name or phone…" (name, raw wa_id, id), filter chip "{Label} ✕" | logic verified · UI unverified | 2 |
| List body precedence (stale banner, spinner, error, "📦 No orders found", rows), client-side pagination 15/page with "Showing a–b of n" and the windowed pager | logic verified · UI unverified | 2 |
| Row: avatar, name ("Unknown"), channel pill (colours, glyphs), status badge (hub state first, mapping table), hub chip / "not in hub", "Open in hub ↗", "push failed" badge + toast, phone line, items summary "·  name ×qty +N more", time ago, amount + currency, spinner; compact 4-row layout | logic verified · UI unverified | 2 |
| Detail: title bar, customer box, meta grid (ORDER ID last 8 / DATE / CHANNEL / CURRENCY), HUB section (payment, push, PUSH FAILED box, links, Copy link), ITEMS (unit × qty, "× qty" when unpriced, "No items recorded", Total), NOTE box, Open conversation, status moves with primary/danger buttons | logic verified · UI unverified | 2 |
| Line maths (`effectiveQty/Unit`, `lineTotal`, amount = subtotal) | verified | 2 |
| `updateStatus`: one at a time, PATCH `{status}`, refetch, close, toast "Order marked as {status}"; failure table (404, may-have-happened reconcile, session expired silent, else) | verified (logic) · UI unverified | 2 |
| Pull / Retry / Back rules; selected row vanishing; restore after death (filter, search, page, selected, scroll) | logic verified · UI unverified (SceneStorage "orders.ui") | 2 |

## 12. Catalog (`feature/catalog/*`)

| Feature | Status | Cycle |
|---|---|---|
| Read-only; `view_catalog` nav gate; snapshot + 5-min poll; audit on init; catch-up on re-show; pull loads both; local filtering | logic verified · UI unverified | 2 |
| Price audit banner (heading rules, subtitle, table, per-piece paragraph with "KES ?") | logic verified · UI unverified | 2 |
| Header counts ("{total} items · {inStock} in stock · {out} out of stock"), source banner copy | logic verified · UI unverified | 2 |
| Search (name / SKU / aliases), category dropdown with emojis (list + aliases + 📦 default), wide side-by-side | logic verified · UI unverified | 2 |
| Grid columns (2/3/4/6 by width, ≥ 118 dp × fontScale), equal-height rows, cards (image → emoji gradient fallback, stock badge "{qty} left" / IN / OUT, description, price or range, "{n} variants", alias chips, SKU, "#id") | logic verified · UI unverified | 2 |
| Detail sheet (96 dp thumb, "{emoji} {category}", price + "per unit" + "KES x · $y", variants table, USD format, aliases, type, Updated, hub lock line), live row tracking | logic verified · UI unverified | 2 |
| States: LoadProblem "Couldn't load the catalogue", "📦 No items found"; persistence of filter/search/audit/open product/scroll | logic verified · UI unverified (SceneStorage "catalog.ui" / "catalog.product") | 2 |

## 13. Deals (`feature/deals/*`)

| Feature | Status | Cycle |
|---|---|---|
| Layout (#F6F7F2, max 1100 dp, 3 columns ≥ 840 dp), loading (3 parallel reads, partial failures keep data, 60 s poll, catch-ups, `planned_action` / `hub_event` 800 ms, pull, Retry), header counts | logic verified · UI unverified | 2 |
| Planned actions queue (header, empty states, row lines with `fmtDue`, buttons Send / Edit & send / Veto / Open chat, busy states) | logic verified · UI unverified | 2 |
| Board columns New / Qualified / Proposal (others under New), deal card (name link, liveAgo, title, ⛔ blocking, "→ Neema/You · due", 📌 guidance, Guidance / Won / Lost), guidance editor (400 chars) | logic verified · UI unverified | 2 |
| Draft dialog (title, reason, placeholder, button labels by state) | logic verified · UI unverified | 2 |
| Send / Veto / Won / Lost / Guidance endpoints and the full failure wording incl. the 4 × 10 s settle loop | verified (logic, incl. the settle loop) · UI unverified | 2 |
| UI persistence (editing, guidance, draftFor…) | unverified (SceneStorage "deals.ui") | 2 |

## 14. Leads (`feature/leads/*`)

| Feature | Status | Cycle |
|---|---|---|
| `Lead` model (LenientTagsSerializer comma-split, `leadScore` clamp, `handle`), `BuyingRhythm`, `LeadEdit`, `diffLead` | verified | 2 |
| Loading (stages + leads, quiet re-reads, pull, Retry, one read at a time, `overlayLocal`) | logic verified · UI unverified | 2 |
| Stages: canonical 7 + custom (yellow) with the colour table; case-insensitive matching | logic verified · UI unverified | 2 |
| Header "Leads Pipeline", "{n} leads · Pipeline KES … · Won KES …", search box | logic verified · UI unverified | 2 |
| Stage pills with counts; board columns (~260 dp + 0.35 peek), column totals, "No leads" | logic verified · UI unverified | 2 |
| Lead card (avatar, name/Unknown, mono phone, score + bar colours, channel icons, spent, tags, liveAgo, ← / → move buttons) | logic verified · UI unverified | 2 |
| Detail sheet (480 dp, stage chips, tags field, notes, stats box + facts line, Save/Cancel, dismiss keeps draft) | logic verified · UI unverified | 2 |
| Card move (optimistic, failure table incl. may-have-happened read), sheet save (changed fields only, `notes_base`, `editLanded` after an uncertain outcome) | verified (logic) · UI unverified | 2 |

## 15. Analytics / Overview (`feature/overview/*`)

| Feature | Status | Cycle |
|---|---|---|
| Requests (stats, attribution, human feed 10, fallback 50), 30 s poll, catch-ups, coalesced reloads on the listed notification types and `intercept_changed`, pull also re-reads orders/agents/catalog | logic verified · UI unverified | 2 |
| Header, "Refreshing…", stats-failed LoadProblem ("Live figures unavailable — showing an estimate") | logic verified · UI unverified | 2 |
| Stat cards (3/2/1 columns, accent strip, icon tile, auto-shrink figure, pulsing placeholder): six cards with their sub-lines | logic verified · UI unverified | 2 |
| "WHERE SALES COME FROM" (table on wide, cards on phone), "7-DAY REVENUE (KES)" bars (tap tooltip), "ORDER STATUS", "BY CHANNEL", "RECENT ACTIVITY" (8), "TOP PRODUCTS BY REVENUE" (5), wide layout ratios | logic verified · UI unverified | 2 |
| Overview maths (port `OverviewMathTest`) | verified | 2 |

## 16. Reports (`feature/reports/*`)

| Feature | Status | Cycle |
|---|---|---|
| Full unpaged `GET /admin/conversations` on the 10-min client (bare array or `{items}`), once per visit, built off-main, midnight rollover | logic verified · UI unverified | 2 |
| States and reasons (timed out / cut off / incomplete / permission), refresh-failure toast | logic verified · UI unverified | 2 |
| Header, range dropdown (7 / 30 / 90 / custom with two date buttons), Export CSV, tabs Overview / Conversations / Orders / Agents | logic verified · UI unverified | 2 |
| Overview stat boxes, mini bars (14), order-status breakdown; tables on wide / cards on phone with the column sets and row caps | logic verified · UI unverified | 2 |
| CSV export (RFC 4180, `.part` file, share sheet "Export report", toasts, failure wording) | `UIActivityViewController` | logic verified · UI unverified (the share sheet; Android's share-target-missing failure has no iOS twin) | 2 |
| Report maths and rollover (port `ReportMathTest`, `ReportsRolloverTest`) | verified | 2 |

## 17. Team (`feature/agents/*`)

| Feature | Status | Cycle |
|---|---|---|
| Data (agents + roles, load on open, re-read on re-show, pull waits for both, failure wording), header "{N} agents · {N} online", Add Agent / New Role | logic verified · UI unverified | 2 |
| Tabs "Agents (N)" / "Roles (N)", agent grid (1–3 columns by 332 dp), agent card (presence, badges, pills, footer switch + Role / Edit / Reset password / Remove), roles list + role card | logic verified · UI unverified | 2 |
| Seven dialogs with their exact copy, requests and toasts (Add, Edit, Reset Password, Remove, Assign Role + PermissionPicker, New/Edit Role with 12 swatches, Delete Role) | logic verified · UI unverified | 2 |
| Validation and conflict toasts, write handling (one at a time, verifying re-read, 404 = removed by someone else), fixed `role_<ms>` id | verified (logic) · UI unverified | 2 |
| Saved state (no passwords) | verified (logic) · UI unverified (SceneStorage "team.ui" / "team.tab" / "team.dialog") | 2 |

## 18. Settings (`feature/settings/*`)

`SettingsViewModel` + `CallingSettingsModel` (NeemaCore `Settings/`), `SettingsScreen` + `OfferCard` + `CallingSettingsCard` (SwiftUI). The logic is pinned by the 83 ported settings tests on Linux (Android's 76, plus the server-route check, the crash list's contract, the Business/AI waits and the rules on their own); the screen compiles on the macOS job and is in the gallery.

| Feature | Status | Cycle |
|---|---|---|
| Layout (two columns ≥ 720 pt), per-card independent loads with LoadProblem + Retry, pull-to-refresh, re-read on return skipping dirty cards | verified (loads, retries, refresh, the dirty-card rule: `SettingsViewModelTests`, `SettingsNetworkTests`); layout unverified (compiles; gallery) | 4 |
| Standing Orders (directives, counter, save toasts incl. `UNCERTAIN_SAVE`, the box locked until the real text arrives) | verified via `SettingsViewModel` | 4 |
| Translation (status, spend line, optimistic switch, toasts, off note) | verified via `SettingsViewModel` | 4 |
| Offer (status, notes, fields, categories chips from the catalogue, SKU picker, date pickers, validation list, save toasts, End confirmation) | verified (rules, bodies, toasts, verify-after-no-answer); the pickers and date sheets unverified (compile only) | 4 |
| Pipeline stages (preview, chips, add with 18-char counter, limit 4, toasts) | verified via `SettingsViewModel` | 4 |
| Business / AI Configuration / Integrations / Danger Zone (local-only cards with their copy and fake saves) | verified (local-only here too: `testLocalCardsNeverCallTheApi`, the 600 ms waits) | 4 |
| WhatsApp calling card (see §9): only-the-diff save, field checks before sending, Meta's words on a refusal, `call_settings` reload unless dirty, the template | verified via `CallingSettingsModel` (7 tests); the hours editor unverified (compile only) | 4 |
| App crash reports card (`GET /admin/client-crashes?limit=20`, expand, Copy report) | verified (the list's contract and 403); the card unverified. Wording: "When the app closes…" rather than Android's "the Android app" — the server lists every phone's reports once iOS reports too (cycle 7) | 4 |
| Saved state (`saveUi`, secrets never saved; a restore once per model) | verified via `SettingsLifecycleTests` (7) | 4 |

## 19. Profile (`feature/profile/*`)

| Feature | Status | Cycle |
|---|---|---|
| Data (me + team row), states, pull | logic verified · UI unverified | 2 |
| Profile card (avatar, role badges, email, Joined · Last active, Edit form FULL NAME / EMAIL / DEPARTMENT, PATCH me, toasts) | logic verified · UI unverified | 2 |
| Stat tiles (Active chats / Status with "Seen {ago}" / Permissions n/20), Availability toggle (optimistic PATCH, toasts) | logic verified · UI unverified | 2 |
| Password change (min 8, confirm, masking, no-answer wording) | logic verified · UI unverified | 2 |
| Appearance (Dark Mode), Notifications switches, Sounds & vibration, Your Permissions grid (20), Account (Settings link, "App version", Sign out confirm) | logic verified · UI unverified — "Stay connected in background" and the battery link are platform-restricted (dropped: no foreground service; background delivery is the cycle 5 / blocked push path); "System notification settings" opens the app's page in iOS Settings | 2 |

## 20. Crash reporting (`core/crash/*`)

| Feature | Android | iOS | Status | Cycle |
|---|---|---|---|---|
| Uncaught handler → `files/crash/<ms>-<kind>.json` (max 10), `last.txt`, `last-fatal.txt`, non-fatals, 48k trace cap | `CrashVault` | `NeemaCore/Crash/CrashVault.swift` (the file rules) + `App/CrashHandlers.swift` (`NSSetUncaughtExceptionHandler` and the fatal signals); MetricKit not read | verified (file rules, `CrashTests`); handlers unverified | 7 |
| `POST /admin/client-crashes` body `{id, at, kind, thread, summary, trace, app_version, build, device, sdk}`; sent at start, sign-in, after a non-fatal; oldest first; stop at first failure | `CrashReporter` | `NeemaCore/Crash/CrashReporter.swift`, the same body (`sdk` = the iOS major version) | verified (`CrashTests`) | 7 |
| Next-launch "Neema closed unexpectedly" dialog (Share / Copy / Close) | `CrashNotice` | `CrashNoticeView` (a sheet with ShareLink, Copy, Close) over `RootView` | unverified | 7 |
| Native tombstones / ANR decoding | `TombstoneText`, `ApplicationExitInfo` | MetricKit diagnostics (not read yet) | platform-restricted | 7 |

## 21. Local persistence

| Android | iOS | Status | Cycle |
|---|---|---|---|
| Encrypted `neema_session` | Keychain (`KeychainStore`, `AfterFirstUnlockThisDeviceOnly`; SECURITY_CHECKLIST §1) | unverified (device code; the store rules verified) | 1/7 |
| `neema_prefs` (theme, background_live, alert_*, notif_*, asked_post_notifications) | `UserDefaults` (`background_live` dropped) | verified (`AppPrefs`; `notif_*` through the profile model) | 2 |
| `neema_notifications` (last 60) | `UserDefaults` (`AgentNotifications`, key `neema_notifications.items`) | verified | 5 |
| `neema_crash` | `Application Support/crash` (`CrashVault`) | verified (file rules) | 7 |
| Snapshots `cacheDir/snapshots/<hash>_<key>.json` (me, agents, orders, catalog, inbox_v2, inbox_memory_v1) | `Caches/snapshots/` (raw response text) | verified (`SnapshotCache`) | 2 |
| Crash files, report CSVs, camera captures (FileProvider) | `Application Support/crash`, `Caches` + the share sheet, the picker's own files | verified (crash, CSV); captures unverified | 2/7 |
| SavedState / `rememberSaveable` keys | `@SceneStorage` + Codable UI state | missing | 3 |

## 22. Design tokens, typography, icons (`core/ui/theme/*`)

| Feature | Status | Cycle |
|---|---|---|
| `NeemaColors` light/dark (20 tokens), Brand (9), Tones (5 × light/dark), Chrome, ChannelColors (+ gradients), Palette ramps (Moss, Willow, Prussian, Sage, Stone, Gray, Slate, Pewter, Amber, Red, Emerald, Green, Blue, Violet, Purple, area literals, pipeline chips, avatar palette) | unverified — the dim tokens, chrome inks and tones added; `Palette` carries every literal the ported screens use | 1/3 |
| Typography: Manrope 400–800, DM Mono 400/500, type scale (headlineSmall 22 EB … labelSmall 11 SB), `TabularNums`, `scaledAtMost` caps | fonts bundled; `Font.custom` scale | unverified — `NeemaFont.manrope` (scales), `.fixed`, `.capped(_:maxScale:)` (Android `scaledAtMost`), the ten-step type scale | 1/3 |
| Spacing (16 / 24 page, 14 / 16 / 20 card, 48 dp targets), corner radii table (4–18) | tokens | unverified — the ported screens use the web's values in points | 3 |
| Icons: `WebIcons` (heroicons paths), `OverviewIcons`, Material icons | SF Symbols equivalents (+ custom paths for brand glyphs) | unverified — `WebIcons` (the heroicon paths, stroked) across the chrome and the login; `OverviewIcons` and `ChannelIcons` for the panels and brand marks; SF Symbols remain where the web has no icon of its own | 3 |
| Shared components: Avatar (initials / person glyph / image, 10-hue palette), ChannelChip, Pill, Loading, EmptyState, ErrorState, Panel, SectionTitle, StatTile, SearchField, FilterChips, ConfirmDialog, CountBadge, LoadProblem, StaleBanner, InlineError | `Views/Components/*` | unverified — `AvatarView`, `ChannelCodeChip`, `TeamPill`, `LoadingView`, `EmptyStateView`, `ErrorStateView`, `PanelCard`, `SectionLabel`, `StatTile`, `CompactSearchField`, `WebBtn` / `TeamBtn`, `FormSheet`, `AmberBadge`, `LoadProblem`, `StaleBanner`, `InlineError`, `AdaptiveSheet` | 2/3 |
| Adaptive rules: `THREAD_MIN 480`, `TWO_PANE_MIN 801`, `DOCKED_NAV_MIN 1200`, `navModeFor` (<600 drawer / <1200 rail / docked), `inboxPanes`, `LocalContentWidthDp` | `NeemaCore/Shell/Adaptive.swift` | verified (`Adaptive.swift`, `AdaptiveTests`) · the shell uses `navMode(for:)`, the inbox `inboxPanes` | 3 |
| Screenshot goldens (Paparazzi, 173+ call PNGs, inbox 141…) as visual references | snapshot tests on macOS CI in a later cycle | partial — a screenshot gallery renders the sign-in screen and every view (phone light/dark, iPad) on the macOS job into the `ios-screenshots` artifact; comparison against Android's goldens is cycle 9 | 3/9 |

## 23. Endpoint coverage (81 endpoints the Android app calls)

Every path, query name and body below exists in `Api/NeemaApi.swift` unless the row says otherwise. "wrapper" = also needs the feature-level wrapper the Android screen uses.

| # | Endpoint | NeemaCore | Screen use | Cycle |
|---|---|---|---|---|
| 1–25 | Inbox / conversations (list page, unpaged list, summary, resolve, get, messages, clear, activity, intercept, release, pause, transfer, reply, translate-reply, approve-draft, latest-draft, generate-draft, note, window, upload-media, recover-media, post-video, ask, answer, whatsapp-invite) | all present (`InboxApi`'s `+` query encoding to mirror in the inbox wrapper) | verified via `InboxViewModel` | 2 |
| 26–33 | Customers / CRM (get, patch, merge_suggestions, merge, unmerge, production enquiry, push, decline) | present (`CrmApi`) | verified via `CustomerViewModel` | 2 |
| 34–35 | Orders list, patch | present | verified via `OrdersFeed` / `OrdersViewModel` | 2 |
| 36–37 | Catalog list, audit | present | verified via `CatalogFeed` / `CatalogViewModel` | 2 |
| 38–42 | Deals list/patch, actions list/approve/veto | present | verified via `DealsViewModel` | 2 |
| 43–44 | Leads list, patch | present (`LeadsApi`) | verified via `LeadsViewModel` | 2 |
| 45–49 | Settings directives / pipeline-stages / translation / offer | present | verified via `SettingsViewModel` (+ `CustomerViewModel`, `LeadsViewModel` for the stages) | 4 |
| 50–51 | Client crashes list, post | present (`api.crashes.list/report`) | list verified (contract, 403); the card reads it; the reporter posts in cycle 7 | 4/7 |
| 52–62 | Me, agents, roles | present | verified via `TeamViewModel` / `ProfileViewModel` (+ `TeamApi`) | 2 |
| 63–64 | Stats, attribution | present | verified via `OverviewViewModel` | 2 |
| 65–81 | Calls (list, get, permission, request-permission, follow-up-done, ice-config, channels, offer, answer, connect ×2, terminate, callback, transcript, transcribe, recording, settings, permission-template) | present | verified (`CallApiContractTests`, the console and settings tests) | 5 |
| — | Auth: agent-auth/login, auth/login, csrf, callback/credentials, session, agent-auth/refresh, auth/refresh | present | verified | 1 |
| — | `GET /api/health` (not used by Android) | — | — | — |

**Route coverage (cycle 4).** `RouteCoverageTests` reads every `http.get/post/put/patch/delete`, `http.raw` and `http.multipart` call in NeemaCore's sources and matches it, method and path, against the server's route table (`ServerRoutes.swift`, generated from `apps/api/app` by `apps/ios/scripts/server_routes.py`): 89 distinct client calls (102 call sites), all served; the 14 admin routes neither app calls are the web's own (ai-cost, analytics/message-rollup, customers identities, demand, identities/health, media, parishes, recovery/preview, settings/proposals, conversations close, media/download, meta/backfill-profiles, posts product).

## 24. WebSocket frame coverage

| Frame | Consumers on Android | iOS status | Cycle |
|---|---|---|---|
| `new_message`, `message` (legacy) | inbox row patch + thread bubble + alerts | verified (inbox rows and bubbles, `MessageAlerts`) | 5 |
| `intercept_changed` | inbox row + live pills; Overview | verified (inbox, Overview) | 2 |
| `ai_draft_ready`, `translations`, `history_cleared` | thread | verified | 2 |
| `notification` (13 types + legacy) | bell, toast, refetches, tray | verified — the orders feed (`order_update`), Deals (`planned_action`, `hub_event`), the Overview's reload list, the bell and the tray (`AgentNotifications`); the in-front toast is the bell's row + the sound | 5 |
| `incoming_call`, `outbound_answer`, `call_answered`, `call_status`, `media_update`, `call_ended`, `call_update`, `call_permission`, `calling_restricted` | CallManager, console, panel, thread | verified — `CallManager` (every frame, `CallManagerTests` / `CallLifecycleTests`), the console (`CallLogLiveTests`), the thread's call pill and the customer panel's calls | 5 |
| `call_settings` | Settings calling card | missing | 4 |
| `pong` | dropped | verified | 1 |

## 25. Platform-restricted items and backend gaps (carried every cycle)

| Item | Why | What iOS does instead | Owner |
|---|---|---|---|
| Alerts and calls while the app is closed | Android keeps the socket open with a foreground service; iOS suspends sockets in the background | APNs alert pushes for notification frames and **PushKit VoIP pushes** for `incoming_call` / `call_answered` / `call_ended`; a device-token register/unregister endpoint tied to sign-out; server-held per-agent notification preferences. The iOS client will ship the registration + CallKit wiring; without the backend it cannot ring a closed app. | backend + Apple push key (**blocked**) |
| Universal Links for `https://neema.bethanyhouse.co.ke/dashboard*` | needs `/.well-known/apple-app-site-association` on the host and the associated-domains entitlement | custom scheme `neema://` works without it | host nginx + Apple team id (**blocked**) |
| Signing, TestFlight, App Store | needs an Apple Developer team and certificates | CI builds for the simulator unsigned (`CODE_SIGNING_ALLOWED=NO`) | owner (**blocked**) |
| Full-screen incoming-call takeover, `USE_FULL_SCREEN_INTENT`, show-when-locked | CallKit owns the lock-screen call UI | CallKit | n/a |
| "Stay connected in background", battery-optimisation prompts, `BootReceiver`, ongoing "Neema is connected" notification | no equivalent | dropped; Profile copy explains that pushes carry alerts | n/a |
| Notification channels and the per-channel settings link | no channels | `UNNotificationCategory`; "System notification settings" opens the app's iOS Settings page | n/a |
| Device-level vibrate / silent-mode detection for message alerts | not exposed | haptics; the switches still gate sounds | n/a |
| Local call recording from WebRTC's audio device module | no public sample hook in the iOS WebRTC SDK | `startRecording` returns nil; the outbox is ported; Meta transcription (`meta_transcription`) stands in — the card says "Recorded by WhatsApp" | decided (cycle 5): platform-restricted |
| `recording_url` playback without an auth header | same on Android | `AVPlayer`; verify `/api/admin/media/*` rules | backend check |
| Hardware keyboard + mouse + drag-and-drop | iPad only | iPad: `.keyboardShortcut`, `.dropDestination`, context menus | Cycle 9 |
