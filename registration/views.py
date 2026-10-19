from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from .models import Student
from .forms import StudentForm
from core.permissions import staff_or_admin_required, admin_required, user_role, section_scope_students
from governance.permissions import perm_required
import io, csv


@login_required
def student_list(request):
    query = request.GET.get('q', '').strip()
    students = Student.objects.select_related('program', 'program__department', 'program__department__faculty').all()
    role = user_role(request.user)
    if role == 'student':
        students = students.filter(user=request.user)
    elif role in ('faculty', 'staff'):
        # Teachers only see students actually enrolled in a section they
        # teach - not the whole department. Student records themselves
        # (add/edit/delete) are admin-only; teachers get a read-only roster
        # for the classes they're actually teaching.
        students = section_scope_students(request.user, students)
    if query:
        students = students.filter(full_name__icontains=query) | students.filter(admission_no__icontains=query)

    # Filters - admin/staff/faculty only, since students only ever see
    # their own single record and these would be meaningless for them.
    district = request.GET.get('district', '').strip()
    province = request.GET.get('province', '').strip()
    department_id = request.GET.get('department', '').strip()
    program_id = request.GET.get('program', '').strip()
    faculty_id = request.GET.get('faculty', '').strip()
    fee_status = request.GET.get('fee_status', '').strip()
    student_type = request.GET.get('student_type', '').strip()

    if role != 'student':
        if district:
            students = students.filter(district__icontains=district)
        if province:
            students = students.filter(province=province)
        if faculty_id:
            students = students.filter(program__department__faculty_id=faculty_id)
        if department_id:
            students = students.filter(program__department_id=department_id)
        if program_id:
            students = students.filter(program_id=program_id)
        if student_type:
            students = students.filter(status=student_type)
        if fee_status in ('paid', 'unpaid'):
            from finance.models import Invoice
            unpaid_student_ids = Invoice.objects.filter(paid=False).values_list('student_id', flat=True)
            if fee_status == 'unpaid':
                students = students.filter(id__in=unpaid_student_ids)
            else:
                students = students.exclude(id__in=unpaid_student_ids)

    context = {'students': students, 'query': query, 'role': role}
    if role != 'student':
        from academics.models import Faculty, Department, Program
        from registration.models import PROVINCE_CHOICES
        context.update({
            'faculties': Faculty.objects.all(), 'departments': Department.objects.select_related('faculty').all(),
            'programs': Program.objects.select_related('department').all(), 'provinces': PROVINCE_CHOICES,
            'student_statuses': Student._meta.get_field('status').choices,
            'filters': {
                'district': district, 'province': province, 'department': department_id,
                'program': program_id, 'faculty': faculty_id, 'fee_status': fee_status, 'student_type': student_type,
            },
        })
    return render(request, 'core/student-management.html', context)


@perm_required('students', 'create')
def student_add(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Student added.')
            return redirect('student-list')
    else:
        form = StudentForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Student', 'cancel_url': '/registration/students/'})


@perm_required('students', 'edit')
def student_edit(request, pk):
    s = get_object_or_404(Student, pk=pk)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=s)
        if form.is_valid():
            form.save()
            messages.success(request, 'Student updated.')
            return redirect('student-list')
    else:
        form = StudentForm(instance=s)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Student', 'cancel_url': '/registration/students/'})


@admin_required
@require_POST
def student_delete(request, pk):
    s = get_object_or_404(Student, pk=pk)
    s.delete()
    messages.success(request, 'Student removed.')
    return redirect('student-list')


@login_required
def student_import(request):
    """Two steps: 1) upload -> full validation report, nothing saved; 2) confirm -> one atomic write.

    Needs students.create (new) or students.edit (existing) for each row's program;
    the System Administrator is not the owner of student records - the Registrar's office is."""
    from governance.permissions import has_perm_anywhere
    from core.models import log_action
    from . import importer
    if not (has_perm_anywhere(request.user, 'students', 'create') or has_perm_anywhere(request.user, 'students', 'edit')):
        raise PermissionDenied('You are not authorised to import student records.')
    if request.method != 'POST':
        return render(request, 'core/student-import.html')

    if request.POST.get('confirm'):
        raw = request.session.pop('student_import_csv', None)
        if raw is None:
            messages.error(request, 'The checked file expired. Please upload it again.')
            return redirect('student-import')
        report, created, updated = importer.commit(raw.encode('utf-8'), request.user)
        if not report.ok:
            return render(request, 'core/student-import.html', {'report': report})
        log_action(request.user, 'STUDENT_IMPORT', obj=f'{created} created, {updated} updated', request=request)
        messages.success(request, f'Import completed: {created} created, {updated} updated. New accounts are inactive until credentials are issued.')
        return redirect('student-list')

    csvfile = request.FILES.get('csvfile')
    if not csvfile:
        messages.error(request, 'Please choose a CSV file to import.')
        return redirect('student-import')
    if not csvfile.name.lower().endswith('.csv'):
        messages.error(request, 'Only CSV files are accepted.')
        return redirect('student-import')
    raw = csvfile.read()
    report = importer.validate(raw, request.user)
    if report.ok:
        request.session['student_import_csv'] = raw.decode('utf-8-sig')
    return render(request, 'core/student-import.html', {'report': report, 'checked': True})


@login_required
def student_export(request):
    """CSV of the students the user is authorised to see, with spreadsheet-formula neutralisation, audited."""
    from governance.permissions import has_perm, has_perm_anywhere
    from core.models import log_action
    from . import importer
    if not has_perm_anywhere(request.user, 'students', 'export'):
        raise PermissionDenied('You are not authorised to export student records.')
    students = Student.objects.select_related('program', 'program__department')
    if not request.user.is_superuser:
        students = [s for s in students if has_perm(request.user, 'students', 'export', program=s.active_program,
                                                    department=s.active_program.department if s.active_program else None)]
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="students.csv"'
    writer = csv.writer(response)
    writer.writerow(['admission_no', 'full_name', 'program', 'status'])
    count = 0
    for s in students:
        prog = s.active_program
        writer.writerow([importer.csv_safe(s.admission_no), importer.csv_safe(s.full_name),
                         importer.csv_safe(prog.code if prog else ''), importer.csv_safe(s.status)])
        count += 1
    log_action(request.user, 'STUDENT_EXPORT', obj=f'{count} students', request=request)
    return response


@login_required
def id_card(request, pk=None):
    """Printable student ID card. Students view their own (no pk); staff/admin can view any by pk."""
    from django.core.exceptions import PermissionDenied
    from django.urls import reverse
    from digital_id import services as digital_id_services
    role = user_role(request.user)
    if pk is None:
        student = Student.objects.filter(user=request.user).first()
        if student is None:
            messages.error(request, "There's no student record linked to your account, so there's no ID card to show.")
            return redirect('dashboard')
    else:
        student = get_object_or_404(Student, pk=pk)
        from core.permissions import can_view_student
        if not can_view_student(request.user, student, module='students'):
            raise PermissionDenied("You can only view ID cards of students you are responsible for.")

    token = digital_id_services.issue_token(student)
    verify_url = request.build_absolute_uri(reverse('digital-id-verify', args=[token]))
    qr_data_uri = digital_id_services.qr_data_uri(verify_url)
    return render(request, 'core/id-card.html', {
        'student': student, 'verify_url': verify_url, 'qr_data_uri': qr_data_uri,
    })
