# PoE Community Companion — production image.
# Multi-stage build: build toolchain (for Pillow's C extensions) stays in the
# builder stage only; the final image ships no compilers.

FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps needed only to compile Pillow wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg62-turbo-dev \
        zlib1g-dev \
        libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    DATA_DIR=/app/data \
    MEDIA_DIR=/app/media

# Runtime-only shared libs matching the wheels built above (no compilers).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        libwebp7 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# App code last so earlier layers (deps) stay cached across code-only changes.
COPY app/ ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Build-time collectstatic needs a SECRET_KEY and does not touch the DB.
# DJANGO_ALLOWED_HOSTS/etc are irrelevant here; whitenoise just needs the
# staticfiles manifest built.
RUN mkdir -p /app/data /app/media /app/staticfiles \
    && DJANGO_SECRET_KEY=build-time-only-not-used-at-runtime \
       python manage.py collectstatic --noinput

RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "4", \
     "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-"]
