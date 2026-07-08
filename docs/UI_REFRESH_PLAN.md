# UI refresh — Figma Make → apps/web (branch: feat/ui-refresh)

Port the Figma **Make** "Workflow and UI Design" (file key `GoxbsN0MVJ79YoyNoPctEv`)
into the existing Next.js admin, **wired to the real API** (not the Make's mock
data). Start with the **inbox** (ConversationsView). Deploys as the `web` GHCR
image on push to `main` — **gate the deploy**, never build on `main`.

## Stacks match → port, don't rewrite
- Make export: React 19 + **shadcn/ui** + **Tailwind v4** + Vite, `src/app/App.tsx`,
  full `components/ui/*`, design tokens in `styles/theme.css` + `globals.css`, assets.
- `apps/web`: Next.js 16 + React 19 + **shadcn/ui** + **Tailwind v4** (`components.json`).
- So: bring the tokens + screens across, adapt **Vite→Next** imports (`@/…`,
  no `index.html`, `next/image` for assets), drop the Make's mock data, wire to ours.

## Getting the Make code in (pick one)
- **Best:** Figma Make → open project → **Download / Export code** → drop `src/`
  in so the exact components/tokens/layout port faithfully.
- **Or:** paste screenshots of each screen and we rebuild to match.
(The Figma MCP returns file *links* that can't be read inline in this setup.)

## The real data contract (what the new inbox wires to)
- **Conversations list / thread:** `src/lib/api.ts` + `src/hooks/useApi.ts` →
  `GET /api/admin/conversations`, messages, intercept/agent actions.
- **Channels (already built!):** `src/lib/channels.tsx` `CHANNEL_CONFIG` +
  `ALL_CHANNELS` — whatsapp/messenger/instagram/email/sms with icons/colors.
  Each conversation now carries a real `channel` (post-cutover) → render the badge.
- **Customer panel:** `GET /api/admin/customers/{wa_id}` — now returns `person_id`
  + `linked_identities` [(channel, external_id, source, confidence)].
- **Identity graph:** `GET /api/admin/customers/{wa_id}/identities` — identities +
  reversible merge history (powers a "linked identities" section + unmerge).
- **Live updates:** `src/lib/websocket.tsx` — `new_message` / `intercept_changed`
  (Messenger inbound now broadcasts these too).
- Existing inbox to replace/redesign: `src/components/views/ConversationsView.tsx`
  (~2.7k lines) + `src/components/ui/CustomerSidebar.tsx`.

## Multichannel surfaces the redesign must include
1. **Channel badge** on every conversation row + in the thread header (CHANNEL_CONFIG).
2. **Channel filter** in the inbox (WhatsApp / Messenger / Instagram / all).
3. **Linked-identities** block in the customer sidebar (from `…/identities`),
   replacing the phantom `merged_ids` with real (channel, external_id) rows.
4. Reply composer works per-channel (backend already routes WhatsApp vs Meta).

## Phased sequence
1. **Design tokens/theme** — reconcile Make `theme.css`/`globals.css` with the
   app's Tailwind v4 tokens (colors, radius, fonts). Low-risk foundation.
2. **Inbox list + thread** (ConversationsView) — new look, wired to the real
   conversations/messages + channel badges + filter.
3. **Customer sidebar** — new look + the real linked-identities section.
4. **Leads / CRM / the rest** — view by view.
5. Verify **`pnpm build`** passes (that's what the web image build runs) → gate deploy.

## Deploy discipline
Same as backend: build → verify (`pnpm build` + preview against live API) → push
`feat/ui-refresh` → `main` → CI rebuilds the `web` image → box pulls (both `-f`
compose files). Keep WIP off `main`.

---

## Inbox screen spec (from the published Figma — file `GoxbsN0MVJ79YoyNoPctEv`)

Four-column layout + left nav. Every region maps to a real endpoint we shipped.

**Left nav (dark navy):** Neema AI / Admin Portal; items Inbox·Orders·Reports·
Leads·Analytics·Catalog·Team·Settings; footer = current user (avatar + role).

**Col 1 — Chats list:**
- Header "Chats" + "N live" pill + "+".  Search box.
- **Channel filter tabs**: All(✨) · WA · FB · IG, each with a live count badge.
  Filters the list by `conversation.channel` (WA→whatsapp, FB→messenger, IG→instagram).
  Uses `CHANNEL_CONFIG` colours/icons (already in `src/lib/channels.tsx`).
- Row: colour avatar (initials / "+" for unknown), name-or-number, last-message
  preview, time-ago, **channel badge** (WA/FB/IG), unread count.
- Data: `GET /api/admin/conversations` (already returns `channel`); WS
  `new_message` prepends/re-sorts.

**Col 2 — Conversation thread:**
- Header: avatar, name, channel badge, phone/handle, online dot; actions
  AI · **Intercept** · Pause · transfer · edit · delete (existing intercept API).
- Bubbles: inbound light, outbound dark; timestamps + read ticks; system pills
  ("X picked up the conversation"). Composer: attach · input · emoji · send.
  Reply posts through the existing send path (now channel-routed to WABA/Meta).

**Col 3 — Activity Log (collapsible):** timeline of intercepts + order_events
  (Picked up / Released to AI / Order placed · KES / Transferred / Conversation
  started) with icon + actor + time-ago.

**Col 4 — Customer panel (PROFILE / INSIGHTS / ACTIVITY tabs):**
- Header: avatar, name + VP tag, phone, Won/flag badges, "Buys …" + LEAD SCORE bar,
  stat trio (Orders · KES spend · Coins).
- **PROFILE**: contact details; **Lead Pipeline** stepper (`lead_stage`); Customer
  Health (Orders/Returns/Disputes); Tags; Notes; **CROSS-CHANNEL + Merge** →
  `GET …/customers/{wa_id}/identities` (linked identities) + `POST …/merge` /
  `…/unmerge`; Mark Won / Mark Lost / Advance Stage.
- **INSIGHTS**: lead score ("Perfect Score / Power Buyer"), Spend Trend chart,
  Purchase Summary (total orders/spent/AOV/last/since), Buying Rhythm, Top Products,
  Lead-Score Breakdown — all from the CRM profile endpoint (`buying_rhythm`, `tier`,
  hub orders/spend, lead score) already built.

**Build order:** tokens/theme → Col1 (list + channel filter + badges) → Col2
(thread + composer) → Col4 PROFILE (with real CROSS-CHANNEL/Merge) → Col3 activity
→ Col4 INSIGHTS. Wire each to the live endpoint above; verify `pnpm build`; gate deploy.
