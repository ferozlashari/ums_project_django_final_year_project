try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except ImportError:
    # celery isn't installed - fine, nothing in this project requires it.
    # Only affects @shared_task autodiscovery if you later run a worker.
    pass
