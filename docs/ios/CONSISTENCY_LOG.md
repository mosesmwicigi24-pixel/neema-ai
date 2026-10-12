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

The iOS gallery of run 38318262683 (the first with the window-hosted renderer:
every list and scroll view visible for the first time) beside the Android
goldens, on the phone, light. "Verified" means the layout, the states shown,
the copy and the colours agree; the differences listed are what was found
and what was done. Two kinds of difference recur and are not defects: the
iOS phone is 390 pt wide where Android's is 412 dp, so a row that fits on
Android may wrap or truncate on iOS by the same rule (both apps share the
rule); and the fixtures differ in dates and counts (the iOS gallery pins
2026-09-25 in UTC, Android's goldens run in Africa/Nairobi), so times and
"ago" labels differ by three hours and totals by the fixture set.

| Screen | Android golden | Verdict |
|---|---|---|
| Sign-in | `ShellScreenshotTest_login` | **fixed**: Android centres the form vertically and puts the logo beside "Neema / ADMIN" on the left; iOS stacked and centred the brand at the top. The subtitle, the field labels and the footer are willow on Android, grey on iOS; the email placeholder rendered in the system's link blue. Now: the same row, the form centred, willow throughout, the placeholders in Android's colours (willow email, half-strength parchment password). |
| Inbox list | `ConversationsScreenshotTest_inbox_all` | **verified**: header, "2 live", the five tabs with counts, the search, the channel chips with badges, the rows (edge colour, avatar, chips, "• Yours", preview, time) and "Loading more…" all agree. |
| Phone header | `ShellScreenshotTest_phoneOffline` | **fixed**: Android keeps "Reconnecting…" whole and truncates the view's name ("Orde…"); iOS truncated the pill ("Rec…"), then the wordmark ("Ne…"). Now the pill and "Neema" keep their letters and the view's name gives way. |
| Orders | `OrdersScreenshotTest_populated` | **fixed**: the channel pill used a letter ("W") for its mark where Android draws the app's glyph; now the WhatsApp / Messenger mark. Otherwise verified: the summary tiles, the search, the rows with status, hub chip, "Open in hub", phone line, items and time. |
| Calls | `CallsScreenshotTest_log` | **verified**: the dark console card, the two chips, the day headings, the rows with outcome, duration and agent, the transcript and call-back buttons. The time sits under the outcome on iOS and to the right on Android because 390 pt is "compact" under the rule both apps share (`width / fontScale < 400`); Android's golden is 412 dp. |
| Catalog | `CatalogScreenshotTest_grid` | **verified**: the price-gap banner, the hub note, the search, the category picker and the two-column grid (image, name, stock pill, price range, variants, aliases, SKU and id). |
| Deals | `DealsScreenshotTest_board` | **verified**: the planned-actions card with the approval and the due action (Send / Edit & send / Veto / Open chat), the stage columns with cards, guidance, Won / Lost. |
| Leads | `LeadsScreenshotTest_kanban` | **verified**: the pipeline line, the search, the stage chips, the columns and cards (score, channel glyph, tags, time, the move button). |
| Analytics | `OverviewScreenshotTest_phone` | **verified**: the six tiles with their colours and lines, "Where sales come from" with the attribution rows. |
| Reports | `ReportsScreenshotTest_overview30d` | **verified**: the range picker, Export CSV, the four tabs with the underline, the four tiles, the two bar charts with day labels. |
| Team | `TeamScreenshotTest_agents` | **fixed**: the two tabs stretched to half the row each (the underline's greedy width); Android keeps them at their labels' width, left-aligned. Otherwise verified: the cards with role pill, email, active / joined, last seen, the availability switch and the four actions. |
| Profile | `ProfileScreenshotTest_view_0` | **fixed**: the email wrapped mid-word ("…co.k / e"); now one line with the tail cut. Otherwise verified: the card, the three stat tiles, Availability, Password, Appearance. |
| Settings | `SettingsScreenshotTest_blank_0` | **verified**: Standing Orders with the counter and the button, Translation with the spend line, the Offer card. |
| Drawer | `ShellScreenshotTest_phoneDrawer` | **verified**: the navy drawer with the brand row, the bell, the eleven rows with badges, the account footer. |
| Bell | `ShellScreenshotTest_bellSheetEmpty` | **verified**: the sheet with "Notifications", the empty state "All caught up / No new notifications". |
| Toast | `ShellScreenshotTest_phoneToastSuccess` | **verified**: the green pill with the check, above the bottom bar. |
| Session expired | `ShellScreenshotTest_sessionExpired` | **fixed**: the password field had no placeholder; Android shows "••••••••". Now the same. |
| Offline | `ShellScreenshotTest_phoneOffline` | **verified** (the banner and the pill; the header fix above). |
| Open thread, ringing call, wrap-up | `ConversationsScreenshotTest_thread_*`, `CallsScreenshotTest_cardRinging`, `CallsWrapUpScreenshotTest_*` | **pending**: the first gallery run hung at the open-thread state; the state is rendered last and logged on the next run, and compared then. |
| iPad inbox | `TabS9UltraScreenshotTest_inbox_tabs9u` | **verified** at 1180 pt: the icon rail (under 1200 pt the sidebar collapses, as Android's does), the list beside the thread with its header, actions and composer; the customer panel docks only on the wider Tab S9 Ultra (1480 dp) by the pane rule both apps share. The "Reconnecting…" pill overlays the top end on both (`OfflineDot(Modifier.align(Alignment.TopEnd))`). The thread pane caught its spinner: the shot came before the messages painted. |
| iPad, the rest | `*Tablet*`, `TabS9UltraScreenshotTest_*` | **partial**: the iPad shots render (1180 × 820 pt); the Tab S9 Ultra's widths, font scales and the split-screen thirds are pinned by `TabletLayoutTests` / `AdaptiveTests`, not rendered. |
| Dark mode | `*Dark*` | **partial**: every screen renders dark (phone); compared for legibility, not pixel by pixel. |
