# Unfinished and Unverified Work Register

Nothing silently omitted. Each row: what the directive asked · exact state ·
the precise dependency · status. Last update: 2026-11-06, end of session 1.

## Blocked on access or inputs only the owner can provide

| Item | State | Dependency | Status |
|---|---|---|---|
| Real-model evaluation baseline and before/after (§5, §6, W10) | harness built and tested model-free (`agent_eval --cases`); never run against the model | a model key: on the box (`docker compose … exec -T api python -m app.jobs.agent_eval --cases --held-out --repeat 3 --out … --packet … --history`) or the `ANTHROPIC_API_KEY` repository secret for the `agent-eval` workflow | BLOCKED |
| Production-derived, anonymised cases (§5) | 0 of the set; the independent cases stand in | the dashboard admin credential saved in the secure form (from a browser), then `GET /api/admin/conversations` + trace reads; anonymisation step to write | BLOCKED |
| `NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` (§2) | not found anywhere reachable | the owner adds it under `docs/` | BLOCKED |
| Live flag values on the box (§2.12) | 22 default-off flags whose production value is unknown | credential → `GET /api/admin/settings/prompt-inputs` and health; or the owner reads `.env` | BLOCKED |
| Human rater scores: emotional (W3), consultative (W4), naturalness (dim 9) | rater packet generator built (`--packet`); no raters, no ratings | the owner names raters (team members, not the developers) and a date; the packet needs the real-model run first | BLOCKED |
| Native-speaker review of the Swahili, French, Portuguese and Sheng cases (W8, §5) | 100 language cases written by an independent author who flagged items to check; `audit.jsonl`'s Hindi reconstructed | native speakers named by the owner | BLOCKED |
| Blind comparison Neema vs skilled human sellers vs a reference agent (§5, §10) | design in EXCELLENCE_SCORE; nothing run | the real-model run, two human sellers answering the same held-out cases, a reference agent with the same tools | NOT STARTED |
| Customer-rated experience (dim 10, §7) | NOT YET MEASURED on the dashboard | an approved post-conversation rating ask (an unprompted message: owner approval) | NOT STARTED |
| Inter-rater agreement on labels (§5) | one rater per case | a second labeller on a 60-case sample; κ reported | NOT STARTED |

## Implemented but not verified in production or with the model

| Item | What exists | What verification needs |
|---|---|---|
| W1-1 gate fails closed | code + unit tests | a gate error in production (tally `held/gate_error`) or an eval run with an injected gate fault |
| W1-2 opt-out door on Meta/TikTok/web | code + unit tests | a real "stop" on Messenger with `meta_agent_reply` on |
| W1-5 takeover re-check fails closed on DB errors | code + unit tests | a DB outage, or a fault-injection test on the box |
| W1-9 paid-acknowledgement rule, W4-1 pressure rule, W8-1 language rule | rule-level tests | the real-model run's `failure_kinds` and `review` tallies; watch for false holds |
| W7-4 empty reply = silence | code + source test | real-model run: `silent` turns on closers/overlaps, no stall line |
| W7-3 prompt contradictions resolved | prompt text | real-model run: questions per reply, length vs target |
| W2-1 floor effect on live replies (holds, paid-claim notes, closer silence) | floor measured model-free | real-model run |
| §7 Performance view | API + DB test + web build | the owner opens it; metrics populate from production data |

## Not done, by decision (recorded)

| Item | Why | Where recorded |
|---|---|---|
| Deferring product-card sends until after the gate (W1-6) | would create a worse failure (words promising cards that then fail) | ADVANCEMENTS_REGISTER W1-6 |
| Refusing an order when the promised offer cannot be read (W1-7) | the owner's recorded trade-off prefers the order; the gap is now surfaced | W1-7 |
| A DB-side idempotency key for orders (W9-3) | needs a migration (owner approval) | INVESTIGATION 9.3 |
| Context-engineering experiment (W7-1: structured state object vs raw history) | must be a controlled comparison on the held-out set; needs the model | INVESTIGATION 7.1 |
| Prompt shortening / SELL LIKE A CONSULTANT rewrite (W4-3) | no blind cut; replay comparison first | INVESTIGATION 4.3 |
| Delivery total consistency (W6-2), `payment_url` key rename (W6-1) | prompt/tool contract changes to be measured with the model | INVESTIGATION 6.1–6.2 |
| Retiring the legacy bridge order path and the expiring receipt shortener (W9-4) | removes a code path hub events may still use; needs a production trace first | INVESTIGATION 9.4 |
| Turn latency instrumentation, availability history, resolution definition | named on the dashboard as NOT YET MEASURED with what each needs | performance.py |

## Opened by verification pass 1 (not fixed in this slice)

| Item | Why open | Where |
|---|---|---|
| Unverifiable takeover → the sweeper re-composes the turn (tools may act twice) | persisting the composed reply for the retry needs a small store; trade-off recorded | 1.5 |
| Comment dedupe is redis-only; a 502 redelivery with redis down could answer a comment twice | DB-side comment id dedupe | 1.6 |
| The blind set must be scored before any held-out claim; the runner cannot exercise the Meta/TikTok/web doors or an overlap silence (WhatsApp contacts, sequential turns) | runner channel parameter; concurrent-turn harness | 6, 13 |
| Four register rows rest on source-string tests (W3-1, W7-6, W10-3, W2-4 wiring) | downgraded; behaviour tests to add | 2 |

## Open owner decisions carried from earlier stages

- the scope of "pause after two unanswered";
- whether to retire the 360 parked outreach rows older than 30 days;
- Android inbox fields (customer state, badge) — API exposes them, app untouched by instruction;
- whether the Sunday house-voice refresh stays automatic.
