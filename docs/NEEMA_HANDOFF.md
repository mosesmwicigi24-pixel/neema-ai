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
- **FB comment funnel** (Bethany House page, LIVE): a comment → intent classify →
  the PUBLIC reply IS the sale. High-intent → real agent reply in `public_comment`
  mode (brief, personal, CATALOGUE-ACCURATE price via search_catalog) + a one-tap
  `wa.me` order link appended in code → close in the comment. Praise/emoji → VARIED
  warm thanks (picked by commenter id, no pitch). Negative → empathy + human. Spam →
  silent. Per-post cap `meta_comment_agent_cap` (30): first N buying comments get
  the full agent reply, rest get a lighter warm line (cost/rate control). The DM is
  a SILENT BONUS (best-effort; no public DM promise) — real DMs to non-testers need
  App Review of `pages_messaging` (subcode 33 otherwise). SET `BUSINESS_INFO` +
  `WHATSAPP_HANDOFF_NUMBER` on the box for the links/logistics to work.
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

## Phase E (2026-07-09/10, Fable autonomous pass) — SHIPPED
- **Phantom WhatsApp contacts FIXED** (`b70e1de`): root cause was crm.py's shim-User
  path + provision_user minting `(whatsapp, <16-17-digit Meta id>)` identities and
  showing the PSID as Phone. Guards: `core/phone.is_plausible_phone` (7-15 digits;
  E.164 max 15, Meta ids 16-17); resolve_person_id_for_wa_id adopt-only for
  non-phones; provision_user phone=NULL + no identity mint for non-phones; CRM
  phone display guarded. **RUN ON BOX to repair existing rows:**
  `docker compose … exec -T api python -m app.jobs.fix_phantoms` (dry-run) then `--apply`.
- **Person-scoped memory** (`ba1b011`): Meta customers now have cross-conversation
  memory on persons.state (was User-only → Meta had none); survives merges; past
  orders via OrderEvent.person_id.
- **Elite consultant prompt** (`605685c`): warm+direct, first-contact asks item +
  city&country, ship-worldwide framing, natural upsell, capture-everything.
- **Messenger location capture** (`75c597a`): capture_contact gains location →
  person.state.location; meta addendum asks city&country.
- Meta Profile API CONFIRMED blocked for non-testers (400 subcode: missing
  permissions; 1/69 named) → names come from asking in chat until App Review.

## Next build (queued)
- **Attribution reporting view** — revenue-by-source. Data link exists now
  (`person.state.source_post` + hub orders → person). Backend aggregation + a small
  Insights panel. This is the clean next slice.
- **Per-page token routing** — map webhook `entry.id`→page token so the "Bethany
  House Executive" page also replies (only the main page's token is held today).

## 🐞 Known bugs
0. ✅ **FIXED (main `739b1c7`)** — MISSING MIGRATION for `messages.comment_context`.
   The column was added to the Message model (85f1643) with no Alembic migration,
   so the deployed model SELECTed a column prod's DB lacked → 500s across the inbox
   (list, thread, comment capture, agent reply). Invisible to /api/health (Redis
   only). Migration `c3f7a1b9d2e4` adds it (`ADD COLUMN IF NOT EXISTS`, reversible);
   runs before uvicorn so it self-heals on deploy. VERIFY going forward: any new
   model column needs a matching migration — run the drift check (below).
   ⚠️ SEPARATE pre-existing bug (NOT fixed): fresh-DB `alembic upgrade head` breaks
   at `a3e90c34e4ac`'s `op.drop_table('custom_roles')` (table never created on a
   fresh DB). Only bites a from-scratch rebuild, not prod. Fix by guarding that
   drop with `IF EXISTS`. This also blocks the automated schema-drift check on a
   fresh DB — until fixed, audit drift by grepping models vs `alembic/versions/`.
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
