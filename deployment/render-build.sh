#!/usr/bin/env bash
# Render build step for the ums-web service. Runs once per deploy.
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --noinput

# Safe to run on every deploy: Django only applies migrations that haven't
# run yet, so this is a no-op after the first successful deploy.
python manage.py migrate --noinput
