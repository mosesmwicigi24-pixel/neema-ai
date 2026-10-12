# Neema iOS — consistency log (cycle 9)

The walk of the iOS app against the Android app, screen by screen and word by
word, at the end of cycle 9. Android (`apps/android`) is the reference; the
web (`apps/web`) is what both copy. Each entry says what was compared, what
differed, and what was done. Statuses are the matrix's.

## How the comparison was made

- **Screens**: the macOS job's `ios-screenshots` artifact (the gallery of
  `NeemaAppTests/Gallery/ScreenGalleryTests.swift`, now hosted in a window so
  lists and scroll views appear) beside Android's Paparazzi goldens in
  `apps/android/app/src/test/snapshots/images/` (902 PNGs). The iOS shots are
  a 390 × 844 pt phone (light and dark) and a 1180 × 820 pt iPad (light);
  Android's are a Pixel-class phone and the Tab S9 Ultra at several widths and
  font scales. Pixels were not compared: layouts, states, copy, colours and
  controls were, by eye.
- **Words**: every quoted literal of two words or more in the Android sources
  (1 202) against every literal in the iOS sources (1 194). 135 Android
  literals have no verbatim iOS twin; each was read in context.

## Words

| Android literal(s) | Verdict |
|---|---|
| Battery saving, "Stay connected in background", "Let Neema run in the background", "Keep Neema signed in — a call rings this phone even when the app is closed", "Allow full-screen notifications…", "Let calls take over the lock screen", "Neema is connected", "Tap to return to the call", "Call in progress" | Android's foreground service, battery optimisation and full-screen intent. No iOS twin by design (CallKit and pushes); the Profile copy says so. **platform-restricted** |
| "Customer messages", "Incoming calls", "Team updates", "Live connection" and their descriptions ("Every message a customer sends…", "Escalations, transfers…", "Chats released to Neema, the morning standup and system checks", "WhatsApp and Messenger calls ringing the team…") | Android notification channel names and descriptions. iOS has no channels; the switches in Profile carry the same meaning. **platform-restricted** |
| "Pop-ups, the lock screen and which alerts Android shows", "Sound and vibration: Neema → Profile → Sounds & vibration." | Android's per-channel settings link. iOS: "System notification settings" opens the app's page. **platform-restricted** |
| "No app on this phone can receive the CSV — install Gmail, Drive or a file manager, then export again.", "Couldn't share the report file — try again.", "Android closed Neema while the CSV was being prepared — tap Export CSV again." | Android share-target failures. iOS shares through `ShareLink` / the activity sheet, which never lacks a target; the export's own failures keep the web's words (`ReportsViewModelTests`). **n/a** |
| "Share the crash report", "When the Android app closes on someone, it sends what went wrong here…" | The crash notice's chooser title and the Settings card copy. iOS: "Share report" on the notice, "On this phone" on the card — same meaning, Apple's register. **verified** |
| "Open notifications" | Android's `onClickLabel` on the bell. iOS: the bell's label is "Notifications" / "Notifications, n unread" (VoiceOver reads the action itself). **verified** |
| "Drop to attach to your reply" | Was missing: the iPad drop target now shows it (cycle 9). **verified (compile only)** |
| "Unreadable thread", "Unreadable inbox page", "not a conversation list", "Permission denied", "bad varint", "truncated field", "fault address 0x", "native crash", "(no backtrace)", "--- crashed thread:" | Exception messages and the Android tombstone parser: never shown to a person. iOS's own decoders say "unreadable" through `ErrorText.UNREADABLE`. **n/a** |
| "WebRTC unavailable", "channels unavailable", "answer failed", "callback failed", "outbound call failed / broke", "recording started / unavailable / finalise failed / upload failed", "background job failed", "got TURN relay candidate ✓", "typ relay" | Log lines and non-fatal labels of the Android softphone. iOS records non-fatals under the same `webrtc-<name>` / `call-<name>` keys (`CallNativeSafetyTests`); the log lines are not printed (no `print` in the iOS code, by the security checklist). **verified** |
| SVG path data (`M12 2C6.477…`, `M13 10V7…`, `M3 8l9 6 9-6…`) | The channel glyphs; iOS carries the same paths in `WebIcons` / `ChannelGlyphs`, split differently. **verified** |
| Fragments around string templates (`} already allows calls — call now`, `}, this is Bethany House.`, `} released back to Neema`, `}} was removed by someone else`, `— showing full in-shop + WhatsApp history`, `Use a date like 2026-12-25.`, `With nothing ticked, the agent falls back…`, `Next page` / `Previous page`, `Failed to transfer`, `Messenger answer rejected`, `Call details`, `empty profile`, `their timeline`, `her promise`, `priced per single piece`) | Found on iOS once the template is joined. **verified** |
| Kotlin code that the extractor read as text (`", to); put("`, `; var build =`…) | Not strings. **n/a** |

Every user-facing Android string therefore has its iOS twin, or an iOS
reason not to.

## Screens

(Filled from the cycle 9 gallery run; see below.)
