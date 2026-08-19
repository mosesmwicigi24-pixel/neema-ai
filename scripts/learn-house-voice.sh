#!/usr/bin/env bash
# Teach Neema the team's own reply style — reads every human reply on record,
# distills length + real exemplars, and injects them into her prompt.
# Rerun any time; zero model cost.   bash scripts/learn-house-voice.sh
set -euo pipefail
REPO="${REPO:-/home/neema/neema-ai}"
cd "$REPO"
if [ -f docker-compose.vps.yml ]; then
    exec docker compose -f docker-compose.yml -f docker-compose.vps.yml \
        exec -T api python -m app.tools.stylebook
fi
exec docker compose exec -T api python -m app.tools.stylebook
