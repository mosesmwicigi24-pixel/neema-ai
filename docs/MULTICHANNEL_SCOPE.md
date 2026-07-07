# Multi-channel ingestion + account-linking — scope

**Goal (from Moses):** *"If we get to know that this person is coming from Facebook,
how can we link those accounts? Know this is the same person who inquired from
Facebook or TikTok."*

Two distinct capabilities are bundled in that ask. They should be built in order —
the first is a prerequisite for the second, and the first is independently valuable.

1. **Multi-channel ingestion** — actually *receive and reply to* messages from
   channels beyond WhatsApp (Messenger, Instagram DM, later TikTok), through the
   same agent and inbox.
2. **Account-linking (identity resolution)** — recognise that a Messenger contact
   and a WhatsApp contact are the *same human*, and present one unified customer.

Today Neema is **WhatsApp-only** and identity **== phone number** (`wa_id`). That
single fact is the root of all the work below.

---

## 1. Where we are today (ground truth)

- **Ingestion:** Meta Cloud API → **n8n workflow** → FastAPI bridge `/api/n8n/*`
  (`apps/api/app/routers/n8n_bridge.py`). There is **no FastAPI webhook** and no
  channel concept in the pipeline — every inbound is assumed WhatsApp.
- **Identity is `wa_id`** (normalised phone, `+`-stripped) across **6 tables**:
  `users`, `conversations`, `messages`, `order_events`, `customer_history`,
  `sessions`. Each has a UUID PK but `wa_id` is the de-facto join key.
- **`conversations.wa_id` is `UNIQUE`** → exactly one conversation per identity.
  A per-channel conversation model breaks this constraint directly.
- **No `channel` column** on conversations/messages/users. Only `order_events`
  has a real `channel` (default `"whatsapp"`). The admin/CRM code already reads
  `getattr(conv, "channel", "whatsapp")` and even renders a
  `("whatsapp","messenger","instagram","email","sms")` breakdown — but it's a
  **phantom**: the column doesn't exist, so everything resolves to `whatsapp`.
  *The UI was scaffolded for multi-channel; the schema never was.*
- **`merge_customers` is cosmetic** (`crm.py`). Despite its docstring, it does
  **not** re-point any `wa_id`-keyed rows — it only copies scalar fields, unions
  tags, and hides the secondary via `state["merged_into"]`. Real linking needs a
  rekey/merge that doesn't exist yet.
