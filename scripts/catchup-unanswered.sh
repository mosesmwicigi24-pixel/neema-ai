#!/usr/bin/env bash
# Answer everything the Meta outage left waiting (DMs + comments, under 24h).
# Run on the VPS after the token is fixed:   bash scripts/catchup-unanswered.sh
set -euo pipefail
REPO="${REPO:-/home/neema/neema-ai}"
cd "$REPO"
if [ -f docker-compose.vps.yml ]; then
    exec docker compose -f docker-compose.yml -f docker-compose.vps.yml \
        exec -T api python -m app.tools.catchup
fi
exec docker compose exec -T api python -m app.tools.catchup
