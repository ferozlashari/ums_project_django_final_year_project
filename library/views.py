import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from .models import Book, BookLoan
from .forms import BookForm
from core.permissions import staff_or_admin_required, user_role
from core.models import notify

LOAN_DAYS = 14
FINE_PER_DAY = 10  # currency units per day overdue


import logging

logger = logging.getLogger('library')


def search_open_library(query, limit=8):
    """Search the free, keyless Open Library API for books from anywhere in
    the world. Returns (results, error_message). error_message is None on
    success, or a short human-readable reason on failure (network/SSL/DNS/
    timeout) - printed to the server console AND shown on the page, instead
    of silently returning nothing."""
    if not query:
        return [], None
    url = 'https://openlibrary.org/search.json?' + urllib.parse.urlencode({'q': query, 'limit': limit})
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.URLError as exc:
        logger.warning('Open Library search failed for %r: %s', query, exc)
        return [], 'Worldwide book search is temporarily unavailable. You can continue using the local library catalog.'
    except Exception as e:
        logger.warning('Open Library search failed for %r: %r', query, e)
        return [], 'Worldwide book search is temporarily unavailable. You can continue using the local library catalog.'
    results = []
    for doc in data.get('docs', [])[:limit]:
        cover_id = doc.get('cover_i')
        ia_ids = doc.get('ia') or []
        results.append({
            'title': doc.get('title', ''),
            'author': ', '.join(doc.get('author_name', [])[:3]),
            'year': doc.get('first_publish_year'),
            'isbn': (doc.get('isbn') or [''])[0],
            'cover_url': f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else '',
            # Real, working link to read the full book online (when the
            # public-domain/lendable text is available via Internet Archive) -
            # not just metadata.
            'read_online_url': f'https://archive.org/details/{ia_ids[0]}' if ia_ids else '',
        })
    return results, None


@login_required
def book_list(request):
    query = request.GET.get('q', '').strip()
    books = Book.objects.all().order_by('title')
    if query:
        books = books.filter(title__icontains=query) | books.filter(author__icontains=query) | books.filter(category__icontains=query)
    online_results = []
    online_error = None
    worldwide_requested = request.GET.get('worldwide') == '1'
    show_online = worldwide_requested and query
    if worldwide_requested and not query:
        online_error = 'Type a title or author in the search box first, then click "Also Search Worldwide".'
        show_online = True
    elif show_online:
        online_results, online_error = search_open_library(query)
    return render(request, 'library/book_list.html', {
        'books': books, 'query': query, 'online_results': online_results,
        'online_error': online_error, 'show_online': show_online, 'role': user_role(request.user),
    })


@staff_or_admin_required
def book_add(request):
    initial = {}
    # Pre-fill from an Open Library search result via query params (Import button).
    for f in ('title', 'author', 'isbn', 'cover_url'):
        v = request.GET.get(f)
        if v:
            initial[f] = v
    if request.GET.get('year'):
        initial['published_year'] = request.GET.get('year')

    if request.method == 'POST':
        form = BookForm(request.POST, request.FILES)
        if form.is_valid():
            book = form.save(commit=False)
            book.available_copies = book.total_copies
            book.added_by = request.user
            book.save()
            messages.success(request, 'Book added to the catalog. Thanks for contributing!')
            return redirect('book-list')
    else:
        form = BookForm(initial=initial)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Book to Library', 'cancel_url': '/library/'})


@staff_or_admin_required
def book_edit(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == 'POST':
        form = BookForm(request.POST, request.FILES, instance=book)
        if form.is_valid():
            form.save()
            messages.success(request, 'Book updated.')
            return redirect('book-list')
    else:
        form = BookForm(instance=book)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Book', 'cancel_url': '/library/'})


@staff_or_admin_required
@require_POST
def book_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if book.loans.filter(status='borrowed').exists():
        messages.error(request, 'This book cannot be removed while it is currently borrowed.')
        return redirect('book-list')
    book.delete()
    messages.success(request, 'Book removed.')
    return redirect('book-list')


@login_required
@require_POST
def borrow_book(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can borrow books.')
        return redirect('book-list')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('book-list')

    try:
        with transaction.atomic():
            book = Book.objects.select_for_update().get(pk=book.pk)
            if not book.is_available:
                messages.error(request, 'No copies currently available.')
                return redirect('book-list')
            if BookLoan.objects.filter(book=book, student=student, status='borrowed').exists():
                messages.info(request, 'You already have this book on loan.')
                return redirect('my-loans')
            due = timezone.localdate() + timedelta(days=LOAN_DAYS)
            BookLoan.objects.create(book=book, student=student, due_date=due)
            book.available_copies -= 1
            book.save(update_fields=['available_copies'])
    except IntegrityError:
        messages.info(request, 'This book is already on your active loan list.')
        return redirect('my-loans')
    due = timezone.localdate() + timedelta(days=LOAN_DAYS)
    notify(
        request.user, f'Book borrowed: {book.title}',
        f'Due back on {due}. Return on time to avoid a fine.',
        level='info', url='/library/my-loans/',
    )
    messages.success(request, f'"{book.title}" borrowed. Due back {due}.')
    return redirect('my-loans')


@login_required
def my_loans(request):
    try:
        student = request.user.student_profile
        loans = BookLoan.objects.filter(student=student).select_related('book')
    except Exception:
        loans = BookLoan.objects.none()
    return render(request, 'library/my_loans.html', {'loans': loans})


@staff_or_admin_required
def all_loans(request):
    loans = BookLoan.objects.select_related('book', 'student').order_by('-borrowed_at')
    return render(request, 'library/all_loans.html', {'loans': loans})


@staff_or_admin_required
@require_POST
def return_book(request, pk):
    loan = get_object_or_404(BookLoan, pk=pk)
    if loan.status == 'returned':
        messages.info(request, 'Already returned.')
        return redirect('all-loans')

    with transaction.atomic():
        loan = BookLoan.objects.select_for_update().select_related('book', 'student').get(pk=loan.pk)
        if loan.status == 'returned':
            messages.info(request, 'Already returned.')
            return redirect('all-loans')
        today = timezone.localdate()
        overdue_days = max(0, (today - loan.due_date).days)
        fine = overdue_days * FINE_PER_DAY
        loan.status = 'returned'
        loan.returned_at = timezone.now()
        loan.fine_amount = fine
        loan.save(update_fields=['status', 'returned_at', 'fine_amount'])
        book = Book.objects.select_for_update().get(pk=loan.book_id)
        book.available_copies = min(book.total_copies, book.available_copies + 1)
        book.save(update_fields=['available_copies'])

    if fine > 0:
        from finance.models import Invoice
        invoice = Invoice.objects.create(
            student=loan.student, category='library_fine', amount=fine,
            reference=f'Late return: {loan.book.title}',
        )
        notify(
            loan.student.user, f'Library fine: {loan.book.title}',
            f'{overdue_days} day(s) overdue - a fine of Rs. {fine} (challan {invoice.challan_no}) was added to your fees.',
            level='warning', url=reverse('challan-detail', kwargs={'pk': invoice.pk}),
        )
        messages.warning(request, f'Book returned. {overdue_days} day(s) overdue — a fine of Rs. {fine} was added to fees.')
    else:
        messages.success(request, 'Book returned on time. No fine.')
    return redirect('all-loans')
