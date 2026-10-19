"""Validated bulk student import/export.

Nothing is written until every row of the file has been checked. Each row is
validated independently (required fields, duplicates, values, program, and the
importing user's own authority over that program) and the result is a list of
row-level errors the operator can fix. The commit step re-validates and then
writes everything in ONE transaction.
"""
import csv
import io
import re
from dataclasses import dataclass, field

from django.db import transaction

STATUSES = {'active', 'graduated', 'suspended', 'withdrawn'}
GENDERS = {'male', 'female', 'other'}
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@dataclass
class RowResult:
    line: int
    admission_no: str = ''
    action: str = ''                       # 'create' | 'update'
    errors: list = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class ImportReport:
    rows: list = field(default_factory=list)
    file_errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.file_errors and all(not r.errors for r in self.rows) and bool(self.rows)

    @property
    def creates(self):
        return sum(1 for r in self.rows if r.action == 'create' and not r.errors)

    @property
    def updates(self):
        return sum(1 for r in self.rows if r.action == 'update' and not r.errors)

    @property
    def error_rows(self):
        return [r for r in self.rows if r.errors]


def csv_safe(value):
    """Stop spreadsheet formula injection in exported cells (=, +, -, @ at the start)."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def validate(raw_bytes, user):
    from academics.models import Program
    from governance.permissions import has_perm
    from registration.models import Student

    report = ImportReport()
    if len(raw_bytes) > MAX_BYTES:
        report.file_errors.append('The file is larger than 2 MB.')
        return report
    try:
        text = raw_bytes.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        headers = {(h or '').strip().lower() for h in (reader.fieldnames or [])}
    except (UnicodeDecodeError, csv.Error):
        report.file_errors.append('The file is not a valid UTF-8 CSV.')
        return report
    if not ({'admission_no', 'admission'} & headers):
        report.file_errors.append('Missing required column: admission_no.')
    if not ({'full_name', 'name'} & headers):
        report.file_errors.append('Missing required column: full_name.')
    if report.file_errors:
        return report

    seen = set()
    programs = {}
    try:
        all_rows = list(reader)
    except csv.Error:
        report.file_errors.append('The file could not be parsed as CSV.')
        return report
    if len(all_rows) > MAX_ROWS:
        report.file_errors.append(f'Too many rows ({len(all_rows)}); the limit is {MAX_ROWS} per file.')
        return report

    for i, raw in enumerate(all_rows, start=2):                       # line 1 is the header
        row = {(k or '').strip().lower(): (v or '').strip() for k, v in raw.items() if k}
        admission_no = row.get('admission_no') or row.get('admission') or ''
        full_name = row.get('full_name') or row.get('name') or ''
        res = RowResult(line=i, admission_no=admission_no)
        report.rows.append(res)
        if not admission_no:
            res.errors.append('admission_no is empty')
        if not full_name:
            res.errors.append('full_name is empty')
        if admission_no:
            if admission_no.lower() in seen:
                res.errors.append('duplicate admission_no inside this file')
            seen.add(admission_no.lower())
        status = row.get('status', '')
        if status and status not in STATUSES:
            res.errors.append(f'status "{status}" is not one of {sorted(STATUSES)}')
        gender = row.get('gender', '')
        if gender and gender not in GENDERS:
            res.errors.append(f'gender "{gender}" is not one of {sorted(GENDERS)}')
        email = row.get('email', '')
        if email and not EMAIL_RE.match(email):
            res.errors.append('email is not a valid address')

        program = None
        pv = row.get('program_code') or row.get('program') or ''
        if pv:
            if pv.lower() not in programs:
                programs[pv.lower()] = (Program.objects.filter(code__iexact=pv).first()
                                        or Program.objects.filter(name__iexact=pv).first())
            program = programs[pv.lower()]
            if program is None:
                res.errors.append(f'program "{pv}" does not exist')

        existing = Student.objects.filter(admission_no=admission_no).first() if admission_no else None
        res.action = 'update' if existing else 'create'
        needed = 'edit' if existing else 'create'
        scope = {'program': program, 'department': program.department} if program else {}
        if existing and not program and existing.active_program:
            scope = {'program': existing.active_program, 'department': existing.active_program.department}
        if not has_perm(user, 'students', needed, **scope):
            res.errors.append(f'you are not authorised to {needed} students' + (f' in {program or existing.active_program}' if (program or (existing and existing.active_program)) else ''))
        if existing and program and existing.active_program_id and existing.active_program_id != program.pk:
            res.errors.append('this would change the student\'s program; use the transfer/enrollment workflow instead')
        res.data = {'full_name': full_name, 'program': program, 'status': status, 'gender': gender, 'email': email,
                    'phone': row.get('phone', ''), 'address': row.get('address', ''), 'cnic': row.get('cnic', ''),
                    'username': row.get('username', '')}
    if not report.rows:
        report.file_errors.append('The file has no data rows.')
    return report


@transaction.atomic
def commit(raw_bytes, user):
    """Re-validate, then write every row or nothing. Returns (report, created, updated)."""
    from django.contrib.auth.models import User
    from core.models import Profile
    from registration.models import Student

    report = validate(raw_bytes, user)
    if not report.ok:
        return report, 0, 0
    created = updated = 0
    for res in report.rows:
        d = res.data
        if res.action == 'update':
            s = Student.objects.get(admission_no=res.admission_no)
            s.full_name = d['full_name']
            if d['program'] and not s.active_program_id:
                s.program = d['program']
            for f in ('phone', 'address'):
                if d[f]:
                    setattr(s, f, d[f])
            if d['gender']:
                s.gender = d['gender']
            if d['status']:
                s.status = d['status']
            s.save()
            updated += 1
        else:
            base = d['username'] or res.admission_no.lower().replace(' ', '_')
            username, n = base, 1
            while User.objects.filter(username__iexact=username).exists():
                username, n = f'{base}_{n}', n + 1
            parts = d['full_name'].split()
            u = User(username=username, email=d['email'], first_name=parts[0], last_name=' '.join(parts[1:]), is_active=False)
            u.set_unusable_password()          # no shared password is ever invented
            u.save()
            Profile.objects.update_or_create(user=u, defaults={'role': 'student'})
            Student.objects.create(user=u, full_name=d['full_name'], admission_no=res.admission_no, cnic=d['cnic'],
                                   phone=d['phone'], address=d['address'], gender=d['gender'], program=d['program'],
                                   status=d['status'] or 'active')
            created += 1
    return report, created, updated
