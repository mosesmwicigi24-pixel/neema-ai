# Instruction-Set Audit — Agent Neema

**Date:** 2026-08-12 · **Auditor:** Fable 5 (AI Systems Architect pass)
**Scope:** `apps/api/app/agent/prompt.py` (835 lines), the three channel addendums in
`runtime.py` (public comment / Meta DM / web), and the 23-tool command list in `tools.py` —
as deployed on `main`, cross-checked against 7 days of production data.
**Core loop protected:** Onboard → Pitch & Make Sale → Close Sale → Capture Records.

---

## 1. Executive Summary

**Overall health: strong, and structurally self-correcting.** This instruction set is not a
first draft — it is a battle log. Nearly every rule carries the name of the live failure that
created it, ~780 tests pin exact phrases, and three send-boundary code gates (links,
country-hedges, rapid echoes) enforce what prompts alone could not. Most critically, the
prompt now opens with an explicit precedence ladder (**WHEN RULES COLLIDE**, 6 ranks:
money-truth safety → complaints → answer-first → channel/brevity → discovery/close →
extras), which resolves conflicts *by construction* rather than by luck.

The audit found **no contradiction that breaks the core loop**. It found 2 genuine rule
collisions with undefined winners, 2 tool-level overlaps, 5 vague triggers, one premature-end
path, and one measurable records gap concentrated in the public-comment funnel. All are
resolvable without restructuring; proposed deltas are in §2–§4, sequenced architecture in §5.

**Production ground truth (last 7 days):** 5,395 active conversations, **99.4 % carry a
person record** (the identity spine holds — the structural half of "capture records" is
solved). Contact *completeness* is the open half: of 4,593 active persons, 11.5 % have a
phone, 13.3 % a name — dominated by Meta comment browsers who ask one price and leave.
`create_order` cannot complete without a phone, so **no order exists without a record**; the
gap is the pre-order funnel, quantified in §4.

---

## 2. Contradictions Found & Resolved

**C1 — Photo-companion upsell vs. IN-A-HURRY mode.** *PRICE WHAT IS IN THE PHOTO* mandates
naming the second visible item with its price and an add-on question in the same breath;
*READ THE ROOM → IN A HURRY* mandates one line, no pleasantries, **no upsell**. A terse
"how much?" under a photo triggers both.
**Priority rule:** *Mood outranks the photo exception. IF the customer reads as IN A HURRY,
THEN the reply is the primary item's price in one line; the visible companion is offered
only when the pace relaxes (next turn at the earliest).*
**Winner & why:** the mood ladder — it is the owner's explicit "read the mood, determine the
best reaction" directive, and serving pace *is* the human-likeness the set optimizes for.

**C2 — Gift-appeal pause vs. never-pause-a-buyer.** *GIFT REQUESTS* step 2 ends with
`pause_conversation`; the off-topic rule forbids pausing "a buyer, a complaint, or an open
order". A customer with an open order who then makes a hardship appeal sits in both.
**Priority rule:** *IF the person has an open order or items in cart, THEN the blessing-and-
close may be sent but `pause_conversation` is never called — the order thread stays live.*
**Winner & why:** never-pause — records/orders capture is non-negotiable, and pausing an
open order can orphan a paid customer.

**C3 — One-question law vs. PROBE SEPARATELY.** "Ask EXACTLY ONE question" vs. "keep the
clarifying question on its own line (or its own short message)… one thing at a time" can be
read as licensing a question *per line*.
**Priority rule:** *PROBE SEPARATELY governs FORMAT (where the one question sits — on its own
line, after the facts); the one-question law governs COUNT (one per message, full stop).*
**Winner & why:** both survive; they were never truly opposed — the ambiguity was the reading.

**C4 — Two capture tools, one duty.** `capture_customer` (core prompt: name/city/role/church
"the moment they share") and `capture_contact` (Meta addendum: same fields, same trigger)
overlap. A model told two names for one action sometimes calls neither.
**Priority rule:** *IF any identity fact lands (name, city/country, phone, role, church),
THEN call the capture tool available in THIS channel's kit in that same turn — the two names
are one duty.* Engineering follow-up: alias one to the other in `tools.py` so the dispatch
table, not the model, absorbs the difference.

**C5 — Brevity numbers drift across surfaces.** Core contract: "1–3 short sentences, ~40
words"; comment addendum: "2–4 short lines". Not a breaking conflict (rank 4 of the ladder
makes the channel rule win on its own surface) — flagged so future edits don't widen the
drift. **Resolution:** treat the core contract as the default and each addendum's figure as
a deliberate per-surface override, stated as such where it appears.

**Resolved-by-design (verified, no action):** buying-intent "close immediately" vs. the
two-step payment ask (the *ask* is immediate; the *link* still waits for yes — consistent);
upsell exceptions vs. the one-suggestion rule (the two exceptions are now named inside the
rule); stock-silence vs. `check_availability` (catalogue items are always available;
the checker is for the un-catalogued); WhatsApp invitation vs. sell-where-they-are (one
offer, in passing, never a redirect — internally consistent).

---

## 3. Ambiguities & Overlaps Resolved (IF / THEN rewrites)

