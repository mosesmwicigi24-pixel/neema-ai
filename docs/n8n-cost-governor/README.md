# Wiring the cost governor (`/route`) + usage logging into n8n

The backend endpoints are already live (`POST /api/n8n/route`, `POST /api/n8n/usage`).
This is the n8n side — done **in the editor**, not by JSON import, because it
adds/rewires nodes in the **Main workflow (the live WhatsApp trigger)** and
threads data around the AI call. The editor validates connections and lets you
test on a real message with one click; a hand-edited JSON import cannot.

Take the backup first (already have one from 2026-07-06):
`docker exec n8n-n8n-1 n8n export:workflow --all --separate --output=/tmp/bak`.

---

## Phase 1 — Loop-killer: dedupe retries + cool-off (highest value, lowest risk)

This is the direct fix for "the AI never gets time to cool off." It stops
WhatsApp retries and runaway back-and-forth from hitting gpt-4.1 at all.

**Where:** in **Neema Assistant Main**, on the wire from
`Gate after Touch` → `Run Customer Profile & Session Setup Sub-Workflow`.

1. **Add an HTTP Request node** named **`Cost Router`**, placed on that wire.
   - Method: `POST`
   - URL: `https://neema.bethanyhouse.co.ke/api/n8n/route`
   - Headers: `x-n8n-secret` = *(the N8N_API_SECRET value — same header the
     other API nodes already send)*
   - Send Body: JSON:
     ```
     {
       "wa_id":      "={{ $('Build Session Vars').item.json.wa_id }}",
       "text":       "={{ $('Build Session Vars').item.json.msgText }}",
       "msg_id":     "={{ $('Build Session Vars').item.json.msgId }}",
       "media_type": "={{ $('Build Session Vars').item.json.media_type || '' }}"
     }
     ```

2. **Add an IF node** named **`Should Run AI?`** right after `Cost Router`:
   - Condition (Boolean, AND):
     - `{{ $json.duplicate }}` **is false**
     - `{{ $json.cooldown_active }}` **is false**
   - **TRUE**  → connect to `Run Customer Profile & Session Setup Sub-Workflow`
   - **FALSE** → connect to a **No Operation** node named `Hold (no reply)` (flow ends; no gpt-4.1 spent)

3. **Fix the data hand-off (important).** `Run Customer Profile…` used to read
   `$json` from `Gate after Touch`. Now its input is the router/IF output, so
   point it back at the original data: anywhere that sub-workflow (and the ones
   after) read `$json.<field>` for session data, change to
   `$('Gate after Touch').item.json.<field>`. In practice the Execute-Workflow
   node passes the whole item, so set the `Cost Router` node's **"Include
   Input Fields"** option ON (Settings → Include Other Input Fields) — then the
   route decision is *added to* the original item and nothing downstream breaks.
   Test one message and confirm the profile/cart still populate.

**Result:** duplicates and cool-off turns end at `Hold (no reply)` — zero
gpt-4.1 calls. Everything else flows exactly as before.

---

## Phase 2 — Cheap path for greetings/acks (optional, more saving)

On the `Should Run AI?` **TRUE** branch, insert one more IF:

- **`Is trivial?`**: `{{ $json.path }}` **equals** `cheap`
  - **TRUE** → a WhatsApp send node using `{{ $json.canned_reply }}` (reuse the
    same send node/credentials as `Reply Dispatch`), then end. (If
    `canned_reply` is empty — a plain "ok"/"thanks" — just end with no reply.)
  - **FALSE** → `Run Customer Profile & Session Setup Sub-Workflow` (full agent)

Greetings ("hi", "habari") get an instant canned welcome; acks ("ok", "asante")
get no reply — neither touches gpt-4.1.

---

## Phase 3 — Measure it: log token usage

So `GET /api/admin/ai-cost` shows real numbers, add an HTTP Request node after
**each** OpenAI node (`Neema AI Agent`, `analyseGPT`, image, transcription),
fire-and-forget:

- Method `POST`, URL `https://neema.bethanyhouse.co.ke/api/n8n/usage`,
  header `x-n8n-secret`, body:
  ```
  {
    "wa_id":             "={{ $('Build Session Vars').item.json.wa_id }}",
    "workflow":          "conversation-intelligence",
    "node":              "Neema AI Agent",
    "model":             "={{ $json.usage ? 'gpt-4.1' : 'gpt-4.1' }}",
    "prompt_tokens":     "={{ $json.usage?.prompt_tokens || 0 }}",
    "completion_tokens": "={{ $json.usage?.completion_tokens || 0 }}",
    "cached_tokens":     "={{ $json.usage?.prompt_tokens_details?.cached_tokens || 0 }}"
  }
  ```
  (`cached_tokens` will start climbing once the prompt-caching change is live —
  that's how you'll SEE the ~43% win.)

---

## Also worth doing in the editor (not safe as blind edits)

- **Cap agent output** — set `maxTokens ≈ 900` on the `Neema AI Agent` node.
  ⚠️ The agent appends a `<CONTROL>{…}</CONTROL>` block that drives order/cart
  logic; too low a cap truncates it and breaks orders. 900 is safe for short
  WhatsApp replies + the control block, but **test an order flow** after.
- **Image detail → low** — on the `Analyze Image` node (Product Image
  Recognition), set Options → Detail = `low` (~85 tokens vs 1–2K). Test that
  product identification still works.

---

## Rollback

Restore from `/root/n8n-backups/20260706-163703/` (see the prompt-caching
README) or re-import the workflow JSON from git history.
