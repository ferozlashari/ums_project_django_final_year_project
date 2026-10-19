from django.contrib import admin
from .models import Book, BookLoan


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'category', 'total_copies', 'available_copies')
    search_fields = ('title', 'author', 'isbn')
    list_filter = ('category',)


@admin.register(BookLoan)
class BookLoanAdmin(admin.ModelAdmin):
    list_display = ('book', 'student', 'borrowed_at', 'due_date', 'status', 'fine_amount')
    list_filter = ('status',)
