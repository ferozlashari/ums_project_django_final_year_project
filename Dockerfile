# University Management System - production image
# Build:  docker build -t ums:latest .
# Run:    see docker-compose.yml for the full stack (app + PostgreSQL)

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=ums_project.settings

WORKDIR /app

# System packages needed to build psycopg2 (PostgreSQL driver) and Pillow.
# Uncomment default-libmysqlclient-dev if you set DB_ENGINE=mysql and
# uncomment mysqlclient in requirements.txt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

COPY . .

# Non-root user - never run the app as root in production.
RUN useradd --create-home --shell /bin/bash umsuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R umsuser:umsuser /app
USER umsuser

EXPOSE 8000

# collectstatic needs real settings (DEBUG/SECRET_KEY) at container start,
# not build time, since those come from environment variables injected at
# `docker run`/`docker compose up` - so it runs in the entrypoint below,
# not as a RUN step here.
COPY --chown=umsuser:umsuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "ums_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
