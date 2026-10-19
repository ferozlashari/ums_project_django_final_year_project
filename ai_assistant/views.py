import json
import time

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .agent import ask_assistant
from .models import Conversation, Message

RATE_LIMIT_MAX = 15       # messages
RATE_LIMIT_WINDOW = 60    # seconds


def _rate_limited(user_id) -> bool:
    key = f'ai_chat_rl:{user_id}'
    hits = cache.get(key, [])
    now = time.time()
    hits = [h for h in hits if now - h < RATE_LIMIT_WINDOW]
    if len(hits) >= RATE_LIMIT_MAX:
        return True
    hits.append(now)
    cache.set(key, hits, RATE_LIMIT_WINDOW)
    return False


@login_required
def chat_page(request):
    conversations = Conversation.objects.filter(user=request.user)
    active_id = request.GET.get('c')
    active = None
    if active_id:
        active = get_object_or_404(Conversation, pk=active_id, user=request.user)
    elif conversations.exists():
        active = conversations.first()
    messages = active.messages.all() if active else []
    return render(request, 'ai_assistant/chat.html', {
        'conversations': conversations,
        'active': active,
        'chat_messages': messages,
    })


@login_required
@require_POST
def new_conversation(request):
    convo = Conversation.objects.create(user=request.user, title='New conversation')
    return redirect(f'/ai/?c={convo.id}')


@login_required
@require_POST
def send_message(request):
    """JSON API used by the floating widget and the full chat page."""
    if _rate_limited(request.user.id):
        return JsonResponse({'error': 'Too many messages - please wait a moment and try again.'}, status=429)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    question = (payload.get('message') or '').strip()
    if not question:
        return JsonResponse({'error': 'Message cannot be empty.'}, status=400)
    if len(question) > 2000:
        return JsonResponse({'error': 'Message is too long (max 2000 characters).'}, status=400)

    conversation_id = payload.get('conversation_id')
    if conversation_id:
        conversation = get_object_or_404(Conversation, pk=conversation_id, user=request.user)
    else:
        title = question[:60] + ('…' if len(question) > 60 else '')
        conversation = Conversation.objects.create(user=request.user, title=title or 'New conversation')

    history = [
        {'role': m.role, 'content': m.content}
        for m in conversation.messages.all().order_by('created_at')[:20]
    ]

    Message.objects.create(conversation=conversation, role='user', content=question)

    result = ask_assistant(request.user, question, history=history)
    Message.objects.create(
        conversation=conversation, role='assistant',
        content=result['answer'], tool_used=result.get('error') or '',
    )
    conversation.save(update_fields=['updated_at']) if hasattr(conversation, 'updated_at') else None

    return JsonResponse({
        'conversation_id': conversation.id,
        'answer': result['answer'],
        'error': result.get('error'),
    })


@login_required
@require_GET
def list_messages(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id, user=request.user)
    data = [
        {'role': m.role, 'content': m.content, 'created_at': m.created_at.isoformat()}
        for m in conversation.messages.all()
    ]
    return JsonResponse({'messages': data})
