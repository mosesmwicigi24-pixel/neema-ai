"""The intelligent, tool-calling Neema agent.

A real agent loop in the backend (historically "Tier 2", which the tier2_
settings prefix still reflects): the model reasons over the conversation and DECIDES when to act by
calling tools (search the hub catalogue, build a cart, create the order, share
the payment link). There is no confirmation regex — the model calls
`create_order` when the customer confirms — which removes an entire class of
Tier 1 bugs.

The hub integration (Part A/B/C) is this agent's tool layer. It runs behind a
per-wa_id flag so it coexists with the live Tier 1 flow until proven.
"""
