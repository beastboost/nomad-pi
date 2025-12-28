console.log("App v1.1 loaded - Cache cleared");
const API_BASE = '/api';
let currentMedia = null;
let driveScanInterval = null;
let statsInterval = null;
let comicPages = [];
let comicIndex = 0;
let comicZoom = 1;
let comicFit = 'width'; // 'width' or 'height'
let lastNetSample = null;
const mediaCache = {};
let showsLibraryCache = null;
let showsState = { level: 'shows', showName: null, seasonName: null };
const SHOWS_STATE_KEY = 'nomadpi.showsState';
let movieMetaObserver = null;
let movieMetaQueue = [];
let movieMetaActive = 0;
const MOVIE_META_CONCURRENCY = 2;
const mediaPageState = {};

function getPageState(category) {
    if (!mediaPageState[category]) {
        mediaPageState[category] = { items: [], offset: 0, limit: 60, q: '', loading: false, hasMore: true };
    }
    return mediaPageState[category];
}

function getMovieMetaObserver() {
    if (movieMetaObserver) return movieMetaObserver;
    if (!('IntersectionObserver' in window)) return null;
    movieMetaObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            movieMetaObserver.unobserve(el);
            const file = el.__movieFile;
            if (file) enqueueMovieMetaFetch(file, el);
        });
    }, { root: null, rootMargin: '300px', threshold: 0.01 });
    return movieMetaObserver;
}

function enqueueMovieMetaFetch(file, el) {
    if (!file || !file.path) return;
    if (file._metaLoaded || file._metaLoading) return;
    file._metaLoading = true;
    movieMetaQueue.push({ file, el });
    pumpMovieMetaQueue();
}

function pumpMovieMetaQueue() {
    while (movieMetaActive < MOVIE_META_CONCURRENCY && movieMetaQueue.length > 0) {
        const task = movieMetaQueue.shift();
        movieMetaActive += 1;
        fetchMovieMeta(task.file).then((meta) => {
            if (meta) applyMovieMetaToCard(task.el, task.file, meta);
        }).catch(() => {}).finally(() => {
            task.file._metaLoading = false;
            task.file._metaLoaded = true;
            movieMetaActive -= 1;
            pumpMovieMetaQueue();
        });
    }
}

async function fetchMovieMeta(file) {
    try {
        const res = await fetch(`${API_BASE}/media/meta?path=${encodeURIComponent(file.path)}&fetch=1&media_type=movie`);
        if (res.status === 401) { logout(); return null; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.configured === false) return null;
        file.omdb = data;
        return data;
    } catch {
        return null;
    }
}

function applyMovieMetaToCard(cardEl, file, data) {
    if (!cardEl || !data) return;
    const titleEl = cardEl.querySelector('.card-title');
    const subEl = cardEl.querySelector('.card-subtitle');
    const shell = cardEl.querySelector('.poster-shell');

    const title = data.title || data.meta?.Title;
    if (titleEl && title) titleEl.textContent = title;

    const year = data.year || data.meta?.Year;
    const rated = data.rated || data.meta?.Rated;
    const runtime = data.runtime || data.meta?.Runtime;
    const parts = [year, rated, runtime].filter(v => v && v !== 'N/A');
    if (subEl && parts.length > 0) subEl.textContent = parts.join(' • ');

    if (shell && !file.poster) {
        const posterUrl = data.poster || data.meta?.Poster;
        if (posterUrl && posterUrl !== 'N/A') {
            const existingImg = shell.querySelector('img.poster-img');
            if (!existingImg) {
                const placeholder = shell.querySelector('.poster-placeholder');
                const img = document.createElement('img');
                img.className = 'poster-img';
                img.loading = 'lazy';
                img.alt = file?.name || 'Poster';
                img.src = posterUrl;
                if (placeholder) placeholder.replaceWith(img);
                else shell.prepend(img);
            }
        }
    }
}

function startStatsAutoRefresh() {
    if (statsInterval) return;
    statsInterval = setInterval(() => {
        loadStorageStats();
    }, 5000);
}

function stopStatsAutoRefresh() {
    if (!statsInterval) return;
    clearInterval(statsInterval);
    statsInterval = null;
}

function saveShowsState() {
    try {
        localStorage.setItem(SHOWS_STATE_KEY, JSON.stringify(showsState));
    } catch {}
}

function restoreShowsState() {
    try {
        const raw = localStorage.getItem(SHOWS_STATE_KEY);
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return false;

        const level = ['shows', 'seasons', 'episodes'].includes(parsed.level) ? parsed.level : 'shows';
        const showName = typeof parsed.showName === 'string' ? parsed.showName : null;
        const seasonName = typeof parsed.seasonName === 'string' ? parsed.seasonName : null;

        if (!showsLibraryCache || showsLibraryCache.length === 0) {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return false;
        }

        if (!showName) {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return true;
        }

        const show = showsLibraryCache.find(s => s.name === showName);
        if (!show) {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return true;
        }

        if (level === 'shows') {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return true;
        }

        if (level === 'seasons') {
            showsState = { level: 'seasons', showName, seasonName: null };
            return true;
        }

        if (level === 'episodes') {
            const season = show.seasons?.find(se => se.name === seasonName);
            if (!season) {
                showsState = { level: 'seasons', showName, seasonName: null };
                return true;
            }
            showsState = { level: 'episodes', showName, seasonName };
            return true;
        }

        return false;
    } catch {
        return false;
    }
}

// Auth Functions
async function login() {
    const passwordInput = document.getElementById('password-input');
    const password = passwordInput.value;
    const errorMsg = document.getElementById('login-error');

    try {
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ password: password })
        });

        if (res.ok) {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('app').classList.remove('hidden');
            // Load initial data
            loadStorageStats();
            loadResume();
            startStatsAutoRefresh();
        } else {
            errorMsg.style.display = 'block';
            passwordInput.value = '';
        }
    } catch (e) {
        console.error(e);
        alert('Login error: ' + e);
    }
}

async function logout() {
    await fetch(`${API_BASE}/auth/logout`, { method: 'POST' });
    location.reload();
}

async function checkAuth() {
    try {
        const res = await fetch(`${API_BASE}/auth/check`);
        const data = await res.json();
        if (data.authenticated) {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('app').classList.remove('hidden');
            loadStorageStats();
            loadResume();
            startStatsAutoRefresh();
        } else {
            // Ensure login screen is visible
            document.getElementById('login-screen').style.display = 'flex';
            document.getElementById('app').classList.add('hidden');
            stopStatsAutoRefresh();
        }
    } catch (e) {
        console.error("Auth check failed", e);
    }
}

function handleLoginKey(e) {
    if (e.key === 'Enter') login();
}

function showSection(id) {
    document.querySelectorAll('main > section').forEach(sec => {
        sec.classList.add('hidden');
        sec.style.display = 'none'; // Force hide
        sec.classList.remove('active', 'animate-fade');
    });

    // Update active nav button
    document.querySelectorAll('nav button').forEach(btn => {
        btn.classList.remove('active');
        if (btn.innerText.toLowerCase() === id.toLowerCase()) {
            btn.classList.add('active');
        }
    });

    const target = document.getElementById(id);
    if (target) {
        target.classList.remove('hidden');
        target.style.display = 'block'; // Ensure display is set
        target.classList.add('active', 'animate-fade');
    }

    // Clear drive scan interval if leaving admin
    if (driveScanInterval) {
        clearInterval(driveScanInterval);
        driveScanInterval = null;
    }

    if (['movies', 'music', 'books', 'gallery', 'files'].includes(id)) loadMedia(id);
    if (id === 'shows') loadShowsLibrary();
    if (id === 'home') {
        loadResume();
        loadStorageStats();
    }
    if (id === 'admin') {
        loadDrives();
        // Auto-refresh drives every 5 seconds while in admin panel
        driveScanInterval = setInterval(() => {
            // Only refresh if we are not currently interacting (simple check)
            if (!document.querySelector('.drive-item button:disabled')) {
                loadDrives(true); // Pass true for silent update
            }
        }, 5000);
    }
}

