"""Single source of truth for the permission matrix (modules x actions)."""

MODULES = [
    ('students', 'Students'), ('admissions', 'Admissions'),
    ('programs', 'Programs / Departments / Faculties'), ('courses', 'Courses'),
    ('curriculum', 'Curriculum'), ('sections', 'Sections & Teacher Assignment'),
    ('registration', 'Course Registration'), ('attendance', 'Attendance'),
    ('exams', 'Examinations'), ('results', 'Results'),
    ('grade_policy', 'Grade Scale / Grade Policy'), ('finance', 'Finance'),
    ('scholarships', 'Scholarships'), ('library', 'Library'), ('hostel', 'Hostel'),
    ('transport', 'Transport'), ('hr', 'HR & Payroll'), ('reports', 'Reports'),
    ('automation', 'Automation Center'), ('data_quality', 'Data Quality / Exceptions'),
    ('policy', 'Policy Center'), ('security', 'Security (users / roles)'),
    ('audit', 'Audit Logs'), ('settings', 'System Settings'),
    ('executive', 'Executive Oversight (VC / Chairman dashboards)'),
    ('student_affairs', 'Student Affairs & Welfare'),
    ('documents', 'Official Documents / Transcripts'),
]

ACTIONS = [
    ('view', 'View'), ('create', 'Create'), ('edit', 'Edit'), ('delete', 'Delete'),
    ('approve', 'Approve'), ('reject', 'Reject'), ('verify', 'Verify'),
    ('publish', 'Publish'), ('unpublish', 'Unpublish'), ('assign', 'Assign'),
    ('import', 'Import'), ('export', 'Export'), ('print', 'Print'),
    ('generate', 'Generate'), ('reconcile', 'Reconcile'), ('void', 'Void'),
    ('override', 'Override'), ('configure', 'Configure'),
]

SCOPE_CHOICES = [
    ('university', 'Whole university'), ('faculty', 'One faculty'),
    ('department', 'One department'), ('program', 'One program'),
    ('semester', 'One academic semester'), ('course', 'One course'),
    ('section', 'One course section'), ('student', 'One student'),
    ('student_category', 'One student category'),
]

# The university's offices, top of the organisation to bottom. Used to group
# roles on the Governance Map and the permission matrix.
OFFICES = [
    ('governance', 'University Governance'),
    ('registry', 'Registrar\'s Office'),
    ('faculty', 'Faculty / Dean\'s Office'),
    ('department', 'Department'),
    ('admissions', 'Admissions Office'),
    ('examination', 'Examination Office'),
    ('finance', 'Finance Office'),
    ('hr', 'HR & Payroll Office'),
    ('services', 'Campus Services'),
    ('it', 'IT & Security'),
    ('audit', 'Audit & Compliance'),
]

