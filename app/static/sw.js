const CACHE_NAME = 'nomad-pi-v1.4.1';
const APP_SHELL = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/style.css',
  '/js/app.js',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-192.png',
  '/icons/maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/icons/icon-512.svg',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
];

// Essential API calls to cache for offline view
const API_CACHE_WHITELIST = [
  '/api/system/stats',
  '/api/media/library/movies',
  '/api/media/library/shows',
  '/api/media/resume'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Caching app shell');
      return Promise.allSettled(
        APP_SHELL.map((asset) => cache.add(asset))
      );
    })
  );
  // Do NOT self.skipWaiting() here if we want to show an update prompt
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('[SW] Deleting old cache:', cacheName);
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

  // Don't cache media streams (audio/video)
  if (url.pathname.includes('/media/stream') ||
      url.pathname.includes('/api/media/stream') ||
      url.pathname.endsWith('.mp4') ||
      url.pathname.endsWith('.mkv') ||
      url.pathname.endsWith('.mp3') ||
      url.pathname.endsWith('.flac')) {
    return;
  }

  // Strategy for App Shell (HTML): Network-First
  if (event.request.destination === 'document' || url.pathname === '/') {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Strategy for Static Assets: Stale-While-Revalidate
  const isAppShellAsset = APP_SHELL.some(asset => url.href.includes(asset) || url.pathname === asset);
  if (isAppShellAsset || event.request.destination === 'script' || event.request.destination === 'style' || event.request.destination === 'font' || event.request.destination === 'image') {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  // Strategy for specific API calls: Network-First with Cache Fallback
  const isWhitelistedApi = API_CACHE_WHITELIST.some(path => url.pathname.includes(path));
  if (isWhitelistedApi) {
    event.respondWith(networkFirst(event.request));
    return;
  }
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request, { ignoreSearch: true });
  const networkPromise = fetch(request).then((networkResponse) => {
    if (networkResponse && networkResponse.status === 200) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  }).catch(err => {
    return cachedResponse || Response.error();
  });
  return cachedResponse || networkPromise;
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const cachedResponse = await cache.match(request, { ignoreSearch: true });
    return cachedResponse || Response.error();
  }
}

// Handle messages from the client
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
