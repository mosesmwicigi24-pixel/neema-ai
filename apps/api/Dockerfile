# ── Stage 1: Builder ──────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install into the default site-packages (no --prefix)
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runner ───────────────────────────────────────
FROM python:3.12-slim AS runner
WORKDIR /app

# The commit this image was built from (deploy.yml passes it). /api/health
# returns it so the box's running version is readable from outside.
ARG GIT_SHA=""
ENV GIT_SHA=$GIT_SHA

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y libpq5 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Media mountpoint must exist appuser-owned BEFORE the volume is first used:
# Docker seeds a fresh named volume from the image path's ownership, and a
# root-owned mountpoint turns every upload into EACCES for the non-root app.
RUN mkdir -p /var/neema/media && chown appuser:appgroup /var/neema/media

# Copy installed packages from builder's default site-packages
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/api/health').raise_for_status()"

CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]