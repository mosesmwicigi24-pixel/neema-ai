# Prompt-caching restructure for the "Neema AI Agent" node

**Goal:** cut ~43% off the main agent's input tokens on every message, with
**no change to what the agent knows** — purely by relocating live data so
OpenAI's automatic prompt caching can kick in.

## Why this works

The `Neema AI Agent` node (in the **Conversation Intelligence & Response**
workflow) sends a ~16,400-token **System Message** on every single message.
That system message had 14 dynamic `{{ … }}` fields baked into an
"ACTIVE SESSION — LIVE VALUES" block, so the text was **different every
message** — which means OpenAI's automatic prompt caching (a ~75% discount on
a stable prefix ≥1024 tokens) **never activated**.

This change moves ONLY that live-values block out of the System Message and
into the User Prompt (where per-turn data belongs). The System Message becomes
**100% static (~15,380 tokens, 0 dynamic fields)** → OpenAI caches it after the
first call in each ~5–10 min window. Nothing is removed; the agent still sees
the customer, cart, catalogue, and order state — it just reads them from the
user turn instead of the system prompt.

## What's in this folder

- `system_message.txt` — paste into the node's **System Message** field. Static, cacheable.
- `user_prompt.txt` — paste into the node's **Text / User Prompt** field. Carries the live values + the original prompt body.

Both files **start with `=`** on purpose — that is n8n's marker for
*expression mode* (so `{{ … }}` gets evaluated). **Keep the leading `=`.**

## How to apply (in the n8n editor — 3 minutes)

1. Open **n8n → Conversation Intelligence & Response → the `Neema AI Agent` node**.
2. Copy the ENTIRE contents of `system_message.txt` into the **System Message** field (replace what's there).
3. Copy the ENTIRE contents of `user_prompt.txt` into the **Text** (user prompt) field (replace what's there).
4. **Save** the workflow. (No n8n restart needed for editor saves.)

## Test before you trust it (important — this agent takes orders)

Right after applying, send 3–4 real WhatsApp messages and confirm the agent
still:
- greets and uses the customer's name/country correctly,
- quotes the right **catalogue prices** and currency (KES vs USD),
- tracks the **cart** (add an item, check the running subtotal),
- handles an **order confirmation** correctly.

If anything looks off, **revert** (see below) and tell me — it's fully reversible.

## Revert

A full backup of every workflow was taken before any changes:
`/root/n8n-backups/20260706-163703/` on the VPS (pointer in
`/root/n8n-backups/LATEST`). To restore just this workflow:

```bash
# on the VPS
ID=I2ERPxA9cXlGwRFK   # Conversation Intelligence & Response
docker cp /root/n8n-backups/20260706-163703/<file>.json n8n-n8n-1:/tmp/restore.json
docker exec n8n-n8n-1 n8n import:workflow --input=/tmp/restore.json
docker exec n8n-n8n-1 n8n update:workflow --id=$ID --active=true
docker restart n8n-n8n-1
```

Or simply re-paste the old prompts from git history of
`n8n/conversation-intelligence-response.json`.

## Measuring the win

Once the `/api/n8n/usage` logging is wired into the workflow (see the main
cost-controls work), `GET /api/admin/ai-cost` will show the drop directly. In
the meantime, OpenAI's dashboard shows cached-token counts climbing on the
`gpt-4.1` calls — that's the caching working.
