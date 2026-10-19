from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# Any document format may be uploaded (PDF, Word, PowerPoint, Excel, EPUB,
# images, audio, video, archives, etc). Only executable/script formats are
# blocked, since students could download and run them from the library.
BLOCKED_EBOOK_EXTENSIONS = ['exe', 'bat', 'cmd', 'sh', 'msi', 'com', 'scr', 'jar', 'js', 'vbs', 'ps1', 'apk']

# Extensions the browser can display directly in a new tab (no download
# needed). Everything else still uploads fine - it just downloads instead
# of previewing inline, because that's a browser limitation, not this app's.
INLINE_VIEWABLE_EXTENSIONS = ['pdf', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'mp3', 'mp4', 'webm']


def validate_not_executable(value):
    ext = value.name.rsplit('.', 1)[-1].lower() if '.' in value.name else ''
    if ext in BLOCKED_EBOOK_EXTENSIONS:
        raise ValidationError(f'.{ext} files are not allowed for security reasons (executable/script format).')


class Book(models.Model):
    title = models.CharField(max_length=300)
    author = models.CharField(max_length=200, blank=True)
    isbn = models.CharField(max_length=30, blank=True)
    category = models.CharField(max_length=100, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    published_year = models.IntegerField(null=True, blank=True)
    cover_url = models.URLField(blank=True)
    total_copies = models.PositiveIntegerField(default=1)
    available_copies = models.PositiveIntegerField(default=1)
    # Optional: the actual full book/document file for digital reading -
    # separate from the physical-copy borrow/return workflow below. Any
    # student can read/download this directly, since it isn't a limited
    # physical copy. No file-type whitelist - any document format works.
    ebook_file = models.FileField(
        upload_to='library_books/', blank=True, null=True,
        validators=[validate_not_executable],
        help_text='Optional: upload the full document - any format (PDF, Word, PowerPoint, Excel, EPUB, images, etc).',
    )
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='books_added')

    def __str__(self):
        return self.title

    @property
    def is_available(self):
        return self.available_copies > 0

    @property
    def ebook_extension(self):
        if not self.ebook_file:
            return ''
        name = self.ebook_file.name
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    @property
    def ebook_viewable_inline(self):
        """True if the browser can display this file directly; False means
        it will download instead (true for Word/PowerPoint/Excel - browsers
        have no built-in viewer for those, only PDFs/images/text/media)."""
        return self.ebook_extension in INLINE_VIEWABLE_EXTENSIONS


class BookLoan(models.Model):
    STATUS_CHOICES = [('borrowed', 'Borrowed'), ('returned', 'Returned')]
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='loans')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='book_loans')
    borrowed_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField()
    returned_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='borrowed')
    fine_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Book Loan'
        verbose_name_plural = 'Book Loans'
        constraints = [
            models.UniqueConstraint(
                fields=['book', 'student'],
                condition=models.Q(status='borrowed'),
                name='uniq_active_book_loan',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['book', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]

    def __str__(self):
        return f'{self.book.title} -> {self.student.full_name}'

    @property
    def is_overdue(self):
        return self.status == 'borrowed' and self.due_date < timezone.now().date()
