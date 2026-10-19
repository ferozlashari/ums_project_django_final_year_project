# MongoDB decision: not added

**Decision:** PostgreSQL stays the only authoritative database. MongoDB is **not** added.

## Why
UMS data is relational and transactional: students -> enrollments -> curriculum -> course registrations -> attendance -> assessments -> results,
and applicants -> preferences -> merit -> offers, and invoices -> payments -> ledger. The system depends on:

* foreign keys and referential integrity (an attendance record must point to a real session and registration);
* unique and partial-unique constraints that hold under concurrent requests (one active enrollment per student, one preference per rank,
  one mark per registration/component, curriculum version uniqueness) - these are already enforced by the database;
* transactions across several tables (seat allocation, payment -> ledger -> receipt, result publication);
* reporting joins (GPA/CGPA, fee reconciliation, department dashboards).

A document database gives none of this for free, and storing the same student/enrollment/payment record in two databases would create two
sources of truth that can disagree.

## Questions that must be answered before MongoDB is ever added
| Question | Today's answer |
|---|---|
| Which exact workload needs documents? | None identified. AI chat history, notifications and audit logs are small, structured and already live in PostgreSQL with access control. |
| Why is PostgreSQL not enough? | It is enough. `JSONField` already covers flexible payloads (e.g. policy values, payment-provider payloads). |
| Volume / query pattern that justifies it? | A single-university deployment is far below the scale where this matters. |
| Access control and retention? | Would need re-implementing outside Django's permission layer. |
| What if it is down? | Core UMS must not depend on it. |
| Operations (backup, monitoring, tests)? | One more stateful service to run, back up and secure. |

## If a real need appears later
Use a feature flag, a separate settings block and explicit schemas; never make it a startup dependency; keep authoritative academic and
financial records in PostgreSQL only; store uploaded files in object storage (S3-compatible, already supported via `CLOUD_STORAGE_*`), not in MongoDB.
