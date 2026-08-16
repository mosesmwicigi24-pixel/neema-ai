# Host nginx — compression tuning (one paste, one check)

**Why this doc exists.** On the production box the nginx *container* is disabled
(`docker-compose.yml`) and a **host-level nginx** terminates TLS and proxies to
`127.0.0.1:3000` (web) and `127.0.0.1:8000` (api). That host config is not in
this repo, so `nginx/nginx.conf` here reaches nobody in production — and
`scripts/box-deploy.sh` only recreates the `api` and `web` containers, never
nginx. The tuning below therefore has to be applied on the box by hand, once.

## What it buys

nginx defaults `gzip_comp_level` to **1**, its weakest setting. Measured on the
real dashboard build:

- **−17.7%** bytes on the dashboard chunk
- **−14.3%** across all JS chunks

Static chunks are served `immutable` with a one-year cache, so each file is
compressed rarely — the CPU cost is negligible and the saving is permanent for
every agent on a mobile link.

## The change

On the box, in the host nginx config (`/etc/nginx/nginx.conf`, inside the
`http { }` block — replace the existing `gzip` lines):

```nginx
gzip on;
gzip_comp_level 6;          # nginx defaults to 1, its weakest
gzip_min_length 256;        # below this the gzip header costs more than it saves
gzip_vary on;               # correct caching by any proxy in front of us
gzip_proxied any;
gzip_types
    text/plain text/css text/xml text/javascript
    application/json application/javascript application/xml
    application/xml+rss application/manifest+json
    image/svg+xml;

tcp_nopush on;              # fill packets before sending — fewer round trips
```

`text/javascript` matters: it is what modern servers label `.js` (the older
`application/javascript` is deprecated), and a type missing from `gzip_types`
is silently shipped **uncompressed**.

Then, always test before reloading — a bad config that is only *reloaded* keeps
the old one running, but a bad config plus a restart takes the site down:

```bash
sudo nginx -t && sudo nginx -s reload
```

## Proving it took

Pick any hashed chunk from the running site and compare the transferred size:

```bash
CHUNK=$(curl -s https://neema.bethanyhouse.co.ke/login \
        | grep -o '/_next/static/chunks/[^"]*\.js' | head -1)
curl -s -o /dev/null -H 'Accept-Encoding: gzip' \
     -w 'over the wire: %{size_download} bytes\n' \
     "https://neema.bethanyhouse.co.ke$CHUNK"
```

Run it before and after the reload — the second number should be materially
smaller. `content-encoding: gzip` alone does **not** prove it worked; nginx was
already gzipping, just weakly, so only the byte count tells the truth.
