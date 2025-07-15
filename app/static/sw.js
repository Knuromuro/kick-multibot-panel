self.addEventListener('install', e => {
  e.waitUntil(caches.open('kickbot-v1').then(cache => cache.add('/')));
});

const DB_NAME = 'kickbot-sync';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore('queue', { autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function storeRequest(data) {
  const db = await openDB();
  const tx = db.transaction('queue', 'readwrite');
  tx.objectStore('queue').add(data);
  return tx.complete;
}

async function sendQueued() {
  const db = await openDB();
  const tx = db.transaction('queue', 'readwrite');
  const store = tx.objectStore('queue');
  const all = await store.getAll();
  for (const item of all) {
    await fetch('/sync/push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([item])
    });
  }
  store.clear();
  return tx.complete;
}

self.addEventListener('fetch', e => {
  if (e.request.method === 'POST' && e.request.url.includes('/dashboard/api')) {
    e.respondWith(
      fetch(e.request.clone()).catch(() => {
        return e.request.clone().text().then(body => {
          const headers = {};
          e.request.headers.forEach((v, k) => { headers[k] = v; });
          storeRequest({ url: e.request.url, method: 'POST', headers, body, timestamp: new Date().toISOString() });
          return self.registration.sync.register('sync-queue').then(() => new Response(JSON.stringify({queued:true}), {status:202}));
        });
      })
    );
  } else {
    e.respondWith(caches.match(e.request).then(res => res || fetch(e.request)));
  }
});

self.addEventListener('sync', e => {
  if (e.tag === 'sync-queue') {
    e.waitUntil(sendQueued());
  }
});
