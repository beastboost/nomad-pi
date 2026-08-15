const CACHE_NAME = 'nomad-pi-v2.0.3-playback';

const APP_SHELL = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/nocturne.css',
  '/js/app.js',
  '/js/app_legacy.js',
  '/js/playback-core.js',
  '/js/replacement-control.js',
  '/js/track-control.js',
  '/js/subtitle-control.js',
  '/js/quality-control.js',
  '/js/device-control.js',
  '/js/admin.js',
  '/js/features.js',
  '/js/reader.js',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-192.png',
  '/icons/maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/icons/icon-512.svg',
  '/vendor/phosphor/regular.css',
  '/vendor/phosphor/fill.css',
  '/vendor/inter/inter.css',
  '/vendor/epub/epub.min.js',
  '/vendor/hls/hls.min.js',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/fill/style.css',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/Phosphor.woff2',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/fill/Phosphor-Fill.woff2',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
];

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
  const local = APP_SHELL.filter((a) => !a.startsWith('http'));
  const remote = APP_SHELL.filter((a) => a.startsWith('http'));

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(local.map((asset) => cache.add(asset)))
    )
  );

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

  if (event.request.method !== 'GET') return;

  if (
    url.pathname.startsWith('/api/playback/') ||
    url.pathname.includes('/media/stream') ||
    url.pathname.includes('/api/media/stream') ||
    url.pathname.endsWith('.m3u8') ||
    url.pathname.endsWith('.m4s') ||
    url.pathname.endsWith('.mp4') ||
    url.pathname.endsWith('.mkv') ||
    url.pathname.endsWith('.mp3') ||
    url.pathname.endsWith('.flac')
  ) {
    return;
  }

  if (event.request.destination === 'document' || url.pathname === '/') {
    event.respondWith(networkFirst(event.request));
    return;
  }

  const isCdnAsset =
    url.hostname.includes('unpkg.com') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    url.hostname.includes('cdn.jsdelivr.net');

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

  const isLocalAsset = APP_SHELL.some(
    (a) => !a.startsWith('http') && url.pathname === a
  );
  if (isLocalAsset) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

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
  const cachedResponse = await cache.match(request);

  const networkPromise = fetch(request)
    .then(async (networkResponse) => {
      if (networkResponse && networkResponse.status === 200 && networkResponse.type !== 'opaque') {
        await evictStaleVariants(cache, request);
        cache.put(request, networkResponse.clone());
      }
      return networkResponse;
    })
    .catch(async () => {
      return cachedResponse || (await cache.match(request, { ignoreSearch: true })) || Response.error();
    });

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
    const cachedResponse = await cache.match(request) ||
      await cache.match(request, { ignoreSearch: true });
    return cachedResponse || Response.error();
  }
}

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
