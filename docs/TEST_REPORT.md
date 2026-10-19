# UMS test and verification report (actual results)

Environment used: Ubuntu 24.04 sandbox, Python 3.12, Django 5.x, PostgreSQL 16, Redis 7. Date of run: October 2026.

| Check | Result |
|---|---|
| Full Django test suite on SQLite (latest run) | **639 tests, 0 failures** (8 skipped: 2 concurrency tests that need PostgreSQL, 6 pre-existing) |
| Full Django test suite on **PostgreSQL 16** (parallel, before the last small additions) | **624 tests, 0 failures** (6 skipped); the 2 concurrency tests were run separately on PostgreSQL and passed |
| Fresh database migration on PostgreSQL (172 migrations) | Passed |
| `makemigrations --check` | No pending model changes |
| `check --deploy` with production env vars | Only `SECURE_HSTS_SECONDS` and `SECURE_SSL_REDIRECT` warnings; both are opt-in by env var until HTTPS is live |
| `collectstatic` | 163 files copied, 467 post-processed |
| gunicorn, `DEBUG=0`, PostgreSQL | `/health/` 200, `/ready/` 200 (database reachable), login page 200; protected URLs redirect anonymous users (302) or 404; security headers present (X-Frame-Options DENY, nosniff, Referrer-Policy) |
| Startup without `DJANGO_SECRET_KEY` and `DEBUG=0` | Refuses to start (correct) |
| Celery worker + Redis + PostgreSQL | Worker connected, `scheduler_tick_task` and `run_automation_task` executed successfully |
| Concurrent seat allocation on PostgreSQL (`academics/tests_concurrency.py`): 8 students racing for 2 seats; the same student registering twice in parallel | Passed: exactly 2 seats filled, 6 refused, no duplicate registration (skipped on SQLite, which has no row locks) |
| PostgreSQL backup/restore round trip | 114 tables, 25 roles, 172 migration records identical after restore |

## Smoke tests (`core/tests_smoke.py`)
* Every URL that needs no arguments, requested as 10 kinds of user (anonymous, system admin, teacher, student, registrar, finance officer, IT admin,
  vice chancellor, exam controller, HR officer): **no page returns a server error**.
* Every internal link shown on 7 role dashboards leads to a real page (no 404/5xx).
* A student login with no linked student record now gets a clear message instead of a logged crash.
These do not prove the pages look right; no browser was available.

## Bulk import / export (`registration/tests_import.py`, 10 tests)
* Import needs `students.create`/`students.edit` for each row's program; teachers, students and the IT administrator are refused; a department-scoped registrar cannot import into another department.
* The file is fully checked first (nothing saved); any bad row (empty name, bad status, unknown program, duplicate admission number, bad email) blocks the whole file and is listed by line number.
* An import cannot change an existing student's program (must use the enrollment workflow); new accounts are inactive with no password.
* Export is limited to the user's scope, neutralises spreadsheet formulas, and both import and export are audited.

## Authorization tests included in the suite
* `core/tests_idor.py` (14 tests): Teacher B vs Teacher A's marks, grade edit/unlock/correction, submissions, quizzes, online classes, attendance corrections, and student documents;
  students vs other students; Finance / IT / Admission officers vs academic records. All must return 403/404.
* `governance/tests.py`: office role catalogue, separation of duties, emergency access, provisioning scope, three-person result publication.
* `workflow/tests.py`: staged approvals, maker-checker, system administrator refused when an office holder exists.

## NOT verified in this environment
* Docker image build and `docker compose up` (Docker is not available here).
* Render / Railway deployment, HTTPS termination and HSTS on a real domain.
* Real SMTP delivery (OTP / verification / reset emails).
* Payment gateways (Safepay, Easypaisa, JazzCash, bank): no credentials, no sandbox test.
* Physical biometric hardware (the UI shows "Not configured").
* Browser rendering / mobile layout and accessibility (no browser was used).
* A load or penetration test.
