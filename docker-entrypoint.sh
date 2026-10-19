#!/bin/bash
set -e
# Only ONE service (web) should migrate/collectstatic. worker/beat set
# RUN_MIGRATIONS=0 so they never race the web container on a fresh database.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "Waiting for database..."
  for i in $(seq 1 30); do python manage.py check --database default >/dev/null 2>&1 && break || sleep 2; done
  echo "Applying database migrations..."
  python manage.py migrate --noinput
  python manage.py seed_roles
  echo "Collecting static files..."
  python manage.py collectstatic --noinput
fi
echo "Starting: $@"
exec "$@"
