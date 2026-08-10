# CI — the quality gate

Two workflows:

| File | Name | Purpose |
| --- | --- | --- |
| `.github/workflows/ci.yml` | **CI** | The tests. Also reusable (`workflow_call`). |
| `.github/workflows/deploy.yml` | **Build & Push** | Builds the two images and pushes them to GHCR. |

**The image push is the deploy.** The VPS runs `scripts/box-deploy.sh` on a
systemd timer and pulls `ghcr.io/…:latest` every couple of minutes, so anything
that reaches GHCR is in production within ~2 min. That is why `deploy.yml`
calls `ci.yml` as a gate: **a red suite means no image is built, so nothing
ships.**

The API container's command is:

```
python -m alembic upgrade head && uvicorn app.main:app …
```

A bad import or a broken migration therefore does not degrade production — it
crash-loops it. `import-smoke` and `migrations` exist specifically for that.

---

## What runs when

| Event | CI | Build & Push |
| --- | --- | --- |
| Open a PR, or push to a branch **with** an open PR | ✅ standalone | ✅ build only, no push |
| Push to `main` | ✅ **as the gate inside Build & Push** | ✅ push to GHCR → deploys |
| `workflow_dispatch` on Build & Push | ✅ unless `skip_tests` | ✅ push to GHCR → deploys |
| Push to a branch with **no** PR | — | — |

`ci.yml` has no bare `push:` trigger, and that is deliberate. Between
`pull_request` (which fires on every push to a PR branch — the `synchronize`
event) and `deploy.yml` calling this workflow on `main`, every commit that can
actually ship is covered. Adding `push` on top makes every PR commit fire the
workflow *twice*, once per event: they either both run (double the minutes and
duplicate checks) or share a concurrency group and cancel each other, leaving a
cancelled, red-looking check on the PR. The first version of this file did the
latter — it's an observed problem, not a hypothetical one.

The gap that leaves is a branch with no PR open yet. If you want CI before
opening one, use *Actions → CI → Run workflow*.

Runs are grouped by ref with `cancel-in-progress`, so pushing again supersedes
the in-flight run. The concurrency key includes `github.workflow`, which inside
a reusable call resolves to the *caller's* name — that is what stops a
standalone CI run from ever cancelling the deploy gate.

## The jobs

All five run in parallel; the whole thing is a couple of minutes.

### `api-tests` — API tests (pytest)
Python 3.12 (matching `apps/api/Dockerfile`), `pip install -r requirements-dev.txt`,
then the full suite. **714 passed, 1 skipped.**

The one skip is `tests/test_migrations.py`, which skips itself when no Postgres
is reachable. That is intentional here — the `migrations` job runs it for real.
Nothing else in `tests/` needs a live service: every DB and Redis touchpoint is
a hand-rolled fake.

> ⚠️ **`/var/neema/media` must exist and be writable** before anything imports
> the app. `app/routers/media.py` runs `os.makedirs("/var/neema/media")` at
> **import time**, with the path hardcoded — so simply importing the app touches
> the filesystem, and on a non-root user it raises `PermissionError` during test
> *collection*. `apps/api/Dockerfile` creates and chowns that exact path, so the
> three CI jobs that import the app do the same (`sudo mkdir -p` +
> `chown`). The `docker run` commands below execute as root, so they don't hit
> it; if you run the suite on your host, create the directory first. Making
> `MEDIA_DIR` env-configurable would remove the whole footgun.

> ⚠️ Always `python -m pytest`, never bare `pytest`. There is no
> `pyproject.toml`, no `pytest.ini` and no `conftest.py` in `apps/api`, so only
> the `-m` form puts the working directory on `sys.path`. Bare `pytest` fails to
> import `app` in all 88 test modules.

### `import-smoke` — crash-loop guard
`python -c "import app.main"`, installed from `requirements.txt` (**not**
`-dev`) so it exercises exactly the dependency set the runtime image ships. Its
own job so the failure reason is unmistakable in the checks list.

### `migrations` — single head + fresh-DB replay
Two things, against a `postgres:16` service container:

1. `python -m alembic heads` must print exactly one head. This needs no
   database and never executes `env.py` — it only reads `alembic/versions/`. A
   split head makes `alembic upgrade head` fail at container start.
2. `tests/test_migrations.py` creates a throwaway database, replays the whole
   chain, and then diffs every SQLAlchemy model column against the migrated
   schema. This is the test that would have caught the `messages.comment_context`
   outage.

The job asserts the replay test actually ran (`1 passed`) rather than skipped,
so a failed service container can't turn into a silent green.

### `lint-ratchet` — ruff
`apps/api` has no ruff config, so this is ruff's default rule set (E4/E7/E9/F),
pinned to `ruff==0.6.9` to match `requirements-dev.txt`.

There is a standing backlog of findings. **The gate is only that the number must
never grow.** The current count is compared against `.ci/ruff-baseline.txt`; the
job prints a per-rule breakdown to the run summary either way.

### `web` — typecheck + build
Node 20 + pnpm 10 (matching `apps/web/Dockerfile`), `pnpm install --frozen-lockfile`,
`pnpm exec tsc --noEmit`, then `pnpm run build` with the same `NEXT_PUBLIC_*`
values `deploy.yml` bakes in — those are compiled into the bundle, so a build
without them is not the build that ships.

---

## Reproducing a job locally

