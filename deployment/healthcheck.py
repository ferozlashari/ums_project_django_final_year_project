"""Container healthcheck: GET /ready/ (checks the database) from inside the container.
Sends a Host header Django will accept, so it works with a locked-down ALLOWED_HOSTS."""
import os, sys, urllib.request

hosts = [h.strip().lstrip('.') for h in os.environ.get('ALLOWED_HOSTS', 'localhost').split(',')
         if h.strip() and h.strip() != '*']
host = hosts[0] if hosts else 'localhost'
req = urllib.request.Request(f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/ready/", headers={'Host': host})
try:
    sys.exit(0 if urllib.request.urlopen(req, timeout=4).status == 200 else 1)
except Exception as exc:
    print(exc); sys.exit(1)
