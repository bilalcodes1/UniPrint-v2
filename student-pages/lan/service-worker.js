'use strict';

const CACHE_VERSION = 'uniprint-v1.1.0';

const APP_SHELL = [
  './',
  './css/style.css',
  './js/main.js',
  './manifest.json',
  './offline.html',
  './icons/icon-192x192.svg',
  './icons/icon-512x512.svg',
];

// ── Install: cache App Shell ───────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_VERSION)
      .then(c => c.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: purge old caches ─────────────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ──────────────────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  const { request } = e;
  const url = new URL(request.url);

  // Skip non-GET and API/socket requests — let browser handle them
  if (request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname.includes('socket.io')) return;

  // Static assets → Cache First
  if (url.pathname.match(/\.(css|js|svg|png|ico|woff2?)$/)) {
    e.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(res => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then(c => c.put(request, copy));
          return res;
        });
      })
    );
    return;
  }

  // HTML pages → Network First with offline fallback
  e.respondWith(
    fetch(request)
      .then(res => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then(c => c.put(request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then(c => c || caches.match('./offline.html')))
  );
});
