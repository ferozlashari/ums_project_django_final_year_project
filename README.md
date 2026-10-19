# University Management System (UMS)

A production-oriented Django University Management System for academic and campus operations. The project keeps one coherent Django architecture and connects authentication, students, academics, attendance, examinations, finance, library, hostel, admissions, HR, transport, complaints, scholarships, careers, online classes, notifications, reporting, and a privacy-first local assistant.

## Design goals

- **Real workflows:** records are created and updated through authenticated web workflows, not static pages.
- **Automation first:** course registration, challan generation, quiz scoring, notifications, fee reminders, late penalties, library reminders, and attendance alerts reduce routine manual work.
- **Deployment & verification:** see [docs/PRODUCTION.md](docs/PRODUCTION.md), [docs/TEST_REPORT.md](docs/TEST_REPORT.md) and [docs/MONGODB_DECISION.md](docs/MONGODB_DECISION.md) (PostgreSQL stays the only authoritative database).
- **Office-based governance:** 25 university office roles (Chancellor/VC, Registrar, Dean, HOD, Admissions, Examination, Finance, HR, Services, IT, Audit) with scoped permissions, separation of duties, multi-person approvals and break-glass auditing — see [GOVERNANCE.md](GOVERNANCE.md). The Parent/Guardian portal is an optional extension.
- **Role isolation:** every role's access is enforced server-side.
- **Zero-cost core:** SQLite + local file storage + Django + open-source Python packages are enough to run the system. No paid API is required.
- **Safe failure:** unexpected exceptions are logged server-side and users receive a friendly message instead of a traceback.
- **Responsive UI:** the same application works on desktop and mobile browsers and includes PWA assets.

## Main modules

### Identity and security
- Django authentication and password hashing
- Username plus student admission number/CNIC login support
- Email verification and password reset
- Login throttling and session timeout
- Optional WebAuthn/passkey verification
- Role-based authorization
- CSRF protection and secure state-changing requests
- File-upload validation
- Field-level encryption support for sensitive values
- Server-side logging and friendly error handling

### Academic operations
- Departments, programs, semesters and courses
- Course sections and instructor allocation
- Student self-service course registration/drop
- Seat-capacity protection
- Timetable and clash detection
- Attendance with manual, self check-in and WebAuthn verification
- Attendance percentage and early-warning alerts
- Exams, grades, GPA/CGPA and marksheets
- Retake/improvement workflows
- Admit-slip eligibility checks
- Assignments and submissions
- Online quizzes with automatic scoring

### Student services
- Admissions
- Student profiles and printable ID cards
- Fee challans and payment-reference submission
- Payment verification workflow
- Automatic overdue reminders and late penalties
- Library catalog, physical loans, fines and digital documents
- Hostel applications and room assignment
- Scholarships
- Complaints
- Transport assignments
- Online classes through free Jitsi meeting rooms
- Careers, internships and applications
- Alumni and mentorship
- Guardian read-only portal
- Notices and in-app notifications

### Local assistant
The default UMS Assistant is **local and zero-cost**. It answers common UMS questions using the authenticated user's own permitted data and Django ORM queries. No API key or internet connection is required.

Optional free-tier Groq/Hugging Face integration remains available for installations that deliberately choose it. If an optional provider is unavailable, the assistant automatically falls back to the local assistant.

## First-time setup

The system starts empty and contains no sample users or records. After installing:

1. Create the System Administrator: `python manage.py createsuperuser`
2. Sign in and open **Data Entry Hub** (`/setup/`). It lists every setup step in order: academic session, semesters, faculties, departments, programs, courses, sections, staff, students and fee policies.
3. Set the university name, policies and email options in **Site Settings**.

## Automation

Run:

```bash
python manage.py run_automation
```

The command automatically handles:

- fee due-soon reminders
- overdue fee alerts
- one-time 5% late-penalty challans
- library due/overdue reminders
- low-attendance warnings
- duplicate-notification suppression for 24 hours

Test without changing data:

```bash
python manage.py run_automation --dry-run
```

For a real deployment, schedule this command once or twice per day using Windows Task Scheduler or cron. The project does not require Celery, RabbitMQ, Redis, Docker, Kubernetes, or any paid scheduler.

