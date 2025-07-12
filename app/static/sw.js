self.addEventListener('install', e => {
  e.waitUntil(caches.open('kickbot-v1').then(cache => cache.add('/')));
});

self.addEventListener('fetch', e => {
  e.respondWith(caches.match(e.request).then(res => res || fetch(e.request)));
});
