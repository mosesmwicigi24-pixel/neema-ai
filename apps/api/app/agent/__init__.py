"""Tier 2 — the intelligent, tool-calling Neema agent.

Unlike Tier 1 (a single GPT call wrapped in ~40 deterministic n8n nodes that
pre-chew context and post-process brittle flags), Tier 2 is a real agent loop in
the backend: the model reasons over the conversation and DECIDES when to act by
calling tools (search the hub catalogue, build a cart, create the order, share
the payment link). There is no confirmation regex — the model calls
`create_order` when the customer confirms — which removes an entire class of
Tier 1 bugs.

The hub integration (Part A/B/C) is this agent's tool layer. It runs behind a
per-wa_id flag so it coexists with the live Tier 1 flow until proven.
"""