- **Lead-source capture (shipped, PR #45)** records *where a lead heard about us*
  (`state["lead_source"]`: facebook/tiktok/referral/…). That is **marketing
  attribution, not a transport channel** — useful context, but it does not mean
  we can receive a Facebook message. Don't conflate the two.

**Implication:** the honest current state is "we know they *said* they came from
Facebook." We cannot yet *receive* a Facebook message, nor prove two contacts are
one person.

---

## 2. Target model

Introduce a first-class **identity** separate from phone, and a **channel** on
conversations/messages.

```
person (NEW)                     ← the human; stable id
  ├─ identity (NEW)  (channel, external_id, display_name, raw_profile)
  │     e.g. (whatsapp, 254700…), (messenger, PSID…), (instagram, IGSID…)
  └─ … rolls up orders, tags, lead_stage, notes, memory

conversation  → gains channel + person_id; drop the UNIQUE(wa_id) constraint
message       → gains channel + external_message_id
order_event   → already has channel; gains person_id
```

- **`person`**: the unit the CRM panel shows. Orders, spend, tags, lead stage,
  agent memory all attach here (or roll up from identities).
- **`identity`**: one row per (channel, external_id). WhatsApp phone, Messenger
  PSID, Instagram-scoped ID, later TikTok. `UNIQUE(channel, external_id)`.
- **Linking = attach two identities to one `person`** (and re-point/merge the
  per-identity conversation history), replacing today's cosmetic merge.

This is a **migration of the identity spine**, so it touches everything. Do it
behind a compatibility shim: keep `wa_id` working (WhatsApp identity's
`external_id`) so nothing regresses while the rest is rebuilt.

---

## 3. Workstreams

### A. Identity spine (foundation — do first, no user-visible change)
- Migrations: `person`, `identity`; add `channel` + `person_id` to
  `conversations`/`messages`, `person_id` to `order_events`; **drop
  `UNIQUE(conversations.wa_id)`**, add `UNIQUE(identity.channel, external_id)`.
- Backfill: every existing `wa_id` → one `person` + one `(whatsapp, wa_id)`
  identity; set `channel="whatsapp"`, `person_id` everywhere.
- Refactor the `wa_id`-keyed query layer to resolve **identity → person**. This
  is the bulk of the effort and the main risk (6 tables, the sync/idempotency
  paths, the agent's `ToolContext.wa_id`, RBAC scoping).
- **Rewrite `merge_customers` into a real merge**: re-point conversations,
  messages, order_events, customer_history to the surviving `person`; make it
  idempotent and reversible-by-audit.

### B. Channel ingestion (Messenger + Instagram first)
- Meta **Messenger + Instagram Messaging** use the same Graph webhook family as
  WhatsApp Cloud API — closest to what n8n already does. **TikTok has no
  comparable inbound messaging API for business DMs → explicitly out of the first
  phase** (revisit as social-listening, not conversation).
- Extend the n8n workflow (or add a sibling) to receive Messenger/IG webhooks,
  normalise to the existing `MessageDto` **plus `channel` + `external_id`**, and
  POST to `/api/n8n/message`. Reply path (`/outbound`) gains per-channel send.
- Per-channel media rules (IG/Messenger attachment fetch differs from WhatsApp).
- Meta app review + page/IG-account tokens + per-channel opt-in/24h-window
  policy compliance. **This is real Meta platform onboarding, not just code.**

### C. Linking UX + heuristics
- Manual link in the panel (operator: "these two are the same person") on top of
  the real merge from A.
- Assisted suggestions: same phone shared across channels (Messenger rarely
  exposes phone — low yield), name + recent-activity similarity, or a
  **verification handshake** (ask on channel B to confirm a code/detail from
  channel A). Keep suggestions advisory; never auto-merge on weak signals.

### D. Agent + CRM surface
- Agent memory/cart/lead-signals keyed by `person`, not `wa_id`, so context
  follows the human across channels.
- CRM panel: real per-channel history (the phantom breakdown becomes real),
  channel badges, "linked identities" section replacing `merged_ids`.

---

## 4. Sequencing & sizing (rough)

| Phase | Delivers | Rough size |
|------|----------|-----------|
| **0. Identity spine (A)** | `person`/`identity`, backfill, query-layer refactor, real merge. No new channel yet — WhatsApp keeps working. | **Large** (the hard part; migration + broad refactor + careful testing) |
| **1. Messenger ingestion (B, one channel)** | Receive+reply on Messenger through the agent; unified inbox. | Medium–Large (+ Meta app review lead time) |
| **2. Instagram DM (B)** | Same for IG. | Medium (mostly config once Messenger works) |
| **3. Linking UX (C, D)** | Manual + assisted linking, person-keyed agent, real channel history. | Medium |
| **TikTok** | Deferred — no business DM ingestion API. Track as attribution/social-listening only. | N/A this effort |

**Recommendation:** Phase 0 is worth doing on its own merits — it turns the
cosmetic merge into a real one and removes the `wa_id`-as-identity debt — even
before any second channel. Ship it first, then decide on Messenger based on
whether the Facebook/IG inbound volume justifies the Meta onboarding.

## 5. Risks / decisions to confirm with Moses
1. **Is Messenger/Instagram inbound volume actually there?** Phase 1 carries Meta
   app-review overhead; worth confirming demand before building.
2. **Phone is the only strong cross-channel key we have, and Messenger usually
   doesn't expose it** — linking will lean on manual + handshake, not automatic.
3. **Blast radius of the identity migration** — 6 tables + sync/idempotency +
   RBAC scoping + the offline mutation model. Must ship behind a `wa_id` shim
   with a reversible backfill.
4. **TikTok expectation** — set it now: no DM ingestion; it stays a lead-source
   tag, not a conversation channel.
