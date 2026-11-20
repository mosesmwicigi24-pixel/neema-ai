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
- **A chat held because sending failed** (three failed deliveries) is released once and will fail the same way: three more attempts, then it stays with staff.
- **Older than the reply window:** a customer who has waited more than about 23 hours cannot be answered by Neema on that channel; the chat is released, and she answers when they next write.
- **The timer runs every five minutes**, so "30 minutes" is 30 to 35.
- The live effect on the 74 blocked follow-ups was not measured.

## Added 2026-11-20 (owner: "Merge and do 1 and 2")

### 1. The warning

| When | What |
|---|---|
| The customer has waited 20 minutes (`auto_release_warn_minutes`) | One alert on the team bell, addressed by first name to the colleague the chat is assigned to ("Team" when nobody is): "this chat goes back to Neema in N min", with how long the customer has waited |

Once per wait. Only where the customer is waiting; a chat nobody is waiting on returns quietly, as before.

### 2. Money matters stay with a person, and are chased

A held chat is a money matter when the reason it was handed over names a refund, a part-payment, a complaint or a delayed order. The reason is read from the hand-over records (a hub event, a complaint case, Neema's own hand-off reason), never from the customer's words.

| When | What |
|---|---|
| Any time, while no colleague has replied | Not handed back to Neema |
| 30 minutes | Team alerted again; a note on the thread; if the customer is waiting and the channel's reply window is open, Neema sends one holding line |
| 2 hours (`money_hold_owner_minutes`) | Alert addressed to the owner; a note on the thread |
| A colleague replies | The matter is closed; the ordinary 30-minute rule applies again |

The holding line, in English or Swahili by the customer's last message:

> Thank you for your patience. This needs a decision from one of my colleagues, and they have not been able to reply yet. I have raised it with them again, and they will answer you here.

It gives no time, no promise and no decision. Each step happens once per matter.

**Decisions taken that the owner may want to change**

| Decision | Why | The alternative |
|---|---|---|
| A delayed order is treated like the three named (refund, part-payment, complaint) | The hub hands it over with "a human should tell the customer personally" | Let Neema take it back after 30 minutes |
| The warning is only for a chat where the customer is waiting | Otherwise every chat a colleague finishes rings a bell 20 minutes later | Warn on every held chat |
| The owner alert uses the team bell, with the title addressed to the owner | The app has no private channel to one person, and no phone alert except for calls | A WhatsApp or SMS to the owner's own number (needs that number configured) |
| After the 2-hour alert nothing further is sent | One line to the customer, two alerts to staff; more would be noise | Repeat the owner alert daily |

**Risks, and what was not verified**

- No model is involved in either addition; the alerts and the line are fixed text. Tested on a real database (11 new tests), not on the live system.
- The bell reaches whoever has the dashboard or app open. A colleague who is offline sees nothing until they return.
- A reason that only mentions one of the words (a held reply that quoted the refund policy) also keeps the chat with a person.
- A money matter nobody ever answers stays silent after the holding line and the two alerts.
- Old unanswered money matters already held when this goes live are alerted on the first run, all at once.
- Settings: `auto_release_warn_minutes` (20, 0 = off), `money_hold_owner_minutes` (120, 0 = off), `money_hold_line` (true). No migration.

## Suggestions (not built)

1. **A daily count** on the dashboard: chats handed back because nobody replied, per colleague. It shows where takeovers are being abandoned.
2. **Working hours.** Outside staffed hours a takeover could release sooner, since nobody is coming.
3. **A private alert to the owner** (WhatsApp or SMS to the owner's own number) for the 2-hour money alert, instead of the shared bell.
