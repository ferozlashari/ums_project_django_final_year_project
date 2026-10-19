// Minimal service worker: enables "Add to Home Screen" / installable PWA
// behavior, plus a friendly offline fallback page for navigation. Intentionally
// does NOT cache API/auth pages or data pages, so data always stays fresh -
// this is about installability and offline app-shell, not full offline data
// access.
const CACHE = 'ums-shell-v2';
const SHELL_ASSETS = ['/static/css/styles.css', '/static/js/scripts.js', '/static/manifest.json', '/static/offline.html'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Page navigations (clicking a link, typing a URL, reloading): always try
  // the network first so data is never stale, but if the network is
  // unreachable, show the friendly offline page instead of the browser's
  // generic "no internet" error screen.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/static/offline.html'))
    );
    return;
  }

  // Only serve the cached app shell for static asset GETs; everything else
  // (API calls, form posts) always goes to the network.
  if (event.request.method === 'GET' && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