async function loadMedia(category) {
    await loadMediaPage(category, true);
}

function renderMediaFromCache(category) {
    const files = mediaCache[category] || [];
    const searchInput = document.getElementById(`${category}-search`);
    const q = (searchInput?.value || '').trim().toLowerCase();
    const filtered = q ? files.filter(f => `${f.name} ${f.folder || ''}`.toLowerCase().includes(q)) : files;
    renderMediaList(category, filtered);
}

async function loadMediaPage(category, reset) {
    const container = document.getElementById(`${category}-list`);
    if (!container) return;

    const searchInput = document.getElementById(`${category}-search`);
    const q = (searchInput?.value || '').trim();
    const state = getPageState(category);
    if (reset) {
        state.items = [];
        state.offset = 0;
        state.q = q;
        state.hasMore = true;
        mediaCache[category] = null;
        container.innerHTML = '<div class="loading">Loading...</div>';
    }

    if (state.loading || !state.hasMore) return;
    state.loading = true;

    try {
        const res = await fetch(`${API_BASE}/media/list_paged/${category}?offset=${state.offset}&limit=${state.limit}&q=${encodeURIComponent(state.q || '')}`);
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) throw new Error(data?.detail || 'Failed to load media');

        const items = Array.isArray(data.items) ? data.items : [];
        state.items = state.items.concat(items);
        state.offset = Number(data.next_offset || (state.offset + items.length));
        state.hasMore = Boolean(data.has_more);
        mediaCache[category] = state.items;
        renderMediaListPaged(category, state.items, state.hasMore);
    } catch (e) {
        console.error(e);
        container.innerHTML = '<p>Error loading media.</p>';
    } finally {
        state.loading = false;
    }
}

function renderMediaListPaged(category, files, hasMore) {
    renderMediaList(category, files);
    const container = document.getElementById(`${category}-list`);
    if (!container) return;

    const footerId = `${category}-load-more`;
    const existing = document.getElementById(footerId);
    if (existing) existing.remove();

    if (!hasMore) return;
    const btn = document.createElement('button');
    btn.id = footerId;
    btn.className = 'primary';
    btn.style.margin = '14px auto';
    btn.style.display = 'block';
    btn.textContent = 'Load more';
    btn.addEventListener('click', () => loadMediaPage(category, false));
    container.appendChild(btn);
}

function renderMediaList(category, files) {
    const container = document.getElementById(`${category}-list`);
    container.innerHTML = '';

    if (category === 'music' && files && files.length > 0) {
        const shuffleBtn = document.createElement('button');
        shuffleBtn.className = 'primary';
        shuffleBtn.style.marginBottom = '10px';
        shuffleBtn.textContent = 'Shuffle All';
        shuffleBtn.onclick = () => {
            const shuffled = [...files].sort(() => 0.5 - Math.random());
            startMusicQueue(shuffled, 0);
        };
        container.appendChild(shuffleBtn);
    }

    if (!files || files.length === 0) {
        container.innerHTML = '<p>No media found.</p>';
        return;
    }

    files.sort((a, b) => {
        if ((a.folder || '.') === (b.folder || '.')) return naturalCompare(a.name, b.name);
        return naturalCompare((a.folder || '.'), (b.folder || '.'));
    });

    files.forEach(file => {
        const div = document.createElement('div');
        div.className = (category === 'music' || category === 'files') ? 'list-item' : 'media-item';
        div.style.position = 'relative';

        let folderHtml = '';
        if (file.folder && file.folder !== '.') {
            if (category === 'music' || category === 'files') {
                folderHtml = `<div style="color:#aaa;font-size:0.85em;">${file.folder}</div>`;
            } else {
                folderHtml = `<div class="folder-tag">${file.folder}</div>`;
            }
        }
        
        const deleteBtn = `<button class="delete-btn" style="background:none;border:none;cursor:pointer;font-size:1.2em;" title="Delete" onclick="deleteItem('${escapeHtml(file.path)}')">🗑️</button>`;
        const cardDeleteBtn = `<button class="delete-btn" style="position:absolute;top:5px;right:5px;z-index:10;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1.2em;line-height:1;" title="Delete" onclick="deleteItem('${escapeHtml(file.path)}')">×</button>`;

        if (category === 'music') {
            const title = escapeHtml(cleanTitle(file.name));
            div.innerHTML = `
                <div style="flex-grow:1;">
                    ${folderHtml}
                    <span>${title}</span>
                </div>
                <div style="display:flex;gap:10px;align-items:center;">
                    <button class="modal-close music-play">Play</button>
                    ${deleteBtn}
                </div>
            `;
            const btn = div.querySelector('.music-play');
            if (btn) {
                btn.addEventListener('click', () => {
                    startMusicQueue(files, files.indexOf(file));
                });
            }
        } else if (category === 'files') {
            div.innerHTML = `
                <div style="flex-grow:1;">
                    ${folderHtml}
                    <span>${file.name}</span>
                </div>
                <div style="display:flex;gap:10px;align-items:center;">
                    <button class="modal-close rename-btn">Rename</button>
                    <a href="${file.path}" target="_blank" class="download-btn">Open</a>
                    ${deleteBtn}
                </div>
            `;
            const renameBtn = div.querySelector('.rename-btn');
            if (renameBtn) {
                renameBtn.addEventListener('click', async () => {
                    const newName = prompt('New filename:', file.name || '');
                    if (!newName) return;
                    const parts = String(file.path || '').split('/');
                    parts.pop();
                    const dest = `${parts.join('/')}/${newName}`.replaceAll('//', '/');
                    await renameMediaPath(file.path, dest);
                    loadMediaPage('files', true);
                });
            }
        } else if (category === 'gallery') {
            if (file.name.match(/\.(jpg|jpeg|png|gif)$/i)) {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${folderHtml}
                    <img src="${file.path}" loading="lazy" alt="${file.name}" onclick="openImageViewer('${escapeHtml(file.path)}', '${escapeHtml(file.name)}')">
                    <div class="caption">${file.name}</div>
                `;
            } else {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${folderHtml}
                    <video controls preload="metadata" src="${file.path}"></video>
                    <div class="caption">${file.name}</div>
                `;
            }
        } else if (category === 'books') {
            const isPdf = /\.pdf$/i.test(file.name || '');
            const isCbz = /\.cbz$/i.test(file.name || '');
            const isCbr = /\.cbr$/i.test(file.name || '');
            const title = escapeHtml(cleanTitle(file.name));
            const folder = file.folder && file.folder !== '.' ? `<div style="color:#aaa;font-size:0.85em;">${escapeHtml(file.folder)}</div>` : '';
            const canView = isPdf || isCbz || isCbr;
            const viewBtn = canView ? `<button class="modal-close view-btn">View</button>` : '';

            div.innerHTML = `
                ${cardDeleteBtn}
                ${folder}
                <h3>${title}</h3>
                <div style="display:flex; gap:10px; padding: 0 10px 12px 10px; align-items:center; justify-content:space-between;">
                    <a href="${file.path}" target="_blank" class="download-btn">Open</a>
                    ${viewBtn}
                </div>
            `;

            const btn = div.querySelector('.view-btn');
            if (btn) {
                btn.addEventListener('click', () => {
                    if (isPdf) openPdfViewer(file.path, file.name || 'PDF');
                    else openComicViewer(file.path, file.name || 'Comic');
                });
            }
        } else {
            let mediaElement = '';
            const isVideo = /\.(mp4|webm|mkv|mov)$/i.test(file.name || '');
            if (category === 'movies' && isVideo) {
                div.className = 'media-item media-card';
                const metaTitle = file.omdb?.title || file.omdb?.meta?.Title || cleanTitle(file.name);
                const metaYear = file.omdb?.year || file.omdb?.meta?.Year;
                const metaRated = file.omdb?.rated || file.omdb?.meta?.Rated;
                const metaRuntime = file.omdb?.runtime || file.omdb?.meta?.Runtime;
                const metaSubtitleParts = [metaYear, metaRated, metaRuntime].filter(v => v && v !== 'N/A');
                const subtitle = metaSubtitleParts.length ? escapeHtml(metaSubtitleParts.join(' • ')) : (file.folder && file.folder !== '.' ? escapeHtml(file.folder) : 'Movie');
                const metaPoster = (!file.poster && (file.omdb?.poster || file.omdb?.meta?.Poster) && (file.omdb?.poster || file.omdb?.meta?.Poster) !== 'N/A') ? (file.omdb?.poster || file.omdb?.meta?.Poster) : null;
                const poster = file.poster
                    ? `<img class="poster-img" src="${file.poster}" loading="lazy" alt="${escapeHtml(file.name)}">`
                    : (metaPoster ? `<img class="poster-img" src="${metaPoster}" loading="lazy" alt="${escapeHtml(file.name)}">` : `<div class="poster-placeholder"></div>`);
                div.innerHTML = `
                    ${cardDeleteBtn}
                    <div class="poster-shell">
                        ${poster}
                        <button class="poster-play">Play</button>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(metaTitle)}</div>
                        <div class="card-subtitle">${subtitle}</div>
                    </div>
                `;
                const btn = div.querySelector('.poster-play');
                if (btn) {
                    btn.addEventListener('click', () => {
                        openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0);
                    });
                }
                div.__movieFile = file;
                const obs = getMovieMetaObserver();
                if (obs) obs.observe(div);
            } else if (isVideo) {
                const subtitle = file.folder && file.folder !== '.' ? escapeHtml(file.folder) : '';
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${folderHtml}
                    <h3>${escapeHtml(cleanTitle(file.name))}</h3>
                    ${subtitle ? `<div style="color:#aaa;font-size:0.85em;padding:0 10px 10px 10px;">${subtitle}</div>` : ''}
                    <div style="padding: 0 10px 12px 10px;">
                        <button class="modal-close play-btn">Play</button>
                    </div>
                `;
                const btn = div.querySelector('.play-btn');
                if (btn) btn.addEventListener('click', () => openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0));
            } else {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${folderHtml}
                    <h3>${escapeHtml(cleanTitle(file.name))}</h3>
                    <button class="play-btn" onclick="openImageViewer('${escapeHtml(file.path)}', '${escapeHtml(cleanTitle(file.name))}')">View Image</button>
                `;
            }
            
            if (file.progress && file.progress.current_time > 0) {
                const pct = (file.progress.current_time / file.progress.duration) * 100;
                div.innerHTML += `<div class="progress-bar"><div class="fill" style="width:${pct}%"></div></div>`;
            }
        }
        container.appendChild(div);
    });
}

