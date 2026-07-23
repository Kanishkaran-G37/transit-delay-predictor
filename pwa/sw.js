// Service worker — caches the app shell so the PWA loads instantly / offline.
const CACHE = 'delhi-transit-v1';
const SHELL = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Live data and map tiles must always hit the network.
  if (url.pathname.startsWith('/api/') || url.hostname.includes('tile.openstreetmap')) return;
  // App shell: cache-first, fall back to network, then to the cached home page.
  e.respondWith(
    caches.match(e.request).then((cached) =>
      cached || fetch(e.request).catch(() => caches.match('/'))
    )
  );
});
