#!/usr/bin/env bash
# One-process deployment for free/PaaS hosts (Render, Railway, Heroku-style).
# Runs migrations, collects static files, starts the built-in scheduler next to
# gunicorn (no Redis / Celery needed), then serves the site.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
if [ -n "${SCHEDULER_MODE:-}" ]; then MODE="$SCHEDULER_MODE"
elif [ -n "${CELERY_BROKER_URL:-}" ]; then MODE="celery"
else MODE="builtin"; fi

[ "${RUN_MIGRATIONS:-1}" = "1" ] && python manage.py migrate --noinput
[ "${RUN_MIGRATIONS:-1}" = "1" ] && python manage.py seed_roles
[ "${RUN_COLLECTSTATIC:-1}" = "1" ] && python manage.py collectstatic --noinput

# Stop everything this script started (scheduler loop + gunicorn) on SIGTERM/SIGINT/exit,
# so a local Ctrl-C or `kill` never leaves the scheduler restart loop running behind.
cleanup() { trap - EXIT TERM INT; kill 0 2>/dev/null || true; }
trap cleanup EXIT TERM INT

if [ "$MODE" = "builtin" ]; then
  echo "Starting built-in scheduler (SCHEDULER_MODE=builtin)"
  # Restarts itself if it ever exits; every job is DB-locked so restarts are safe.
  ( while true; do python manage.py run_scheduler || true; sleep 10; done ) &
fi

gunicorn ums_project.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - &
wait $!
