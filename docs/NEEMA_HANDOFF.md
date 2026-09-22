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
- **Currency gate** — ONE currency, never two (owner 2026-09-05; the chain is
  `services/market.py`, the only place it is decided): KES only when the EVIDENCE
  says Kenya — a +254 WhatsApp number; the website visitor's IP (web_chat
  geolocates it onto the user row); a Facebook/Messenger/Instagram/TikTok id
  merged with a +254 WhatsApp number (a linked WhatsApp identity, the WhatsApp
  user row, a phone given WITH its country code); or their own words (a
  captured Kenyan location, a panel edit). Zambia→ZMW the same way; everyone
  else, and anyone unplaced, USD. NOT evidence: a Facebook locale, a name, a
  bare "0712…" whose country we assumed. No country question, ever. USD prefers
  the hub's own `price_usd`, falls back to KES÷`usd_kes_rate` (default 100). On request,
  Neema converts USD→local at the central-bank rate, as the arithmetic gives it.
  Prices are quoted EXACTLY as the hub holds them — never rounded to a unit or
  a ten (owner rule 2026-09-03; `app/core/money.py` is the one formatter).
- **The official voice** (owner 2026-09-15, from the green-cassock thread): English
  is the selling language — Swahili ONLY when the comment itself is Swahili, no
  Swahili sprinkles in English; the hub names the item and prices it (a hub row's
  own name + what they see, never a composed name or a remembered price; 'the one
  you're wearing' is the presenter's garment); every question takes the order
  ("Kindly place your order — colour, how many, how soon?"), never chat for its
  own sake; human, not bot (no "Very well", no product poetry, no boilerplate,
  no markdown, "$170" not "$170 USD"). `app/agent/voice.py` strips markdown,
  the redundant currency word and butler openers at the public seams; the canned
  pools close on the order. KISWAHILI SANIFU: a Swahili reply (only when THEY
  wrote Swahili) is standard, official Swahili under the same rules — hub names
  kept as written, one price per item, no Sheng, no "tunaship"/"unaweza order",
  the close "Tafadhali weka oda yako — tuambie rangi na idadi unayohitaji.
  Unaihitaji lini?"; `voice.looks_swahili` picks the Swahili canned pools
  (`_SW_*`) for a Swahili comment; "Upo wapi?" is stripped at the send boundary.
  ASK ONLY WHAT THE HUB CANNOT ANSWER (owner 2026-09-15): a stock item (trays,
  cups, wafers, wine, tallits — `made_to_order` false in the hub) is never asked
  its colour or size; its specifics come from `details`, and the close asks how
  many, how soon, which city. A made-to-order item (cassocks, shirts, stoles…)
  is asked colour then size/measurements. Every search row carries `ask_next`;
  the canned pools split the same way (`_STOCK_*` vs the made-to-order pools).
- **Never price a guess** (owner 2026-09-21: a tallit post sold anointing oil,
  a dress design a bell, a cope a ring — each a canned line filled from an
  arbitrary hub row). Every post identity now carries a `source` and a
  `confidence` (`post_catalog.with_provenance`): team 1.0, storefront link 1.0,
  caption 0.95, reposted catalogue photo 0.95, vision confirmed 0.9,
  vision-name 0.7, a model's read 0.6, a pre-provenance record "legacy" 0.5.
  `identity_trusted` (trusted source and ≥ 0.8) is the ONLY gate to a canned
  price: an untrusted post keeps the model reading the post image every turn,
  the free no-model path and the over-cap line sell nothing on it, and a bare
  price ask under it gets "which item are you asking about?". The resolver
  never searches with the caption's lead words any more (a post it cannot name
  gets no product); the catalogue search matches whole words with stop-words
  dropped, marks any-token fallbacks `match: "partial"`, and answers an
  all-stop-word query with nothing. A caption naming one item in several sizes
  ("Tallits / Prayer shawls" → Medium and Large) is one family identity priced
  "from" the cheapest. A product the COMMENT named but the caption did not
  ("what is an apostolic ring?") is never recorded as the post's identity, and
  a caption-less post records a model read only when the model saw the frame.
  The vision rung (`post_catalog.product_from_vision`): the light model picks
  ONE exact catalogue name from the post photo (narrowed by the caption's
  product words) at CONF=high, then confirms SAME/DIFFERENT against that
  product's own catalogue photo; only SAME is trusted. A NONE is cached a day
  per image. The team override stamps "team".
