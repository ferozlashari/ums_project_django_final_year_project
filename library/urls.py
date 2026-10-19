from django.urls import path
from . import views

urlpatterns = [
    path('', views.book_list, name='book-list'),
    path('add/', views.book_add, name='book-add'),
    path('<int:pk>/edit/', views.book_edit, name='book-edit'),
    path('<int:pk>/delete/', views.book_delete, name='book-delete'),
    path('<int:pk>/borrow/', views.borrow_book, name='borrow-book'),
    path('my-loans/', views.my_loans, name='my-loans'),
    path('loans/', views.all_loans, name='all-loans'),
    path('loans/<int:pk>/return/', views.return_book, name='return-book'),
]
