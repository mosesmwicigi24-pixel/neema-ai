# A chat a person holds goes back to Neema after 30 quiet minutes

Owner's word, 2026-11-19: "If the human interception remains for 30 minutes without being released and without chats continue, release that chat to Neema. So disconnect the human and let the Neema AI pick up. So this avoids chats that have been taken by humans to remain inactive." Status: **on the branch, tested without the model; not merged.**

## What existed

A timed release already ran every five minutes (`services/auto_release.py`), at 45 minutes. It had two exceptions, and they are where chats sat inactive:

| Exception | From | Effect |
|---|---|---|
| Never over a waiting customer | Owner, 2026-10-10 | A chat whose newest message was an unanswered customer message stayed with the person for good |
| A hold stays with staff until a person replies | Owner ("held replies → Human + notify") | A chat flagged to the team (a held reply, a failed order, a delivery failure) waited for a colleague however long it took |

The first exception was added because 1,500 of 1,544 releases in 30 days were a loop: the missed-reply sweeper escalated a chat to a person, the timer released it, the sweeper escalated it again, every six minutes or so.

On 19 November the live server showed 74 planned follow-ups blocked because the chat was held by a person.

## The rule now

| Chat held by a person | After |
|---|---|
| Nobody is waiting (a colleague answered, or the customer signed off) | Released when the colleague has been quiet 30 minutes (was 45) |
| The customer is waiting and no colleague has replied | Released when the customer has waited 30 minutes. Neema answers the waiting message within about two minutes (the existing missed-reply sweep), while the channel's reply window is open |
| The same chat comes back to staff for the same wait (her answer is held, or it is escalated again) | Stays with staff until a person replies or the customer writes again |

- The thirty minutes are counted from when the customer began waiting, so a colleague always has thirty minutes on a new message.
- **One automatic release per wait.** This is what stops the October loop from starting again.
- Neema is told on her first turn back how she got the chat: not to imply a colleague answered, to answer what she can, and where it truly needs a person to say honestly that a colleague has not picked it up yet and that she has raised it again.
- Staff see a note on the thread: "Back to Neema — no colleague reply in 30 min; the customer was still waiting for an answer."

Settings: `AUTO_RELEASE_MINUTES` (30; 0 switches the timer off) and `AUTO_RELEASE_WAITING` (true; false restores the October rule). No migration.

## What this reverses

Both exceptions above were the owner's earlier decisions. This instruction replaces them; the switch restores the first.

## Risks, and what was not verified

- **Not run with the model.** How Neema words the pick-up after a colleague's silence has not been seen.
- **Sensitive holds come back too.** A chat handed to staff for a refund request, a part payment or a delayed order returns to Neema after thirty minutes like any other. Her instructions already keep her from promising a refund or a resolution, and the note tells her to say a colleague has not picked it up; but she is answering a customer who was told a person would.
- **A chat held because sending failed** (three failed deliveries) is released once and will fail the same way: three more attempts, then it stays with staff.
- **Older than the reply window:** a customer who has waited more than about 23 hours cannot be answered by Neema on that channel; the chat is released, and she answers when they next write.
- **The timer runs every five minutes**, so "30 minutes" is 30 to 35.
- The live effect on the 74 blocked follow-ups was not measured.

## Suggestions (not built)

1. **Warn before releasing.** At 20 minutes, ping the colleague who holds the chat: "release in 10 minutes unless you reply". Cheap, and it turns a silent hand-back into a prompt to answer.
2. **Keep money matters with a person, but chase.** For refund, part-payment and complaint holds: instead of handing back to Neema, re-alert the team at 30 minutes and the owner at 2 hours, and let Neema send one honest holding line.
3. **A daily count** on the dashboard: chats handed back because nobody replied, per colleague. It shows where takeovers are being abandoned.
4. **Working hours.** Outside staffed hours a takeover could release sooner, since nobody is coming.
