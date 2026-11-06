# Outbound communication — shadow week and rollout (Stages 4–5)

The corrective programme of 2026-11-05 (PR #310, Stages 1–3) ships with
every new contextual rule in **shadow** and every safety rule **on**. This
is the runbook for the week after the deploy and for turning enforcement
on. Nothing here sends a customer a message; the verification reads what
the live system already records.

## 0. What the deploy changes (and what it does not)

Deploy = merge to `main` (Build & Push runs on `main`; the box pulls the
image; `alembic upgrade head` runs at container start and applies
`e8a1c3d5f7b9` — two columns, a backfill of OPEN `agent_actions`, a merge of
open duplicates with a visible reason, a partial unique index).

Always on from the first minute (correctness, never shadowed):
opt-out; one message per customer per tick; an open team check holds sales
follow-ups; template purposes; a payment reminder re-reads the hub; a
customer's own hold ("give me time / comparing / consulting") defers
unprompted sales rows; a language outside en/sw/fr parks unprompted rows
for a person.

In shadow (sent as before, but recorded): the three contextual rules —
customer wrote after planning, a colleague replied after planning, one
unprompted sales message per Nairobi day.

Retired: the 15:00 re-engage sweep (owner decision 2).

## 1. Box configuration

| Variable | Default | Meaning |
|---|---|---|
| `OUTREACH_MODE` | `shadow` | `shadow` sends and records what `enforce` would have done; `enforce` holds. Flips without a deploy (restart the api). |
| `CUSTOMER_STATE_NOTE` | `true` | the light-model note after real turns (floor-only when `false`). |
| `CUSTOMER_HOLD_DAYS` | `7` | how long a bare "give me time" holds unprompted sales rows. |
| `RECOVERY_CART_ENABLED` / `RECOVERY_PAYMENT_ENABLED` | as today | the planners that file `buying_follow_up` / `payment_reminder` rows. |
| `WA_EVENT_BODY` | empty | the approved order-update template body (`{1}{2}{3}`) so the inbox shows the customer's exact words. |
| `WA_FOLLOWUP_TEMPLATE` | empty | an approved follow-up template; until set, a deciding customer's check-in outside the window waits for a person. |
| `RECOVERY_REENGAGE_ENABLED` | — | ignored now; can be removed from `.env`. |

## 2. Reading the shadow week (Stage 4)

Daily, no customer contact involved:

1. **The 08:00 standup** line "🧭 Outreach: yesterday the contextual rules
   would have held N and deferred M …" — the redis tally
   `outreach:shadow:YYYYMMDD` (14-day expiry).
2. **The rows**: every outbound an unprompted path sent carries
   `messages.raw_meta` with `kind="outreach"`, `class`, `planner`,
   `reference` and, in shadow, `shadow=["suppress: …"]`. Deals → Needs
   approval shows parked rows with their reason in `agent_actions.reason`
   (`[merged: …]`, `[they write in 'hi' — …]`, `sent? outcome unknown — …`).
3. **One thread**:
   `docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api python -m app.jobs.outreach_trace <number> --days 7`
   — origin of every outbound row, delivery status, the planned actions in
   every status, the deal's hold / team check / blocking, contact
   preferences, redis guards. Read-only; the number is masked in the heading.
4. **The log**: one line per decision, contact masked —
   `outreach actions whatsapp/…1234 shadow-suppress: the customer wrote after this was planned …`
   (`grep "outreach " ` on the api logs). Verdicts: `go`, `send`, `hold`,
   `park`, `defer`, `suppress`, `shadow-*`, `enforced_*`.

Questions the week answers, per the brief:

- Of the rows shadow would have **suppressed**, how many went to a customer
  who had in fact just written or been answered by a colleague? (Each one
  is a message the audit set out to remove.)
- Of the rows shadow would have **deferred** (second unprompted sales
  message of the day), did any recover a sale the first did not?
- Did any **hold** or **park** stop a message a person then judged should
  have gone? (Deals → Needs approval; the person's tap is the override.)
- Any `sent? outcome unknown` rows: did the thread show the message
  delivered (then the row is closed by hand), or not (then a person
  resends by hand — the system never does)?
- The regression threads (Judas, Willy, Pastor Emmanuel): trace each once
  mid-week; expected = no duplicate commitment, no second greeting, nothing
  while a team check or a hold is open.

## 3. Turning enforcement on (Stage 5) — from the dashboard, one rule at a time

Settings → **Unprompted messages** (admin only; `GET/PUT /api/admin/settings/outreach`).
The card shows the mode, each rule with how often it fired yesterday + today,
and switches. Nothing here needs SSH or a restart: the dispatcher reads the
control at the start of every sweep (redis-cached, 5 min; a change clears the
cache at once).

| Control | Meaning |
|---|---|
| Mode `shadow` (default) | every contextual rule records what it would do; messages still go |
| Rule switch (while in shadow) | that one rule is enforced; the others stay in shadow |
| Mode `enforce` | every rule enforced |

The environment (`OUTREACH_MODE`, `OUTREACH_ENFORCE_RULES`) is only the
default before anyone touches the card; the card's rows override it for good.

Recommended order, each step under the owner's explicit approval (it changes
which messages live customers receive):

1. After the shadow week: enforce **the customer wrote after planning** and
   **a colleague replied after planning**. Both are near-certain — the thread
   already carries an answer — and the read-out shows how many messages each
   would have held.
2. A week later, on the tally: enforce **one unprompted sales message per
   customer per day**. This one trades recoveries for restraint; read
   Reports → recovery outcomes for the week before deciding.
3. Mode `enforce` once all three are on (equivalent; keeps the card simple).
4. Watch the next two standups and `/api/health` → `outreach`:
   `enforced_suppress` / `enforced_defer` should match the shadow counts of
   the week before; `rows.needs_approval` should not grow.

Rollback of any step: flip the switch back. Nothing is lost — rows the rule
held are vetoed with their reason and visible under Deals → Needs approval;
rows it deferred come due the next morning.

## 4. Rollback

- Config only: `OUTREACH_MODE=shadow` returns to send-and-record at once;
  `CUSTOMER_STATE_NOTE=false` leaves the deterministic floor alone.
- Code: revert the PR and redeploy. The migration's downgrade drops the
  index and the two columns; rows merged by the migration stay vetoed with
  their reason (the newest booking of each commitment was kept and still
  goes). State written to JSONB meanwhile (`persons.state.contact_preferences`,
  `persons.state.customer_state`, `deals.next_action.hold` / `team_check`,
  `messages.raw_meta` stamps) is inert to the previous code.

## 5. Owner-side items that unlock more

- A follow-up template approved in WhatsApp Manager → `WA_FOLLOWUP_TEMPLATE`
  (a deciding customer's check-in can then keep its day after the window).
- The order-update template text → `WA_EVENT_BODY`.
- A Swahili template, if wanted: today templates are English.
