#!/usr/bin/env bash
# Install a Meta Page access token on this box — safely, and with the checks
# that a whole morning of 2026-08-19 was spent learning the hard way.
#
# Why this exists: rotating the page token by hand means holding four facts at
# once (which token kind, which page, which app, which secret) and every one of
# them was got wrong at least once that morning — a user token pasted where a
# page token belonged, the owner's Facebook USER id typed as the App ID, an
# empty META_APP_SECRET producing "Error validating client secret", and finally
# a token that installed cleanly and would have died silently 100 minutes later.
# The script asks for one thing at a time and refuses to install anything it
# has not verified against Graph itself.
#
#   bash scripts/meta-token-install.sh
#
# Env overrides: REPO (default /home/neema/neema-ai), GRAPH_VER (v19.0),
# HEALTH_URL (http://127.0.0.1:8000/api/health).
set -euo pipefail

REPO="${REPO:-/home/neema/neema-ai}"
ENVF="$REPO/.env"
GRAPH="https://graph.facebook.com/${GRAPH_VER:-v19.0}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"

die() { printf '\n!! %s\n\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }
hr()  { printf -- '─%.0s' $(seq 1 66); printf '\n'; }

command -v curl    >/dev/null || die "curl is not installed"
command -v python3 >/dev/null || die "python3 is not installed"
[ -f "$ENVF" ]                || die "no .env at $ENVF — set REPO=/path/to/repo"

# py <expr-script> — parse the JSON on stdin; prints nothing on malformed input
py() { python3 -c "$1" 2>/dev/null || true; }

hr
say "Meta page token installer — nothing is written until you confirm."
hr

# ── 1. the token ─────────────────────────────────────────────────────────────
# read -rsp keeps the token off the screen AND out of ~/.bash_history.
read -rsp "Paste a token (page token OR user token): " TOK; echo
[ -n "${TOK:-}" ] || die "nothing pasted"
say "   (${#TOK} characters)"

DBG="$(curl -s -G "$GRAPH/debug_token" -d "input_token=$TOK" -d "access_token=$TOK")"
KIND="$(printf '%s' "$DBG" | py 'import json,sys; print(json.load(sys.stdin)["data"].get("type",""))')"
APPID="$(printf '%s' "$DBG" | py 'import json,sys; print(json.load(sys.stdin)["data"].get("app_id",""))')"
APPNAME="$(printf '%s' "$DBG" | py 'import json,sys; print(json.load(sys.stdin)["data"].get("application",""))')"
[ -n "$KIND" ] || die "Graph would not describe that token:
$(printf '%s' "$DBG" | head -c 300)"

say ""
say "   token kind : $KIND"
say "   issued by  : $APPNAME (app id $APPID)"

# ── 2. a user token becomes a page token; extend it first so it never dies ───
if [ "$KIND" != "PAGE" ]; then
    say ""
    say "That is a USER token. A user token cannot send messages — it is the key"
    say "that fetches the page's own token. Extending it first is what makes the"
    say "resulting page token permanent."

    SECRET="$(grep -m1 '^META_APP_SECRET=' "$ENVF" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r' || true)"
    if [ -n "$SECRET" ]; then
        say "   using META_APP_SECRET from .env (${#SECRET} chars)"
    else
        say ""
        say "No META_APP_SECRET in .env. Get it at developers.facebook.com →"
        say "My Apps → $APPNAME (app id $APPID) → Settings → Basic → App Secret."
        read -rsp "Paste the App Secret (blank = skip, token will be temporary): " SECRET; echo
    fi

    if [ -n "${SECRET:-}" ]; then
        PAIR="$(curl -s -G "$GRAPH/$APPID" -d "fields=id,name" -d "access_token=$APPID|$SECRET")"
        printf '%s' "$PAIR" | grep -q '"name"' \
            || die "that App ID + App Secret pair is not valid — Graph said:
$(printf '%s' "$PAIR" | head -c 300)"
        say "   app credentials verified"

        EX="$(curl -s -G "$GRAPH/oauth/access_token" \
              -d "grant_type=fb_exchange_token" -d "client_id=$APPID" \
              -d "client_secret=$SECRET" -d "fb_exchange_token=$TOK")"
        LONG="$(printf '%s' "$EX" | py 'import json,sys; print(json.load(sys.stdin).get("access_token",""))')"
        [ -n "$LONG" ] || die "exchange failed — Graph said:
$(printf '%s' "$EX" | head -c 300)"
        TOK="$LONG"
        say "   user token extended (${#TOK} chars)"
    fi

    ACC="$(curl -s -G "$GRAPH/me/accounts" -d "fields=id,name,access_token" \
           -d "limit=200" -d "access_token=$TOK")"
    LIST="$(printf '%s' "$ACC" | py 'import json,sys
d=json.load(sys.stdin).get("data") or []
for i,p in enumerate(d,1): print("%2d) %-40s %s" % (i, p.get("name",""), p.get("id","")))')"
    [ -n "$LIST" ] || die "that login administers no pages — Graph said:
$(printf '%s' "$ACC" | head -c 300)"

    say ""
    say "Pages this login administers:"
    say "$LIST"
    say ""
    # Chosen by NUMBER, never by id: typing a page id that was not in the list
    # is exactly how the wrong page got picked twice.
    read -rp "Number of the page to use: " N
    printf '%s' "$N" | grep -Eq '^[0-9]+$' || die "'$N' is not a number from the list"
    TOK="$(printf '%s' "$ACC" | py "import json,sys
d=json.load(sys.stdin).get('data') or []
i=int('$N')-1
print(d[i]['access_token'] if 0 <= i < len(d) else '')")"
    [ -n "$TOK" ] || die "no page at number $N"
fi

# ── 3. verify what we are about to install, against Graph ────────────────────
ME="$(curl -s -G "$GRAPH/me" -d "fields=id,name,category" -d "access_token=$TOK")"
PAGE_ID="$(printf '%s' "$ME" | py 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
PAGE_NAME="$(printf '%s' "$ME" | py 'import json,sys; print(json.load(sys.stdin).get("name",""))')"
CATEGORY="$(printf '%s' "$ME" | py 'import json,sys; print(json.load(sys.stdin).get("category",""))')"
[ -n "$PAGE_ID" ] || die "Graph rejected the resulting token:
$(printf '%s' "$ME" | head -c 300)"
# Only a Page carries `category`. A System User token answers /me happily and
# then 400s on every send ("Object with ID 'me' does not exist").
[ -n "$CATEGORY" ] || die "that token is VALID but is NOT a page token (no category) —
every send would fail. Paste the USER token instead and pick the page."

DBG2="$(curl -s -G "$GRAPH/debug_token" -d "input_token=$TOK" -d "access_token=$TOK")"
EXPAT="$(printf '%s' "$DBG2" | py 'import json,sys; print(json.load(sys.stdin)["data"].get("expires_at",""))')"
SCOPED="$(printf '%s' "$DBG2" | grep -c 'pages_messaging' || true)"

if [ "${EXPAT:-0}" = "0" ]; then
    LIFE="never expires"
else
    LIFE="EXPIRES $(date -u -d "@$EXPAT" '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo "at $EXPAT") — TEMPORARY"
fi

hr
say "  page      : $PAGE_NAME"
say "  page id   : $PAGE_ID"
say "  category  : $CATEGORY"
say "  lifetime  : $LIFE"
say "  messaging : $([ "$SCOPED" -gt 0 ] && echo 'pages_messaging present' || echo 'pages_messaging MISSING — sends will fail')"
say "  env file  : $ENVF"
hr
[ "${EXPAT:-0}" = "0" ] || say "NOTE: a temporary token restores service now but dies at the time above."
read -rp "Install this token? (yes/no): " OK
[ "$OK" = "yes" ] || die "nothing was changed"

# ── 4. write it ──────────────────────────────────────────────────────────────
BACKUP="$ENVF.bak.$(date +%Y%m%d%H%M%S)"
cp "$ENVF" "$BACKUP"
say "   backup: $BACKUP"

python3 - "$ENVF" "$TOK" "$PAGE_ID" "${SECRET:-}" <<'PY'
import io, json, sys
envf, tok, pid, secret = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
lines = io.open(envf, encoding="utf-8").read().splitlines()
out, seen_tok, seen_sec = [], False, False
for ln in lines:
    if ln.startswith("META_PAGE_TOKEN="):
        out.append("META_PAGE_TOKEN=" + tok); seen_tok = True
    elif ln.startswith("META_APP_SECRET=") and secret:
        out.append("META_APP_SECRET=" + secret); seen_sec = True
    elif ln.startswith("META_PAGE_TOKENS="):
        # A page-id → token map, when present, OVERRIDES META_PAGE_TOKEN for
        # that page: updating only the fallback looks like a no-op deploy.
        s = ln.split("=", 1)[1].strip(); q = ""
        if s[:1] in "\"'" and s[-1:] == s[:1]:
            q, s = s[:1], s[1:-1]
        try:
            m = json.loads(s) if s else {}
        except Exception:
            m = {}
        if isinstance(m, dict) and m:
            m[pid] = tok
            out.append("META_PAGE_TOKENS=" + q + json.dumps(m, separators=(",", ":")) + q)
            print("   map entry updated for page", pid)
        else:
            out.append(ln)
    else:
        out.append(ln)
if not seen_tok:
    out.append("META_PAGE_TOKEN=" + tok)
if secret and not seen_sec:
    out.append("META_APP_SECRET=" + secret)
    print("   META_APP_SECRET added — webhook signature verification is now ON")
io.open(envf, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("   META_PAGE_TOKEN written")
PY
chmod 600 "$ENVF"

# ── 5. restart — `docker compose restart` does NOT re-read the env file ──────
say ""
say "Recreating the api container (a plain restart would keep the OLD token)…"
cd "$REPO"
if [ -f docker-compose.vps.yml ]; then
    docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --no-deps --force-recreate api
else
    docker compose up -d --no-deps --force-recreate api
fi

say ""
say "Health: $(curl -s --max-time 10 "$HEALTH_URL" | head -c 300)"
hr
say "Now send ONE reply from the dashboard to a Messenger thread."
say "No red toast = done. A red toast carries Graph's own reason — paste it."
[ "${EXPAT:-0}" = "0" ] || say "Reminder: this token is TEMPORARY ($LIFE). Rerun with a USER token."
hr