## Quick start — Windows 11

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

Open:

`http://127.0.0.1:8000/`

### One-command setup

```powershell
.\setup.bat
```

The setup script installs dependencies, applies committed migrations, runs Django checks and starts the development server. It does **not** generate migrations automatically.

## Linux/macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

## Database

SQLite is the default and requires no database server.

For larger installations, PostgreSQL is supported by setting:

```env
DB_ENGINE=postgresql
POSTGRES_DB=ums
POSTGRES_USER=umsuser
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Then:

```bash
python manage.py migrate
```

## Environment configuration

Copy `.env.example` to `.env` and change at minimum:

```env
DJANGO_SECRET_KEY=generate-a-long-random-secret
DEBUG=1
ALLOWED_HOSTS=localhost,127.0.0.1
DB_ENGINE=sqlite
LLM_PROVIDER=local
```

Generate a production secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Never commit `.env` or real credentials.

## Production checklist

Before production deployment:

```bash
python manage.py check --deploy
python manage.py collectstatic --noinput
```

Use `DEBUG=0`, a unique secret key, correct `ALLOWED_HOSTS`, HTTPS, secure cookies, backups, and a production WSGI/ASGI server. Do not use Django's `runserver` as the production web server.

## Free online classes

Online classes use Jitsi Meet room URLs. The UMS application only schedules and authorizes access; the actual video meeting is handled by the free Jitsi service.

## Public admissions and verification

The project supports:

- public admission applications
- authenticated student applications
- public challan/payment-status verification

Public pages expose only the minimum information necessary for verification.

## Testing

Run the complete Django test suite:

```bash
python manage.py test
```

Also run:

```bash
python manage.py check
python manage.py check --deploy
```

## Project structure

```text
ums_project_django5/
├── academics/
├── admissions/
├── ai_assistant/
├── alumni/
├── api/
├── assignments/
├── attendance/
├── biometrics/
├── careers/
├── complaints/
├── core/
├── exams/
├── finance/
├── hostel/
├── hr/
├── library/
├── onlineclass/
├── parents/
├── quizzes/
├── registration/
├── risk_analytics/
├── scholarships/
├── timetable/
├── transport/
├── ums_project/
├── manage.py
├── requirements.txt
├── requirements-ai.txt       # optional external AI integrations
├── .env.example
├── setup.bat
├── setup.sh
└── run_automation.bat / run_automation.sh
```

The project intentionally avoids unnecessary microservices and paid infrastructure. Django remains the single source of truth for authentication, business rules, database transactions, permissions, templates, and APIs.

## Operational monitoring

Two lightweight endpoints are included for local/prod monitoring:

- `GET /health/` — liveness check; returns only a generic service status.
- `GET /ready/` — readiness check; verifies database connectivity and returns HTTP 503 if the database is unavailable.

Neither endpoint exposes credentials, exception messages, database details, or student information.

## Optional AI integrations

The core application is intentionally independent of external AI services. Install `requirements-ai.txt` only if you explicitly want the optional LangGraph/Groq/Hugging Face integrations:

```bash
pip install -r requirements-ai.txt
```

Keep `LLM_PROVIDER=local` for the zero-cost offline assistant.

## Production workflow engine
The project now centralizes authoritative university rules in `core/services/`:
- `academic.py` — semester/program/prerequisite/duplicate/capacity/credit checks and atomic course registration.
- `exams.py` — attendance/fee/registration checks for exam eligibility.
- `finance.py` — atomic payment submission and confirmation.
- `automation.py` — idempotent due-fee and low-attendance monitoring.

Administrators configure policy values in Site Settings; normal student operations are validated and executed by these services rather than by template logic.

## REST API
Authenticated API clients can use session authentication or DRF token authentication. Obtain a token at `/api/v1/auth/token/` and send `Authorization: Token <token>`.
Core self-service endpoints include `/api/v1/me/academic-summary/`, `/api/v1/me/eligible-sections/`, `/api/v1/me/exam-eligibility/`, `/api/v1/me/fees/`, `/api/v1/me/register-course/`, and `/api/v1/me/invoices/<id>/payment/`.

## AI providers
The built-in assistant is always available without an API key. Optional providers are Groq, Hugging Face, and Google Gemini. AI is an assistance layer only: it cannot execute arbitrary SQL/commands or bypass Django permissions, validation, transactions, or audit requirements.


## Known limitations

- The automated test suite runs on SQLite. Run it against PostgreSQL (and Redis, if used) in your own environment before going live.
- Payment providers (EasyPaisa/JazzCash/bank), SMS, e-mail and physical biometric hardware need real external accounts/devices; only the adapter/configuration layer is included, and unconfigured integrations show as "Not Configured".
- Timetable generation is a simple first-fit planner (it never forces a clash, but it does not optimise quality). Transport recommendation matches address words to stop names, so stop names must resemble how students write their addresses.
- The retake pipeline covers application, approval, fee challan, payment-gated eligibility and slip; there is no separate exam-seat allocation step.

## Security and release controls

### Authorization
- The Django superuser is the only unrestricted System Administrator.
- A non-superuser `is_staff` flag is never an administrative wildcard. Sub-administrators require an explicit governance RoleAssignment and are limited by module/action/scope and optional expiry.
- Teacher/faculty access remains limited to assigned teaching sections; students see their own records.
- Published results are locked. Changes use the ResultChangeRequest/approval/version history workflow.

### Email verification, reset and account changes
- Verification, password-reset and email-change messages support both a short-lived single-use 6-digit code and a signed one-click link.
- Codes are hashed, expire, are rate-limited, and are never stored in clear text.
- Real inbox delivery requires SMTP configuration; the console backend is explicitly development-only.

### Fees and challans
- Fee policies are program/semester scoped and can contain admission, semester, degree/convocation, hostel, transport, scholarship/waiver and other institution-defined items.
- Examination fee is retained only for historical compatibility and is not a per-course automatic charge. It must be explicitly configured by an authorized finance administrator if the institution actually uses it.
- Challans are generated from authoritative fee policies and invoice lines, not from client-submitted amounts.

### Payments
- Safepay has a real hosted-checkout adapter with tracker/signature/webhook verification. It is enabled only when merchant credentials are supplied.
- JazzCash/EasyPaisa/bank/card integrations must remain disabled until the institution supplies the provider's merchant credentials and completes the provider's sandbox certification. The system must never mark a payment successful merely because a browser returned.
- All payment callbacks are idempotent and ledger-affecting operations are transaction-protected.

### Deployment
Supported targets are local Windows/Linux, Docker Compose, Render, Railway-compatible container/PaaS deployment, and a conventional VPS (Nginx + Gunicorn + PostgreSQL + Redis + Celery). The current server-rendered Django application does not require Vercel. A future React/Next.js frontend can use the existing API and be hosted separately.

Run the new preflight before deployment:

```bash
python manage.py production_check
python manage.py check --deploy
python manage.py collectstatic --noinput
```

For a real deployment, run PostgreSQL, Redis, Celery worker and Celery Beat, configure the same `DJANGO_SECRET_KEY` and `FIELD_ENCRYPTION_KEY` for web/worker/beat, configure SMTP, and complete at least one real sandbox payment transaction before enabling online checkout.

Deployment matrix: see `deployment/DEPLOYMENT_MATRIX.md`.

## Role automation (teacher, results officer, student)

* **Teacher Automation** (`/teacher/automation/`): one attendance sheet for every class timetabled today (save all at once,
  optional finalise/lock, "present-all" for unmarked classes), a marks sheet per section (raw marks per assessment component;
  total, grade and grade point are calculated), "submit all complete results", and a housekeeping run (low-attendance and
  assignment-due notifications). Only the teacher's own sections are ever touched.
* **Result verification** (`/results/workflow/`): teacher submitted → department verified → exam office approved → published.
  Each stage needs its own `results` permission for the course's program; reopening needs `override` and a reason. All audited.
* **Student Smart Actions** (`/student/automation/`): register the recommended curriculum courses and generate the semester
  challan, using the same eligibility and fee rules as the normal pages.
* **Schedulers**: `SCHEDULER_MODE=builtin|external|celery|off` — see `DEPLOYMENT.md`.
