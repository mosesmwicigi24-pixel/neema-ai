# Conversational Naturalness & Social Intelligence (slice 20)

Owner's directive, 2026-11-10. Status: **slice 20 merged on the owner's word ("merge 369", 4b56485)**; slice 20b (§5b, from the owner's screenshots) is on the branch, tested without the model.

## 1. What was investigated

| Area | Where | What it does today |
|---|---|---|
| Comment engine | `agent/runtime.py` `_run_comment_engage` | Reads each comment (`read_comment`), plans public reply / DM / human, answers through `run_turn(public_comment=True)` or a canned pool |
| Campaign (giveaway) handling | `is_campaign_post`, `_host_reading`, `_campaign_context`, `_campaign_facts`, `_campaign_canned` | Host framing: a gift, never priced, never "win"; the owner's own reply (2026-09-26) given as "the shape of your reply" |
| Thread memory | `_history(post_id=…)`, `_thread_rows` | The model already sees this person's earlier comments and our replies under the same post |
| Closer silence (DMs) | `agent/cooling.py` `silence_decision` | A bare thanks / ok / amen / thumbs-up gets nothing back — DMs only |
| Slice 19 | `services/buyer_intent.py` | Request ladder; skipped on public comments and when the turn carries a campaign caption |
| Commercial EI, register | `agent/prompt.py` | Calm register, brevity contract, "never repeat yourself" |

## 2. Findings — why replies read as mechanical

1. **The campaign brief was a script, applied to every comment.** `_campaign_context` handed the model the owner's full first reply ("Hello Pastor, welcome to Bethany House! … selecting one recipient … Follow us … May we have your name, church and town?") as the shape of the reply on *every* turn. A person who nominated a pastor and then supplied the church got the welcome and the selection procedure again.
2. **Every comment with a letter in it was promoted to a full model answer under a campaign.** `_host_reading` lifts "Amen", "Thank you", "Ok" to `high`, so a returning person's acknowledgement drew another full host reply.
3. **The closer-silence rule did not exist for comments.** It protected DMs only.
4. **Over the model cap, a returning entrant got the stock line again** ("Thank you for joining in … We've received your comment").
5. **Two prompt lines prescribed habit.** "Every reply moves acknowledge → answer → advance" and "Vary your acknowledgements ('Noted', 'A fine choice', 'Thank you — noted')" taught a rotation of stock openers.
6. **Slice 19 and giveaways.** Safe where the campaign caption is in the turn. Not safe for a message about the giveaway that arrives without post context (for example a WhatsApp "I nominate my pastor for the free cassock"): the request ladder could answer it with the gift boundary.

## 3. Conflicts with established rules, and how each was resolved

| Established rule | Conflict | Resolution |
|---|---|---|
| Owner's campaign reply as the shape (2026-09-26) | Recited on every turn | Kept for the **first** answer, marked "substance, not a script"; a continuing exchange gets a different brief |
| "Vary your acknowledgements" | Rotation of stock openers is the new complaint | Rewritten: most replies need no acknowledgement; said once is not said again |
| "acknowledge → answer → advance" | Forces an acknowledgement | "answer → advance", acknowledgement only when there is something to acknowledge |
| "Confirm with quiet courtesy: 'Noted — …', 'Thank you'" (register) | — | Unchanged: it governs *how* to confirm when a confirmation is needed |
| First-contact welcome ("Welcome to Bethany House") | Directive says not automatic | Unchanged for a genuine first contact; the new rule limits it to once |
| Canned sell pools ("Thank you{name} 🙏 This is our …") | Open with thanks by the owner's 2026-09-16 cadence | **Not changed** — see §6 |

## 4. Changes (small, additive)

- **One conversation per person per post.** `_thread_prior` reads our earlier replies to this person under this post. The count (`returning`) and whether the gift was already explained (`explained`) ride the reading into the model's brief.
- **A continuing campaign exchange gets its own brief** (`_campaign_continues`): no fresh welcome, no selection procedure again, save the detail and acknowledge it by what matters, ask only for what the caption requires that is still missing, never imply selection, never ask for a phone, address or email in public, never pivot to a sale.
- **React instead of replying.** A bare acknowledgement (`cooling.silence_decision`: thanks, ok, amen, a thumbs-up) from someone we have already answered under that post gets the Page's Like (Facebook, when likes are on) and no words — and no model call. An inbox note records the decision so a person can overrule it. A question, a buying word, a figure or a photo always keeps its turn.
- **No stock line twice.** A returning entrant with no model answer (over the cap) is liked, not thanked for joining again — unless the comment carries details or a question.
- **Ordinary (non-campaign) threads** carry a short "this continues the exchange" note for a returning commenter.
- **DMs from a campaign post:** "said once is enough" added to the campaign context.
- **Prompt:** new rule "READ WHAT THE MESSAGE IS BEFORE YOU ANSWER IT" (what the message does; thanks are for something; a supplied detail is taken, not recited; length follows the message; no question to prolong the chat; silence only after checking nothing is unanswered, pending or actionable).
- **Slice 19:** `buyer_intent.campaign_participation` — a nomination or a reference to the giveaway is protected from the request ladder; the note writer is told participation is not assistance.

No migration, no new setting, no change to prices, sales journeys, the gate, the complaint path or outreach.

## 5. Verification

| Scenario from the directive | How it was checked | Result |
|---|---|---|
| Returning commenter's acknowledgement | `test_an_acknowledgement_after_our_reply_is_liked_not_answered` (7 phrasings) | No reply, no model call, note written |
| Nomination then details = one exchange | `test_anything_that_needs_an_answer_still_gets_its_turn`, `test_the_continuing_brief_drops_the_welcome_and_the_procedure` | Turn runs with `returning`/`explained`; brief has no welcome or procedure |
| No premature closure | questions, buying words, figures, photos keep their turn | Pass |
| First comment unchanged | `test_a_first_acknowledgement_is_still_answered_once` | Pass |
| Ordinary product enquiries | existing comment and campaign suites | Pass unchanged |
| Genuine assistance requests (slice 19) | `test_an_ordinary_request_or_enquiry_is_not_read_as_participation` + slice 19 suites | Pass unchanged |
| Giveaway participation not assistance | `test_participation_is_protected_from_the_request_ladder` | Pass |

New file `tests/test_conversational_naturalness.py` (39 tests with 20b). Two pinned tests updated to the new wording (`test_register.py`, `test_comment_likes.py`).

## 5b. Checked against the owner's Facebook screenshots (slice 20b)

The screenshots arrived after slice 20 was merged: the cassock giveaway post and its thread, as Neema answered it **before** slice 20.

| What the thread shows | Cause | Covered by |
|---|---|---|
| Second and third replies open "Thank you, Siyethemba", recite the church and the name back, and repeat "our team will select one recipient… follow us" | The scripted brief on every turn | Slice 20 (continuing brief) |
| The church was recorded and said back as "**Bethany House** Pentecostal Holiness Church" | Facebook puts the Page's name, as a tag, in front of a thread reply; it was read as part of the church's name | **20b**: `_strip_page_tag` removes the tag from a thread reply before it is read |
| She asked for the church and town, then the pastor's full name | The brief listed "name, church, town, size" as things to ask for. This caption asks only for a nomination and the reason | **20b**: ask only for what THIS caption asks; when they have answered, the exchange is complete |
| A pastor asking to receive the gift herself (in Swahili) was told "if you'd like one for yourself, our Cassock is KES 13,000" | "Another item they bring up may be served" was applied to the gift itself | **20b**: asking to receive the gift, for one's pastor or oneself, is taking part; never an offer to buy, never a price unless they ask to buy |

Tests added to `tests/test_conversational_naturalness.py` (39 in all).

## 6. Not verified, and remaining risks

- **No model run.** Whether Neema's actual wording is now natural and non-repetitive is unverified; only what she is told and when she is called are tested. Evaluation runs remain stopped on the owner's word.
- **The Page tag is recognised by name** ("Bethany House", or an "@handle"). If the Page is renamed the pattern must follow.
- **Canned lines still open with "Thank you" / "Welcome to Bethany House".** The model-free price lines and first-contact lines keep the owner's 2026-09-16 cadence. Changing them is a wording decision for the owner.
- **A Like instead of words** depends on `meta_comment_like` being on; on Instagram there is no Like, so the acknowledgement is simply left.
- **"Explained" is read by keyword** from our earlier replies; a reply that explained the gift in unusual words would let the gift's line be said once more.
- **The participation guard is keyword-based** ("nominate", "giveaway", the post's gift). Someone who writes "giveaway" while asking for charity would not get the slice 19 boundary on that message.

## 7. Rollback

Revert the slice 20 commit. No data is written that needs undoing (the only new rows are inbox notes).
