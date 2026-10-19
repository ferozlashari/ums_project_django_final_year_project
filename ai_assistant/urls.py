from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_page, name='ai-chat'),
    path('new/', views.new_conversation, name='ai-chat-new'),
    path('api/send/', views.send_message, name='ai-chat-send'),
    path('api/conversations/<int:conversation_id>/messages/', views.list_messages, name='ai-chat-messages'),
]