# Additive and explicit: a Finance Officer does NOT get results, an Exam
# Controller does NOT get refunds, and so on. Each tuple is
# (name, description, {module: [actions]}).
DEFAULT_ROLES = {
    # ---- University governance: oversight and approval, NOT day-to-day CRUD
    'chancellor': ('Chancellor / Chairman', 'Institution-level oversight, reports and escalated approvals. Read-only on operations.', {
        'executive': ['view', 'approve', 'export', 'print'],
        'reports': ['view', 'export', 'print'], 'audit': ['view'],
    }),
    'vice_chancellor': ('Vice Chancellor / Rector', 'Chief executive: university dashboard, escalated approvals, exception review.', {
        'executive': ['view', 'approve', 'reject', 'export', 'print'],
        'reports': ['view', 'export', 'print', 'generate'],
        'students': ['view'], 'results': ['view'], 'finance': ['view'], 'admissions': ['view'], 'audit': ['view'],
    }),
    'pro_vice_chancellor': ('Pro Vice Chancellor', 'Deputy to the VC: academic oversight and reports.', {
        'executive': ['view', 'export'], 'reports': ['view', 'export', 'print'],
        'students': ['view'], 'results': ['view'], 'programs': ['view'],
    }),
    # ---- Registry
    'registrar': ('Registrar', 'Official academic records, enrolment, registration approvals and student documents.', {
        'students': ['view', 'create', 'edit', 'export', 'print'],
        'registration': ['view', 'create', 'edit', 'approve', 'override'],
        'documents': ['view', 'generate', 'print', 'export', 'approve'],
        'programs': ['view'], 'results': ['view'],
        'reports': ['view', 'export', 'print', 'generate'],
    }),
    'academic_admin': ('Academic Administrator', 'Owns faculties, programs, courses and curriculum.', {
        'programs': ['view', 'create', 'edit'],
        'courses': ['view', 'create', 'edit', 'delete', 'approve', 'publish'],
        'curriculum': ['view', 'create', 'edit', 'approve'],
        'sections': ['view', 'create', 'edit', 'assign'],
    }),
    # ---- Faculty / Department (use a faculty- or department-scoped assignment)
    'dean': ('Dean / Faculty Director', 'Faculty-level academic management and review across its departments.', {
        'programs': ['view', 'edit'], 'courses': ['view', 'approve'], 'curriculum': ['view', 'approve'],
        'sections': ['view', 'assign'], 'students': ['view'], 'attendance': ['view'],
        'results': ['view', 'verify'], 'reports': ['view', 'export'],
    }),
    'hod': ('Head of Department', 'Department courses, sections, teacher assignment and result review.', {
        'courses': ['view'], 'sections': ['view', 'create', 'edit', 'assign'],
        'results': ['view', 'verify'], 'attendance': ['view'], 'students': ['view'], 'reports': ['view'],
    }),
    'department_coordinator': ('Department Coordinator', 'Timetable, sections and attendance monitoring for one department.', {
        'sections': ['view', 'create', 'edit'], 'attendance': ['view'], 'students': ['view'], 'courses': ['view'],
    }),
    # ---- Admissions: officer verifies, committee decides
    'admission_officer': ('Admission Officer', 'Applications, documents, eligibility and merit data entry. Does not make the selection decision.', {
        'admissions': ['view', 'create', 'edit', 'verify', 'generate'],
        'students': ['view'],
    }),
    'admission_committee': ('Admission Committee', 'Selection, rejection and offer publication.', {
        'admissions': ['view', 'approve', 'reject', 'publish'],
    }),
    # ---- Examination: HOD verifies -> Exam Officer approves -> Controller publishes
    'exam_officer': ('Examination Officer', 'Exam schedules, rooms, admit cards and exam-office verification of results.', {
        'exams': ['view', 'create', 'edit', 'generate', 'print'],
        'results': ['view', 'approve', 'export'],
    }),
    'exam_controller': ('Controller of Examinations', 'Result publication, unpublish/reopen and grade policy.', {
        'exams': ['view', 'approve', 'publish', 'configure'],
        'results': ['view', 'publish', 'unpublish', 'override', 'export', 'print'],
        'grade_policy': ['view', 'configure'],
        'documents': ['view', 'approve'],
        'reports': ['view', 'export'],
    }),
    # ---- Finance: officer raises, manager approves, cashier receives
    'finance_officer': ('Finance Officer', 'Invoices, challans, payment posting and reconciliation. Cannot approve refunds or waivers.', {
        'finance': ['view', 'create', 'edit', 'reconcile', 'export', 'print', 'generate'],
        'scholarships': ['view'], 'reports': ['view', 'export'],
    }),
    'finance_manager': ('Finance Manager', 'Approves refunds, waivers and fee adjustments; voids documents.', {
        'finance': ['view', 'approve', 'reject', 'void', 'export', 'print'],
        'scholarships': ['view', 'approve'], 'reports': ['view', 'export'],
    }),
    'cashier': ('Cashier', 'Receives payments and issues receipts only.', {
        'finance': ['view', 'create', 'print'],
    }),
    # ---- HR: officer maintains records, payroll officer prepares, manager approves
    'hr_officer': ('HR Officer', 'Staff and faculty records, appointments, leave and attendance.', {
        'hr': ['view', 'create', 'edit', 'export'],
    }),
    'payroll_officer': ('Payroll Officer', 'Prepares payroll; does not approve it.', {
        'hr': ['view', 'generate', 'export', 'print'],
    }),
    'hr_manager': ('HR Manager', 'Approves payroll, appointments and contracts.', {
        'hr': ['view', 'approve', 'reject', 'export'],
    }),
    # ---- Campus services
    'librarian': ('Librarian', 'Library catalogue, loans and fines.', {
        'library': ['view', 'create', 'edit', 'assign', 'export'],
    }),
    'hostel_officer': ('Hostel Officer', 'Hostel applications and room allocation.', {
        'hostel': ['view', 'create', 'edit', 'approve', 'reject', 'assign'], 'students': ['view'],
    }),
    'transport_officer': ('Transport Officer', 'Routes, vehicles and transport assignments.', {
        'transport': ['view', 'create', 'edit', 'assign'], 'students': ['view'],
    }),
    'student_affairs_officer': ('Student Affairs Officer', 'Student welfare, scholarships review and complaints. No academic or finance authority.', {
        'student_affairs': ['view', 'create', 'edit', 'approve'], 'scholarships': ['view', 'edit'],
        'students': ['view'],
    }),
    # ---- IT: runs the software, holds NO academic / finance / admission authority
    'it_administrator': ('IT / System Administrator', 'Users, roles, settings, backups and automation. No authority over admissions, results or money.', {
        'security': ['view', 'create', 'edit', 'configure'],
        'settings': ['view', 'edit', 'configure'],
        'automation': ['view', 'configure', 'generate'],
        'data_quality': ['view'], 'audit': ['view'],
    }),
    'security_administrator': ('Security Administrator', 'Authentication policy, access reviews and audit-log inspection.', {
        'security': ['view'], 'audit': ['view', 'export'], 'data_quality': ['view'],
    }),
    # ---- Audit
    'read_only_auditor': ('Auditor (read-only)', 'Can view records and audit logs; cannot change anything.', {
        'students': ['view'], 'results': ['view'], 'finance': ['view'], 'audit': ['view'],
        'reports': ['view', 'export'],
    }),
}

