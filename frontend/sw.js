const CACHE_NAME = 'swimmate-public-v3';
const CACHE_URLS = [
  '/static/style.css',
  '/landing',
  '/login',
  '/register',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k.startsWith('swimmate-') && k !== CACHE_NAME).map((k) => caches.delete(k))
  )).then(() => self.clients.claim()));
});

// Network First: 항상 최신 데이터 우선, 실패 시 캐시 제공
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Private API/media (including byte-range 206) must NEVER enter CacheStorage.
  if (e.request.method !== 'GET' || e.request.headers.has('range') ||
      url.origin !== self.location.origin || !CACHE_URLS.includes(url.pathname) || url.search) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.status === 200 && !res.redirected && !/no-store|private/i.test(res.headers.get('cache-control') || '')) {
          const clone = res.clone();
          e.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone)).catch(() => {}));
        }
        return res;
      })
      .catch(async () => (await caches.match(e.request)) || Response.error())
  );
});
