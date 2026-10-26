# ── build stage: install dependencies under /install, laid out like /usr/local ─
FROM python:3.15-alpine AS build

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# ── runtime stage: same base, plus the packages and app; no pip/setuptools ────
FROM python:3.15-alpine

ARG APP_VERSION=0.1.0
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="finance_tracker" \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.revision=$VCS_REF

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINANCE_TRACKER_DATA_DIR=/data

# The base image's own pip and ensurepip wheels are never used at runtime;
# removing them drops them from the image's vulnerability surface.
RUN python -m pip uninstall -y pip \
 && rm -rf /usr/local/lib/python3.15/ensurepip \
 && mkdir -p /data

# Packages land in /usr/local (gunicorn in /usr/local/bin), not a venv, so they
# work even when a container carries its own PATH from an older image.
COPY --from=build /install /usr/local

WORKDIR /app
COPY . .

EXPOSE 5757

CMD ["gunicorn", "--bind", "0.0.0.0:5757", "--worker-class", "gthread", "--workers", "1", "--threads", "4", "--timeout", "60", "--preload", "wsgi:app"]
