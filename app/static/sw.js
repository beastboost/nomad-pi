const CACHE_NAME = 'nomad-pi-v2';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/css/style.css',
  '/css/admin.css',
  '/js/app.js',
  '/js/admin.js',
  '/icons/icon-512.svg',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
];

// Essential API calls to cache for offline view (stats, basic media info)
const API_CACHE_WHITELIST = [
  '/api/system/stats',
  '/api/media/library/movies?offset=0&limit=60',
  '/api/media/library/shows?offset=0&limit=60'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('Caching static assets');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle GET requests
  if (event.request.method !== 'GET') return;

  // Strategy for static assets: Stale-While-Revalidate
  if (STATIC_ASSETS.includes(url.pathname) || STATIC_ASSETS.includes(event.request.url)) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  // Strategy for specific API calls: Network-First with Cache Fallback
  const isWhitelistedApi = API_CACHE_WHITELIST.some(path => event.request.url.includes(path));
  if (isWhitelistedApi) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Default strategy: Network-Only for most things (especially large media files)
  // We don't want to cache video/audio files in the service worker cache
  // as they are handled by the browser's native range requests and disk cache.
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request);
  const networkPromise = fetch(request).then((networkResponse) => {
    if (networkResponse.status === 200) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  }).catch(err => {
    console.warn('SW fetch failed:', err);
    return cachedResponse; // Fallback to cache if network fails
  });
  return cachedResponse || networkPromise;
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.status === 200) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const cachedResponse = await cache.match(request);
    return cachedResponse || Response.error();
  }
}