# Where each default role sits on the Governance Map: (office, rank).
ROLE_OFFICE = {
    'chancellor': ('governance', 1), 'vice_chancellor': ('governance', 2), 'pro_vice_chancellor': ('governance', 3),
    'registrar': ('registry', 1), 'academic_admin': ('registry', 2),
    'dean': ('faculty', 1), 'hod': ('department', 1), 'department_coordinator': ('department', 2),
    'admission_officer': ('admissions', 1), 'admission_committee': ('admissions', 2),
    'exam_officer': ('examination', 1), 'exam_controller': ('examination', 2),
    'finance_officer': ('finance', 1), 'finance_manager': ('finance', 2), 'cashier': ('finance', 3),
    'hr_officer': ('hr', 1), 'payroll_officer': ('hr', 2), 'hr_manager': ('hr', 3),
    'librarian': ('services', 1), 'hostel_officer': ('services', 2), 'transport_officer': ('services', 3),
    'student_affairs_officer': ('services', 4),
    'it_administrator': ('it', 1), 'security_administrator': ('it', 2),
    'read_only_auditor': ('audit', 1),
}

# ---------------------------------------------------------------------------
# Separation of duties. One person must not be able to both start and finish a
# sensitive process, and the people who run the software must not hold the
# authority the software enforces.  Each rule: (label, side A, side B); holding
# any permission from A *and* any from B is a conflict.
# ---------------------------------------------------------------------------
SOD_RULES = [
    ('IT / security administration must not also decide admissions, results or money',
     [('security', 'create'), ('security', 'edit'), ('security', 'configure'), ('settings', 'configure')],
     [('admissions', 'approve'), ('results', 'publish'), ('results', 'approve'), ('finance', 'approve'), ('finance', 'create')]),
    ('Admission selection must be separate from examination results',
     [('admissions', 'approve'), ('admissions', 'publish')],
     [('results', 'verify'), ('results', 'approve'), ('results', 'publish'), ('results', 'override')]),
    ('Result verification, exam-office approval and publication are three different people',
     [('results', 'verify')], [('results', 'approve'), ('results', 'publish')]),
    ('Exam-office approval must be separate from publication',
     [('results', 'approve')], [('results', 'publish')]),
    ('Whoever raises a finance document must not approve refunds or waivers',
     [('finance', 'create'), ('finance', 'edit'), ('finance', 'reconcile')],
     [('finance', 'approve'), ('finance', 'void')]),
    ('Payroll preparation must be separate from payroll approval',
     [('hr', 'generate')], [('hr', 'approve')]),
    ('Academic course control must be separate from finance',
     [('courses', 'approve'), ('curriculum', 'approve')],
     [('finance', 'approve'), ('finance', 'create')]),
]


# ---------------------------------------------------------------------------
# Who may create accounts for which office. Having the right to create an
# account never gives authority over that person's work - and no office can
# create roles of an office that is above or beside it.
# ---------------------------------------------------------------------------
PROVISIONING = {
    ('security', 'create'): ['it_administrator', 'security_administrator'],
    ('executive', 'approve'): ['chancellor', 'vice_chancellor', 'pro_vice_chancellor', 'registrar', 'dean',
                               'exam_controller', 'finance_manager', 'hr_manager', 'read_only_auditor'],
    ('registration', 'approve'): ['hod', 'department_coordinator', 'academic_admin'],
    ('finance', 'approve'): ['finance_officer', 'cashier'],
    ('results', 'publish'): ['exam_officer'],
    ('admissions', 'approve'): ['admission_officer'],
    ('hr', 'approve'): ['hr_officer', 'payroll_officer', 'librarian', 'hostel_officer', 'transport_officer',
                        'student_affairs_officer', 'admission_committee'],
}
