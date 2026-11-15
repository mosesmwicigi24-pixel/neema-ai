# The call relay (TURN)

Owner's word, 2026-11-15: calls were not connecting ("The call audio couldn't connect").

## Why a relay

A WhatsApp call's audio travels between the staff device and WhatsApp's servers. On mobile data and on many office networks that path cannot be opened directly, and the audio must pass through a relay (a TURN server). Without a dependable relay the call is accepted, then ends after 20 seconds with no audio.

Until now the only relay offered to devices was a free public one. This adds our own.

## What is in the code

- `docker-compose.vps.yml`: a `turn` service (coturn), **off by default** (compose profile `turn`).
- `services/wa_calling.turn_credentials`: each device is handed a relay username that expires (6 hours) and a credential derived from `TURN_SECRET`. The secret never leaves the server.
- `GET /api/admin/calls/ice-config` returns `relay: true` when our relay is configured.
- Private address ranges are refused as relay targets, so the relay cannot be used to reach the server's own services.

## Switching it on (on the server)

1. Open the firewall (and the hosting provider's firewall, if it has one):
   - UDP and TCP **3478**
   - UDP **49160–49200**
2. Add to the server's `.env` (the secret is a long random value; `openssl rand -hex 32`):
   ```
   TURN_SECRET=<long random value>
   TURN_EXTERNAL_IP=<the server's public IPv4 address>
   TURN_URL=turn:<server's public address>:3478,turn:<server's public address>:3478?transport=tcp
   ```
   `<server's public address>` may be the IP or a DNS name that points at it.
3. Start the relay and restart the API so it reads the new values:
   ```sh
   docker compose -f docker-compose.yml -f docker-compose.vps.yml --profile turn up -d turn
   docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d api
   ```
4. Check: `GET /api/admin/calls-diagnostics` (signed in) shows `"relay": true`. Place a test call on mobile data.

To switch it off: stop the `turn` container and remove `TURN_URL` from `.env`.

## A managed relay instead

Any managed TURN service works without the `turn` container: set `TURN_URL`, `TURN_USERNAME` and `TURN_CREDENTIAL` to the values the provider gives, and leave `TURN_SECRET` empty.

## Knowing whether it worked

Every call whose audio fails now sends a short report from the device: the connection states, the kinds of network path it found (direct, via STUN, via a relay), whether our relay was offered. No number and no audio. The last 500 are at `GET /api/admin/calls-diagnostics`, each with a plain reading, for example "Our relay was offered but the device could not reach it (port blocked, or the relay is down)". Such a call is logged as **failed**, where it used to be logged as completed.

## Limits

- **Not verified on the live server.** The relay container has not been started there; the ports and `.env` values are the owner's to set.
- The relay listens without TLS (port 3478, UDP and TCP). A network that allows only port 443 will still fail; a TLS listener on 443 needs a certificate and a free port 443, which this shared server's web proxy holds.
- The public fallback relay is still offered after ours, as before.
- Relay traffic counts against the server's bandwidth: roughly 0.5 MB per call-minute.

## Ringing only free staff

Owner's choice, 2026-11-15: "ring all free staff at once, skipping only the busy ones".

- Who is busy is read from the call rows themselves: someone who answered a call that is still live, or who is ringing a customer.
- A new call does not ring the devices of a busy person: their browser socket and their phone's push are both skipped. What follows the ring (answered, ended) still reaches everyone.
- When every member of staff is on a call, the call rings everyone, and they see "is also calling".
- Switch: `CALL_RING_SKIP_BUSY=false` makes every device ring, as before.

Limits: the server does not know who has the app open, so "free" means "not on a call", not "at their desk". Someone who ends their call while a second one is still ringing is not rung for it; it appears in their missed list if nobody else answers.