| # | Vague text | Operational rewrite |
|---|---|---|
| A1 | "upsell only when it **genuinely fits**" | IF need fully settled AND no suggestion made this conversation AND candidate complements a cart line or their order history, THEN one suggestion, ≤2 lines. ELSE none. |
| A2 | "when a season is **close**, ask (once)" | IF `church_calendar` shows a season/feast within **21 days** AND it hasn't been mentioned, THEN one seasonal line, once per conversation. |
| A3 | "**after about three** off-topic turns" | IF 3 consecutive customer turns contain no Bethany-House business, THEN one kind close, then `pause_conversation` (subject to C2's never-pause guard). |
| A4 | "**If turns have passed** since you last looked a product up" | IF >5 messages or >10 minutes since this product's last `search_catalog`, THEN re-search before re-quoting. |
| A5 | "record `set_lead_source`… only when it **comes up naturally**" | IF the customer names where they found us unprompted, THEN record in that turn. NEVER ask for it. |
| A6 | "ask their city **when the order is being settled**" | IF delivery (not pickup) is chosen and city is unknown, THEN ask once in the delivery step. That is the only sanctioned location question. |

**Overlaps merged:** duplicate never-re-ask guidance (SLOT CHECK vs. CONTINUITY — keep both,
they guard different moments: pre-question vs. pre-reply); duplicate photo-identification
rules (PRICE-THE-PHOTO now cross-references READING-A-PHOTO's both-options rule — done in a
prior commit); C4's twin capture tools (above).

---

## 4. Execution Order Findings

**The mapped sequence, as the instructions actually order it:**
Greet (once, dayparted) → answer-first if they opened with a question → discovery, one slot
a turn (colour → gender → overlay → set → quantities) → grounded quote (tool prices only) →
cards → cart with running subtotal → "that's all" → delivery/pickup (city asked HERE) →
two-step payment ask → yes → `create_order` (**hard gate: requires phone**) → payment link
(KES) / human route (international) → contacts + thanks → after-sale arc via hub events.
**Verdict: the sequence respects the core loop.** Onboarding is capture-instrumented
(`capture_customer`/`save_parish`/`save_measurements`/`remember` all fire *the moment* facts
land, not at a form stage) — the correct design for chat.

**Gap G1 (premature end):** the gift-appeal pause (C2) — fixed by the never-pause guard.

**Gap G2 (records, quantified):** the public-comment funnel can end with a conversation +
post-identity record but **no contact record** — by design (public privacy forbids asking),
and it is why person-contact completeness reads 11.5 %. The capture surface for commenters
is the auto-sent private reply. *IF a commenter shows buying intent (quantity, "how do I
order", a price-flinch), THEN the reply must reference the private message once at close
("drop your number there and we'll arrange delivery") — the one sanctioned bridge.* Already
in the comment addendum; the metric to watch is below.

**Gap G3 (silent fizzle):** no instruction can force a customer to keep replying; the system
compensates outside the prompt (initiative follow-ups on kept promises, take-back scans,
scribed deals). Correct architecture — noted so nobody "fixes" it inside the prompt.

**Recommended instrumentation (not prompt changes):** add one nightly QA metric —
*conversations that reached cart or payment stage in the last 24 h with no phone on file* —
so the only records gap that costs money is watched by the standup, not by audits.

---

## 5. Revised Sequential Instruction Draft

The live prompt already implements the correct order; what follows is the **canonical
architecture** future edits must preserve, with the audit's deltas folded in. (The full text
lives in `prompt.py`; wholesale replacement would discard ~780 pinned regression tests for
zero behavioral gain — the deltas in §2/§3 are the deployable change set.)

0. **Precedence ladder** (exists): money-truth safety → complaint/grief → answer-first →
   channel rules & brevity → discovery/close → extras. **Delta:** add rank note — *mood
   modifiers (IN A HURRY, GRIEF) bind at rank 2½: they modulate every lower rank.* (C1)
1. **Onboard:** dayparted greeting once · title kept · location never asked, read from cues
   (IP/prefix/language) · capture-on-utterance tools · answer-first override.
2. **Pitch:** grounded quotes only (tool, this conversation) · same-name families · no-price-
   is-not-free · photo pricing (mood-gated, C1) · cards · mood ladder · slot discovery ·
   never-dump-menu · stock silence · availability confirm-never-deny.
3. **Close:** cart with running subtotal · delivery step (the one city ask, A6) · two-step
   payment · `create_order` phone gate · KES link / international human route · "paid" is a
   claim until the hub confirms.
4. **Capture (continuous, not a stage):** `capture_customer`≡`capture_contact` (C4) ·
   `save_parish` · `save_measurements` · `remember` · `set_lead_source` (A5) ·
   `schedule_check_in` — each fires the turn its fact lands; deals scribe files the rest.
5. **After-sale & guardrails:** complaint runbook (acknowledge→find out→tell→`raise_complaint`
   →stay) · gift-appeal close with never-pause guard (C2) · WhatsApp invitation once ·
   off-topic three-strikes (A3) · send-boundary gates (links, country-asks, echoes) as the
   last word on their rules.

---

*Method note: every finding was checked against the deployed text on `main` at audit time and,
where measurable, against production (record-completeness query, 2026-08-12). Deltas are
small by intent — this set's strength is that its rules are earned, tested, and enforced;
an audit's job here is alignment, not rewriting.*
