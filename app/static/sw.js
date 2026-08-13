const CACHE_NAME = 'nomad-pi-v2.0.0';

const APP_SHELL = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/nocturne.css',
  '/js/app.js',
  '/js/admin.js',
  '/js/reader.js',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-192.png',
  '/icons/maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/icons/icon-512.svg',
  // Vendored icon + type assets (scripts/vendor-assets.sh). Same-origin, so
  // these are the ones that actually matter for an offline first load.
  '/vendor/phosphor/regular.css',
  '/vendor/phosphor/fill.css',
  '/vendor/inter/inter.css',
  '/vendor/epub/epub.min.js',
  // CDN fallbacks — fetched opportunistically, never block activation
  // Phosphor icon CSS + webfonts (the design system's icon set)
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/fill/style.css',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/Phosphor.woff2',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/fill/Phosphor-Fill.woff2',
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
  // Only same-origin assets block activation. Cross-origin CDN requests are
  // fetched opportunistically outside waitUntil: on a Pi with no internet
  // (the normal travel case) they hang until the socket gives up, which used
  // to stall activation ~16s and delay offline support exactly when it is
  // needed most.
  const local = APP_SHELL.filter((a) => !a.startsWith('http'));
  const remote = APP_SHELL.filter((a) => a.startsWith('http'));

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(local.map((asset) => cache.add(asset)))
    )
  );

  // Best-effort, non-blocking; failures are expected and harmless offline.
  caches.open(CACHE_NAME).then((cache) => {
    remote.forEach((asset) => {
      cache.add(new Request(asset, { mode: 'cors' })).catch(() => {});
    });
  });
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
    url.hostname.includes('unpkg.com') ||
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
