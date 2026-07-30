# Neema: from responder to agentic partner — the build plan

Two threads, one build: (1) true agency — Neema owns outcomes, acts first,
hears the results of her actions; (2) true partnership — every autonomous
capability ships with a **window** (you see it), a **handle** (you steer it),
and a **lesson-collector** (it learns from you).

Everything ships behind a per-phase flag (default OFF), verified in the Docker
harness, deployed dark, then flipped — the WHATSAPP_NATIVE playbook.

---

## Phase E — Standing Orders (first: smallest, immediate steering wheel)

**What:** an operator-editable directives box Neema obeys every turn —
"push copes this week", "Easter rush: quote 3-week lead", per-deal guidance.

- `operator_directives` stored in a new `app_settings` KV table (id, value,
  updated_by, updated_at) + `GET/PUT /admin/settings/directives` (crm.py
  pattern; permission `manage_settings`).
- Injected into `build_system_prompt` as a `STANDING ORDERS FROM THE TEAM`
  block, hard-capped at 600 chars, with the rule: *directives never override
  pricing/stock/payment safety rules*.
- Settings UI: one textarea + "Neema reads this before every reply" hint.
- Tests: injection present/absent; cap enforced; safety-rules precedence line.

**Size:** ~half a day. **Flag:** none needed (empty box = no-op).

---

## Phase A — Event Agency (revenue first: she hears what her actions caused)

**A1. Hub → Neema event webhook.**
- Hub repo (`bethany-house`) PR: emit `POST {neema}/api/hub/events` with HMAC
  (`X-Hub-Events-Signature`, shared secret) on: `order.paid`,
  `order.production_started`, `order.shipped` (+tracking), `order.delivered`,
  `order.delayed`, `payment.partial`, `refund.requested`. Payload: event id,
  order id/number, customer phone, items, amounts.
- Neema: new `routers/hub_events.py` — HMAC verify, redis idempotency on event
  id, resolve person/conversation via phone (identity spine), enqueue handling.
- Settings: `hub_events_secret` (endpoint 503s while empty — inert by default).

**A2. Celebrations are hers (auto-send).**
Two payment sources, one behaviour: hub `order.paid` events AND Neema's own
M-Pesa reconciler (a direct paybill payment matched to a person/open deal fires
the same internal event — money that skips hub checkout still gets thanked).
`order.paid` → instant warm confirmation + what happens next;
`production_started` → "the workshop has begun"; `shipped` → tracking;
`delivered` → aftercare + gentle review ask.
- Compose via `run_turn` in a constrained "announce" mode (event context
  injected, read-only tool set + no discovery) so the message is personal, not
  a template.
- **24h-window law:** outside the WhatsApp window → send approved template if
  `WA_EVENT_TEMPLATE` configured, else surface as a planned action for a human.
  Quiet hours (08–20 Nairobi) respected; queue until morning.
- Persist to thread + ws broadcast (the inbox shows what she sent and why —
  the *window*).

**A3. Disappointments are yours (draft + ping).**
`order.delayed` / `payment.partial` / `refund.requested` → Intercept row +
`ws:channel:agents:all` notification + a ready draft attached to the composer
(read_only `run_turn`). The human sends, edits, or ignores — the *handle*.

- Tests: HMAC + idempotency; event→person resolution; celebration vs
  disappointment routing; window/quiet-hour gating; announce-mode tool lockdown.

**Size:** 1–2 days Neema-side + a hub PR. **Flag:** secret unset = off.

---

## Phase F — One Memory Across Voice and Text (cheap; slots right after A)

**What:** calls and chat are separate brains today — a customer discusses
everything on a call, then messages, and Neema has no idea the call happened.
The transcripts/summaries already sit in the `calls` table; they just never
reach the agent.

- `run_turn` context: inject a compact `RECENT CALLS WITH THIS CUSTOMER` block
  (last 3 call summaries for the person, dated) ahead of the history — so
  "as we discussed on the phone" is real.
- Handoff briefings (C1) and the deal extractor (B1) read the same block.
- Sidebar already shows transcripts; no UI work.
- Tests: block present when calls exist, absent otherwise; caps (3 calls,
  ~200 chars each); person-resolution across channels.

**Size:** ~half a day. **Flag:** none needed (no calls = no block).

---

## Phase B — Deal State + Initiative (she owns outcomes, visibly)

