self.addEventListener('install', event => {
  event.waitUntil(
    caches.open('kickbot-cache').then(cache => cache.addAll([
      '/',
      '/dashboard',
      '/static/dashboard.js'
    ]))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(resp => resp || fetch(event.request))
  );
});
