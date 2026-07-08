# Multi-channel ingestion + identity reconciliation — design & plan

**Branch:** `epic/multichannel-identity` (long-lived). Feature work cuts off this
branch and merges back into it; the whole epic fuses to `main` only when it's a
coherent, deployable unit. **`main` auto-deploys to prod — keep WIP off it.**

This doc is the brief for the effort. It captures the debate and the decisions so a
fresh session can resume mid-stride. Companion: [`MULTICHANNEL_SCOPE.md`](./MULTICHANNEL_SCOPE.md)
(the schema-level scope). Prior shipped groundwork on `main`: country-safe phone
matching (`app/core/phone.py`), hub-sourced orders, lead-source capture.

---

## Confirmed context (from Moses)

- **One Meta Business account** holds WhatsApp + Messenger + Instagram → Meta's
  **ID-Matching API** (`ids_for_pages` / `ids_for_apps`) can link a Messenger PSID
  and an Instagram IGSID as the **same person, deterministically**. This is the
  strongest lever inside the Meta world.
- **Runs Meta ads** → **Click-to-WhatsApp (CTWA)** is live: the first WhatsApp
  message from an ad click carries a referral payload (`ctwa_clid`, ad id, source)
  — a deterministic bridge from a FB/IG ad to a WhatsApp identity, and full
  content→revenue attribution.
- **Huge volume, urgent:** ~14M reel views in 28 days; a **~2-week backlog of
  unanswered Messenger/IG/FB inquiries**. This is money on the floor *now* — the
  backlog is both the fire and the identity goldmine.
- Agreed stance: **precision over recall** — never auto-merge World A ↔ World B on
  weak signals; always human-confirm.

## The core model: two identity worlds

- **World A — phone-anchored:** WhatsApp (`wa_id`) + hub walk-in/POS records.
  Reconcile *deterministically* on E.164 phone (already collision-safe).
- **World B — Meta scoped-ID:** Messenger (**PSID**, per Page) + Instagram
  (**IGSID**, per account). **No phone, usually no email.**

The whole problem: **A and B share no natural key.** Strategy = unify *within* each
world strongly, then bridge the two clusters opportunistically.

## Reconciliation as a confidence ladder (never a single "merge")

- **Tier 1 — deterministic, auto-link:** same phone (WA↔hub, or a B-user who
  volunteers one); Meta ID-Match (PSID↔IGSID); email; **payment** (see below);
  order-number / M-Pesa code quoted cross-channel; CTWA click-id.
- **Tier 2 — assisted, human confirms:** name + product-interest + timing overlap,
  surfaced in a review queue; verification handshake ("what number for updates?").
  Show the reviewer the FB/IG **profile pic + username** beside the WhatsApp profile.