- **Like every answered comment** (owner 2026-09-22, from the Page's
  Professional dashboard: "Reply to 400 comments" half done, "React to 400
  comments" at 0 — Neema replied to everything and reacted to nothing). After
  every public reply that landed, the comment engine gives the Page's Like
  (`meta_send.like_comment`, `POST /{comment-id}/likes`, the same
  pages_manage_engagement permission the replies use), a beat later: a
  question, a hello, a cheer, an "amen", a live-stream welcome. Never on a
  complaint, never on spam (no reply, no Like), never on Instagram (no such
  edge). `META_COMMENT_LIKE` (default on) switches it off. The commenter is
  notified and comes back to the thread; the dashboard task moves with the
  replies.
- **A set is priced as its total** (owner 2026-09-21: under a five-piece
  cassock outfit, "the Cassock is $120" was read as the price of the whole
  set — "if the description describes a product that has different
  combinations of items, we should always do the total"). The identity ladder
  reads a caption that ENUMERATES several items (`post_catalog
  .caption_item_kinds`: a run of list pieces each naming one kind of hub row —
  "cassock, shirt, collar, cincture belt and stole") and never resolves it to
  one of them: with a set cue ("complete", "set", "comes with", a person
  "robed in"…) it is the hub's own SET row whose contents cover the list
  (`product_set_from_caption` — the row's `components` parsed from the hub
  description, "Cassock Set" $200 comes with cassock, stole, belt, straight
  collar shirt and a 12 inch clergy collar), else the listed rows TOTALLED
  when each is exactly one hub row (`bundle_from_caption` → a synthetic
  `bundle` row: names joined with " + ", KES/USD totals, the dearest item's
  slug); anything less is no identity, and the model gets the rule and the
  listed items in its context. The resolver leads the sink with the RECORDED
  row (by slug, then exact name — "cassock set" also finds the cheaper ladies'
  set) and attaches `components`; a bundle record keeps its items and is
  re-totalled from fresh hub rows. The canned lines (`_SET_*` / `_BUNDLE_*`,
  Swahili too) say the set's one price WITH ITS SCOPE ("goes for $200,
  everything included"), what it comes with — the main piece as "the", the
  rest as "a", "all in one order" — and the owner's one step ("let us know how
  many sets you may need and how soon you want them delivered"; the colour
  when made to order); `search_catalog` marks a set row `set` with
  `comes_with`; the prompt rule A SET IS PRICED AS ITS TOTAL and the comment
  addendum carry the same law, with two closing rules the post exposed
  ("think as the best linguist in business and closing the sales"): A PRICE
  CARRIES ITS SCOPE (the scoping words sit beside the number — "everything
  included", "alone", "each", "from") and "DO YOU DO / MAKE THIS FOR …?" IS A
  YES (yes first, in their own words, then the post's item with its price,
  then the one step — never a clarifying question, never an example item the
  post never showed). "Signature belt" (the owner's word) is the hub's CINCTURE BELT
  (`core/synonyms`). Hub row to check (owner-side): the "Cassock Set" row is
  $200 / KES 19,500 while its five pieces sum to $220 — the set row is the
  figure Neema gives, as the hub's own.
- **Cheapest first, then climb; say it like a person** (owner 2026-09-16). A
  KIND of thing ("how much is that Holy Communion set?") is a RANGE, not a row:
  `synonyms.RANGES` names the hub rows in it (communion trays and sets — the
  wooden and aluminium trays, the silver and golden trays, the stacked sets)
  and the neighbours that are NOT (chalices, cups, wafers, bread, wine);
  `search_catalog` returns the range cheapest first with a `range` note, and
  every ordinary search leads with the row whose NAME carries the words, then
  the cheapest. The prompt rule CHEAPEST FIRST, THEN CLIMB lists from the
  humblest up and stays in the range. A customer who tapped one of our ads
  carries its headline into the context (`runtime._ad_headline`), so "that
  set" is the ad's product. The photo/comment reply takes the owner's spoken
  shape — "This is our Silver Communion Tray, and it goes for $180. It comes
  with a lid, a holder and a basin, and 40 cups are included in the package
  for free. Kindly place your order now and let us know how many trays you may
  need and how soon you want them delivered." — and the comment-DM is the
  answer + the order link, nothing after (the "tell me a little more" tail is
  gone). Hub row to fix (owner-side): "Double Stacked Silver Tray Set" is USD
  600 against KES 36,000 — it belongs in the USD rows CSV.
- **One item, many names** (`app/core/synonyms.py`, owner 2026-09-06): "cross
  and chain", "pendant", "pastor's / bishop's cross" ARE the hub's Pectoral
  Cross. The table rewrites the customer's words at every seam (catalogue
  search, product cards, order lines, post captions, live-comment vocabulary)
  and the prompt says the same, so Neema guides them to the hub row instead of
  "let me confirm". Add a family there when the owner rules two names one item;
  the hub's own aliases still carry everything else.
- **WhatsApp formatting**: agent emits `*bold*` (not `**`); Messenger = plain text;
  the web inbox renders WhatsApp markup (`apps/web/src/lib/waText.tsx`).
- **FB comment funnel** (Bethany House page, LIVE): a comment → intent classify →
  the PUBLIC reply IS the sale. High-intent → real agent reply in `public_comment`
  mode (brief, personal, CATALOGUE-ACCURATE price via search_catalog) + a one-tap
  `wa.me` order link appended in code → close in the comment. Praise/emoji → VARIED
  warm thanks (picked by commenter id, no pitch). Negative → empathy + human. Goodwill
  ("we can't wait to have you in Zambia", "welcome", "congratulations") → a real,
  personal public reply from the model, no DM; on a post that sells nothing (a
  journey, a milestone) the comment rules make Neema the HOST, not the shopkeeper
  (owner, 2026-09-03). The promise she may repeat to "where are you in my
  country?" is `expansion_note` (env `EXPANSION_NOTE`: Zambia 2027, serving the
  southern region) — said with its year, never as if already open. Spam → silent. Per-post cap `meta_comment_agent_cap` (30): first N buying comments get
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
`META_COMMENT_REPLY`, `META_COMMENT_LIKE`, `META_PAGE_ID` (FB page ids [+ IG account id]),
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

## Phase E continued (attribution → tokens → perf → review pack)
- **Attribution live** (`681be7f`): GET /api/admin/attribution + "Where Sales Come
  From" card on Analytics — leads/orders/revenue by (source, post), honest
  `unattributed` row.
- **Per-page token routing** (`f42bb1d`): META_PAGE_TOKENS="pageid:token,…";
  webhook stamps the owning page on each identity; all reply paths act as the
  right page. TO ENABLE Executive replies: generate its Page token, set
  META_PAGE_TOKENS with both pages, up -d api.
- **Inbox polling calmed** (`5f8e98e`): fallback polls 20/30/45/120s, paused when
  tab hidden, refetch on return (WS remains primary).
- **Meta location surfaced**: CRM profile falls back to person.state.location
  (capture_contact) when User.location is empty.
- **App Review pack**: docs/APP_REVIEW_PACK.md — permissions, use-case texts,
  screencast script, reviewer steps. Submit to unlock DMs + private replies +
  profile names in one review.

## Tier-1 design port (2026-07-10, `9f92055` + `5478f3d`) — LIVE
Moses's ChatGPT/n8n two-stage design reviewed. NOT ported (superseded by Tier 2
architecture): state extractor, mood/commercial JSON, control lines, cart-text
reconstruction, image-caption pipeline. PORTED: clergy-wear expertise (full-set
composition, overlay base-garment-first, colour→gender→set→customer-led qty),
country-aware payment (KE→M-Pesa link; intl→discover route WU/Mukuru + handoff)
and fulfilment (KE: delivery/pickup, KES 350, >3kg advisory, pay-before-delivery;
intl: couriers, no unprompted pickup), live Nairobi-daypart greeting + clergy
titles, anti-nag rules, and a code-enforced `pause_conversation` tool (2h redis
cooldown honored by both schedulers). DEFERRED pending Moses: country→payment-
method map (he'll supply), catalogue pass (full-set SKUs + colour/material
variants — hub doesn't expose variant lists yet; agent captures via remember).

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
- Agent: `app/agent/{runtime,tools,prompt,cart,memory}.py`; the owner's
  same-item names: `app/core/synonyms.py`
- Meta: `app/routers/meta_webhook.py`, `app/services/meta_send.py`
- Identity: `app/services/{identity,merge,reconcile}.py`, `app/models/person.py`
- WhatsApp bridge/hook: `app/routers/n8n_bridge.py`, `app/services/n8n_bridge.py`
- Jobs: `app/jobs/reengage.py`
- Inbox API: `app/routers/admin.py` (`/conversations`)
- Web inbox: `apps/web/src/components/views/ConversationsView.tsx`, `ui/Avatar.tsx`
