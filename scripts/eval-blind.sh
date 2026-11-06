#!/usr/bin/env bash
#
# The real-model evaluation on the BLIND held-out set — run ON the box, where
# the model key lives in the api container's environment. One command; the
# results land in ./eval-out/ on the box, ready to copy into
# docs/intelligence/results/ and to read in BENCHMARK_RESULTS.md.
#
#   sudo scripts/eval-blind.sh            # pass^3 over the 120 blind cases
#   sudo scripts/eval-blind.sh --repeat 1 # a quick single pass
#
# Sends are sandboxed by the runner itself (no customer is messaged); the
# throwaway contacts it creates are cleaned up at the end. Costs model calls:
# roughly 3 × 459 turns at the configured tier-2 model.
set -euo pipefail
REPO=${REPO:-/home/neema/neema-ai}
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.vps.yml)
cd "$REPO"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SHA=$(git rev-parse --short HEAD)
OUT=eval-out
mkdir -p "$OUT"
echo "== floors (deterministic) on the blind set, code $SHA"
"${COMPOSE[@]}" exec -T api python -m app.jobs.eval_floors --file blind_heldout.jsonl \
  --json "/tmp/floors-blind-$STAMP.json" | tail -20
"${COMPOSE[@]}" cp "api:/tmp/floors-blind-$STAMP.json" "$OUT/floors-blind-$SHA-$STAMP.json"
echo "== real model on the blind set (pass^k), code $SHA"
"${COMPOSE[@]}" exec -T api python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl \
  "$@" --out "/tmp/agent-eval-blind-$STAMP.json" --packet "/tmp/rater-packet-$STAMP.md" --history \
  2>&1 | tee "$OUT/agent-eval-blind-$SHA-$STAMP.log" | tail -40
"${COMPOSE[@]}" cp "api:/tmp/agent-eval-blind-$STAMP.json" "$OUT/agent-eval-blind-$SHA-$STAMP.json"
"${COMPOSE[@]}" cp "api:/tmp/rater-packet-$STAMP.md" "$OUT/rater-packet-$SHA-$STAMP.md"
echo "== done: $OUT/"
ls -la "$OUT" | tail -4
echo "Copy the three files into docs/intelligence/results/ and the summary block"
echo "of the .log into BENCHMARK_RESULTS.md ('Real-model baseline')."
