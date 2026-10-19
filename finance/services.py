"""Deterministic finance actions shared by web views and the AI assistant's
agentic tools, so both call the exact same validated code path - no
duplicated eligibility/amount logic between the two."""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.models import SiteSettings, notify
from .models import Invoice


@dataclass(frozen=True)
class ChallanResult:
    ok: bool
    invoice: Invoice | None = None
    message: str = ''


class FeeChallanService:
    """Self-service challan generation - one method per challan type a
    student is allowed to raise themselves, each enforcing its own
    eligibility rule before creating an Invoice. Every method follows the
    same shape: check eligibility -> check for an existing unpaid challan
    of that category -> compute the amount from real configured/related
    data (never a guessed number) -> create it."""

    @staticmethod
    def _existing_unpaid(student, category):
        return Invoice.objects.select_for_update().filter(student=student, category=category, paid=False).order_by('id').first()

    @staticmethod
    def _create(student, category, amount, reference, semester=None, due_days=30):
        invoice = Invoice.objects.create(
            student=student, category=category, amount=amount, reference=reference, semester=semester,
            due_date=timezone.localdate() + timezone.timedelta(days=due_days),
        )
        notify(student.user, f'{invoice.get_category_display()} challan generated: {invoice.challan_no}', f'{invoice.amount} is due on {invoice.due_date}.', level='warning', url=f'/finance/challan/{invoice.pk}/')
        return ChallanResult(True, invoice=invoice, message=f'Challan {invoice.challan_no} generated for Rs. {invoice.amount}, due {invoice.due_date}.')

    @classmethod
    @transaction.atomic
    def generate_semester_fee(cls, student):
        """Tuition for the CURRENT semester, program-wise (Program.semester_fee).
        One challan per student per semester - a paid one blocks a second."""
        program = student.active_program
        if not program:
            return ChallanResult(False, message='No academic program is assigned to your record. Please contact administration.')
        from core.services.academic import AcademicEligibilityService
        semester = AcademicEligibilityService.current_semester()
        if semester:
            done = Invoice.objects.filter(student=student, category='semester', semester=semester).order_by('-id').first()
            if done:
                return ChallanResult(True, invoice=done, message=f'A semester fee challan for {semester.name} already exists ({done.challan_no}).')
        existing = cls._existing_unpaid(student, 'semester')
        if existing:
            return ChallanResult(True, invoice=existing, message=f'You already have an unpaid semester challan ({existing.challan_no}).')
        amount = program.semester_fee
        if amount is None or amount <= 0:
            return ChallanResult(False, message='Your program does not have a valid semester fee configured.')
        return cls._create(student, 'semester', amount, f'Semester tuition fee - {program.name}' + (f' - {semester.name}' if semester else ''), semester=semester)

    @classmethod
    @transaction.atomic
    def generate_application_fee(cls, student, program):
        """One-time application fee of the applicant's FIRST-choice program."""
        amount = program.application_fee
        if not amount or amount <= 0:
            return ChallanResult(False, message='This program has no application fee.')
        reference = f'Application fee - {program.name}'
        existing = Invoice.objects.filter(student=student, category='admission', reference=reference).first()
        if existing:
            return ChallanResult(True, invoice=existing, message=f'Application fee challan {existing.challan_no} already exists.')
        return cls._create(student, 'admission', amount, reference, due_days=14)

    @classmethod
    @transaction.atomic
    def generate_admission_fee(cls, student):
        """One-time admission fee of the program the student was ADMITTED to."""
        program = student.active_program
        if not program:
            return ChallanResult(False, message='No program is assigned to this student.')
        amount = program.admission_fee
        if not amount or amount <= 0:
            return ChallanResult(False, message='This program has no admission fee.')
        reference = f'Admission fee - {program.name}'
        existing = Invoice.objects.filter(student=student, category='admission', reference=reference).first()
        if existing:
            return ChallanResult(True, invoice=existing, message=f'Admission fee challan {existing.challan_no} already exists.')
        return cls._create(student, 'admission', amount, reference, due_days=14)

    @classmethod
    @transaction.atomic
    def generate_degree_fee(cls, student):
        """One-time degree/convocation fee, only for a graduating student."""
        program = student.active_program
        if not program:
            return ChallanResult(False, message='No program is assigned to this student.')
        position = student.current_academic_position or {}
        if student.status != 'graduated' and not position.get('is_final_semester'):
            return ChallanResult(False, message='The degree fee is charged in the final semester or after graduation.')
        amount = program.degree_fee
        if not amount or amount <= 0:
            return ChallanResult(False, message='This program has no degree fee.')
        reference = f'Degree fee - {program.name}'
        existing = Invoice.objects.filter(student=student, category='degree').first()
        if existing:
            return ChallanResult(True, invoice=existing, message=f'Degree fee challan {existing.challan_no} already exists.')
        return cls._create(student, 'degree', amount, reference, due_days=30)

    @classmethod
    def issue_late_fee(cls, invoice, grace_days=0):
        """Create the one late-penalty challan for an overdue, unpaid invoice.
        Shared by the admin button and the automatic overdue task."""
        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
            if invoice.category == 'penalty' or invoice.paid or not invoice.due_date:
                return ChallanResult(False, message='This challan is not eligible for a late fee.')
            if timezone.localdate() <= invoice.due_date + timezone.timedelta(days=grace_days):
                return ChallanResult(False, message='This challan is not overdue yet.')
            reference = f'Late fee for {invoice.challan_no}'
            existing = Invoice.objects.filter(category='penalty', reference=reference).first()
            if existing:
                return ChallanResult(False, invoice=existing, message='A late penalty has already been generated for this challan.')
            from decimal import Decimal
            amount = (invoice.amount * (SiteSettings.load().late_fee_percent / Decimal('100'))).quantize(Decimal('0.01'))
            if amount <= 0:
                return ChallanResult(False, message='No late fee is configured.')
            penalty = Invoice.objects.create(student=invoice.student, category='penalty', amount=amount, reference=reference,
                                             due_date=timezone.localdate() + timezone.timedelta(days=7))
        notify(penalty.student.user, f'Late penalty challan issued: {penalty.challan_no}',
               f'A late fee of {amount} was added because {invoice.challan_no} is overdue.', level='danger',
               url=f'/finance/challan/{penalty.pk}/')
        return ChallanResult(True, invoice=penalty, message=f'Late penalty challan {penalty.challan_no} generated.')

    @classmethod
    @transaction.atomic
    def generate_hostel_fee(cls, student):
        """Hostel fee is charged once per academic year, not per semester
        - a separate, independent charge from tuition/exam fees (never
        bundled with them). 'Already have one' therefore checks the
        current year's unpaid challan, and additionally blocks a second
        one within the same year even if the first was already paid."""
        from hostel.models import HostelApplication
        allocation = HostelApplication.objects.filter(student=student, status='approved', assigned_room__isnull=False).first()
        if not allocation:
            return ChallanResult(False, message='You do not have an approved hostel room allocation, so there is nothing to charge a hostel fee for.')
        current_year = timezone.localdate().year
        existing_unpaid = cls._existing_unpaid(student, 'hostel')
        if existing_unpaid:
            return ChallanResult(True, invoice=existing_unpaid, message=f'You already have an unpaid hostel challan ({existing_unpaid.challan_no}).')
        already_this_year = Invoice.objects.filter(student=student, category='hostel', created_at__year=current_year).exists()
        if already_this_year:
            return ChallanResult(False, message=f'A hostel fee challan for {current_year} has already been generated for you. Hostel fee is charged once per academic year.')
        amount = SiteSettings.load().hostel_annual_fee
        if amount is None or amount <= 0:
            return ChallanResult(False, message='Hostel fee is not configured yet. Please contact administration.')
        return cls._create(student, 'hostel', amount, f'Hostel fee ({current_year}) - {allocation.hostel} ({allocation.assigned_room})')

    @classmethod
    @transaction.atomic
    def generate_transport_fee(cls, student):
        assignment = getattr(student, 'transport_assignment', None)
        if not assignment:
            return ChallanResult(False, message='You do not have an active transport route assignment, so there is nothing to charge a transport fee for.')
        existing = cls._existing_unpaid(student, 'transport')
        if existing:
            return ChallanResult(True, invoice=existing, message=f'You already have an unpaid transport challan ({existing.challan_no}).')
        amount = assignment.route.fare_per_semester
        if amount is None or amount <= 0:
            return ChallanResult(False, message='Your assigned route does not have a fare configured. Please contact administration.')
        return cls._create(student, 'transport', amount, f'Transport fee - {assignment.route.name}')