async function renameMediaPath(oldPath, newPath) {
    const res = await fetch(`${API_BASE}/media/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_path: oldPath, new_path: newPath })
    });
    if (res.status === 401) { logout(); return; }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'Rename failed');
    return data;
}

async function organizeShows(preview) {
    const out = document.getElementById('organize-status');
    if (out) out.textContent = preview ? 'Previewing…' : 'Organizing…';
    try {
        const res = await fetch(`${API_BASE}/media/organize/shows?dry_run=${preview ? 1 : 0}&rename_files=1`, { method: 'POST' });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) throw new Error(data?.detail || 'Organize failed');
        const planned = Array.isArray(data.planned) ? data.planned : [];
        const lines = [];
        lines.push(`dry_run=${data.dry_run} moved=${data.moved} skipped=${data.skipped} errors=${data.errors}`);
        for (const it of planned.slice(0, 20)) {
            if (it?.from && it?.to) lines.push(`${it.from} -> ${it.to}`);
        }
        if (planned.length > 20) lines.push(`…and ${planned.length - 20} more`);
        if (out) out.textContent = lines.join('\n');
    } catch (e) {
        if (out) out.textContent = String(e?.message || e);
    }
}

async function organizeMovies(preview) {
    const out = document.getElementById('organize-status');
    if (out) out.textContent = preview ? 'Previewing…' : 'Organizing…';
    try {
        const res = await fetch(`${API_BASE}/media/organize/movies?dry_run=${preview ? 1 : 0}&use_omdb=1&write_poster=1`, { method: 'POST' });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) throw new Error(data?.detail || 'Organize failed');
        const planned = Array.isArray(data.planned) ? data.planned : [];
        const lines = [];
        lines.push(`dry_run=${data.dry_run} moved=${data.moved} skipped=${data.skipped} errors=${data.errors}`);
        for (const it of planned.slice(0, 20)) {
            if (it?.from && it?.to) lines.push(`${it.from} -> ${it.to}`);
        }
        if (planned.length > 20) lines.push(`…and ${planned.length - 20} more`);
        if (out) out.textContent = lines.join('\n');
    } catch (e) {
        if (out) out.textContent = String(e?.message || e);
    }
}

function naturalCompare(a, b) {
    const ax = String(a || '').toLowerCase().split(/(\d+)/).map(p => (p.match(/^\d+$/) ? Number(p) : p));
    const bx = String(b || '').toLowerCase().split(/(\d+)/).map(p => (p.match(/^\d+$/) ? Number(p) : p));
    const n = Math.max(ax.length, bx.length);
    for (let i = 0; i < n; i++) {
        if (ax[i] === undefined) return -1;
        if (bx[i] === undefined) return 1;
        if (ax[i] === bx[i]) continue;
        if (typeof ax[i] === 'number' && typeof bx[i] === 'number') return ax[i] - bx[i];
        return String(ax[i]).localeCompare(String(bx[i]));
    }
    return 0;
}

function cleanTitle(name) {
    let s = String(name || '');
    s = s.replace(/\.[^.]+$/, '');
    s = s.replace(/[\._]+/g, ' ');
    s = s.replace(/\s+/g, ' ').trim();
    s = s.replace(/\b(480p|720p|1080p|2160p|4k|hdr|hevc|x265|x264|h265|h264|aac|ac3|dts|web[- ]dl|webrip|bluray|brrip|dvdrip|remux)\b/ig, '').replace(/\s+/g, ' ').trim();
    s = s.replace(/[\[\(].*?[\]\)]/g, '').replace(/\s+/g, ' ').trim();
    return s || String(name || '');
}

function startMusicQueue(list, startIdx) {
    const audio = document.getElementById('global-audio');
    const bar = document.getElementById('player-bar');
    if (!audio || !bar) return;
    musicQueue = (list || []).filter(f => f && f.path);
    if (musicQueue.length === 0) return;
    musicIndex = Math.max(0, Math.min(startIdx || 0, musicQueue.length - 1));
    if (musicShuffle) {
        musicShuffleOrder = shuffleOrder(musicQueue.length, musicIndex);
        musicShufflePos = 0;
    }
    bar.classList.remove('hidden');
    playMusicAt(musicIndex);
}

function shuffleOrder(n, start) {
    const arr = [];
    for (let i = 0; i < n; i++) arr.push(i);
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    if (n > 1 && arr[0] !== start) {
        const k = arr.indexOf(start);
        if (k > 0) { const t = arr[0]; arr[0] = arr[k]; arr[k] = t; }
    }
    return arr;
}

function playMusicAt(idx) {
    const audio = document.getElementById('global-audio');
    const titleEl = document.getElementById('player-title');
    if (!audio || !musicQueue[idx]) return;
    musicIndex = idx;
    const track = musicQueue[musicIndex];
    if (titleEl) titleEl.textContent = cleanTitle(track.name);
    audio.src = track.path;
    audio.play().catch(() => {});
    const playBtn = document.getElementById('player-play');
    if (playBtn) playBtn.textContent = 'Pause';
}

function musicNext() {
    if (!musicQueue.length) return;
    if (musicShuffle) {
        if (!musicShuffleOrder.length) musicShuffleOrder = shuffleOrder(musicQueue.length, musicIndex);
        musicShufflePos = Math.min(musicShufflePos + 1, musicShuffleOrder.length - 1);
        playMusicAt(musicShuffleOrder[musicShufflePos]);
        return;
    }
    playMusicAt((musicIndex + 1) % musicQueue.length);
}

function musicPrev() {
    if (!musicQueue.length) return;
    if (musicShuffle) {
        musicShufflePos = Math.max(musicShufflePos - 1, 0);
        playMusicAt(musicShuffleOrder[musicShufflePos] ?? musicIndex);
        return;
    }
    playMusicAt((musicIndex - 1 + musicQueue.length) % musicQueue.length);
}

function openPdfViewer(path, title) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    heading.textContent = title ? String(title) : 'PDF';
    const safeTitle = escapeHtml(title ? String(title) : 'PDF');
    const safePath = escapeHtml(path);
    body.innerHTML = `<iframe class="pdf-frame" src="${safePath}" title="${safeTitle}"></iframe>`;
    modal.classList.remove('hidden');
}

function closeViewer() {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    if (body) body.innerHTML = '';
    if (modal) modal.classList.add('hidden');
    comicPages = [];
    comicIndex = 0;
}

function openImageViewer(path, title) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) return;

    heading.textContent = title ? String(title) : 'Image';
    body.innerHTML = `<div class="image-viewer"><img src="${escapeHtml(path)}" style="max-width:100%; max-height:80vh; border-radius:8px;"></div>`;
    modal.classList.remove('hidden');
}

function openVideoViewer(path, title, startSeconds = 0) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    heading.textContent = title ? String(title) : 'Video';
    body.innerHTML = '';

    const video = document.createElement('video');
    video.className = 'video-frame';
    video.controls = true;
    video.preload = 'metadata';
    video.src = path;
    video.addEventListener('timeupdate', () => updateProgress(video, path));
    video.addEventListener('loadedmetadata', () => checkResume(video, path, Number(startSeconds || 0)), { once: true });

    body.appendChild(video);
    modal.classList.remove('hidden');
}

async function openComicViewer(path, title) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    heading.textContent = title ? String(title) : 'Comic';
    body.innerHTML = `<div class="loading" style="padding:40px;">
        <div class="logo animate-fade" style="font-size:1.5rem; margin-bottom:10px;">Loading Comic...</div>
        <div class="progress-container" style="max-width:200px; margin:0 auto;"><div class="progress-fill" style="width:100%; animation: pulse 1.5s infinite;"></div></div>
    </div>`;
    modal.classList.remove('hidden');
    comicZoom = 1;

    try {
        const res = await fetch(`${API_BASE}/media/books/comic/pages?path=${encodeURIComponent(path)}`);
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data || {});
            body.innerHTML = `<div style="padding:40px; text-align:center;">
                <div style="font-size:3rem; margin-bottom:20px;">⚠️</div>
                <div style="color:#ddd; font-size:1.1rem;">${escapeHtml(msg || 'Failed to load comic.')}</div>
            </div>`;
            return;
        }
        comicPages = Array.isArray(data.pages) ? data.pages : [];
        comicIndex = 0;

        if (comicPages.length === 0) {
            body.innerHTML = `<div style="padding:40px; text-align:center; color:#ddd;">No pages found in this comic.</div>`;
            return;
        }

        renderComicPage();
    } catch (e) {
        body.innerHTML = `<div style="padding:40px; text-align:center; color:#ddd;">Failed to connect to server.</div>`;
    }
}

function renderComicPage() {
    const body = document.getElementById('viewer-body');
    if (!body) return;
    if (!comicPages || comicPages.length === 0) return;
    comicIndex = Math.max(0, Math.min(comicIndex, comicPages.length - 1));

    const page = comicPages[comicIndex];
    const url = page?.path || page?.url || '';
    const total = comicPages.length;
    const idx = comicIndex + 1;

    body.innerHTML = `
        <div class="comic-viewer">
            <div class="comic-controls">
                <button class="comic-btn" onclick="comicPrev()" ${comicIndex === 0 ? 'disabled' : ''}>
                    <span>←</span> Previous
                </button>
                <div class="comic-indicator">${idx} / ${total}</div>
                <button class="comic-btn primary" onclick="comicNext()" ${comicIndex >= total - 1 ? 'disabled' : ''}>
                    Next <span>→</span>
                </button>
            </div>
            <div class="comic-stage" id="comic-stage">
                <div class="comic-page-wrapper" id="comic-wrapper" style="transform: scale(${comicZoom})">
                    <img class="comic-page" src="${escapeHtml(url)}" alt="Page ${idx}" 
                         style="max-width: ${comicFit === 'width' ? '100%' : 'none'}; 
                                max-height: ${comicFit === 'height' ? '80vh' : 'none'};">
                </div>
                <div class="zoom-controls">
                    <button class="zoom-btn" onclick="changeComicZoom(0.1)" title="Zoom In">+</button>
                    <button class="zoom-btn" onclick="changeComicZoom(-0.1)" title="Zoom Out">-</button>
                    <button class="zoom-btn" onclick="toggleComicFit()" title="Toggle Fit">
                        ${comicFit === 'width' ? '↕️' : '↔️'}
                    </button>
                </div>
            </div>
        </div>
    `;

    // Preload next page
    if (comicIndex < total - 1) {
        const nextImg = new Image();
        nextImg.src = comicPages[comicIndex + 1].path || comicPages[comicIndex + 1].url;
    }
}

function changeComicZoom(delta) {
    comicZoom = Math.max(0.5, Math.min(3, comicZoom + delta));
    const wrapper = document.getElementById('comic-wrapper');
    if (wrapper) wrapper.style.transform = `scale(${comicZoom})`;
}

function toggleComicFit() {
    comicFit = comicFit === 'width' ? 'height' : 'width';
    renderComicPage();
}

function comicPrev() {
    if (comicIndex > 0) {
        comicIndex -= 1;
        comicZoom = 1;
        renderComicPage();
        document.getElementById('comic-stage')?.scrollTo(0, 0);
    }
}

function comicNext() {
    if (comicPages && comicIndex < comicPages.length - 1) {
        comicIndex += 1;
        comicZoom = 1;
        renderComicPage();
        document.getElementById('comic-stage')?.scrollTo(0, 0);
    }
}

document.addEventListener('keydown', (e) => {
    const modal = document.getElementById('viewer-modal');
    if (!modal || modal.classList.contains('hidden')) return;
    if (e.key === 'Escape') closeViewer();
    if (e.key === 'ArrowLeft') comicPrev();
    if (e.key === 'ArrowRight') comicNext();
});

async function loadShowsLibrary() {
    const container = document.getElementById('shows-list');
    if (!container) return;

    container.innerHTML = '<div class="loading">Loading...</div>';
    try {
        if (!showsLibraryCache) {
            const res = await fetch(`${API_BASE}/media/shows/library`);
            if (res.status === 401) { logout(); return; }
            const data = await res.json();
            showsLibraryCache = data.shows || [];
        }
        if (!restoreShowsState()) {
            showsState = showsState || { level: 'shows', showName: null, seasonName: null };
        }
        renderShows();
    } catch (e) {
        console.error(e);
        container.innerHTML = '<p>Error loading shows.</p>';
    }
}

function setShowsLevel(level, showName = null, seasonName = null) {
    showsState = { level, showName, seasonName };
    saveShowsState();
    renderShows();
}

function shouldContinue(progress) {
    if (!progress) return false;
    const t = Number(progress.current_time || 0);
    const d = Number(progress.duration || 0);
    if (!Number.isFinite(t) || !Number.isFinite(d)) return false;
    return t > 60 && (d - t) > 60;
}

function collectContinueEpisodes(showName = null) {
    if (!showsLibraryCache) return [];
    const out = [];
    for (const show of showsLibraryCache) {
        if (showName && show.name !== showName) continue;
        for (const season of (show.seasons || [])) {
            for (const ep of (season.episodes || [])) {
                if (shouldContinue(ep.progress)) {
                    out.push({
                        showName: show.name,
                        seasonName: season.name,
                        name: ep.name,
                        path: ep.path,
                        progress: ep.progress
                    });
                }
            }
        }
    }

    out.sort((a, b) => {
        const at = Date.parse(a.progress?.last_played || '') || 0;
        const bt = Date.parse(b.progress?.last_played || '') || 0;
        if (bt !== at) return bt - at;
        return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
    });

    return out;
}

function renderShows() {
    const container = document.getElementById('shows-list');
    const breadcrumb = document.getElementById('shows-breadcrumb');
    const searchInput = document.getElementById('shows-search');
    const continueEl = document.getElementById('shows-continue');
    if (!container) return;

    const q = (searchInput?.value || '').trim().toLowerCase();
    container.innerHTML = '';
    if (continueEl) continueEl.innerHTML = '';

    const getDelBtn = (path) => `<button class="delete-btn" style="position:absolute;top:5px;right:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1.2em;line-height:1;" title="Delete" onclick="event.stopPropagation(); deleteItem('${escapeHtml(path)}')">×</button>`;

    if (!showsLibraryCache || showsLibraryCache.length === 0) {
        container.innerHTML = '<p>No shows found.</p>';
        if (breadcrumb) breadcrumb.innerHTML = '';
        return;
    }

    if (breadcrumb) {
        breadcrumb.innerHTML = '';

        const showsLink = document.createElement('a');
        showsLink.href = '#';
        showsLink.textContent = 'Shows';
        showsLink.onclick = (e) => { e.preventDefault(); setShowsLevel('shows'); };
        breadcrumb.appendChild(showsLink);

        if (showsState.showName) {
            breadcrumb.append(' / ');
            const showLink = document.createElement('a');
            showLink.href = '#';
            showLink.textContent = showsState.showName;
            showLink.onclick = (e) => { e.preventDefault(); setShowsLevel('seasons', showsState.showName, null); };
            breadcrumb.appendChild(showLink);
        }

        if (showsState.seasonName) {
            breadcrumb.append(' / ');
            const seasonLabel = document.createElement('span');
            seasonLabel.textContent = showsState.seasonName;
            breadcrumb.appendChild(seasonLabel);
        }
    }

    if (showsState.level === 'shows') {
        const list = q ? showsLibraryCache.filter(s => s.name.toLowerCase().includes(q)) : showsLibraryCache;

        if (continueEl && !q) {
            const cont = collectContinueEpisodes().slice(0, 6);
            if (cont.length > 0) {
                const title = document.createElement('h3');
                title.textContent = 'Continue Watching';
                continueEl.appendChild(title);

                const grid = document.createElement('div');
                grid.className = 'media-grid';

                cont.forEach(item => {
                    const div = document.createElement('div');
                    div.className = 'media-item';
                    const start = Number(item.progress?.current_time || 0);
                    div.innerHTML = `
                        <div style="color:#aaa;font-size:0.85em;margin-bottom:6px;">${escapeHtml(item.showName)} • ${escapeHtml(item.seasonName)}</div>
                        <h3 style="margin-top:0;">${escapeHtml(item.name)}</h3>
                        <video width="100%" controls preload="metadata" 
                            src="${item.path}#t=${start}"
                            ontimeupdate="updateProgress(this, '${item.path}')"></video>
                    `;
                    if (item.progress?.duration) {
                        const pct = (Number(item.progress.current_time || 0) / Number(item.progress.duration || 1)) * 100;
                        div.innerHTML += `<div class="progress-bar"><div class="fill" style="width:${pct}%"></div></div>`;
                    }
                    grid.appendChild(div);
                });

                continueEl.appendChild(grid);
            }
        }

        list.forEach(show => {
            const div = document.createElement('div');
            div.className = 'media-item show-card';
            const poster = show.poster
                ? `<img class="show-poster" src="${show.poster}" loading="lazy" alt="${escapeHtml(show.name)}">`
                : `<div class="show-poster" style="background: radial-gradient(circle at 30% 20%, rgba(229, 9, 20, 0.35), rgba(20, 20, 20, 0.95) 60%);"></div>`;
            div.innerHTML = `
                ${getDelBtn(show.path)}
                ${poster}
                <div class="show-meta">
                    <h3 class="show-title">${escapeHtml(show.name)}</h3>
                    <div class="show-subtitle">${(show.seasons || []).length} season(s)</div>
                </div>
            `;
            div.style.cursor = 'pointer';
            div.onclick = () => setShowsLevel('seasons', show.name, null);
            container.appendChild(div);
        });
        return;
    }

    const show = showsLibraryCache.find(s => s.name === showsState.showName);
    if (!show) {
        setShowsLevel('shows');
        return;
    }

    if (showsState.level === 'seasons') {
        const seasons = q ? show.seasons.filter(s => s.name.toLowerCase().includes(q)) : show.seasons;
        seasons.forEach(season => {
            const div = document.createElement('div');
            div.className = 'media-item';
            div.style.position = 'relative';
            div.innerHTML = `
                ${getDelBtn(season.path)}
                <h3>${escapeHtml(season.name)}</h3>
                <div style="color:#aaa;font-size:0.9em;">${season.episodes.length} episode(s)</div>
            `;
            div.style.cursor = 'pointer';
            div.onclick = () => setShowsLevel('episodes', show.name, season.name);
            container.appendChild(div);
        });
        return;
    }

    const season = show.seasons.find(s => s.name === showsState.seasonName);
    if (!season) {
        setShowsLevel('seasons', show.name, null);
        return;
    }

    const episodes = q ? season.episodes.filter(e => e.name.toLowerCase().includes(q)) : season.episodes;
    if (episodes.length === 0) {
        container.innerHTML = '<p>No episodes found.</p>';
        return;
    }

    episodes.forEach(ep => {
        const div = document.createElement('div');
        div.className = 'media-item media-card';
        div.innerHTML = `
            ${getDelBtn(ep.path)}
            <div class="poster-shell">
                <div class="poster-placeholder"></div>
                <button class="poster-play">Play</button>
            </div>
            <div class="card-meta">
                <div class="card-title">${escapeHtml(ep.name)}</div>
                <div class="card-subtitle">${escapeHtml(show.name)} • ${escapeHtml(season.name)}</div>
            </div>
        `;

        if (ep.progress && ep.progress.current_time > 0) {
            const pct = (ep.progress.current_time / ep.progress.duration) * 100;
            div.innerHTML += `<div class="progress-bar"><div class="fill" style="width:${pct}%"></div></div>`;
        }
        const btn = div.querySelector('.poster-play');
        if (btn) btn.addEventListener('click', () => openVideoViewer(ep.path, ep.name, ep.progress?.current_time || 0));
        container.appendChild(div);
    });
}

function escapeHtml(str) {
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

async function updateProgress(mediaElement, filePath) {
    if (Math.abs(mediaElement.currentTime - (mediaElement.lastTime || 0)) < 5) return;
    mediaElement.lastTime = mediaElement.currentTime;

    await fetch(`${API_BASE}/media/progress`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            file_path: filePath,
            current_time: mediaElement.currentTime,
            duration: mediaElement.duration || 0
        })
    });
}

function checkResume(mediaElement, filePath, savedTime) {
    if (savedTime > 60 && (mediaElement.duration - savedTime) > 60) {
        // If saved time is significant, prompt or auto-resume? 
        // For now, let's just set the time.
        // mediaElement.currentTime = savedTime; 
        // Usually better to let user choose, or just set it.
        // Let's set it but notify
        console.log(`Resuming ${filePath} at ${savedTime}`);
        mediaElement.currentTime = savedTime;
    }
}

async function loadResume() {
    const container = document.getElementById('resume-list');
    const section = document.getElementById('resume-section');
    if (!container) return;
    
    try {
        const res = await fetch(`${API_BASE}/media/resume?limit=12`);
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        const watching = Array.isArray(data.items) ? data.items : [];
        
        if (watching.length > 0) {
            section.classList.remove('hidden');
            container.innerHTML = '';
            watching.forEach(file => {
                 const div = document.createElement('div');
                 div.className = 'media-item media-card';
                 const label = file.type ? escapeHtml(file.type) : 'Video';
                 div.innerHTML = `
                    <div class="poster-shell">
                        <div class="poster-placeholder"></div>
                        <button class="poster-play">Play</button>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(file.name)}</div>
                        <div class="card-subtitle">${label}</div>
                    </div>
                 `;
                 const btn = div.querySelector('.poster-play');
                 if (btn) btn.addEventListener('click', () => openVideoViewer(file.path, file.name, file.progress?.current_time || 0));
                 if (file.progress?.duration) {
                    div.innerHTML += `<div class="progress-bar"><div class="fill" style="width:${(file.progress.current_time/file.progress.duration)*100}%"></div></div>`;
                 }
                 container.appendChild(div);
            });
        } else {
            section.classList.add('hidden');
        }

    } catch(e) {
        console.error(e);
    }
}

const uploadQueue = [];

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

document.addEventListener('DOMContentLoaded', () => {
    checkAuth(); // Check auth on load

    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const folderInput = document.getElementById('folder-input');
    const uploadCategory = document.getElementById('upload-category');
    const showsUploadOptions = document.getElementById('shows-upload-options');
    const moviesSearch = document.getElementById('movies-search');
    const showsSearch = document.getElementById('shows-search');
    const musicSearch = document.getElementById('music-search');
    const filesSearch = document.getElementById('files-search');
    const audio = document.getElementById('global-audio');
    const bar = document.getElementById('player-bar');
    const titleEl = document.getElementById('player-title');
    const btnPlay = document.getElementById('player-play');
    const btnPrev = document.getElementById('player-prev');
    const btnNext = document.getElementById('player-next');
    const btnShuffle = document.getElementById('player-shuffle');
    const seek = document.getElementById('player-seek');
    const timeEl = document.getElementById('player-time');
    const vol = document.getElementById('player-volume');

    if (audio && bar) {
        audio.addEventListener('timeupdate', () => {
            if (musicQueue[musicIndex]) updateProgress(audio, musicQueue[musicIndex].path);
            if (seek && Number.isFinite(audio.duration) && audio.duration > 0) {
                seek.value = String(Math.floor((audio.currentTime / audio.duration) * 100));
            }
            if (timeEl) {
                const cur = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
                const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
                timeEl.textContent = `${formatClock(cur)} / ${formatClock(dur)}`;
            }
        });
        audio.addEventListener('ended', () => musicNext());
        audio.addEventListener('play', () => { if (btnPlay) btnPlay.textContent = 'Pause'; });
        audio.addEventListener('pause', () => { if (btnPlay) btnPlay.textContent = 'Play'; });
    }

    if (btnPlay && audio) {
        btnPlay.addEventListener('click', () => {
            if (!audio.src) return;
            if (audio.paused) audio.play().catch(() => {});
            else audio.pause();
        });
    }
    if (btnPrev) btnPrev.addEventListener('click', () => musicPrev());
    if (btnNext) btnNext.addEventListener('click', () => musicNext());
    if (btnShuffle) {
        btnShuffle.addEventListener('click', () => {
            musicShuffle = !musicShuffle;
            btnShuffle.classList.toggle('active', musicShuffle);
            if (musicShuffle && musicQueue.length) {
                musicShuffleOrder = shuffleOrder(musicQueue.length, musicIndex);
                musicShufflePos = 0;
            }
        });
    }
    if (seek && audio) {
        seek.addEventListener('input', () => {
            const pct = Number(seek.value || 0) / 100;
            if (Number.isFinite(audio.duration) && audio.duration > 0) {
                audio.currentTime = audio.duration * pct;
            }
        });
    }
    if (vol && audio) {
        vol.addEventListener('input', () => {
            const v = Number(vol.value);
            audio.volume = Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 1;
        });
    }
    if (titleEl && !titleEl.textContent) titleEl.textContent = 'Not playing';

    if (uploadCategory && showsUploadOptions) {
        const syncShowsOptions = () => {
            const isShows = uploadCategory.value === 'shows';
            showsUploadOptions.classList.toggle('hidden', !isShows);
        };
        uploadCategory.addEventListener('change', syncShowsOptions);
        syncShowsOptions();
    }

    if (dropZone) {
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');

            const items = e.dataTransfer.items;
            if (items) {
                const entries = [];
                for (let i = 0; i < items.length; i++) {
                    const item = items[i].webkitGetAsEntry();
                    if (item) {
                        await traverseFileTree(item, entries);
                    }
                }
                handleFiles(entries);
            } else {
                handleFiles(e.dataTransfer.files);
            }
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => handleFiles(e.target.files));
    }
    
    if (folderInput) {
        folderInput.addEventListener('change', (e) => handleFiles(e.target.files));
    }

    if (moviesSearch) {
        moviesSearch.addEventListener('input', debounce(() => {
            loadMediaPage('movies', true);
        }, 300));
    }
    if (musicSearch) {
        musicSearch.addEventListener('input', debounce(() => {
            loadMediaPage('music', true);
        }, 300));
    }
    if (showsSearch) {
        showsSearch.addEventListener('input', debounce(() => {
            if (showsLibraryCache) renderShows();
        }, 300));
    }
    if (filesSearch) {
        filesSearch.addEventListener('input', debounce(() => {
            loadMediaPage('files', true);
        }, 300));
    }
});

function formatClock(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, '0')}`;
}

