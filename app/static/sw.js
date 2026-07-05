const CACHE_NAME = 'nomad-pi-v1.4.6';

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
  '/api/system/settings',
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

  // Local static assets (e.g. manifest.json — everything else is already
  // routed by the destination checks above)
  const isLocalAsset = APP_SHELL.some(
    (a) => !a.startsWith('http') && url.pathname === a
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
  // Exact-URL match only: matching with ignoreSearch would return an OLD
  // ?v= entry ahead of the freshly cached one, defeating cache busting.
  const cachedResponse = await cache.match(request);

  const networkPromise = fetch(request)
    .then(async (networkResponse) => {
      // Only cache non-opaque responses where we can confirm success.
      // Opaque responses (cross-origin no-cors) always show status 0 — we
      // cannot tell them apart from a CDN error page, so caching them risks
      // permanently storing a 503/429 under the correct asset key.
      // CDN fonts/icons are pre-cached during install with mode:'cors' so
      // they arrive as real responses; don't need to re-cache them here.
      if (networkResponse && networkResponse.status === 200 && networkResponse.type !== 'opaque') {
        await evictStaleVariants(cache, request);
        cache.put(request, networkResponse.clone());
      }
      return networkResponse;
    })
    .catch(async () => {
      // Offline and no exact match: fall back to any version of this asset —
      // a stale stylesheet beats a broken page.
      return cachedResponse || (await cache.match(request, { ignoreSearch: true })) || Response.error();
    });

  // Serve cached immediately if available; revalidate in background
  return cachedResponse || networkPromise;
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200 && networkResponse.type !== 'opaque') {
      await evictStaleVariants(cache, request);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    // Offline: prefer the exact URL, fall back to any variant of it.
    const cachedResponse = await cache.match(request) ||
      await cache.match(request, { ignoreSearch: true });
    return cachedResponse || Response.error();
  }
}

// Remove previously cached entries for the same path with a different query
// string (old ?v= versions) so they can never shadow the current one.
async function evictStaleVariants(cache, request) {
  try {
    const url = new URL(request.url);
    if (!url.search) return;
    const stale = await cache.keys(request, { ignoreSearch: true });
    await Promise.all(stale.filter((k) => k.url !== request.url).map((k) => cache.delete(k)));
  } catch { /* eviction is best-effort */ }
}

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
