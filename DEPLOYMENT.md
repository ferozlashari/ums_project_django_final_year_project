# UMS Deployment Guide

The same code runs everywhere; only environment variables change. Pick the row that fits.

| Option | Needs | Scheduler | Best for |
|---|---|---|---|
| Local (Windows/Linux) | Python | none (use Automation Center) | development |
| **Free single process** (Render free, Railway, Heroku-style) | PostgreSQL | `builtin` + optional pinger | small or low-traffic site |
| **Docker lite** (`docker-compose.lite.yml`) | Docker | `builtin` | small server |
| **Docker full** (`docker-compose.yml`) | Docker | `celery` | proper server |
| **VPS** (Ubuntu + nginx + systemd) | a server | `builtin` or `celery` | real university deployment |

**Free hosting tiers are not suitable for production.** Free tiers sleep when idle, expire databases (Render free Postgres ~30 days),
have ephemeral disks and no backups. A real university system needs paid, persistent infrastructure and backups.

## 0. Variables every deployment needs
| Variable | Notes |
|---|---|
| `DJANGO_SECRET_KEY` | 50+ chars. `python -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `FIELD_ENCRYPTION_KEY` | `python manage.py generate_encryption_key`. **Identical on web, worker and beat** or CNIC fields become unreadable. Back it up separately from database backups. |
| `DEBUG=0`, `DATABASE_URL` (or `DB_ENGINE=postgresql` + `POSTGRES_*`) | |
| `SMTP_HOST/PORT/USER/PASSWORD`, `DEFAULT_FROM_EMAIL` | Without SMTP, verification/reset codes are only printed to the console. |
| `SECURE_SSL_REDIRECT=1 SECURE_PROXY_SSL_HEADER=1 SECURE_COOKIES=1` | Behind HTTPS. |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Render/Railway hostnames are trusted automatically. |

Never commit `.env`, keys, passwords or the production database.

## 1. Background jobs — choose one (`SCHEDULER_MODE`)
Jobs: automation (fee reminders, late fees, challans, low-attendance, standing), risk scoring, data-quality scan.
Every job is database-locked and only runs when due, so doubling up triggers is harmless.

* `builtin` — `python manage.py run_scheduler` beside the web process. **No Redis.** `deployment/start-single.sh` starts it for you.
* `external` — a free pinger calls `POST /internal/cron/` with `Authorization: Bearer $CRON_SECRET` every 5–15 min.
  This also wakes a sleeping free host. Set `CRON_SECRET` (20+ chars); without it the endpoint returns 404.
* `celery` — Redis + worker + beat. Set `CELERY_BROKER_URL`.
* `off` — nothing scheduled.

Check status in **Automation Center** (real last-run times, no invented countdown) and with `python manage.py production_check`.

## 2. Local
```
pip install -r requirements.txt && cp .env.example .env
python manage.py migrate && python manage.py createsuperuser && python manage.py runserver
```
Run tests: `pip install -r requirements-dev.txt && DEBUG=1 python manage.py test`

## 3. Render
* **Free tier:** New → Blueprint → `render-free.yaml` (one web service + free Postgres, built-in scheduler).
  Add a pinger for `/internal/cron/` (secret = the generated `CRON_SECRET`). Uploads need `CLOUD_STORAGE_*` or they vanish on redeploy.
* **Full stack:** `render.yaml` (web + worker with embedded beat + Postgres + Redis). Render has **no free worker plan**.
  Secrets are generated once in the `ums-shared` env group so web and worker always match.
  Enter the SAME SMTP values when Render prompts for web and worker.
* After first deploy: Shell → `python manage.py createsuperuser`, then `python manage.py production_check`.

## 4. Railway
Add PostgreSQL, deploy this repo (`railway.toml` uses the Dockerfile and `deployment/start-single.sh`).
Set the section 0 variables plus `CRON_SECRET`. For Celery add Redis, `SCHEDULER_MODE=celery`, and a second service running the Procfile `worker` line.

## 5. Docker
```
cp .env.example .env     # set DJANGO_SECRET_KEY, FIELD_ENCRYPTION_KEY, POSTGRES_PASSWORD, DB_ENGINE=postgresql
docker compose -f docker-compose.lite.yml up --build     # Postgres + app, http://localhost:8000
docker compose up --build                                # full: nginx, web, worker, beat, Postgres, Redis, http://localhost
```
Only `web` runs migrations; worker/beat wait for web's healthcheck (`/ready/` checks the database).

## 6. VPS (Ubuntu)
1. `apt install nginx postgresql redis-server python3-venv certbot python3-certbot-nginx`; create user `ums`, project in `/srv/ums`.
2. Put the variables in `/etc/ums/ums.env` (mode 600). All units read this one file, so keys match.
3. `venv/bin/pip install -r requirements.txt`; `manage.py migrate`, `collectstatic`, `createsuperuser`.
4. Copy `deployment/systemd/ums-web.service` and either `ums-scheduler.service` (no Redis) **or** `ums-worker.service` + `ums-beat.service`; `systemctl enable --now`.
5. `deployment/nginx-vps.conf` → `/etc/nginx/sites-available/ums`; `certbot --nginx -d your.domain`; set `MEDIA_ACCEL_PREFIX=/_protected_media/`.
6. Firewall: allow 22, 80, 443 only. Never expose Postgres/Redis.

## 7. Private uploads
CNIC scans, certificates and submissions are **never** served from a public path. `/media/<file>` requires login and the
file's own access rule (owner, the reviewing staff, or System Admin). Behind nginx the file is streamed from an internal-only location.

## 8. Backups
`deployment/backup.sh` (pg_dump + media + retention) from cron; restore steps are in the script header.
Keep `FIELD_ENCRYPTION_KEY` backed up separately. **Test a restore** — an untested backup is not a backup.

## 9. Before calling it live
```
python manage.py check --deploy
python manage.py production_check --strict
python manage.py collectstatic --noinput
DEBUG=1 python manage.py test
```
Then test the real flows: register → email code/link → login → password reset → sub-admin permissions → registration → attendance →
marks → submit → verify → publish → correction → challan → Safepay sandbox callback → Celery/scheduler run.

## Before going live
Test these in your own environment: the PostgreSQL connection, Redis and Celery workers (if used), `docker compose up`,
a real deployment on your host, real SMTP delivery, and a Safepay payment in its test environment. JazzCash and Easypaisa
need merchant credentials and show as "Not configured" until the institution supplies them.
