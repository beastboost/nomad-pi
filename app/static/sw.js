const CACHE_NAME = 'nomad-pi-v2.0.15-media-experience';

const APP_SHELL = [
  '/', '/index.html', '/manifest.json', '/css/nocturne.css', '/css/appliance-polish.css', '/css/media-experience.css',
  '/js/app.js', '/js/app_legacy.js', '/js/playback-core.js', '/js/runtime-ui-guard.js', '/js/debrid-lite.js', '/js/player-mobile-fix.js', '/js/direct-play-guard.js',
  '/js/replacement-control.js', '/js/track-control.js', '/js/subtitle-control.js',
  '/js/quality-control.js', '/js/device-control.js', '/js/watch-party.js', '/js/audio-direct-bridge.js', '/js/music2-player.js', '/js/music-player-polish.js',
  '/js/music2-fallback.js', '/js/media-exclusivity.js', '/js/stream-keep-control.js', '/js/universal-search.js', '/js/series-download-picker.js', '/js/universal-home.js',
  '/js/offline-control.js', '/js/download-live.js', '/js/library-health.js', '/js/media-actions.js', '/js/storage-failover.js', '/js/playback-health-ui.js', '/js/profile-context.js', '/js/profile-switch.js', '/js/reader-state.js', '/js/reader-ui-polish.js',
  '/js/admin.js', '/js/features.js', '/js/reader.js',
  '/icons/icon-192.png', '/icons/icon-512.png', '/icons/maskable-192.png',
  '/icons/maskable-512.png', '/icons/apple-touch-icon.png', '/icons/icon-512.svg',
  '/vendor/phosphor/regular.css', '/vendor/phosphor/fill.css', '/vendor/inter/inter.css',
  '/vendor/epub/epub.min.js', '/vendor/hls/hls.min.js',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/fill/style.css',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/Phosphor.woff2',
  'https://unpkg.com/@phosphor-icons/web@2.1.1/src/fill/Phosphor-Fill.woff2',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
];

const API_CACHE_WHITELIST = [
  '/api/system/stats', '/api/media/library/movies', '/api/media/library/shows',
  '/api/media/library/music', '/api/media/library/books', '/api/media/library/gallery',
  '/api/media/library', '/api/media/resume', '/api/media/watchlist', '/api/system/settings',
];

self.addEventListener('install', (event) => {
  const local = APP_SHELL.filter((a) => !a.startsWith('http'));
  const remote = APP_SHELL.filter((a) => a.startsWith('http'));
  event.waitUntil(caches.open(CACHE_NAME).then((cache) =>
    Promise.allSettled(local.map((asset) => cache.add(asset)))
  ).then(() => self.skipWaiting()));
  caches.open(CACHE_NAME).then((cache) => {
    remote.forEach((asset) => cache.add(new Request(asset, { mode: 'cors' })).catch(() => {}));
  });
});

self.addEventListener('activate', (event) => {
  event.waitUntil(Promise.all([
    caches.keys().then((cacheNames) => Promise.all(
      cacheNames.map((name) => name !== CACHE_NAME ? caches.delete(name) : undefined)
    )),
    self.clients.claim(),
  ]));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (
    url.pathname.startsWith('/api/playback/') ||
    url.pathname.startsWith('/api/debrid/universal/stream/') ||
    url.pathname.includes('/media/stream') ||
    url.pathname.includes('/api/media/stream') ||
    url.pathname.endsWith('.m3u8') || url.pathname.endsWith('.m4s') || url.pathname.endsWith('.ts') ||
    url.pathname.endsWith('.mp4') || url.pathname.endsWith('.mkv') ||
    url.pathname.endsWith('.mp3') || url.pathname.endsWith('.flac')
  ) return;

  if (event.request.destination === 'document' || url.pathname === '/' || url.pathname === '/js/app.js') {
    event.respondWith(networkFirst(event.request));
    return;
  }
  const isCdnAsset =
    url.hostname.includes('unpkg.com') || url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') || url.hostname.includes('cdn.jsdelivr.net');
  if (
    isCdnAsset || event.request.destination === 'script' || event.request.destination === 'style' ||
    event.request.destination === 'font' || event.request.destination === 'image'
  ) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }
  const isLocalAsset = APP_SHELL.some((a) => !a.startsWith('http') && url.pathname === a);
  if (isLocalAsset) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }
  const isWhitelistedApi = API_CACHE_WHITELIST.some((path) =>
    url.pathname.startsWith(path) || url.pathname.includes(path)
  );
  if (isWhitelistedApi) event.respondWith(networkFirst(event.request));
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
    .catch(async () => cachedResponse || (await cache.match(request, { ignoreSearch: true })) || Response.error());
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
    return await cache.match(request) || await cache.match(request, { ignoreSearch: true }) || Response.error();
  }
}

async function evictStaleVariants(cache, request) {
  try {
    const url = new URL(request.url);
    if (!url.search) return;
    const stale = await cache.keys(request, { ignoreSearch: true });
    await Promise.all(stale.filter((k) => k.url !== request.url).map((k) => cache.delete(k)));
  } catch {}
}

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});
