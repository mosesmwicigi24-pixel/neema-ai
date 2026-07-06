#!/usr/bin/env bash
#
# Pull-based deployer — runs ON the VPS on a systemd timer (see deploy/).
#
# Why pull-based: this box sits behind a Hostinger edge that intermittently
# drops GitHub-runner IPs on port 22, so an Actions->box SSH push is
# unreliable. Instead, CI only builds + pushes images to GHCR, and the box
# pulls them itself. Outbound from the box always works, so this is immune to
# the inbound block.
#
# Requires the neema-ai-api / neema-ai-web GHCR packages to be PUBLIC so the
# box can pull anonymously (no stored registry credentials on this shared box).
#
# Idempotent: git fetch/reset + compose pull + up -d are all no-ops when
# nothing changed, so running every couple of minutes causes no churn.
set -euo pipefail

REPO=/home/neema/neema-ai
LOCK=/tmp/neema-deploy.lock
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.vps.yml)

# Never run two deploys at once (a slow pull must not overlap the next tick).
exec 9>"$LOCK"
flock -n 9 || { echo "another deploy is running; skipping"; exit 0; }

cd "$REPO"

# 1. Sync the working tree to origin/main (compose files, migrations, code).
#    Run git as the owning user so file ownership stays consistent.
sudo -u neema git fetch --quiet origin main
LOCAL=$(sudo -u neema git rev-parse HEAD)
REMOTE=$(sudo -u neema git rev-parse origin/main)
sudo -u neema git reset --quiet --hard origin/main

# 2. Pull the images CI built. Capture whether anything actually changed.
BEFORE_API=$(docker image inspect -f '{{.Id}}' ghcr.io/mosesmwicigi24-pixel/neema-ai-api:latest 2>/dev/null || echo none)
BEFORE_WEB=$(docker image inspect -f '{{.Id}}' ghcr.io/mosesmwicigi24-pixel/neema-ai-web:latest 2>/dev/null || echo none)
"${COMPOSE[@]}" pull --quiet api web
AFTER_API=$(docker image inspect -f '{{.Id}}' ghcr.io/mosesmwicigi24-pixel/neema-ai-api:latest 2>/dev/null || echo none)
AFTER_WEB=$(docker image inspect -f '{{.Id}}' ghcr.io/mosesmwicigi24-pixel/neema-ai-web:latest 2>/dev/null || echo none)

# 3. Recreate only when the git ref or an image digest changed.
if [ "$LOCAL" = "$REMOTE" ] && [ "$BEFORE_API" = "$AFTER_API" ] && [ "$BEFORE_WEB" = "$AFTER_WEB" ]; then
  echo "$(date -Is) up to date ($REMOTE)"
  exit 0
fi

echo "$(date -Is) deploying ${REMOTE:0:8} (api $BEFORE_API->$AFTER_API, web $BEFORE_WEB->$AFTER_WEB)"
"${COMPOSE[@]}" up -d --no-deps api web

# 4. Health gate.
for i in $(seq 1 10); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health || true)
  [ "$code" = "200" ] && { echo "$(date -Is) deploy OK, api healthy"; exit 0; }
  sleep 6
done
echo "$(date -Is) WARNING: api did not report healthy after deploy" >&2
exit 1
