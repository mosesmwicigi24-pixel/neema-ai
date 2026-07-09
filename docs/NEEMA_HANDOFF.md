# Neema — session handoff (device-independent state)

Cross-device handoff for the **multichannel + identity epic**. On a new device
(e.g. claude.ai/code on iPad), start with: *"Read docs/NEEMA_HANDOFF.md and continue."*

Last updated: 2026-07-09. Branch of record: work is fused to **`origin/main`**
(deploys to prod automatically). Latest relevant commit: `f642420`.

## How this ships (don't hand-run on the box)
- Push to `main` → GitHub Actions **Build & Push** → the VPS pulls on a systemd
  timer (~2 min) and recreates containers. Health: `GET https://neema.bethanyhouse.co.ke/api/health` → `{"status":"ok"}`.
- **Verify every backend change** in a throwaway Docker (postgres:16-alpine +
  python:3.11-slim): `py_compile` + full `pytest` + a boot import. 128 tests green.
- Deploy needs BOTH compose files: `docker compose -f docker-compose.yml -f docker-compose.vps.yml …` (a plain `up` once caused a 502).

## Live in prod now
- **WhatsApp + Messenger/IG agent** (one brain, one KES hub catalogue). Messenger/IG
  read-only tools; checkout routed to WhatsApp.
- **Currency gate**: Kenya(+254)→KES; everyone else + all Meta→USD. USD prefers the
  hub's own `price_usd`, falls back to KES÷`usd_kes_rate` (default 100). On request,
  Neema converts USD→local at the central-bank rate, rounding up to nearest 10.
- **WhatsApp formatting**: agent emits `*bold*` (not `**`); Messenger = plain text;
  the web inbox renders WhatsApp markup (`apps/web/src/lib/waText.tsx`).
- **FB comment funnel** (Bethany House page, LIVE): a comment → intent classify
  (`classify_comment_intent`) → `plan_comment_actions`: high=public answer+DM,
  low=light public thanks, negative=empathetic+route-to-human, spam=silent. Public
  reply works; the private-reply DM opener needs a TOP-LEVEL comment + App Review of
  `pages_messaging` for the public (subcode 33 otherwise).
- **One-tap WhatsApp close**: `whatsapp_checkout_link` tool → `wa.me` deep link
  prefilled with product + a `ref`, minted to redis `waref:<ref>`.
- **Social profile enrichment**: FB comment name (free) + Messenger/IG profile
  (name+photo via User Profile API) → `person.display_name` + inbox avatar.
- **waref bridge** (`identity.reconcile_waref`): a WhatsApp arrival carrying the
  deep-link `ref` is merged into the phone-anchored person + stamped with
  `source_post`/`lead_source`. Social→phone identity precipitation.
- Identity spine (persons/identities/identifiers, reversible merge), M-Pesa payment
  reconciler, hub-sourced catalogue + order push.

## Enable/config flags (env on the box)
`META_AGENT_REPLY`, `META_PAGE_TOKEN`, `META_VERIFY_TOKEN`, `META_APP_SECRET`,
`META_COMMENT_REPLY`, `META_PAGE_ID` (FB page ids [+ IG account id]),
`WHATSAPP_HANDOFF_NUMBER`, `USD_KES_RATE`, `BUSINESS_INFO`.

## Moses's open manual to-dos
1. 🔐 **Regenerate `META_PAGE_TOKEN`** — it leaked in logs earlier (code no longer
   logs tokens; token now sent via `Authorization` header). Update `.env` → `up -d api`.
2. Set **`BUSINESS_INFO`** (location/hours/delivery/payment/contacts) so logistics
   questions answer from real facts, not the catalogue.
3. Instagram: subscribe the page's `feed`-equivalent + link IG to the Bethany House
   Page (currently connected via the standalone Instagram-login route). FB page IS
   subscribed via `POST /{pageid}/subscribed_apps?subscribed_fields=feed,messages,messaging_postbacks,messaging_referrals`.
4. **App Review** of `pages_messaging`/`pages_manage_engagement`/`instagram_manage_*`
   for beyond-tester reach.

## Next build (queued)
- **Attribution reporting view** — revenue-by-source. Data link exists now
  (`person.state.source_post` + hub orders → person). Backend aggregation + a small
  Insights panel. This is the clean next slice.
- **Per-page token routing** — map webhook `entry.id`→page token so the "Bethany
  House Executive" page also replies (only the main page's token is held today).

## 🐞 Known bugs
1. ✅ **FIXED (main `8128b7c`)** — human reply to a FB/IG COMMENT conversation
   500'd. `_deliver_agent_reply` (`app/services/conversation.py`) now routes a
   comment conversation to the PUBLIC comment edge (`reply_to_comment`) using the
   comment_id persisted on the inbound comment Message (`waba_msg_id`); DMs +
   WhatsApp unchanged; the send is wrapped so a failure returns
   `{"ok":false,"error":…}` not a 500. NOTE: a human reply on a comment posts a
   PUBLIC comment reply (reliable). A private-reply→DM path could be added later
   but needs top-level-comment eligibility + App Review.
2. Minor: the comment author's numeric FB id renders in the "Phone" field
   ("27426443210383735") — external_id shown as phone. Cosmetic.
3. Inbox polls a LOT (orders/messages/conversations/agents/catalog/session
   repeat rapidly in the Network tab) — worth throttling/batching for perf, not
   urgent.

## Unconfirmed / verify
- Did the **re-engage `--send`** sweep (`python -m app.jobs.reengage --send`) complete?
- Is the **Messenger DM** reply (not just comments) working end-to-end in prod?

## Key files
- Agent: `app/agent/{runtime,tools,prompt,cart,memory}.py`
- Meta: `app/routers/meta_webhook.py`, `app/services/meta_send.py`
- Identity: `app/services/{identity,merge,reconcile}.py`, `app/models/person.py`
- WhatsApp bridge/hook: `app/routers/n8n_bridge.py`, `app/services/n8n_bridge.py`
- Jobs: `app/jobs/reengage.py`
- Inbox API: `app/routers/admin.py` (`/conversations`)
- Web inbox: `apps/web/src/components/views/ConversationsView.tsx`, `ui/Avatar.tsx`
