# ── build stage: install dependencies into a self-contained venv ──────────────
FROM python:3.15-alpine AS build

COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /venv \
 && /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
 && /venv/bin/pip uninstall -y pip

# ── runtime stage: same base, plus the venv and app; no pip/setuptools ────────
FROM python:3.15-alpine

ARG APP_VERSION=0.1.0
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="finance_tracker" \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.revision=$VCS_REF

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINANCE_TRACKER_DATA_DIR=/data \
    PATH=/venv/bin:$PATH

# The base image's own pip and ensurepip wheels are never used at runtime;
# removing them drops them from the image's vulnerability surface.
RUN python -m pip uninstall -y pip \
 && rm -rf /usr/local/lib/python3.15/ensurepip \
 && mkdir -p /data

COPY --from=build /venv /venv

WORKDIR /app
COPY . .

EXPOSE 5757

CMD ["gunicorn", "--bind", "0.0.0.0:5757", "--worker-class", "gthread", "--workers", "1", "--threads", "4", "--timeout", "60", "--preload", "wsgi:app"]