function traverseFileTree(item, entryList, path = '') {
    return new Promise((resolve) => {
        if (item.isFile) {
            item.file((file) => {
                entryList.push({ file, relativePath: `${path}${file.name}` });
                resolve();
            });
        } else if (item.isDirectory) {
            const dirReader = item.createReader();
            dirReader.readEntries(async (entries) => {
                for (const entry of entries) {
                    await traverseFileTree(entry, entryList, `${path}${item.name}/`);
                }
                resolve();
            });
        } else {
            resolve();
        }
    });
}

function handleFiles(files) {
    const queueDiv = document.getElementById('upload-queue');
    const list = Array.isArray(files) ? files : Array.from(files);
    for (const entry of list) {
        const isWrapped = entry && entry.file instanceof File;
        const file = isWrapped ? entry.file : entry;
        const relativePath = isWrapped ? entry.relativePath : (file.webkitRelativePath || file.name);

        uploadQueue.push({ file, relativePath });
        const item = document.createElement('div');
        item.textContent = `${relativePath} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
        item.style.fontSize = '0.9em';
        item.style.borderBottom = '1px solid #444';
        queueDiv.appendChild(item);
    }
}

async function uploadFiles() {
    const category = document.getElementById('upload-category').value;
    const statusDiv = document.getElementById('upload-status');
    const rawShowName = (document.getElementById('upload-show-name')?.value || '').trim();
    
    if (uploadQueue.length === 0) {
        alert("No files selected!");
        return;
    }

    statusDiv.innerHTML = '<div class="progress-container"><div id="upload-progress-bar" class="progress-fill" style="width:0%">0%</div></div>';
    const progressBar = document.getElementById('upload-progress-bar');
    
    const items = uploadQueue.filter(e => e.file && e.file.size > 0);
    const totalFiles = items.length;
    const totalBytes = items.reduce((sum, e) => sum + (e.file?.size || 0), 0);
    let completedBytes = 0;
    let completed = 0;
    let processed = 0;
    let errors = 0;
    const errorList = [];

    if (totalFiles === 0) {
        alert("No files selected!");
        return;
    }
    
    const concurrency = 5;
    const loadedByIndex = new Array(totalFiles).fill(0);

    function computeDisplayName(entry) {
        const file = entry.file;
        let displayName = entry.relativePath || file.name;
        displayName = String(displayName || '').replaceAll('\\', '/');
        if (category === 'shows') {
            let showName = rawShowName.replaceAll('/', '').replaceAll('\\', '').trim();
            if (!showName) {
                showName = inferShowNameFromFilename(displayName);
            }

            const parts = displayName.split('/').filter(Boolean);
            const first = (parts[0] || '').toLowerCase();
            const seasonLike = first.startsWith('season') || first.startsWith('series') || /^s\d{1,3}/.test(first);
            if (showName) {
                if (parts[0] !== showName) {
                    displayName = `${showName}/${displayName}`;
                }
            } else if (parts.length < 2 || seasonLike) {
                displayName = `Unsorted/${displayName}`;
            }
        }
        return displayName;
    }

    function updateAggregateProgress() {
        const inFlightBytes = loadedByIndex.reduce((sum, v) => sum + v, 0);
        const uploaded = completedBytes + inFlightBytes;
        const pct = totalBytes > 0 ? (uploaded / totalBytes) * 100 : 0;
        progressBar.style.width = `${pct}%`;
        progressBar.textContent = `${formatBytes(uploaded)}/${formatBytes(totalBytes)} (${pct.toFixed(0)}%)`;
    }

    async function uploadOne(entry, index) {
        const file = entry.file;
        const displayName = computeDisplayName(entry);
        try {
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', `${API_BASE}/media/upload_stream/${category}?path=${encodeURIComponent(displayName)}`, true);
                xhr.setRequestHeader('Content-Type', 'application/octet-stream');
                xhr.setRequestHeader('X-File-Path', displayName);
                xhr.upload.onprogress = function(e) {
                    if (!e.lengthComputable) return;
                    loadedByIndex[index] = e.loaded;
                    updateAggregateProgress();
                };
                
                xhr.onload = function() {
                    if (xhr.status === 200) {
                        resolve();
                    } else if (xhr.status === 401) {
                        logout();
                        reject('Unauthorized (Session Expired)');
                    } else if (xhr.status === 413) {
                        reject('File Too Large');
                    } else {
                        let detail = '';
                        try {
                            const parsed = JSON.parse(xhr.responseText || '{}');
                            if (typeof parsed.detail === 'string') detail = parsed.detail;
                            else if (parsed.detail) detail = JSON.stringify(parsed.detail);
                        } catch {
                            detail = (xhr.responseText || '').trim();
                        }
                        if (detail) {
                            reject(`Server Error ${xhr.status}: ${detail}`);
                        } else {
                            reject(`Server Error ${xhr.status}: ${xhr.statusText}`);
                        }
                    }
                };
                
                xhr.onerror = function() {
                    reject('Network Error (Check Connection/Permissions)');
                };
                
                xhr.send(file);
            });
            completed++;
            completedBytes += file.size || 0;
            loadedByIndex[index] = 0;
        } catch (e) {
            console.error(`Failed to upload ${displayName}:`, e);
            errors++;
            errorList.push(`${displayName}: ${e}`);
            loadedByIndex[index] = 0;
        }

        processed++;
        const pctFiles = Math.round((processed / totalFiles) * 100);
        if (totalBytes > 0) {
            const pctBytes = (completedBytes / totalBytes) * 100;
            progressBar.style.width = `${pctBytes}%`;
            progressBar.textContent = `${formatBytes(completedBytes)}/${formatBytes(totalBytes)} (${pctFiles}%)`;
        } else {
            progressBar.style.width = `${pctFiles}%`;
            progressBar.textContent = `${processed}/${totalFiles} (${pctFiles}%)`;
        }
    }

    const queue = items.map((entry, idx) => ({ entry, idx }));
    const workers = new Array(Math.min(concurrency, queue.length)).fill(0).map(async () => {
        while (queue.length) {
            const next = queue.shift();
            if (!next) return;
            await uploadOne(next.entry, next.idx);
            updateAggregateProgress();
        }
    });
    await Promise.all(workers);

    if (errors === 0) {
        statusDiv.innerHTML = `<span style="color:#4caf50">Success! Uploaded ${completed} files.</span>`;
        uploadQueue.length = 0; // Clear queue
        document.getElementById('upload-queue').innerHTML = '';
    } else {
        let errorHtml = `<span style="color:var(--danger-color)">Finished with ${errors} errors. Uploaded ${completed}/${totalFiles}.</span>`;
        errorHtml += '<div style="max-height:100px;overflow-y:auto;background:#333;padding:5px;margin-top:5px;font-size:0.8em;">';
        errorList.forEach(err => {
            errorHtml += `<div>${err}</div>`;
        });
        errorHtml += '</div>';
        statusDiv.innerHTML = errorHtml;
    }

    if (completed > 0) {
        delete mediaCache[category];
        if (category === 'shows') showsLibraryCache = null;

        const active = document.querySelector('main > section.active')?.id;
        if (active === category) {
            if (category === 'shows') {
                loadShowsLibrary();
            } else {
                loadMedia(category);
            }
        }
    }
}

async function deleteItem(path) {
    if (!confirm('Are you sure you want to delete this item? This cannot be undone.')) return;
    try {
        const res = await fetch(`${API_BASE}/media/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
        if (res.status === 401) { logout(); return; }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || 'Delete failed');
        }
        
        // Clear caches
        delete mediaCache['movies'];
        delete mediaCache['music'];
        delete mediaCache['books'];
        delete mediaCache['gallery'];
        delete mediaCache['files'];
        showsLibraryCache = null;

        const active = document.querySelector('main > section.active')?.id;
        if (active === 'shows') loadShowsLibrary();
        else if (active) loadMedia(active);
    } catch (e) {
        alert(e.message);
    }
}

