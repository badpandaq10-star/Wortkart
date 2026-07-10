// WortKart Service Worker — cevrimdisi calisma icin basit cache-first strateji
const CACHE_NAME = 'wortkart-cache-v1';
const SELF_URL = self.location.href.replace(/sw\.js.*$/, '');

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Ana sayfayi (kendi HTML dosyasini) onbelleğe almayi dene.
      // Bu asamada hangi dosya adiyla acildigini bilemeyebiliriz, o yuzden
      // hem klasor kokunu hem de kaydi tetikleyen sayfayi eklemeyi deneriz.
      return cache.addAll([SELF_URL]).catch(() => {});
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200 && event.request.url.startsWith('http')) {
            const copy = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
          }
          return networkResponse;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