- **Tier 3 — weak signals: never merge.** A wrong merge (someone sees another
  person's orders) is far worse than a missed link.

## Out-of-the-box levers (the heart of the strategy)

1. **Let identity precipitate out of money, don't chase it.** Make **WhatsApp the
   universal checkout** for all channels — every serious Messenger/IG buyer is moved
   to WhatsApp for "order confirmation + payment link." The phone key falls out of
   *closing the sale*, not a separate handshake.
2. **M-Pesa is a Kenya-specific deterministic reconciler — CONFIRMED LIVE.** The hub
   **already captures the payer MSISDN + registered name on payment**, so a no-phone
   social lead is bound into World A the moment they pay. This is the load-bearing
   bridge — **lean the whole funnel on it.** Build: on payment, resolve/create the
   `person` from the M-Pesa MSISDN (E.164) and attach the paying channel identity to
   it. The precision-first "only auto-merge on money" model is now concrete.
3. **Order numbers / payment refs / M-Pesa codes = portable identity tokens.**
   Anyone quoting `BH-1234` on any channel binds that channel identity to whoever
   placed it.
4. **Comment-to-DM — ALREADY LIVE.** They already convert public reel/post comments
   into DMs, so the top-of-funnel capture exists (correcting the earlier assumption
   that it was untapped). The work is therefore **integration, not building**: route
   those comment-driven DMs into the agent (so they stop becoming backlog) and
   **attribute each back to the reel/post that drove it** for the content→revenue loop
   (lever 8). TODO when building: confirm whether the current comment→DM is automated
   (a tool/Meta automation) or manual, since that dictates where we hook in.
5. **Cluster & defer, don't force a merge.** Keep identities as separate
   *person-candidates*; collapse only when a hard key arrives (payment / volunteered
   phone) or a human confirms. Reversible clustering > premature merging.
6. **Route the relationship to WhatsApp; use FB/IG as capture.** Messenger/IG give a
   24h reply window then lock out; WhatsApp has template re-engagement. Every flow's
   job: move a hot lead across the border *within* 24h.
7. **Backlog first, revenue-weighted triage.** The agent needs no identity to answer
   "how much / do you have / where are you." Clear the backlog now; mine it as a warm
   remarketing + identity-capture list. Score inbound by buying intent — the goal is
   **"never miss a buyer,"** not "answer everything."
8. **Content→revenue loop.** With CTWA + reel-level data, attribute reel → chats →
   orders. Turns a blind 14M-view engine into "this content produces communion-set
   buyers." The most data-driven thing we can build.

## Architecture (the identity spine)

```
person                                   ← the human; the CRM unit
  ├─ identity(channel, external_id)       whatsapp:2547…, messenger:PSID, instagram:IGSID
  ├─ identifier(type, value, source, confidence)   phone/email volunteered or matched
  └─ rolls up orders, tags, memory, lead_stage, cart
conversation → gains channel + person_id; DROP UNIQUE(conversations.wa_id)
message      → gains channel + external_message_id
order_event  → already has channel; gains person_id
```

- Reconciliation = attach identities to one `person` at a recorded confidence,
  **reversibly and auditably** (today's `merge_customers` is cosmetic — it re-points
  NO rows; it must become a real, reversible merge).
- Agent memory/cart/context key on `person` so context follows a human across
  channels once linked.

## Meta platform realities / guardrails

- Messenger + IG ride the **same Messenger-Platform webhook** once IG is linked to
  the Page; same relay pattern as WhatsApp today (Meta → n8n → `/api/n8n/*`).
- Needs **App Review**: `pages_messaging`, `instagram_manage_messages`,
  `business_management` (for ID-Match). Page + IG tokens. Weeks of platform
  paperwork, not engineering.
- **Per-channel 24h window + tag/template policies** differ — proactive outreach is
  constrained differently per channel.
- **Automation policy:** at this volume, automated DMs must stay inside Meta's
  automation + human-handoff rules or risk the account driving all the revenue.
  Design within tags/handoff from day one.

## Progress (epic/multichannel-identity)

**Phase 0 — identity spine: SHIPPED into the epic branch (verified, additive,
WhatsApp unchanged).** Not yet fused to `main`. Commits:
- `persons` + `identities` (`UNIQUE(channel, external_id)`) + nullable
  `person_id`/`channel` on the wa_id tables; one migration adds **and backfills**
  (every wa_id → one person + one `(whatsapp, wa_id)` identity).
- `app/services/identity.py` resolver wired into every write path so no new row
  lands with a NULL `person_id` (backfill did history; this does the future).
- **Real, reversible merge**: `app/services/merge.py` moves identities +
  re-points history onto the surviving person, tombstones the secondary, writes a
  `person_merges` audit; `POST /customers/{wa_id}/merge` is now real +
  `…/unmerge` reverses it. (The old merge was cosmetic.)
- CRM panel surfacing: profile returns `person_id` + real `linked_identities`;
  `GET /customers/{wa_id}/identities` returns the identity graph + merge history.
- Verified end-to-end on Postgres 16 (backfill unifies person_id; UNIQUE rejects
  dup identities; merge/unmerge round-trips exactly; migrations up/downgrade
  clean). Test suite: 87 passed.

**Deliberately NOT done yet (and why):**
- `UNIQUE(conversations.wa_id)` is still in place and the query layer still keys on
  `wa_id` — cutting it over to `person` is the next spine slice, gated on nothing
  external but larger/riskier; kept separate so each epic merge stays coherent.
- Messenger/Instagram ingestion — blocked on **Meta App Review** (`pages_messaging`,
  `instagram_manage_messages`, `business_management`); platform paperwork, not code.
- M-Pesa payment→person receiver — the neema side is ready to build, but it needs
  the **hub** (`feat/customer-country-e164` in bethany-house) to expose the payer
  MSISDN to a neema endpoint; cross-repo contract, so parked until that lands.
- Pre-existing: the Alembic chain isn't replayable on a fresh DB (migration
  `6436af8b40be` drops `custom_roles`/agent cols the initial migration never
  creates). Flagged as a separate task; doesn't affect prod (already past it).

## Recommended sequence

0. ~~**Identity spine (World-A only)**~~ — **DONE** (see Progress above), minus the
   `wa_id`-query-layer cutover + dropping `UNIQUE(conversations.wa_id)`, which is
   the next spine slice.
1. **Messenger ingestion (pilot channel)** — in+out through the agent; unified inbox.
2. **Wire the existing comment-to-DM into the agent** — route the comment-driven DMs
   (already live) through the agent + tag them with the source reel/post.
3. **Instagram DM** — mostly config once Messenger works.
4. **Reconciliation service** — confidence tiers, **payment/M-Pesa auto-link
   (confirmed available)**, Meta ID-Match for PSID↔IGSID, review queue for Tier 2.
5. **Content→revenue attribution** — CTWA + reel-level reporting.

## Confirmed / open decisions

- [x] Hub captures **M-Pesa payer MSISDN + name** on payment → deterministic
      reconciler is LIVE; lean the funnel on it.
- [x] **Comment-to-DM is already live** → work is integration + attribution, not
      building the funnel. (Confirm automated vs manual when building.)
- [ ] Meta App Review scope + timeline (who owns the Business Manager submission).
- [ ] Sequence check: backlog/triage vs identity spine — which lands first for the
      new session? (Recommend: ship a Messenger *answering* pilot fast to stop the
      bleed, build the spine in parallel; wire M-Pesa payment → `person` early since
      it's the deterministic bridge and the data already exists.)
