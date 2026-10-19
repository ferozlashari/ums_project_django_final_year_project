# Heroku-style process types (also read by Railway/Nixpacks and Dokku).
# Free / single process: only `web` is needed - it starts the built-in scheduler itself.
web: bash deployment/start-single.sh
# Full stack with Redis (set CELERY_BROKER_URL, SCHEDULER_MODE=celery):
worker: celery -A ums_project worker --loglevel=info --concurrency=2 --beat
