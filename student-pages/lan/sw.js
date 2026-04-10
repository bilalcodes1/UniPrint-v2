/* UniPrint Service Worker v1.2.0 */
const CACHE_VERSION = 'v1.2.0';
const STATIC_CACHE  = `uniprint-static-${CACHE_VERSION}`;
const PAGES_CACHE   = `uniprint-pages-${CACHE_VERSION}`;

const STATIC_ASSETS = [
  './',
  './index.html',
  './css/style.css',
  './js/main.js',
  './manifest.json',
  './icons/icon-192x192.svg',
  './icons/icon-512x512.svg',
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap',
  'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js',
  'https://cdn.socket.io/4.7.4/socket.io.min.js',
];

// Install — pre-cache statics
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(STATIC_ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// Activate — purge old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys
        .filter(k => k !== STATIC_CACHE && k !== PAGES_CACHE)
        .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch strategy
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and API/WebSocket requests
  if (request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/socket.io/')) return;

  // Static assets → Cache First
  if (
    request.destination === 'style' ||
    request.destination === 'script' ||
    request.destination === 'image' ||
    request.destination === 'font' ||
    url.origin !== self.location.origin
  ) {
    event.respondWith(
      caches.match(request).then(cached =>
        cached || fetch(request).then(res => {
          if (res && res.status === 200) {
            const clone = res.clone();
            caches.open(STATIC_CACHE).then(c => c.put(request, clone));
          }
          return res;
        }).catch(() => cached)
      )
    );
    return;
  }

  // HTML pages → Network First, cache fallback
  event.respondWith(
    fetch(request)
      .then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(PAGES_CACHE).then(c => c.put(request, clone));
        }
        return res;
      })
      .catch(() => caches.match(request))
  );
});

// Push notification handler
self.addEventListener('push', event => {
  const data = event.data?.json() ?? { title: 'UniPrint', body: 'إشعار جديد' };
  event.waitUntil(
    self.registration.showNotification(data.title || 'UniPrint', {
      body:    data.body    || '',
      icon:    './icons/icon-192x192.svg',
      badge:   './icons/icon-192x192.svg',
      tag:     data.tag     || 'uniprint',
      data:    data.url     || '/',
      vibrate: [100, 50, 100],
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const target = event.notification.data || '/';
      const existing = list.find(c => c.url.includes(self.location.origin));
      return existing ? existing.focus() : clients.openWindow(target);
    })
  );
});
