# Stage 3 — customer intelligence (development branch only)

Commits on `claude/where-are-we-bx9v9w` on top of Stage 2 (6966080) and its
close-out (55c2658). **Not deployed; no migration in this stage.**

## 1. Files and functions changed

New
- `app/services/customer_state.py` — the whole stage lives here:
  `floor()` (deterministic reading: stop › paid claim › complaint › consulting › comparing › needs time › ready › closing; en/sw/fr), `guess_language()` (script first, then Swahili by word list and verb shape, then French, then English), `note()` + `parse_note()` (the light model's JSON note, no tools, defensively parsed), `apply()` (what a reading writes), `after_turn()` (floor first, note only when the floor is silent and a key is configured), `hold_open()` / `hold_for()` / `language_for()` / `automated_ok()` (what the dispatcher asks), `turn_note()` / `live_note()` (what the next live turn is told), `note_llm()`.
- `tests/test_outreach_stage3.py` (51), `tests/test_outreach_stage3_db.py` (5, real Postgres; added to CI's Migrations job list).

Changed
- `app/services/deals.py` — `_CUSTOMER_PROMISE_RE` now hears "I will contact / call / message / text / remind / consult / ask / discuss … you on Thursday"; `scribe_update` reads the floor, opens a deal for a request for time or a payment claim even before a cart, and calls `customer_state.after_turn` after its own commit (a failure there never loses the scribe's work).
- `app/services/actions.py` — `process_due`: before the contextual decision, and never shadowed: an open hold moves every unprompted sales row (`routine`) to the day the customer named; a stored language outside en/sw/fr parks a routine row, or any row outside the window, as `needs_approval` with the reason "they write in 'hi' — a person should write this".
- `app/agent/runtime.py` — the live turn gets a `(CUSTOMER STATE: …)` note: the hold and its day ("do NOT ask again when they will decide, do NOT re-pitch"), an item still under team confirmation, a payment claim ("never announce it as received").
- `app/agent/prompt.py` — WHEN RULES COLLIDE gains rank 5, "What THEY said about buying", above discovery, the close and extras; items renumbered 6 and 7.
- `app/routers/admin.py` — inbox rows carry `customer_state` (what they last said) and `language`.
- `app/core/config.py` — `customer_state_note` (default on; silent without an API key), `customer_hold_days` (7).

## 2. Root causes addressed

| Audit | Correction |
|---|---|
| intent understood by the reply, invisible to the schedulers (§1.1 Willy: "I'll compare in Arusha" → nudged anyway) | the floor writes a HOLD on the deal; the dispatcher defers every sales row to the named day (or a week); the next live turn is told not to re-ask or re-pitch |
| language never stored; English templates and composed nudges to a Hindi-speaking pastor (§1.1 Pastor Emmanuel) | language on `persons.state.contact_preferences.language` from their own words; unprompted automation parks for a person outside en/sw/fr; the live turn still answers in their language |
| "I have already paid" treated as a sales turn | recorded on the deal as a claim awaiting the hub; never marked paid; the next turn thanks and waits for the hub's confirmation |
| customer promises recognised only for a few verbs | the contact/consult verbs added; one `customer_promise` row per deal under the Stage 2 identity |
| prompt: "advance to the next slot" vs "wait" with no order between them | precedence rank 5 settles it; no instruction removed — the review found the repeats (check-in rule in two blocks, greeting in three) consistent with each other, so they were left rather than rewritten under test pins |

## 3. Design decisions and alternatives

- **Floor before model, model never decides "send".** The deterministic floor is the guarantee for the phrases the audit found; the note (haiku-class, ~400 tokens, no tools) adds coverage for phrasings the floor misses. Any reading, from either, can only set state the dispatcher treats as *wait* or *ask a person*. Alternative rejected: a model call on the dispatcher's path at send time (cost per tick, and a model deciding to send).
- **A hold is deal state, not a row status.** It lives in `deal.next_action["hold"]` beside the scribe's own `kind` (customer_promise, team_check survive untouched) and is read by `hold_for()`; a new column was not needed and the Deals board already shows `blocking` ("Comparing prices — until 09 Nov"). Clearing: the customer's next real buying message (exploring/quoting/ready), or the day passing.
- **Default hold of 7 days** for a bare "give me time"; a named day holds until 10:00 Nairobi that day. Tunable (`CUSTOMER_HOLD_DAYS`).
- **A promise still goes during a hold.** "I'll contact you on Thursday" books the Thursday check-in (class promise) and holds the sales nudges until Thursday; on Thursday the check-in goes and the nudge behind it is merged by the Stage 1 one-message rule — one message.
- **Language gate = scripts we cannot automate**, not "anything but English": Swahili and French customers keep their composed follow-ups (the composer writes in their language); Hindi, Arabic, Amharic and other scripts park. English templates to a Swahili customer are unchanged behaviour, flagged below.
- **Precedence line added rather than text removed** — stated plainly as a deviation from "remove rather than add": the duplicates found agree with each other, and two are pinned by existing tests; the conflict was one of rank, which a rank fixes.

## 4. Tests executed

- `tests/test_outreach_stage3.py` 51 passed: the floor in three languages (and its silence on questions and ordinary messages), the named day, language detection incl. Devanagari/Arabic, note parsing, floor-before-model with no tools, no model without a key, hold/clear/paid-claim/team-check on fakes, the live note, the widened promise verbs, the prompt rank, the hook order in the scribe and the dispatcher.
- `tests/test_outreach_stage3_db.py` 5 passed on a real Postgres: **Willy** (comparing in Arusha → nudge held a week, not sent even in shadow, live note set; returns → hold lifts, nudge goes once), **Pastor Emmanuel in Hindi** (language stored, cart nudge parked for a person, nothing sent), **"consult the committee and contact you on Thursday"** said twice (one promise row, hold until Thursday 10:00, nudge waits for Thursday, promise goes when due, nudge merged), **"I have already paid"** (claim recorded, deal still open, note for the next turn), **language switch** sw → en.
- Neighbouring suites (stage 1/2 unit + DB, deals, quote follow-up, audit fixes, prompt audits, companion upsell, deferral, actions): green. ruff 96 (= Stage 2, baseline 115). `import app.main`: ok.
- Full suite (local, real Postgres): 3024 passed, 0 failed, 1 xpassed. CI on aa2b5a2: every check green — API tests, Migrations (single head + fresh-DB replay, with the Stage 1–3 Postgres suites), import smoke, lint ratchet, web typecheck + build, Docker build.

## 5. Known limitations and remaining risks

- The note runs after every real turn where the floor is silent (one light completion); it is on by default and off without a key. Cost is metered under purpose `state`; if the owner prefers, `CUSTOMER_STATE_NOTE=false` leaves the floor alone.
- The floor is conservative by design (a comparison inside a question is ignored); the note covers the rest, and both are visible on the person (`customer_state.source`).
- A hold suppresses *unprompted sales* rows only; care rows (fit check, payment reminder) and kept promises still go — intentionally.
- The Meta (Messenger/Instagram) live turn shares the scribe hook, so holds and language apply there too; inbound-id overlap handling for Meta is still outstanding from Stage 1.
- Approved WhatsApp templates are English; a Swahili or French customer outside the window still receives the English template (unchanged). A Swahili template is an owner-side approval.
- The inbox shows the new fields only once the web/Android clients read them (API-side only in this stage; nothing in the apps changed).

## 6. Customer-experience impact (when deployed)

- "Let me compare prices" / "I must ask the bishop" / "give me time" is heard once and respected: no nudge until the day they named, and the next reply neither asks "when will you decide?" nor re-lists the items.
- A customer who writes in Hindi is answered in Hindi by the live turn and never receives a machine-written English follow-up; a colleague sees the parked row with the reason.
- "I already paid" earns thanks and a wait for the hub, never a premature confirmation or a payment chase.
- "I'll contact you Thursday" produces exactly one Thursday message.

## 7. Migration and rollback

- No migration; new state lives in existing JSONB (`deals.next_action.hold`, `persons.state.customer_state`, `persons.state.contact_preferences.language`) and is inert to earlier code.
- Rollback = revert the commit. Flags without a deploy: `CUSTOMER_STATE_NOTE`, `CUSTOMER_HOLD_DAYS`.

## 8. Decisions requested

1. Approve the Stage 3 commit for the staged PR (merge = deploy, held for your word).
2. Default hold length for a bare "give me time": 7 days, or shorter?
3. Keep the model note on from day one (recommended; it is read-only and metered), or floor-only for the shadow week?