async function rescanLibrary() {
    if (!confirm('Rescan all libraries? This may take a while.')) return;
    try {
        const res = await fetch(`${API_BASE}/media/scan`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Scan failed');
        alert(data.message);
    } catch (e) {
        alert(e.message);
    }
}

async function prepareDrive(path) {
    if (!confirm(`Create standard folders (movies, shows, etc.) on ${path}?`)) return;
    try {
        const res = await fetch(`${API_BASE}/media/system/prepare_drive?path=${encodeURIComponent(path)}`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        alert(data.message);
    } catch (e) {
        alert(e.message);
    }
}

function inferShowNameFromFilename(pathOrName) {
    const baseName = String(pathOrName || '').split('/').pop() || '';
    const name = baseName.replace(/\.[^.]+$/, '');
    const m = name.match(/^(.*?)(?:\bS\d{1,3}\s*E\d{1,3}\b|\b\d{1,3}x\d{1,3}\b|\bEpisode\s*\d{1,3}\b)/i);
    if (!m || !m[1]) return '';
    const cleaned = m[1].replace(/[\.\-_]+/g, ' ').replace(/\s+/g, ' ').trim();
    if (cleaned.length < 2) return '';
    return cleaned;
}

async function loadStorageStats() {
    try {
        const res = await fetch(`${API_BASE}/system/storage`);
        if (res.status === 401) return;
        const data = await res.json();
        
        const percent = Number(data.percent || 0);
        const freeGB = Number(data.free || 0) / (1024 ** 3);
        const totalGB = Number(data.total || 0) / (1024 ** 3);
        const usedGB = Number(data.used || 0) / (1024 ** 3);

        const cpuPercent = Number(data.cpu_percent);
        const ramPercent = Number(data.ram_percent);
        const ramUsedGB = Number(data.ram_used || 0) / (1024 ** 3);
        const ramTotalGB = Number(data.ram_total || 0) / (1024 ** 3);

        const now = Date.now();
        const sent = Number(data.net_bytes_sent);
        const recv = Number(data.net_bytes_recv);
        let downRate = null;
        let upRate = null;
        if (lastNetSample && Number.isFinite(sent) && Number.isFinite(recv)) {
            const dt = (now - lastNetSample.t) / 1000;
            if (dt > 0) {
                downRate = (recv - lastNetSample.r) / dt;
                upRate = (sent - lastNetSample.s) / dt;
            }
        }
        if (Number.isFinite(sent) && Number.isFinite(recv)) {
            lastNetSample = { t: now, s: sent, r: recv };
        }

        const storageEl = document.getElementById('storage-stats');
        const cpuEl = document.getElementById('cpu-stats');
        const ramEl = document.getElementById('ram-stats');
        const netEl = document.getElementById('net-stats');
        const headerEl = document.getElementById('header-stats');

        if (storageEl) storageEl.innerText = `${percent.toFixed(0)}% used • ${usedGB.toFixed(1)}/${totalGB.toFixed(1)} GB • ${freeGB.toFixed(1)} GB free`;
        if (cpuEl && Number.isFinite(cpuPercent)) cpuEl.innerText = `${cpuPercent.toFixed(0)}%`;
        if (ramEl && Number.isFinite(ramPercent)) ramEl.innerText = `${ramPercent.toFixed(0)}% • ${ramUsedGB.toFixed(1)}/${ramTotalGB.toFixed(1)} GB`;
        if (netEl) netEl.innerText = `${downRate === null ? '↓ --' : `↓ ${formatRate(downRate)}`} • ${upRate === null ? '↑ --' : `↑ ${formatRate(upRate)}`}`;
        if (headerEl) headerEl.innerText = `${Number.isFinite(cpuPercent) ? `CPU ${cpuPercent.toFixed(0)}%` : ''}${Number.isFinite(ramPercent) ? ` • RAM ${ramPercent.toFixed(0)}%` : ''}${downRate === null ? '' : ` • ↓ ${formatRate(downRate)}`}${upRate === null ? '' : ` • ↑ ${formatRate(upRate)}`}`;
    } catch (e) {
        console.error(e);
    }
}

function formatBytes(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = n;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatRate(bytesPerSec) {
    return `${formatBytes(bytesPerSec)}/s`;
}

let lastDriveData = '';
let musicQueue = [];
let musicIndex = -1;
let musicShuffle = false;
let musicShuffleOrder = [];
let musicShufflePos = 0;
async function systemControl(action) {
    const msg = action === 'update' ? 'Are you sure you want to update from GitHub? This will pull latest files and restart the service.' : `Are you sure you want to ${action} the device?`;
    if (!confirm(msg)) return;

    try {
        const res = await fetch(`${API_BASE}/system/control/${action}`, { method: 'POST' });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        alert(data.status || data.message || 'Action initiated');
    } catch (e) {
        console.error(e);
        alert('Error controlling system.');
    }
}

async function loadDrives(silent = false) {
    const container = document.getElementById('drive-list');
    if (!silent) container.innerHTML = '<div class="loading">Scanning...</div>';
    
    try {
        const res = await fetch(`${API_BASE}/system/drives`);
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        
        // Check if data changed to avoid flickering
        const currentDataStr = JSON.stringify(data);
        if (silent && currentDataStr === lastDriveData) {
            return;
        }
        lastDriveData = currentDataStr;

        container.innerHTML = '';
        const devices = data.blockdevices || data; 
        
        if (!devices || devices.length === 0) {
            container.innerHTML = 'No external drives found.';
            return;
        }

        function renderDevice(dev) {
            const label = dev.label || dev.name || 'Unknown';
            const size = dev.size || 'Unknown';
            const fstype = dev.fstype || dev.type || '';
            const uuid = dev.uuid || '';
            
            let html = `<div class="drive-item" style="border: 1px solid var(--border-color); padding: 10px; margin-bottom: 10px; border-radius: 8px; background: rgba(255,255,255,0.05);">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                    <div>
                        <strong>${escapeHtml(label)}</strong> <small>(${escapeHtml(dev.name || dev.device || '')})</small>
                        <br><small>${escapeHtml(size)} • ${escapeHtml(fstype)}</small>
                        ${uuid ? `<br><small style="color:#888; font-family:monospace;">${escapeHtml(uuid)}</small>` : ''}
                    </div>`;
            
            if (dev.mountpoint) {
                html += `<div style="display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end;margin-top:5px;">
                    <span class="badge success" style="margin-right:auto;">Mounted: ${escapeHtml(dev.mountpoint)}</span>
                    <button class="primary small" onclick="prepareDrive('${escapeHtml(dev.mountpoint)}')">Prepare</button>
                    <button class="secondary small" onclick="mediaState.path='${escapeHtml(dev.mountpoint).replaceAll('\\', '\\\\')}';showSection('files');loadMedia('files');">Browse</button>
                    <button class="danger small drive-unmount" data-mountpoint="${escapeHtml(dev.mountpoint)}">Unmount</button>
                </div>`;
            } else if ((dev.type === 'part' || dev.fstype) && !dev.children) {
                 const mountName = dev.label || dev.uuid || dev.name || dev.device;
                 const devPath = dev.device || dev.name;
                 html += `<div>
                    <button class="primary small drive-mount" data-device="${escapeHtml(devPath || '')}" data-name="${escapeHtml(mountName || '')}">Mount</button>
                 </div>`;
            }
            html += `</div></div>`;
            
            if (dev.children) {
                dev.children.forEach(child => {
                    html += `<div style="margin-left:20px; border-left: 2px solid var(--border-color); padding-left: 10px;">${renderDevice(child)}</div>`;
                });
            }
            return html;
        }

        if (Array.isArray(devices)) {
            devices.forEach(dev => {
                const div = document.createElement('div');
                div.innerHTML = renderDevice(dev);
                container.appendChild(div);
            });
        }

        container.querySelectorAll('.drive-mount').forEach(btn => {
            btn.addEventListener('click', () => {
                mountDrive(btn.dataset.device || '', btn.dataset.name || '', btn);
            });
        });
        container.querySelectorAll('.drive-unmount').forEach(btn => {
            btn.addEventListener('click', () => {
                unmountDrive(btn.dataset.mountpoint || '');
            });
        });
    } catch (e) {
        console.error(e);
        container.innerHTML = 'Error scanning drives.';
    }
}

async function mountDrive(device, name, btn) {
    // Clean name for mount point
    name = String(name).replace(/[^a-zA-Z0-9-_]/g, '');
    if (!name) name = 'usb_drive';

    try {
        let devPath = device;
        if (!device.startsWith('/') && !device.startsWith('PhysicalDrive')) {
            devPath = `/dev/${device}`;
        }
        
        if (btn) {
            btn.innerText = 'Mounting...';
            btn.disabled = true;
        }

        const res = await fetch(`${API_BASE}/system/mount?device=${devPath}&mount_point=${name}`, {
            method: 'POST'
        });
        if (res.status === 401) { logout(); return; }
        const result = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(result.detail || result.error || 'Mount failed');
        }
        
        if (result.status === 'mounted' || result.status === 'not_implemented_on_windows') {
            loadDrives(); 
        } else {
            alert('Error: ' + (result.message || JSON.stringify(result)));
            if (btn) {
                btn.innerText = 'Mount';
                btn.disabled = false;
            }
        }
    } catch (e) {
        alert('Error: ' + e);
        loadDrives();
    }
}

async function systemControl(action) {
    if (!confirm(`Are you sure you want to ${action} the system?`)) return;

    try {
        const res = await fetch(`${API_BASE}/system/control/${action}`, { method: 'POST' });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            alert(data.error || data.detail || `Failed to ${action}.`);
            return;
        }
        alert(data.status || `System ${action} initiated.`);
    } catch (e) {
        alert(`Error: ${e}`);
    }
}

async function unmountDrive(mountpoint) {
    if (!confirm(`Unmount ${mountpoint}?`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/system/unmount?target=${encodeURIComponent(mountpoint)}`, {
            method: 'POST'
        });
        if (res.status === 401) { logout(); return; }
        const result = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(result.detail || result.error || 'Unmount failed');
        }
        
        if (result.status === 'unmounted' || result.status === 'not_implemented_on_windows') {
            loadDrives();
        } else {
            alert('Error: ' + (result.message || JSON.stringify(result)));
        }
    } catch (e) {
        alert('Error: ' + e);
    }
}
