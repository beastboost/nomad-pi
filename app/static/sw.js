const CACHE_NAME = 'nomad-pi-v1.4.4';

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
  // FontAwesome CSS
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
  // FontAwesome webfonts — these are what the CSS references for icons to render
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.woff2',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.ttf',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-regular-400.woff2',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-regular-400.ttf',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-brands-400.woff2',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-brands-400.ttf',
  // Google Fonts CSS (font files are cached on first use via stale-while-revalidate)
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
];

// API responses to cache with network-first + fallback
const API_CACHE_WHITELIST = [
  '/api/system/stats',
  '/api/media/library/movies',
  '/api/media/library/shows',
  '/api/media/library/music',
  '/api/media/library/books',
  '/api/media/library/gallery',
  '/api/media/library',
  '/api/media/resume',
  '/api/media/watchlist',
  '/api/user/settings',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Pre-caching app shell and fonts');
      // allSettled so a single CDN miss doesn't abort everything
      return Promise.allSettled(
        APP_SHELL.map((asset) =>
          cache.add(new Request(asset, { mode: 'cors' })).catch((err) => {
            console.warn('[SW] Failed to pre-cache:', asset, err);
          })
        )
      );
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          }
        })
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle GET requests
  if (event.request.method !== 'GET') return;

  // Never intercept media streams — let the browser handle range requests
  if (
    url.pathname.includes('/media/stream') ||
    url.pathname.includes('/api/media/stream') ||
    url.pathname.endsWith('.mp4') ||
    url.pathname.endsWith('.mkv') ||
    url.pathname.endsWith('.mp3') ||
    url.pathname.endsWith('.flac')
  ) {
    return;
  }

  // HTML documents: network-first
  if (event.request.destination === 'document' || url.pathname === '/') {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Static assets + fonts + images + CDN resources: stale-while-revalidate
  const isCdnAsset =
    url.hostname.includes('cdnjs.cloudflare.com') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com');

  if (
    isCdnAsset ||
    event.request.destination === 'script' ||
    event.request.destination === 'style' ||
    event.request.destination === 'font' ||
    event.request.destination === 'image'
  ) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  // Local static assets (CSS, JS, icons by pathname)
  const isLocalAsset = APP_SHELL.some(
    (a) => !a.startsWith('http') && (url.pathname === a || url.href.endsWith(a))
  );
  if (isLocalAsset) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  // Whitelisted API calls: network-first with cached fallback
  const isWhitelistedApi = API_CACHE_WHITELIST.some((path) =>
    url.pathname.startsWith(path) || url.pathname.includes(path)
  );
  if (isWhitelistedApi) {
    event.respondWith(networkFirst(event.request));
    return;
  }
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request, { ignoreSearch: true });

  const networkPromise = fetch(request)
    .then((networkResponse) => {
      // Cache successful responses AND opaque cross-origin responses (status 0)
      if (networkResponse && (networkResponse.status === 200 || networkResponse.type === 'opaque')) {
        cache.put(request, networkResponse.clone());
      }
      return networkResponse;
    })
    .catch(() => cachedResponse || Response.error());

  // Serve cached immediately if available; revalidate in background
  return cachedResponse || networkPromise;
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && (networkResponse.status === 200 || networkResponse.type === 'opaque')) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    const cachedResponse = await cache.match(request, { ignoreSearch: true });
    return cachedResponse || Response.error();
  }
}

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
