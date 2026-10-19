# UMS production deployment guide

Everything below marked **(verified)** was actually run while preparing this release (see `docs/TEST_REPORT.md`).
Everything marked **(not verified)** needs real infrastructure or credentials and must be tested by you before go-live.

## 1. Requirements
Python 3.12, PostgreSQL 14+ (primary database), Redis 6+ (only for Celery/scheduling/cache), a reverse proxy providing HTTPS.

## 2. Required environment variables
See `deployment/production.env.example`. Minimum: `DEBUG=0`, `DJANGO_SECRET_KEY` (>= 50 chars), `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, PostgreSQL settings, `FIELD_ENCRYPTION_KEY`. The app refuses to start with `DEBUG=0` and no secret key (verified).

## 3. First deployment
```
pip install -r requirements.txt gunicorn
python manage.py migrate --noinput            # fresh PostgreSQL migration: verified
python manage.py seed_roles                   # installs the 25 office roles
python manage.py collectstatic --noinput      # verified
python manage.py createsuperuser              # the System Administrator (technical owner)
gunicorn ums_project.wsgi:application --bind 0.0.0.0:8000 --workers 3
python manage.py check --deploy               # should list only SECURE_SSL_REDIRECT / HSTS until HTTPS is enabled
```
Health: `GET /health/` (process alive) and `GET /ready/` (database reachable; returns 503 otherwise). Both verified over a real gunicorn + PostgreSQL run.

## 4. First office holders
Log in as the System Administrator -> Governance -> create the first Vice Chancellor / Registrar accounts (bootstrap path). From then on each
office head creates accounts only for the roles under them (`/governance/provision/`). The System Administrator cannot approve university matters;
the only exception is time-limited, reasoned Emergency Access (`/governance/emergency/`).

## 5. Docker / Compose
`docker compose up --build` starts PostgreSQL, Redis, web (gunicorn), a Celery worker/beat and nginx (see `docker-compose.yml`).
**Not verified:** Docker is not available in the environment used to prepare this release, so the images were never built or started here.
Run `docker compose build && docker compose up` once and confirm `/ready/` before relying on it.

## 6. Render / Railway
`render.yaml`, `render-free.yaml` and `railway.toml` are provided. **Not verified** (no platform account). Set the same variables as section 2 on
the web service **and** every worker service - especially `FIELD_ENCRYPTION_KEY` and `DJANGO_SECRET_KEY`. Free tiers have no persistent disk:
use S3-compatible storage (`CLOUD_STORAGE_*`) for uploads and a paid/persistent database for real data.

## 7. Celery / Redis (verified locally)
`celery -A ums_project worker -l info` connected to Redis, registered `core.tasks.*`, and executed `scheduler_tick_task` and `run_automation_task`
against PostgreSQL successfully. Set `SCHEDULER_MODE=celery` and run one worker plus one beat/scheduler in production.

## 8. Backup and restore (verified)
```
pg_dump -h HOST -U USER -Fc ums > ums_$(date +%F).dump
createdb ums_restore && pg_restore -h HOST -U USER -d ums_restore --no-owner ums_$(date +%F).dump
```
A dump/restore round trip reproduced all 114 tables, all 25 roles and all 172 migration records. Also back up `media/` (or your object storage) and the
`FIELD_ENCRYPTION_KEY`. A database backup without the key cannot decrypt CNIC fields. Test restores regularly.

## 9. Encryption key
Keep `FIELD_ENCRYPTION_KEY` identical across web, workers and scheduler and never regenerate it on startup. To rotate: back up the database, keep the
old key, verify decryption, re-encrypt with the new key, validate, deploy the new key everywhere, and keep the old key until recovery is proven.

## 10. Production checklist
- [ ] `DEBUG=0`, strong `DJANGO_SECRET_KEY`, stable `FIELD_ENCRYPTION_KEY`
- [ ] HTTPS working, then `SECURE_SSL_REDIRECT=1`, `SECURE_COOKIES=1`, `SECURE_HSTS_SECONDS`
- [ ] `python manage.py check --deploy` clean
- [ ] PostgreSQL with backups and a tested restore
- [ ] SMTP configured and a real verification email received (**not verified**)
- [ ] Payment gateway sandbox payment + webhook signature tested (**not verified**)
- [ ] Celery worker + scheduler running; failures monitored
- [ ] First office holders created; System Administrator not holding office roles
- [ ] Teacher/student isolation tests (`core/tests_idor.py`) green on your database
- [ ] Physical biometric hardware: shows "Not configured" until a real device is integrated

## 11. Known limitations
* Docker, Render, Railway, SMTP, payment gateways and biometric hardware are untested here.
* HSTS and SSL redirect are opt-in by environment variable so a plain-HTTP trial server is never locked out.
* The URL-guessing (IDOR) test matrix covers the main teacher/student/office endpoints, not every route.
* Field-level hiding of sensitive data (e.g. CNIC) beyond encryption at rest has not been separately audited.
