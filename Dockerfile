FROM python:3.12-slim

WORKDIR /app

ARG APP_VERSION=0.1.0
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="finance_tracker" \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.revision=$VCS_REF

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINANCE_TRACKER_DATA_DIR=/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; \
    find /app -name '*.pyc' -delete 2>/dev/null; \
    mkdir -p /data

EXPOSE 5757

CMD ["gunicorn", "--bind", "0.0.0.0:5757", "--worker-class", "gthread", "--workers", "1", "--threads", "4", "--timeout", "60", "--preload", "wsgi:app"]