**B1. The Deal object (shared board's spine).**
- `deals` table: id, person_id, conversation_id, title, items_snapshot JSONB,
  stage (mirrors lead pipeline), blocking TEXT, next_action JSONB
  `{kind, due_at, owner: ai|human, note}`, guidance TEXT (operator-editable,
  injected into her prompt for THIS deal), status (open/won/lost), timestamps.
- Created/updated by a cheap post-turn extractor (not the selling prompt):
  after each agent turn, a rules-first pass (cart changed? order created?
  explicit "waiting on X" in reply?) updates the deal; LLM-lite fallback only
  when rules are ambiguous. The seller sells; the scribe files.

**B2. Planned-actions queue (initiative with a veto window).**
- `agent_actions` table: id, deal_id, due_at, kind (follow_up | promise |
  event_fallback), draft TEXT, status (planned | needs_approval | sent |
  vetoed | done), created_by (ai|human), reason.
- In-process scheduler (asyncio loop, 60s tick, redis leader lock — the sweep
  infra pattern): due `planned` → compose draft (read_only) → sensitivity gate
  → auto-send OR flip to `needs_approval` + notification.
- Sensitivity gate (starts conservative): total > KES 50k, upset-flagged
  thread, >2 prior nudges, human-touched deal → always needs approval.
- Promise detection to SEED the queue, narrow first: Neema's own "let me
  confirm/check and get back" → auto follow-up in 3h; customer's "I'll confirm
  tomorrow / after the meeting" → next-morning nudge. Regex + timeword parse in
  post-turn; LLM only for date resolution.

**B3. The Deals board (the window + the handle).**
- Dashboard view: columns by stage; card = customer, items, blocking, next
  action + countdown, owner chip (Neema/You). Card actions: take it / give it
  back / edit due time / edit guidance / veto planned action / approve
  needs_approval (one tap, draft pre-filled).
- Endpoints: `GET /admin/deals`, `PATCH /admin/deals/{id}`,
  `POST /admin/actions/{id}/approve|veto`.

- Tests: extractor rules; scheduler leader-lock + due selection; gate
  thresholds; approve/veto transitions; promise parser table-driven cases.

**Size:** 2–3 days. **Flag:** `DEALS_ENABLED` (board renders read-only from
day one; auto-sends gated separately by `AGENT_INITIATIVE`).

---

## Phase C — Copilot Mode (human-held conversations keep BOTH workers working)

**C1. Handoff briefing:** on intercept flip → read_only summary note into the
thread (why escalated, what's settled, suggested opening) + sidebar card.
**C2. Continuous drafting:** in human mode, each inbound triggers a background
draft (debounced, read_only) pushed over ws into the composer as a dismissible
suggestion. Toggle per conversation; off for notes.
**C3. Scribe mode (fixes today's CRM blindness):** in human mode, after each
exchange, run a capture-only pass — tool set {capture_customer,
save_measurements, save_parish, remember, deal-update}, **no reply, no sends**
(the read_only machinery inverted: write CRM, never speak). Everything the
human's conversation reveals still lands on the profile.
**C4. Take-back chip:** resolved + idle N hours (default 4) → notification
"Take this back?" → one click releases to AI with a context recap turn.
**C5. Ask-Neema sidebar (facts on demand):** a small query box in the customer
sidebar — "what were his sizes?", "what did he order last Easter?" — answered
by a read_only turn over this person's history, orders, measurements and calls.
The human never digs; the junior fetches.

- Tests: scribe tool lockdown (must never send/order); briefing generated on
  flip; draft ws contract; idle detector.

**Size:** 1–2 days. **Flag:** `COPILOT_MODE`.

---

## Phase D — Learning Loops (your corrections become her behavior)

**D1. Correction capture:** when a human edits an AI draft then sends, store
the (draft, sent) pair in `agent_feedback` (+ conversation id, distance).
Wire: composer knows draft origin; include `draft_of` on the reply POST.
**D2. Nightly self-QA sweep:** sample yesterday's conversations, grade against
her own contract (slot re-asks, price vs tool mismatch, unanswered questions,
missed close after buying signal) — findings table + links.
**D3. Morning standup:** one dashboard notification (and template-gated
WhatsApp to the owner if configured): closed/КЕS totals, misses with links,
deals needing a human today with reasons, one proposed rule change.
**D4. Weekly distillation:** corrections + QA findings → up to 3 proposed rule
changes in Settings; approving appends to `learned_rules` (app_settings, hard
cap, shown in prompt under standing orders; rejectable anytime).

- Tests: correction pairing; QA graders on synthetic transcripts (reuse the
  audit fixtures); distillation cap; standup composition.

**Size:** 1–2 days. **Flag:** `LEARNING_LOOPS` (capture always on — passive).

---

## Cross-cutting laws (every phase)

1. **24h WhatsApp window:** no free-form outbound outside it — template or
   human, never a policy violation.
2. **Quiet hours** 08:00–20:00 Nairobi for anything Neema initiates.
3. **One writer:** all agent-initiated sends go through `schedule_reply`-grade
   dedup so retries/leader-failover never double-message.
4. **Migrations:** alembic chain + mirrored idempotent DDL in
   `MIGRATION_STATEMENTS` (deals, agent_actions, agent_feedback, app_settings).
5. **Dark deploys:** flags default off; flip per phase after a live smoke test;
   every phase independently revertible.
6. **Adversarial review** (the workflow panel) on each phase's diff before
   deploy — it has caught real bugs in 3 of the last 4 features.

## Measurement (so "better partner" is a number, not a feeling)

- Payment→confirmation latency (target: <60s from A2, from hours today).
- Follow-up conversion: % of planned actions that get a customer reply.
- Human minutes per closed deal (copilot should cut it).
- Capture completeness in human-held threads (scribe: from ~0% to parity).
- QA violation rate per 100 conversations, week over week (learning loop).

## Sequence & effort

| Order | Phase | Effort | Depends on |
|---|---|---|---|
| 1 | E — Standing orders | 0.5d | — |
| 2 | A — Event agency | 1–2d + hub PR | hub webhook |
| 3 | F — Voice+text memory | 0.5d | — |
| 4 | B — Deals + initiative | 2–3d | A (events feed deals) |
| 5 | C — Copilot mode (incl. Ask-Neema) | 1.5–2.5d | F (calls in briefings) |
| 6 | D — Learning loops | 1–2d | C (draft-origin wire) |

Roughly a week and a half of focused builds, each phase live and verified
before the next begins.
