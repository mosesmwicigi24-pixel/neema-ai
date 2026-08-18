# Cost guardrails — why a $54 day can't sneak up again

The August 17 bill ($54.52 in one day) was found on the platform dashboard
*after* the account ran dry. This page maps every guard that now stands
between one AI call and a surprising day, from the smallest scope to the
largest — and what each one looks like when it trips.

## The ladder

| Scope | Guard | Where | Bound |
|---|---|---|---|
| One API call | `max_tokens` | `tier2_max_tokens` (1024) | output per call |
| One turn | tool-loop cap | `tier2_max_iterations` (8; comments 4) | calls per turn |
| One turn | history window | `_history(limit=20)` | prompt growth |
| One image | 1092px downscale | `agent/media.py` | ~1.2k tokens/image |
| One message | webhook dedup + debounce | WA token buffer; Meta `mid` (10 min); comments (7 d) | one turn per inbound |
| One stuck DM | **3 delivery attempts, then a human** | `reply_sweeper` | was ~276 turns/day |
| One follow-up | **3 attempts, then needs_approval** | `services/actions.py` | was ~1,440 turns/day |
| One post | comment cap / day | `meta_comment_agent_cap` (300) | viral-post fan-out |
| One comment | $0 fast path | identified post + bare price ask | no model at all |
| One order event | dedup 7 d + celebrate guard | `hub_events` | ≤1 turn per event |
| **One day** | **spend breaker** | `services/ai_budget.py` | the whole bill |

## The daily breaker (`services/ai_budget.py`)

Every metered turn (all channels, comments, drafts, sweeps, jobs — everything
through `run_turn`) adds its estimated cost to a redis counter keyed by UTC
day. Two rungs, both env-tunable, both deliberately set **above** a normal
post-overhaul day (~$28–36) — this is a breaker, not a target:

- **`AI_DAILY_BUDGET_USD` (soft, default $40) → economy.** Main-model turns
  downgrade to the light model (`tier2_model_light`). Every customer still
  gets an answer, at roughly a third of the price. One WARNING log line marks
  the switch.
- **`AI_DAILY_STOP_USD` (hard, default $60) → stop.** Agent turns refuse
  *before* buying a token. Customers get the existing hold line (once per
  thread per 2 h), threads get flagged to the team, and `/api/health` shows
  `"kind": "budget", "needs_a_human": true`. Public comments keep being
  answered at $0 from the canned sell pools (real product, real price, DM
  link). Clears itself at **midnight UTC**.

Set a rung to `0` to disable it. Everything fails **open**: if redis is down,
the meter skips and replies flow — the breaker can never be the outage.

### When it trips
1. `curl https://<host>/api/health` → `agent.kind` says `budget`.
2. Decide: expected heavy day → raise `AI_DAILY_STOP_USD` in the box env and
   restart the api container; runaway → read the 08:00 standup's per-node
   split (`facebook:comment`, `whatsapp`, …) to see where the money went.

## Honest metering

- The estimate table (`core/ai_pricing.py`) prices **unknown models at
  Sonnet-class rates** on purpose: a renamed model must trip the breaker
  early, never slip under it.
- The row logs the model that *actually served* the turn and the node
  (channel / `channel:comment`), so the standup's split is real.
- Unmetered leftovers (each a fraction of a cent, deliberately excluded):
  the comment intent labeler, call transcription, the daily standup draft.

## Defense in depth — the one thing only you can do

Our meter is an **estimate** on our side of the wire. Please also set a
billing alert on the platform itself (platform.claude.com → Billing) at about
$60/day — then a surprise would need to get past two independent meters.
