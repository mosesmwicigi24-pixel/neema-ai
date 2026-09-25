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
- **Double verification, not gating** (owner 2026-09-25, two Messenger
  threads after the gate went live: "When am in Uganda" and "My wansapp
  number" were answered with the holding line, a thumbs-up with "I can't
  open that image", "I'm saying ok" with the holding line, and "how much
  that in rands" with "let me confirm the exact rate with our team" —
  "change from gating to double verifying… make the logic consistent").
  Every reply is now read TWICE — the rules and the reviewer both, every
  draft — and their findings carry a WEIGHT (`review.rule_findings`):
  HARD (a figure from nowhere, the wrong item priced, a link no tool gave, an
  order status with no source) and SOFT (a where-question, two currencies,
  and everything the reviewer says). The reply that goes out is the best
  VERIFIED draft (`runtime._gate_turn_reply`): clean → sent; a finding →
  one rewrite with the reasons and the facts, read twice again → sent when
  clean; still not clean → the best draft with NO hard finding is sent and
  the soft notes are logged (tally "soft") — a reply is corrected, never
  strangled; only a hard finding on BOTH drafts holds: a public reply
  returns "" (the engine's holding line + a colleague), a private reply gets
  ONE holding line (the price one when the finding is a figure or an item),
  never two in a row (`review.held_recently`, 6 h — the colleague is already
  flagged), never for an acknowledgement (silence), and the conversation is
  flagged with the reasons and the draft. The where-question rule reads a
  QUESTION about where we are ("where are you located?", "do you have shops
  in South Africa?"), never a sentence that names a place. A THUMBS-UP IS
  THE END (owner: "satisfaction — you should not continue"): Messenger's
  Like sticker (`meta_webhook._sticker`, three sticker ids) is the text
  "👍", never a photo; any other sticker "[sticker]"; `runtime
  .is_silent_ack` (👍 🙏 ❤️ 👌 🙌 ✅ …) makes `closer_gate` silent ALWAYS —
  not even the one warm line a typed "thanks" gets; "I'm saying ok",
  "noted", "alright", "kk", "sawa sawa" are acknowledgements (`_ACK_RE`);
  and `_run_and_send` / `_run_and_send_meta` never send an empty reply.
  THEIR OWN MONEY AT TODAY'S RATE (`services/fx`): a "how much in rands /
  naira / pounds?" fetches USD rates once a day from a public source
  (open.er-api.com; Redis 24 h, a stale copy a week; the house KES rate and
  the hub's ZMW prices are never overridden), gives the writer "TODAY'S
  RATE: 1 USD = 16.43 ZAR" and the verifier the same rate (the USD price ×
  the rate is an allowed figure; the currency they asked for by name may
  stand beside the USD price); no rate → the writer says the price is
  charged in USD and converts at the day's rate, never invents a rate,
  never promises to "confirm the rate with the team" (the prompt's
  local-currency exception now says so). The reviewer no longer calls an
  ordinary promise ("a colleague will reach out") an invention. Health:
  `review: {passed, rewritten, soft, held}`. STRESS-TESTED before it shipped
  (owner: "stress test many scenarios… to the level of human intelligence"):
  `tests/test_verification_stress.py` runs ~100 real-chat shapes through
  the real rules and gate, hunting FALSE HOLDS (a good reply strangled) and
  FALSE PASSES (a figure from nowhere let through). What it found and fixed:
  a figure matches to the UNIT (`_close`: ±0.5, or 0.05%), not to half a
  percent ("KES 22,100" for a KES 22,000 tray is wrong); a conversion starts
  from the hub's own USD, never from KES at the house rate when the hub has
  a USD price; ZMW at the house rate only for a Zambian turn; a KES figure
  derived from USD only when the row has no KES; a fee rides only on a
  price, a quantity multiple or a fact — never on a half or a conversion
  ("R2,300" had been explained as a conversion plus a stray instruction
  figure); the owner's instruction figures count only ABOUT DELIVERY (the
  prompt's "Eliad Oil at USD 50" is an example, not a fact — today the
  allow-list is exactly KES 350); the customer's own figure in THIS
  message is a fact ("my budget is KES 15,000"); number words are
  quantities ("two trays", "tatu", "a dozen"); "22k" is 22,000; every row
  the reply names is read against the ask and the item finding stands only
  when NONE fits ("the Golden at $220, or the Silver at $180 if you
  prefer" passes) and is hard only when money is quoted; an order-status
  claim must be about THEIR order ("we have delivered to Kampala before" is
  not one; "your tracking number is…" without a tool is); a link we sent
  earlier in the conversation may be repeated; "where do I order?" is not
  a where-question; the website never shows an empty bubble (a held
  acknowledgement becomes "🙏"). PHOTOS (owner 2026-09-25, the same evening:
  the cards went out and the next line said "I can't send photos from
  here"): the verifier reads the turn's own actions — `review.cards_sent`
  (send_product_cards results) — and a reply that says it cannot send
  photos is a HARD finding when photos were just sent (a contradiction) and
  soft otherwise; a reply that says "here are the photos" when none went
  out is soft. The rewrite block now lists WHAT THIS TURN ALREADY DID
  (`review.actions_text`: photos sent, cart updated, order created, contact
  saved…) so the second draft speaks of them as done, and its wording no
  longer says "no tool" (the first version's "no tool" read as "I can't
  send photos"). The prompt says it plainly (YOU CAN SEND PHOTOS on
  WhatsApp, Messenger, Instagram and the website), and the cards tool's
  own note when a card could not be delivered never says photos are
  impossible. A public comment, which cannot carry a photo, is exempt.
  VARIANTS PRICED APART (owner 2026-09-25: "The Straight Collar is $10, all
  sizes the same price" — the 8-inch is $3.50, the 10-inch $4; the hub's six
  collar variants all carried $10 under one label, a placeholder). The
  search tool dedupes identical variants and adds a `variant_note`: prices
  that differ → "ONE short line: 'from <cheapest> by size/colour — which?';
  then the variant's own price; never one flat price"; one figure for every
  variant → "ask which, quote once, NEVER say 'all sizes / colours are the
  same price'". The verifier (`review.variant_issues`, kind "variants"):
  the same-price claim is HARD when the variants differ and soft otherwise;
  a variant named in the reply (or asked for) quoted at another variant's
  price is HARD ("the 10 inch variant is priced KES 400 / USD 4 — not 10");
  one flat price for a product priced apart, with no variant named and no
  range said, is soft (the distinctive variant words — "10", "navy" — are
  read with the money figures stripped, so the "10" in "$10" names no size;
  a hyphen in "10-inch" is not a range). The canned comment line prices a
  varied product "from" its cheapest variant (`runtime._variant_floor`).
  The prompt carries the short shape and the ban. HUB-SIDE, STILL OPEN: the
  Straight Collar's variants need their sizes as attributes and their own
  prices (8" $3.50, 10" $4 …) — today they are six identical rows at $10,
  so Neema can only say "from $10" until the hub is corrected.
- **The gate before posting** (owner 2026-09-25: "someone is asking for
  golden trays and you give silver… put a gate to review before posting…
  when someone asks for Holy Communion Cups without specifying chalice, give
  the plastic, stainless and glass cups, not chalice cups… every post should
  be verified before posting for accuracy and correct figures"). Live: "gold
  trays with holes to place tot glasses? shops in South Africa?" got the
  silver set at $180 and no word on South Africa (the canned line: the post's
  product, because "trays" was enough for `_names_product`); "where is your
  location, holy communion cups" got the $650 chalice and no location.
  `agent/review.py` is the gate, and EVERY public reply passes it before it
  posts. The RULES (always on): every money figure in the reply is a hub
  price of a row looked up this turn (`search_catalog`'s rows), its house-rate
  conversion, a quantity multiple, a half (a deposit) or a figure the owner's
  own instructions state — else "a figure from nowhere"; the item the reply
  sells (the row it names, else the one row whose price it quotes) is the
  finish they asked for (gold ≠ silver; stainless / steel ARE the Silver line)
  and the kind (communion cups are the small cups — plastic, silver, glass,
  pre-packed — never a chalice unless they say chalice; a tray is not cups);
  a where-question ("your location", "shops in South Africa") is answered.
  The REVIEWER (`COMMENT_REPLY_REVIEW`, default on; one light-model line;
  skipped past the budget stop): fails a wrong item, a wrong figure or a
  question left unanswered. A draft that fails is written ONCE more with the
  reviewer's reasons in its context (`run_turn(review_notes=…)`); a second
  failure never posts — the thread gets the honest holding line
  (`_VERIFY_HOLD_POOL`: "let me confirm the exact item and price — one of our
  team will answer you right here") and the comment is routed to a colleague
  whose note opens "HELD BACK BY THE REVIEWER" with the reasons. The canned
  (no-model) path refuses to sell the post's product for a comment asking
  another finish or kind (`item_issues`; `_names_product` says no too) and
  holds the same way. The search learned the same: golden is gold
  (`_SEARCH_STEM`), the partial fallback ranks name hits first, "trays with
  holes / tray for the cups / cup tray" are a communion tray, "holy communion
  cups / tot glasses / wine cups" are communion cups, "stainless / steel /
  metal cups" the Silver Communion Cups (`core/synonyms` families), and a
  "communion cups" RANGE returns the four cup rows cheapest first, chalices
  excluded. The prompt and the addendum carry the rules (THE FINISH THEY
  ASKED FOR IS THE ITEM; COMMUNION CUPS ARE THE SMALL CUPS; ANSWER EVERY
  QUESTION IN THE COMMENT; EVERY REPLY IS VERIFIED BEFORE IT POSTS).
  EVERY CHANNEL (owner, the same day: "extend the gate to WhatsApp, Chat,
  Messenger, Facebook — make it very intelligent"): the gate now lives
  INSIDE `runtime.run_turn`, so a WhatsApp, Messenger, Instagram, TikTok or
  website reply passes it exactly as a public comment does — real turns
  only (a read-only draft, a scribe pass and a system-composed instruction
  are not gated, `_gate_applies`). The turn keeps its GROUND TRUTH: the
  transcript as the writer saw it and every tool result (`tool_log`). The
  figure rule reads it all — a cart or order total, an offer price, a
  figure already said in the conversation, a sum of two known figures — so
  a DM's arithmetic passes and a figure from nowhere does not. New rules on
  every channel: one currency per reply; no link a tool did not return; no
  order-status claim ("shipped", "on its way") without `check_order_status`
  or our own earlier word; and a reply that SAYS we do not have the finish
  asked and offers the nearest stands the finish rule down. The reviewer in
  a private chat reads the last turns and the tool results too, and fails a
  reply that re-asks a detail already given, contradicts an earlier turn,
  invents availability or a status, or answers in the wrong language; money
  and order turns are reviewed by the MAIN model (`_reviewer_model`), the
  rest by the light one; `REPLY_REVIEW` (default on) is the private-chat
  switch, `COMMENT_REPLY_REVIEW` the comments'. A failing draft is
  REWRITTEN, not retried: the gate first fetches the hub rows for what they
  actually asked (`_facts_for_ask`, the read-only search on the canonical
  ask), then one model call with NO tools gets the reasons, THE FACTS (every
  row in hand, every other tool result) and the draft (`review
  .rewrite_block`) — nothing is ordered or sent twice. A second failure: a
  public reply returns "" (the engine's holding line + the colleague's
  note); a private reply becomes `_REVIEW_HOLD_DM` ("let me confirm the
  exact details — one of our team will come back to you right here") and
  the conversation is FLAGGED with "HELD BACK BY THE REVIEWER", the reasons
  and the unsent draft (`_flag_held_reply`, an Intercept flag the dashboard
  shows). Each verdict is tallied per UTC day in Redis (`review:YYYY-MM-DD`:
  pass / rewritten / held, per channel) and `/api/health` shows `review:
  {passed, rewritten, held}` — the number to watch: a rising `held` is the
  hub or the prompt drifting, a rising `rewritten` is the writer drifting.
- **A comment thread is the post's thread** (owner 2026-09-23: under a ring
  post, "How much is it?" was quoted the ring in dollars and a reply inside
  that thread, "In Kenya shillings", was answered "KES 19,000 for the full set
  — cassock, shirt, collar, stole and belt"). Where the cassock came from: a
  comment conversation is ONE per person per channel across every post, so
  the ring turn's transcript was that commenter's own earlier cassock-set
  exchange under another post, "in Kenya shillings" re-priced the last item
  in it, and the webhook had dropped `parent_id`, so nothing said he was
  answering the ring quote. Now: a public-comment turn's transcript is THIS
  post's thread only (`runtime._thread_rows` — their comments whose
  `comment_context.post_id` is the post, and our replies whose
  `comment_context.reply_to` names one of them; `_history(post_id=…)` fetches
  wider, then keeps the thread's last turns; rows from before attribution are
  left out); the webhook keeps `parent_id` (the post's own id is not a
  parent); a reply inside a thread carries the comment it answers and our
  reply to it (`_thread_parent` from our inbox, `_thread_parent_context`: "a
  currency, a colour, a size after a quote is the SAME item — 'in Kenya
  shillings' after a dollar quote is that item in KES"); the cross-channel
  lines under a comment say who they are, never what the comment is about;
  and the rule STAY ON THE POST'S PRODUCT says so. The same post was on record
  as the model's "Apostolic Ring" ($40) when the caption said "Premium
  Bishop's Ring" — the hub's "Ring" ($20), a name too short for containment,
  and both ring rows share ONE photo, so neither the image nor the vision
  rung can tell them apart. The caption scorer (`_hub_caption_match`) now
  runs inside the ladder (`resolve_post`) before any model reads a post, and
  an UNTRUSTED record (model / vision-name / legacy) is a lead the ladder
  re-reads once an hour per post (`postcat:retry:*`), a trusted hit replacing
  it. Hub-side, still open: name the premium bishop's ring as its own row and
  give the two rings their own photos.
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
- **Read the intent, grade it, route it** (owner 2026-09-22: "is it a
  request, a complaint, a commendation? A complaint graded on severity and
  referred to a human; a compliment handled by Neema; a statement that looks
  like all three resolved wisely"). `runtime.read_comment` is one reading of a
  public comment — `intent` (the plan's key, unchanged: high / low / negative
  / goodwill / spam), `kind` (request / question / complaint / praise / mixed
  / greeting / other), `severity` (a complaint's weight 1–3) and `ask` (what a
  request wants); the deterministic readers hold on every path (cheering,
  displeasure, a greeting, the REQUEST shape `looks_request`, the grade
  `grade_complaint`: 3 a scam or fraud accusation, a threat to report, abuse;
  2 an order gone wrong, money paid, poor quality, weeks waiting; 1 a
  correction or a disappointment), then one light-model line fills the rest;
  `classify_comment_intent` is its intent. A grievance gets the line by its
  weight (`empathy_text`: mild = the old line; serious/grave = an apology, a
  colleague today, and a PRIVATE message opened first so the details come
  privately — the public line claims it only when it went); a MIXED comment
  thanks first. The team's note is typed and graded (`_human_note`); a
  serious or grave complaint is an escalation (`record_escalation`: the bell
  and the pill), the rest a flag. A REQUEST or QUESTION Neema could not
  answer in the thread (no model) gets their words noted back and a person
  promised (`_REQUEST_ACK_POOL` / `_QUESTION_ACK_POOL`), and the team is
  handed it to answer RIGHT THERE; the model path gets the reading in its
  context (`_reading_context`) and the rule READ THE INTENT, THEN ANSWER IT
  (a request is answered with the shelf). Residues removed the same day: the
  neutral line no longer says "send us a message" / "tell us a little more"
  (it promises a person, and a person is told), and the retired DM-nudge and
  comment-invite pools are gone. Why it lingered: the Florence work (2026-08)
  made complaints one bucket with one line and one note, "the thread is the
  shop" (2026-08-10) stopped the model deflecting but left the no-model
  fallbacks as signposts, and a request was never a kind of its own — so a
  request during the credit stop got the signpost.
- **Like every answered comment** (owner 2026-09-22, from the Page's
  Professional dashboard: "Reply to 400 comments" half done, "React to 400
  comments" at 0 — Neema replied to everything and reacted to nothing). After
  every public reply that landed, the comment engine gives the Page's Like
  (`meta_send.like_comment`, `POST /{comment-id}/likes`, the same
  pages_manage_engagement permission the replies use), a beat later: a
  question, a hello, a cheer, an "amen", a live-stream welcome. Never on a
  complaint, never on spam (no reply, no Like), never on Instagram (no such
  edge). THE HOUSE USES TWO REACTIONS ONLY — the Like and the Love (owner
  2026-09-22: "only likes and love, we do not use any other"); never Haha,
  Wow, Sad, Angry or Care. The API lets a Page put only the Like on a
  comment, so the Like is the one reaction Neema sends. `META_COMMENT_LIKE`
  (default on) switches it off. The commenter is notified and comes back to
  the thread; the dashboard task moves with the replies.
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
