from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from . import views

urlpatterns = [
    path('', views.fee_list, name='fees-list'),
    path('add/', views.fee_add, name='fee-add'),
    path('generate-my-challan/<str:kind>/', views.generate_my_challan, name='generate-my-challan'),
    path('challan/<int:pk>/', views.challan_detail, name='challan-detail'),
    path('challan/<int:pk>/pay/', views.pay_now, name='pay-now'),
    path('challan/<int:pk>/pay/online/', views.gateway_checkout, name='gateway-checkout'),
    path('payments/<int:payment_id>/return/', views.gateway_return, name='gateway-return'),
    path('payments/webhook/safepay/', csrf_exempt(views.gateway_webhook), name='gateway-webhook'),
    path('challan/<int:pk>/late-fee/', views.apply_late_fee, name='apply-late-fee'),
    path('payments/pending/', views.pending_payments, name='pending-payments'),
    path('payments/<int:payment_id>/confirm/', views.confirm_payment, name='confirm-payment'),
    path('verify-challan/', views.verify_challan, name='verify-challan'),
]