All of these use the team's `python:3.12-slim` one-liner, so you get the same
interpreter and a clean dependency set regardless of what's on your machine.

**The suite** (from the repo root):

```bash
docker run --rm -v "$PWD/apps/api":/w -w /w python:3.12-slim sh -c '
  pip install -q -r requirements-dev.txt &&
  DATABASE_URL=postgresql+asyncpg://x:x@127.0.0.1:5432/x \
  DATABASE_URL_SYNC=postgresql+psycopg2://x:x@127.0.0.1:5432/x \
  SECRET_KEY=x \
  python -m pytest -q -rs'
```

**Import smoke:**

```bash
docker run --rm -v "$PWD/apps/api":/w -w /w python:3.12-slim sh -c '
  pip install -q -r requirements.txt &&
  DATABASE_URL=x DATABASE_URL_SYNC=x SECRET_KEY=x python -c "import app.main"'
```

**Single alembic head** (no database needed):

```bash
docker run --rm -v "$PWD/apps/api":/w -w /w python:3.12-slim sh -c '
  pip install -q -r requirements.txt && python -m alembic heads'
```

**Migration replay** (needs a throwaway Postgres — don't point it at a database
you care about, the test creates and drops databases):

```bash
docker network create neema-ci 2>/dev/null
docker run -d --rm --name neema-ci-pg --network neema-ci \
  -e POSTGRES_USER=neema -e POSTGRES_PASSWORD=neema -e POSTGRES_DB=neema postgres:16

docker run --rm --network neema-ci -v "$PWD/apps/api":/w -w /w python:3.12-slim sh -c '
  pip install -q -r requirements-dev.txt &&
  DATABASE_URL=postgresql+asyncpg://neema:neema@neema-ci-pg:5432/neema \
  DATABASE_URL_SYNC=postgresql+psycopg2://neema:neema@neema-ci-pg:5432/neema \
  SECRET_KEY=x \
  python -m pytest -q -rs tests/test_migrations.py'

docker rm -f neema-ci-pg
```

**Ruff count** (the exact number the ratchet compares):

```bash
docker run --rm -v "$PWD/apps/api":/w -w /w python:3.12-slim sh -c '
  pip install -q ruff==0.6.9 &&
  ruff check . --output-format=json |
  python -c "import json,sys;print(len(json.load(sys.stdin)))"'
```

**Web:**

```bash
docker run --rm -v "$PWD/apps/web":/w -w /w node:20-alpine sh -c '
  corepack enable && pnpm install --frozen-lockfile &&
  pnpm exec tsc --noEmit &&
  NEXT_PUBLIC_API_URL=https://neema.bethanyhouse.co.ke/api \
  NEXT_PUBLIC_WS_URL=ws://neema.bethanyhouse.co.ke \
  pnpm run build'
```

---

## Updating the ruff baseline

`.ci/ruff-baseline.txt` holds a single number and nothing else.

**Lowering it (the only direction you should normally move):** when you
genuinely fix findings, run the ruff count command above, write the new number
into the file, and commit it in the same PR as the fix. The job prints a
`::notice::` telling you the new number whenever the count drops, so you don't
have to work it out yourself. Lowering is not enforced — CI stays green if you
forget — but every number you leave on the table is a finding someone can
reintroduce for free.

**Raising it:** don't. If CI says the count went up, the PR added findings; fix
them. The only legitimate reason to raise the baseline is a ruff **version
bump** that introduces new rules or changes existing ones. In that case bump the
pin in both `apps/api/requirements-dev.txt` and the `Install ruff` step, re-run
the count, and say so explicitly in the PR description.

Deliberately not doing: `ruff --fix` on the backlog. It touches ~45 unused
imports across the app and would bury real review in noise. Fix them in
dedicated passes.

> Note: 4 of the current findings are `F821 undefined-name`
> (`app/main.py` × 3, `app/services/wa_native.py` × 1) — those are real latent
> `NameError`s, not style nits, and deserve their own fix.

---

## Emergency: shipping without the gate

**When:** production is down, you have a one-line fix, and you cannot wait for
the suite (or the suite itself is broken by an infrastructure problem — a GitHub
outage, a dead package index).

**When not:** a test is failing and you think it's flaky. Investigate it. A
flaky test in this suite has never been flaky; the suite is pure and
deterministic (no network, no clock dependence, no services).

**How:** Actions → **Build & Push** → *Run workflow* → branch `main` → tick
**skip_tests** → *Run workflow*. This skips the `ci` job and builds/pushes the
images directly, so the box picks them up on the next tick.

**Afterwards:** open a follow-up PR the same day that gets CI green again. A
skipped gate is a debt, not a decision.

---

## Recommended branch protection

CI only *blocks the deploy*; it does not by itself stop a merge. To make these
checks required on `main`, the repo owner can run:

```bash
gh api -X PUT repos/mosesmwicigi24-pixel/neema-ai/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -F 'required_status_checks[strict]=true' \
  -F 'required_status_checks[checks][][context]=API tests (pytest)' \
  -F 'required_status_checks[checks][][context]=Import smoke (crash-loop guard)' \
  -F 'required_status_checks[checks][][context]=Migrations (single head + fresh-DB replay)' \
  -F 'required_status_checks[checks][][context]=Lint ratchet (ruff)' \
  -F 'required_status_checks[checks][][context]=Web (typecheck + build)' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews=' \
  -F 'restrictions='
```

This is a repo-settings change and is left to the owner.
