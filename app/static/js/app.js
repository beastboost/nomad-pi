/* ══════════════════════════════════════════════════════════════════════════
   Nomad Pi — mobile app shell (Nocturne)

   Four tabs: Home, Library, Downloads, Server. Detail, Player, Search and
   Settings push on top of the active tab and pop with the back control.

   Markup is built from data via `data-*` attributes and read back through
   dataset in delegated listeners — user-controlled strings (file names,
   paths, SSIDs) never reach an inline handler, so the whole class of
   quoting/XSS bugs that inline onclick invites cannot occur here.
   ══════════════════════════════════════════════════════════════════════════ */

const API = '/api';
const TOKEN_KEY = 'nomad_auth_token';

/* ── State ─────────────────────────────────────────────────────────────── */

const S = {
    tab: 'home',
    screen: 'home',
    stack: [],
    profile: null,
    stats: null,
    lib: 'movies',
    libItems: [],
    libSort: 'name',
    libView: 'grid',
    sel: null,
    dl: 'active',
    debrid: { provider: null, query: '', titles: [], title: null, results: [] },
    health: null,
    remux: null,
    omdb: null,
    healthRunning: false,
    audio: { el: null, queue: [], index: -1, playing: false },
};

const LIB_TABS = [
    { key: 'movies',  label: 'Movies',  icon: 'ph ph-film-slate', grid: true },
    { key: 'shows',   label: 'Shows',   icon: 'ph ph-television', grid: true },
    { key: 'music',   label: 'Music',   icon: 'ph ph-music-note', grid: false },
    { key: 'books',   label: 'Books',   icon: 'ph ph-book-open',  grid: false },
    { key: 'gallery', label: 'Gallery', icon: 'ph ph-images',     grid: false },
    { key: 'files',   label: 'Files',   icon: 'ph ph-folder',     grid: false },
];

const SORTS = [
    { key: 'recent', label: 'Recently added' },
    { key: 'name',   label: 'Name (A–Z)' },
    { key: 'name_d', label: 'Name (Z–A)' },
    { key: 'year',   label: 'Year (newest)' },
    { key: 'year_a', label: 'Year (oldest)' },
];

const VIDEO_EXT = ['mp4','mkv','avi','mov','webm','m4v','ts','wmv','flv','3gp','mpg','mpeg','m2ts','mts','vob','mpe'];
const AUDIO_EXT = ['mp3','flac','wav','m4a','aac','ogg','opus','wma'];
const IMAGE_EXT = ['jpg','jpeg','png','gif','webp','bmp','heic'];
const BOOK_EXT  = ['pdf','epub','cbz','cbr','mobi','azw3','txt'];
const REMUXABLE = ['mkv','ts','m2ts','mts','avi','wmv','flv','mpg','mpeg'];

/* ── Small utilities ───────────────────────────────────────────────────── */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(str) {
    return String(str ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function token() { return localStorage.getItem(TOKEN_KEY); }
function authHeaders() {
    const t = token();
    return t ? { Authorization: `Bearer ${t}` } : {};
}

/* FastAPI reports validation failures as detail: [{loc, msg, type}, ...].
   Rendering that object directly is where "[object Object]" came from. */
async function readError(res) {
    const fallback = `Request failed (${res.status})`;
    let j;
    try { j = await res.json(); } catch { return fallback; }
    const d = j?.detail ?? j?.message;
    if (!d) return fallback;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
        const parts = d.map(e => {
            if (typeof e === 'string') return e;
            const field = Array.isArray(e?.loc) ? e.loc.filter(x => x !== 'body').join('.') : '';
            return field ? `${field}: ${e?.msg || 'invalid'}` : (e?.msg || 'invalid');
        }).filter(Boolean);
        return parts.length ? parts.join('\n') : fallback;
    }
    if (typeof d === 'object') return d.msg || d.message || JSON.stringify(d);
    return String(d);
}

async function api(path, opts = {}) {
    const res = await fetch(API + path, {
        ...opts,
        headers: {
            ...authHeaders(),
            ...(opts.body ? { 'Content-Type': 'application/json' } : {}),
            ...(opts.headers || {}),
        },
    });
    if (res.status === 401) { logout(); throw new Error('Unauthorized'); }
    if (!res.ok) {
        const err = new Error(await readError(res));
        err.status = res.status;
        throw err;
    }
    if (res.status === 204) return null;
    return res.json();
}

function ext(path) {
    const m = String(path || '').match(/\.([a-z0-9]+)$/i);
    return m ? m[1].toLowerCase() : '';
}
function baseName(path) {
    const p = String(path || '');
    return p.split('/').filter(Boolean).pop() || p;
}
function stripExt(name) {
    return String(name || '').replace(/\.[a-z0-9]+$/i, '');
}
function fmtSize(bytes) {
    const b = Number(bytes || 0);
    if (!b) return '';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.min(u.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
    return `${(b / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}
function fmtTime(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
             : `${m}:${String(r).padStart(2, '0')}`;
}
function fmtUptime(sec) {
    const s = Math.floor(Number(sec) || 0);
    if (!s) return '';
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return `up ${d}d ${h}h`;
    if (h) return `up ${h}h ${m}m`;
    return `up ${m}m`;
}
function fmtLeft(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    if (s < 60) return 'nearly done';
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return h ? `${h}h ${m}m left` : `${m} min left`;
}
function streamUrl(path, extra = '') {
    const t = token();
    return `${API}/media/stream?path=${encodeURIComponent(path)}${t ? `&token=${encodeURIComponent(t)}` : ''}${extra}`;
}
/* VLC's handler wants an absolute http(s) URL after the scheme. */
function vlcUrl(path) {
    const abs = new URL(streamUrl(path), location.origin).href;
    return `vlc://${abs.replace(/^https?:\/\//, '')}`;
}

/* In a standalone PWA a plain <a href> can be swallowed by the service
   worker scope, so the file never lands. Open it out of the app context. */
function downloadFile(path) {
    const url = streamUrl(path, '&download=true');
    const a = document.createElement('a');
    a.href = url;
    a.download = baseName(path);
    a.rel = 'noopener';
    a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast('Download started', 'info', 2500);
}

function posterUrl(p) {
    if (!p) return '';
    if (/^https?:/i.test(p)) return p;
    return streamUrl(p);
}
function kindOf(path, category) {
    const e = ext(path);
    if (VIDEO_EXT.includes(e)) return 'video';
    if (AUDIO_EXT.includes(e)) return 'audio';
    if (IMAGE_EXT.includes(e)) return 'image';
    if (BOOK_EXT.includes(e)) return 'book';
    if (category === 'movies' || category === 'shows') return 'video';
    if (category === 'music') return 'audio';
    if (category === 'gallery') return 'image';
    if (category === 'books') return 'book';
    return 'other';
}

/* ── Toast / dialog / sheet ────────────────────────────────────────────── */

function toast(msg, kind = 'info', ms = 4000) {
    const stack = $('#toast-stack');
    if (!stack) return;
    const icons = { info: 'ph-fill ph-info', success: 'ph-fill ph-check-circle',
                    warn: 'ph-fill ph-warning-circle', error: 'ph-fill ph-x-circle' };
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.innerHTML = `<i class="${icons[kind] || icons.info}"></i><span>${escapeHtml(msg)}</span>`;
    stack.appendChild(el);
    setTimeout(() => {
        el.style.transition = 'opacity .25s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 260);
    }, ms);
}

let _dialogResolve = null;
function confirmDialog(title, body, action = 'Confirm') {
    return new Promise(resolve => {
        _dialogResolve = resolve;
        $('#dialog-title').textContent = title;
        $('#dialog-body').textContent = body;
        $('#dialog-confirm').textContent = action;
        $('#dialog-wrap').classList.remove('hidden');
    });
}
function closeDialog(result) {
    $('#dialog-wrap').classList.add('hidden');
    if (_dialogResolve) { _dialogResolve(result); _dialogResolve = null; }
}

function openSheet(html) {
    const sheet = $('#sheet');
    sheet.innerHTML = `<div class="sheet-grip"></div>${html}`;
    sheet.classList.remove('hidden');
    $('#sheet-scrim').classList.remove('hidden');
}
function closeSheet() {
    $('#sheet').classList.add('hidden');
    $('#sheet-scrim').classList.add('hidden');
}

function setToggle(btn, on, icon) {
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.classList.toggle('btn-primary', on);
    const i = btn.querySelector('i');
    if (i) i.className = `${on ? 'ph-fill' : 'ph'} ${icon}`;
}

/* ── Navigation ────────────────────────────────────────────────────────── */

const TAB_SCREENS = { home: 'home', library: 'library', downloads: 'downloads', server: 'server' };

function showScreen(name) {
    S.screen = name;
    $$('.screen').forEach(el => el.classList.toggle('active', el.dataset.screen === name));
    const immersive = name === 'player' || name === 'reader';
    $('#tabbar').classList.toggle('hidden', immersive);
    const isPlayer = name === 'player';
    const mini = $('#mini-player');
    if (mini && !mini.classList.contains('hidden')) {
        mini.style.bottom = isPlayer ? '20px' : '';
    }
}

function goTab(tab) {
    S.tab = tab;
    S.stack = [];
    $$('.tab').forEach(b => {
        const on = b.dataset.tab === tab;
        b.classList.toggle('active', on);
        const i = b.querySelector('i');
        const base = { home: 'house', library: 'squares-four', downloads: 'arrow-circle-down', server: 'hard-drives' }[b.dataset.tab];
        if (i) i.className = on ? `ph-fill ph-${base}` : `ph ph-${base}`;
    });
    showScreen(TAB_SCREENS[tab]);
    if (tab === 'home') loadHome();
    if (tab === 'library') loadLibrary();
    if (tab === 'downloads') loadDownloads();
    if (tab === 'server') loadServer();
}

function push(screen) {
    S.stack.push(S.screen);
    showScreen(screen);
}

function back() {
    if (S.screen === 'player') stopVideo();
    if (S.screen === 'reader' && typeof closeReader === 'function') closeReader();
    const prev = S.stack.pop();
    showScreen(prev || TAB_SCREENS[S.tab] || 'home');
}

/* ══════════════════════════════════════════════════════════════════════════
   Auth
   ══════════════════════════════════════════════════════════════════════════ */

async function login(ev) {
    if (ev) ev.preventDefault();
    const u = $('#username-input').value.trim();
    const p = $('#password-input').value;
    const errEl = $('#login-error');
    const btn = $('#login-btn');
    if (!u || !p) { errEl.textContent = 'Enter a username and password.'; return; }

    btn.disabled = true;
    btn.textContent = 'Signing in…';
    errEl.textContent = '';
    try {
        const res = await fetch(`${API}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Incorrect username or password');
        const tok = data.token || data.access_token;
        if (!tok) throw new Error('Server did not return a session token');
        localStorage.setItem(TOKEN_KEY, tok);
        $('#password-input').value = '';
        await startApp();
    } catch (e) {
        errEl.textContent = e.message || 'Sign in failed';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Enter Nomad';
    }
}

function logout() {
    try { fetch(`${API}/auth/logout`, { method: 'POST', headers: authHeaders() }); } catch {}
    localStorage.removeItem(TOKEN_KEY);
    stopVideo();
    stopAudio();
    $('#app-shell').classList.add('hidden');
    $('#login-screen').classList.remove('hidden');
}

/* ══════════════════════════════════════════════════════════════════════════
   Home
   ══════════════════════════════════════════════════════════════════════════ */

function railCard(item) {
    const path = item.path || '';
    const title = item.title || item.name || baseName(path);
    const poster = posterUrl(item.poster);
    const pct = item.pct != null ? item.pct : null;
    const sub = item.sub || '';
    return `
      <button class="rail-item" data-open="${escapeHtml(path)}">
        <div class="art">
          ${poster ? `<img src="${escapeHtml(poster)}" alt="" loading="lazy" onerror="this.remove()">`
                   : `<i class="ph ph-film-slate"></i>`}
          ${pct != null ? `<div class="art-progress"><span style="width:${pct}%"></span></div>` : ''}
        </div>
        <div class="tile-title">${escapeHtml(stripExt(title))}</div>
        <div class="tile-meta">${escapeHtml(sub)}</div>
      </button>`;
}

async function loadHome() {
    const prof = S.profile || {};
    const hour = new Date().getHours();
    const part = hour < 12 ? 'Morning' : hour < 18 ? 'Afternoon' : 'Evening';
    const who = prof.name || prof.username || '';
    $('#home-greeting').textContent = who ? `${part}, ${who}` : `Good ${part.toLowerCase()}`;

    loadServerPill();

    // Continue watching + hero
    try {
        const data = await api('/media/resume?limit=12');
        const items = (data.items || []).filter(i => i.path);
        const mapped = items.map(i => {
            const cur = Number(i.progress?.current_time || 0);
            const dur = Number(i.progress?.duration || 0);
            const pct = dur > 0 ? Math.min(100, Math.round((cur / dur) * 100)) : 0;
            return {
                path: i.path,
                name: i.name,
                poster: i.poster,
                pct,
                current: cur,
                duration: dur,
                sub: dur > 0 ? fmtLeft(dur - cur) : '',
            };
        });

        const heroWrap = $('#home-hero-wrap');
        const contWrap = $('#home-continue-wrap');
        if (mapped.length) {
            heroWrap.classList.remove('hidden');
            renderHero(mapped[0]);
            const rest = mapped.slice(1);
            contWrap.classList.toggle('hidden', rest.length === 0);
            $('#home-continue').innerHTML = rest.map(railCard).join('');
        } else {
            heroWrap.classList.add('hidden');
            contWrap.classList.add('hidden');
        }
    } catch {
        $('#home-hero-wrap').classList.add('hidden');
        $('#home-continue-wrap').classList.add('hidden');
    }

    // Recently added
    let recentCount = 0;
    try {
        const data = await api('/media/recently_added?limit=12');
        const items = (data.items || []).filter(i => i.path);
        recentCount = items.length;
        $('#home-recent-wrap').classList.toggle('hidden', items.length === 0);
        $('#home-recent').innerHTML = items.map(i => railCard({
            path: i.path,
            name: i.title || i.name,
            poster: i.poster,
            sub: i.year ? String(i.year) : (i.category || ''),
        })).join('');
    } catch {
        $('#home-recent-wrap').classList.add('hidden');
    }

    renderHomeExtras(recentCount);
}

/* Home should never be a greeting over an empty page. Below the rails sit
   jump-off points into every library, and — when the box has nothing indexed
   at all — a direct route to fixing that. */
async function renderHomeExtras(recentCount) {
    let wrap = $('#home-extras');
    if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'home-extras';
        wrap.className = 'section';
        $('#screen-home .screen-scroll').appendChild(wrap);
    }

    const hasResume = !$('#home-hero-wrap').classList.contains('hidden');
    const empty = !hasResume && !recentCount;

    wrap.innerHTML = `
      <div class="section-head"><div class="kicker">Jump in</div></div>
      <div class="quick-grid">
        ${LIB_TABS.map(t => `
          <button class="quick" data-quick="${t.key}">
            <i class="${escapeHtml(t.icon)}"></i>${escapeHtml(t.label)}
          </button>`).join('')}
      </div>
      ${empty ? `
        <div class="card card-lg" style="margin:22px 20px 0">
          <div class="health-title">Nothing indexed yet</div>
          <div class="health-note" style="margin-bottom:12px">
            Add media to the Pi, pull something in from Downloads, or run a scan
            if the files are already there.
          </div>
          <div class="btn-row">
            <button class="btn" data-tab="downloads"><i class="ph ph-arrow-circle-down"></i>Downloads</button>
            <button class="btn btn-primary" data-act="scan"><i class="ph ph-arrows-clockwise"></i>Scan now</button>
          </div>
        </div>` : ''}`;
}

function renderHero(item) {
    const poster = posterUrl(item.poster);
    $('#home-hero').innerHTML = `
      <div class="hero">
        <div class="hero-art" data-open="${escapeHtml(item.path)}">
          ${poster ? `<img src="${escapeHtml(poster)}" alt="" onerror="this.remove()">` : ''}
          <i class="ph ph-image hero-ghost"></i>
          <div class="hero-copy">
            <div class="hero-title">${escapeHtml(stripExt(item.name || baseName(item.path)))}</div>
            <div class="hero-sub">${escapeHtml(item.sub || '')}</div>
          </div>
        </div>
        <div class="hero-progress"><span style="width:${item.pct || 0}%"></span></div>
        <div class="hero-actions">
          <button class="btn btn-primary" data-play="${escapeHtml(item.path)}" data-at="${item.current || 0}">
            <i class="ph-fill ph-play"></i> Resume
          </button>
          <button class="btn btn-icon" data-open="${escapeHtml(item.path)}" aria-label="Details">
            <i class="ph ph-info"></i>
          </button>
        </div>
      </div>`;
}

async function loadServerPill() {
    const dot = $('#home-status-dot');
    const text = $('#home-status-text');
    try {
        const s = await api('/system/stats');
        S.stats = s;
        const bits = [];
        bits.push('Online');
        if (s.temp) bits.push(`${Math.round(s.temp)}°C`);
        if (s.disk_free) bits.push(`${fmtSize(s.disk_free)} free`);
        let dls = 0;
        try {
            const d = await api('/debrid/downloads');
            dls = (d.downloads || []).filter(x => (x.status || '') === 'downloading').length;
        } catch {}
        if (dls) bits.push(`${dls} downloading`);
        text.textContent = bits.join(' · ');
        const hot = s.temp && s.temp >= 75;
        const full = s.disk_percent && s.disk_percent >= 92;
        dot.className = `status-dot${hot || full ? ' warn' : ''}`;
    } catch {
        text.textContent = 'Server unreachable — showing cached data';
        dot.className = 'status-dot down';
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   Library
   ══════════════════════════════════════════════════════════════════════════ */

function renderLibTabs() {
    $('#lib-tabs').innerHTML = LIB_TABS.map(t =>
        `<button class="chip${t.key === S.lib ? ' active' : ''}" data-lib="${t.key}">${escapeHtml(t.label)}</button>`
    ).join('');
}

async function loadLibrary() {
    renderLibTabs();
    const body = $('#lib-body');
    body.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    $('#lib-sort-label').textContent = SORTS.find(s => s.key === S.libSort)?.label.replace(/ \(.*\)/, '') || 'Name';
    try {
        if (S.lib === 'shows') {
            await loadShows();
            $('#lib-count').textContent = `${SHOWS.list.length} show${SHOWS.list.length === 1 ? '' : 's'}`;
            renderShowsGrid(body);
            return;
        }
        // The route defaults to limit=50 — without an explicit limit any
        // library over 50 items was silently truncated with no 'load more'.
        const data = await api(`/media/library/${S.lib}?limit=5000`);
        if (data.has_more) {
            console.warn(`library ${S.lib}: ${data.total} items, showing first 5000`);
        }
        S.libItems = (data.items || []).filter(i => i && i.path);
        renderLibItems();
    } catch (e) {
        body.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Could not load library')}</div>`;
        $('#lib-count').textContent = '';
    }
}

function sortedLibItems() {
    const items = [...S.libItems];
    const name = i => String(i.title || i.name || baseName(i.path)).toLowerCase();
    const year = i => Number(i.year || 0);
    switch (S.libSort) {
        case 'name':   items.sort((a, b) => name(a).localeCompare(name(b))); break;
        case 'name_d': items.sort((a, b) => name(b).localeCompare(name(a))); break;
        case 'year':   items.sort((a, b) => year(b) - year(a)); break;
        case 'year_a': items.sort((a, b) => year(a) - year(b)); break;
        default: break; // 'recent' — server order
    }
    return items;
}

/* Posters come from OMDb (or a local poster.jpg). With no key configured the
   grid is just placeholder glyphs and nothing says why — so say why. */
function artworkHint(items) {
    if (S.omdb !== false) return '';
    const withArt = items.filter(i => i.poster).length;
    if (withArt > items.length / 2) return '';
    return `
      <div class="card" style="margin-bottom:14px">
        <div class="dl-title">No artwork?</div>
        <div class="dl-meta" style="margin:4px 0 10px">
          Posters need an OMDb API key. It is free and takes a minute.
        </div>
        <button class="btn" data-admin="keys" style="min-height:40px">
          <i class="ph ph-key"></i>Add an OMDb key
        </button>
      </div>`;
}

function renderLibItems() {
    const items = sortedLibItems();
    const def = LIB_TABS.find(t => t.key === S.lib) || LIB_TABS[0];
    const grid = def.grid && S.libView === 'grid';
    $('#lib-count').textContent = `${items.length} item${items.length === 1 ? '' : 's'}`;
    const body = $('#lib-body');

    if (!items.length) {
        body.innerHTML = `<div class="empty"><i class="ph ph-folder-open"></i>Nothing in ${escapeHtml(def.label.toLowerCase())} yet.<br>Add media to the Pi, then run a scan from the Server tab.</div>`;
        return;
    }

    if (grid) {
        body.innerHTML = artworkHint(items) + `<div class="grid">${items.map(i => {
            const poster = posterUrl(i.poster);
            const title = stripExt(i.title || i.name || baseName(i.path));
            const meta = i.year || (i.size ? fmtSize(i.size) : '');
            return `
              <button class="grid-item" data-open="${escapeHtml(i.path)}">
                <div class="art">
                  ${poster ? `<img src="${escapeHtml(poster)}" alt="" loading="lazy" onerror="this.remove()">`
                           : `<i class="${escapeHtml(def.icon)}"></i>`}
                </div>
                <div class="tile-title">${escapeHtml(title)}</div>
                <div class="tile-meta">${escapeHtml(String(meta || ''))}</div>
              </button>`;
        }).join('')}</div>`;
    } else {
        body.innerHTML = `<div class="list">${items.map(i => {
            const title = stripExt(i.title || i.name || baseName(i.path));
            const meta = i.size ? fmtSize(i.size) : (i.folder || '');
            return `
              <button class="list-row row-rule" data-open="${escapeHtml(i.path)}">
                <div class="list-thumb"><i class="${escapeHtml(def.icon)}"></i></div>
                <div class="list-body">
                  <div class="list-title">${escapeHtml(title)}</div>
                  <div class="list-sub">${escapeHtml(String(meta || ''))}</div>
                </div>
                <i class="ph ph-caret-right list-caret"></i>
              </button>`;
        }).join('')}</div>`;
    }
}

function openSortSheet() {
    const def = LIB_TABS.find(t => t.key === S.lib) || LIB_TABS[0];
    openSheet(`
      <div class="kicker" style="margin-bottom:10px">Sort by</div>
      <div class="list">
        ${SORTS.map(s => `
          <button class="sheet-option row-rule" data-sort="${s.key}">
            <span>${escapeHtml(s.label)}</span>
            ${s.key === S.libSort ? '<i class="ph ph-check" style="font-size:17px;color:var(--color-accent)"></i>' : ''}
          </button>`).join('')}
      </div>
      ${def.grid ? `
        <div class="kicker" style="margin:20px 0 10px">View</div>
        <div class="btn-row">
          <button class="btn${S.libView === 'grid' ? ' btn-primary' : ''}" data-view="grid" style="min-height:44px">Grid</button>
          <button class="btn${S.libView === 'list' ? ' btn-primary' : ''}" data-view="list" style="min-height:44px">List</button>
        </div>` : ''}
    `);
}

/* ══════════════════════════════════════════════════════════════════════════
   Detail
   ══════════════════════════════════════════════════════════════════════════ */

async function openDetail(path) {
    if (!path) return;
    push('detail');
    const body = $('#detail-body');
    const name = stripExt(baseName(path));
    const kind = kindOf(path);

    body.innerHTML = `
      <div class="detail-art">
        <button class="btn btn-icon detail-back" data-back aria-label="Back"><i class="ph ph-arrow-left"></i></button>
        <div class="detail-copy"><h1>${escapeHtml(name)}</h1><div class="detail-meta">Loading…</div></div>
      </div>
      <div class="empty"><div class="spinner"></div></div>`;

    let meta = {};
    try { meta = await api(`/media/meta?path=${encodeURIComponent(path)}`); } catch {}

    S.sel = { path, meta, kind };

    // /media/meta returns the flat file_metadata row (lowercase columns) and,
    // when cached, the raw OMDb payload under meta.meta with capitalised keys
    // (Title/Plot/Genre/Runtime). Reading only the lowercase form meant the
    // synopsis, genres and runtime never rendered for OMDb-backed titles.
    const info = meta.metadata || meta.meta || {};
    const pick = (...keys) => {
        for (const k of keys) {
            for (const src of [meta, info]) {
                const v = src?.[k];
                if (v && v !== 'N/A') return v;
            }
        }
        return '';
    };
    const title = pick('title', 'Title') || name;
    const poster = posterUrl(pick('poster', 'Poster'));
    const year = pick('year', 'Year');
    const runtime = pick('runtime', 'Runtime');
    const genreRaw = pick('genre', 'Genre');
    const genres = genreRaw ? String(genreRaw).split(',').map(g => g.trim()).filter(Boolean).slice(0, 4) : [];
    const overview = pick('plot', 'Plot', 'overview', 'Overview');
    const prog = meta.progress || {};
    const cur = Number(prog.current_time || 0);
    const dur = Number(prog.duration || 0);
    const metaLine = [year, runtime, meta.size ? fmtSize(meta.size) : ''].filter(Boolean).join(' · ');
    const canRemux = kind === 'video' && REMUXABLE.includes(ext(path));
    const isWatched = !!(meta.watched || prog.watched || (dur > 0 && cur / dur >= 0.95));
    let inWatchlist = false;
    try {
        const wl = await api('/media/watchlist');
        inWatchlist = (wl.items || []).some(w => (w.path || w) === path);
    } catch {}
    const playLabel = cur > 30 ? `Resume · ${fmtTime(cur)}` : (kind === 'video' ? 'Play' : kind === 'audio' ? 'Play' : 'Open');

    body.innerHTML = `
      <div class="detail-art">
        ${poster ? `<img src="${escapeHtml(poster)}" alt="" onerror="this.remove()">` : ''}
        <button class="btn btn-icon detail-back" data-back aria-label="Back"><i class="ph ph-arrow-left"></i></button>
        <div class="detail-copy">
          <h1>${escapeHtml(title)}</h1>
          <div class="detail-meta">${escapeHtml(metaLine || ext(path).toUpperCase())}</div>
        </div>
      </div>

      <div class="detail-actions">
        <button class="btn btn-primary btn-lg" data-play="${escapeHtml(path)}" data-at="${cur}">
          <i class="ph-fill ph-play"></i> ${escapeHtml(playLabel)}
        </button>
        <button class="btn btn-icon${inWatchlist ? ' btn-primary' : ''}" data-watchlist="${escapeHtml(path)}"
                aria-pressed="${inWatchlist}" aria-label="Watchlist">
          <i class="${inWatchlist ? 'ph-fill' : 'ph'} ph-heart"></i>
        </button>
        <button class="btn btn-icon${isWatched ? ' btn-primary' : ''}" data-watched="${escapeHtml(path)}"
                aria-pressed="${isWatched}" aria-label="Mark watched">
          <i class="${isWatched ? 'ph-fill' : 'ph'} ph-check-circle"></i>
        </button>
      </div>

      ${dur > 0 && cur > 0 ? `<div class="detail-note">${escapeHtml(fmtLeft(dur - cur))} · ${Math.round((cur / dur) * 100)}% watched</div>` : ''}

      <div style="padding:18px 20px 0">
        ${genres.length ? `<div class="detail-tags">${genres.map(g => `<span class="tag">${escapeHtml(g)}</span>`).join('')}</div>` : ''}
        ${overview ? `<p class="detail-overview">${escapeHtml(overview)}</p>` : ''}
      </div>

      <div style="padding:24px 20px 0">
        <div class="kicker" style="margin-bottom:10px">File</div>
        <div class="card">
          <div class="facts">
            <div class="fact"><span class="fact-key">Type</span><span class="fact-val">${escapeHtml(ext(path).toUpperCase() || '—')}</span></div>
            ${meta.size ? `<div class="fact"><span class="fact-key">Size</span><span class="fact-val">${escapeHtml(fmtSize(meta.size))}</span></div>` : ''}
            <div class="fact"><span class="fact-key">Path</span><span class="fact-val" style="color:var(--text-70)">${escapeHtml(path)}</span></div>
            ${canRemux ? `
              <div class="facts-divider"></div>
              <button class="btn" id="remux-btn" ${S.remux?.path === path ? 'disabled' : `data-remux="${escapeHtml(path)}"`}>
                <i class="ph ph-arrows-clockwise" style="font-size:16px"></i><span>${
                  S.remux?.path === path ? `Converting — ${S.remux.pct}%` : 'Convert to MP4'}</span>
              </button>
              <div class="facts-note">Rewraps to MP4 for iPhone playback. No re-encode.</div>` : ''}
            <div class="facts-divider"></div>
            <button class="btn" data-download="${escapeHtml(path)}">
              <i class="ph ph-download-simple" style="font-size:16px"></i>Download file
            </button>
            ${kind === 'video' ? `
              <a class="btn" href="${escapeHtml(vlcUrl(path))}">
                <i class="ph ph-vinyl-record" style="font-size:16px"></i>Open in VLC
              </a>
              <div class="facts-note">VLC plays anything the browser will not — HEVC, DTS, odd containers.</div>` : ''}
          </div>
        </div>
      </div>`;
}

/* ── Remux ─────────────────────────────────────────────────────────────── */

let _remuxPoll = null;

async function startRemux(path) {
    const btn = $('#remux-btn');
    const label = btn?.querySelector('span');
    try {
        const data = await api(`/media/remux/start?path=${encodeURIComponent(path)}`, { method: 'POST' });
        if (data.status === 'unsupported') { toast(data.message || 'This file needs a full re-encode.', 'warn', 7000); return; }
        if (data.status === 'failed')      { toast(data.error || 'Convert failed', 'error'); return; }
        if (data.status === 'completed')   { toast('Already converted — playing MP4', 'success'); playVideo(data.output_path, 0); return; }

        if (btn) btn.disabled = true;
        toast('Converting in the background — you can keep browsing', 'info', 5000);
        S.remux = { job: data.job_id, path, pct: 0 };
        clearInterval(_remuxPoll);
        _remuxPoll = setInterval(async () => {
            let st;
            try { st = await api(`/media/remux/status?job_id=${encodeURIComponent(data.job_id)}`); }
            catch { return; }               // transient — keep polling

            S.remux.pct = Math.round(st.progress || 0);
            // The detail page may have been left; only paint if it is still there.
            const liveBtn = $('#remux-btn');
            const liveLabel = liveBtn?.querySelector('span');

            if (st.status === 'completed') {
                clearInterval(_remuxPoll); _remuxPoll = null;
                S.remux = null;
                if (liveBtn) {
                    liveBtn.disabled = false;
                    if (liveLabel) liveLabel.textContent = 'Play converted MP4';
                    delete liveBtn.dataset.remux;
                    liveBtn.dataset.play = st.output_path;
                    liveBtn.dataset.at = '0';
                }
                toast('Converted to MP4 ✓ — play it from the file card', 'success', 6000);
            } else if (st.status === 'failed') {
                clearInterval(_remuxPoll); _remuxPoll = null;
                S.remux = null;
                if (liveBtn) { liveBtn.disabled = false; if (liveLabel) liveLabel.textContent = 'Convert to MP4'; }
                toast(st.error || 'Convert failed', 'error', 6000);
            } else if (liveLabel) {
                liveLabel.textContent = `Converting — ${S.remux.pct}%`;
            }
        }, 2000);
    } catch (e) {
        toast(e.message || 'Convert failed', 'error');
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   Video player
   ══════════════════════════════════════════════════════════════════════════ */

const V = {
    el: null, path: null, url: null,
    stallTimer: null, reconnects: 0, saveTimer: null, seekTo: 0,
};
const MAX_RECONNECTS = 8;

function playVideo(path, at = 0) {
    const kind = kindOf(path);
    if (kind === 'audio') { playAudio(path); return; }
    if (kind !== 'video') {
        // Books, comics, PDFs and images all open in the in-app reader.
        openReader(path, at);
        return;
    }

    stopVideo();
    push('player');

    V.path = path;
    V.url = streamUrl(path);
    V.reconnects = 0;
    V.seekTo = Number(at) || 0;

    const title = stripExt(baseName(path));
    $('#player-title').textContent = title;
    $('#player-sub').textContent = ext(path).toUpperCase();

    const stage = $('#player-stage');
    $('#player-ghost')?.classList.add('hidden');

    const video = document.createElement('video');
    video.playsInline = true;
    video.setAttribute('playsinline', '');
    video.preload = 'metadata';
    video.src = V.url;
    video.autoplay = true;
    stage.insertBefore(video, stage.firstChild);
    V.el = video;

    video.addEventListener('loadedmetadata', () => {
        if (V.seekTo > 1 && V.seekTo < (video.duration || Infinity) - 5) {
            video.currentTime = V.seekTo;
        }
        updateScrub();
    }, { once: true });

    video.addEventListener('timeupdate', updateScrub);
    video.addEventListener('timeupdate', () => {
        if (!video.paused) throttledSession('playing');
    });
    video.addEventListener('play',  () => { setPlayIcon(true); requestWake(); throttledSession('playing', true); showChrome(); });
    video.addEventListener('pause', () => { setPlayIcon(false); releaseWake(); saveProgress(); throttledSession('paused', true); releaseChrome(); });
    video.addEventListener('ended', () => {
        setPlayIcon(false); saveProgress(true); throttledSession('stopped', true);
        if (typeof offerNextEpisode === 'function') offerNextEpisode(V.path);
    });

    // Stall detection → reconnect. 'waiting' fires on normal buffering too, so
    // only a stall that has not resolved after 10s is treated as a dead stream.
    video.addEventListener('waiting', () => {
        if (V.stallTimer || video.paused || video.ended) return;
        V.stallTimer = setTimeout(() => {
            V.stallTimer = null;
            if (!video.paused && !video.ended && video.readyState < 3) reconnectVideo();
        }, 10000);
    });
    const clearStall = () => { if (V.stallTimer) { clearTimeout(V.stallTimer); V.stallTimer = null; } };
    video.addEventListener('playing', () => {
        clearStall();
        if (V.reconnects > 0) { V.reconnects = 0; toast('Stream reconnected ✓', 'success', 2000); }
    });
    video.addEventListener('canplay', clearStall);
    video.addEventListener('pause', clearStall);

    video.addEventListener('error', () => {
        const err = video.error;
        if (!err) return;
        if (err.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED || err.code === MediaError.MEDIA_ERR_DECODE) {
            const canRemux = REMUXABLE.includes(ext(path));
            toast(canRemux ? "This format won't play here — try Convert to MP4 on the detail page."
                           : "This format can't be played in the browser.", 'warn', 8000);
        } else {
            reconnectVideo();
        }
    });

    video.play().catch(() => {});
    armChrome();
    clearInterval(V.saveTimer);
    V.saveTimer = setInterval(() => saveProgress(), 5000);
}

/* Controls fade after 3s of no input while playing, and come back on any
   tap, move or key. Without this, fullscreen showed the same permanent
   control slab and gained nothing. */
let _chromeTimer = null;

function showChrome() {
    const scr = $('#screen-player');
    if (!scr) return;
    scr.classList.remove('chrome-hidden');
    clearTimeout(_chromeTimer);
    _chromeTimer = setTimeout(() => {
        if (V.el && !V.el.paused && !document.querySelector('#next-ep')) {
            scr.classList.add('chrome-hidden');
        }
    }, 3000);
}

function armChrome() {
    const scr = $('#screen-player');
    if (!scr || scr._chromeBound) { showChrome(); return; }
    ['pointerdown', 'pointermove', 'keydown'].forEach(ev =>
        scr.addEventListener(ev, showChrome, { passive: true }));
    scr._chromeBound = true;
    showChrome();
}

function releaseChrome() {
    clearTimeout(_chromeTimer);
    _chromeTimer = null;
    $('#screen-player')?.classList.remove('chrome-hidden');
}

let _lastSession = 0;
function throttledSession(state, force = false) {
    const now = Date.now();
    if (!force && now - _lastSession < 5000) return;
    _lastSession = now;
    const v = V.el;
    if (!v || !V.path || typeof dashboardSession !== 'function') return;
    dashboardSession(V.path, stripExt(baseName(V.path)), state, v.currentTime, v.duration);
}

function reconnectVideo() {
    const video = V.el;
    if (!video) return;
    if (V.stallTimer) { clearTimeout(V.stallTimer); V.stallTimer = null; }
    if (V.reconnects >= MAX_RECONNECTS) {
        toast('Stream keeps dropping. Check the connection to the Pi.', 'error', 8000);
        return;
    }
    V.reconnects++;
    const at = video.currentTime;
    const wasPlaying = !video.paused;
    toast(`Stream dropped — reconnecting (${V.reconnects}/${MAX_RECONNECTS})…`, 'warn', 3000);
    video.src = `${V.url}&_r=${Date.now()}`;
    video.load();
    video.addEventListener('loadedmetadata', () => {
        if (at > 1) video.currentTime = at;
        if (wasPlaying) video.play().catch(() => {});
    }, { once: true });
}

function stopVideo() {
    releaseChrome();
    if (typeof cancelNextEpisode === 'function') cancelNextEpisode();
    clearInterval(V.saveTimer); V.saveTimer = null;
    if (V.stallTimer) { clearTimeout(V.stallTimer); V.stallTimer = null; }
    if (V.el) {
        saveProgress();
        V.el.pause();
        V.el.removeAttribute('src');
        V.el.load();
        V.el.remove();
        V.el = null;
    }
    $('#player-ghost')?.classList.remove('hidden');
    releaseWake();
    if (V.path) throttledSession('stopped', true);
    V.path = null;
}

function setPlayIcon(playing) {
    const i = $('#player-play i');
    if (i) i.className = playing ? 'ph-fill ph-pause' : 'ph-fill ph-play';
}

function updateScrub() {
    const v = V.el;
    if (!v || !v.duration || !isFinite(v.duration)) return;
    const pct = (v.currentTime / v.duration) * 100;
    $('#player-fill').style.width = `${pct}%`;
    $('#player-knob').style.left = `${pct}%`;
    $('#player-elapsed').textContent = fmtTime(v.currentTime);
    $('#player-remaining').textContent = `-${fmtTime(v.duration - v.currentTime)}`;
}

async function saveProgress(finished = false) {
    const v = V.el;
    if (!v || !V.path || !v.duration || !isFinite(v.duration)) return;
    try {
        await fetch(`${API}/media/progress`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: V.path,
                current_time: finished ? v.duration : v.currentTime,
                duration: v.duration,
            }),
            keepalive: true,
        });
    } catch {}
}

let _wakeLock = null;
async function requestWake() {
    try { if ('wakeLock' in navigator) _wakeLock = await navigator.wakeLock.request('screen'); } catch {}
}
function releaseWake() {
    try { _wakeLock?.release(); } catch {}
    _wakeLock = null;
}

/* ══════════════════════════════════════════════════════════════════════════
   Audio — mini player + now playing sheet
   ══════════════════════════════════════════════════════════════════════════ */

function playAudio(path) {
    const a = S.audio;
    if (!a.el) {
        a.el = new Audio();
        a.el.addEventListener('timeupdate', updateNP);
        a.el.addEventListener('play',  () => { a.playing = true;  setAudioIcons(); });
        a.el.addEventListener('pause', () => { a.playing = false; setAudioIcons(); });
        a.el.addEventListener('ended', () => nextTrack());
    }
    a.el.src = streamUrl(path);
    a.el.play().catch(() => {});
    const title = stripExt(baseName(path));
    $('#mini-title').textContent = title;
    const q = S.audio.queue;
    $('#mini-sub').textContent = q.length > 1
        ? `${S.audio.index + 1} of ${q.length}` : 'Nomad Pi';
    $('#np-title').textContent = title;
    $('#np-artist').textContent = 'Nomad Pi';
    $('#mini-player').classList.remove('hidden');
    if (S.screen === 'player') $('#mini-player').style.bottom = '20px';
    updateMediaSession(title);
}

function stopAudio() {
    const a = S.audio;
    if (a.el) { a.el.pause(); a.el.removeAttribute('src'); }
    a.playing = false;
    $('#mini-player').classList.add('hidden');
    $('#now-playing-sheet').classList.add('hidden');
}

function toggleAudio() {
    const a = S.audio;
    if (!a.el) return;
    if (a.el.paused) a.el.play().catch(() => {}); else a.el.pause();
}

function nextTrack() {
    const a = S.audio;
    if (a.queue.length && a.index < a.queue.length - 1) {
        a.index++;
        playAudio(a.queue[a.index]);
    } else {
        a.playing = false;
        setAudioIcons();
    }
}
function prevTrack() {
    const a = S.audio;
    if (a.queue.length && a.index > 0) { a.index--; playAudio(a.queue[a.index]); }
    else if (a.el) a.el.currentTime = 0;
}

function setAudioIcons() {
    const cls = S.audio.playing ? 'ph-fill ph-pause' : 'ph-fill ph-play';
    const m = $('#mini-play i'); if (m) m.className = cls;
    const n = $('#np-play i');   if (n) n.className = cls;
}

function updateNP() {
    const a = S.audio.el;
    if (!a || !a.duration || !isFinite(a.duration)) return;
    const pct = (a.currentTime / a.duration) * 100;
    $('#np-fill').style.width = `${pct}%`;
    $('#np-knob').style.left = `${pct}%`;
    $('#np-elapsed').textContent = fmtTime(a.currentTime);
    $('#np-remaining').textContent = `-${fmtTime(a.duration - a.currentTime)}`;
}

function updateMediaSession(title) {
    if (!('mediaSession' in navigator)) return;
    try {
        navigator.mediaSession.metadata = new MediaMetadata({ title, artist: 'Nomad Pi' });
        navigator.mediaSession.setActionHandler('play',  () => toggleAudio());
        navigator.mediaSession.setActionHandler('pause', () => toggleAudio());
        navigator.mediaSession.setActionHandler('nexttrack', () => nextTrack());
        navigator.mediaSession.setActionHandler('previoustrack', () => prevTrack());
    } catch {}
}

/* ══════════════════════════════════════════════════════════════════════════
   Downloads
   ══════════════════════════════════════════════════════════════════════════ */

const DL_TABS = [
    { key: 'active', label: 'Active' },
    { key: 'find',   label: 'Find' },
];

function renderDlTabs() {
    $('#dl-tabs').innerHTML = DL_TABS.map(t =>
        `<button class="chip${t.key === S.dl ? ' active' : ''}" data-dl="${t.key}">${escapeHtml(t.label)}</button>`
    ).join('');
}

async function loadDownloads() {
    renderDlTabs();
    const body = $('#dl-body');
    if (S.dl === 'active') return renderActiveDownloads(body);
    return renderFind(body);
}

async function renderActiveDownloads(body) {
    body.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        const data = await api('/debrid/downloads');
        const list = data.downloads || [];
        if (!list.length) {
            body.innerHTML = `<div class="empty"><i class="ph ph-arrow-circle-down"></i>No downloads running.<br>Use <strong>Find</strong> to search your debrid provider.</div>`;
            return;
        }
        const free = S.stats?.disk_free ? `${fmtSize(S.stats.disk_free)} free` : '';
        body.innerHTML = `
          <div class="list" style="gap:12px">
            ${list.map(d => {
                const pct = Math.round(Number(d.progress || 0));
                const done = (d.status || '') === 'completed';
                const failed = (d.status || '') === 'error' || (d.status || '') === 'failed';
                const speed = d.speed ? `${fmtSize(d.speed)}/s` : '';
                const status = failed ? (d.error || 'Failed') : done ? 'Complete' : (speed || d.status || '');
                return `
                  <div class="dl-card">
                    <div class="dl-top">
                      <div style="min-width:0;flex:1">
                        <div class="dl-title">${escapeHtml(d.filename || d.name || 'Download')}</div>
                        <div class="dl-meta">${escapeHtml(d.category ? `→ /data/${d.category}` : '')}</div>
                      </div>
                      ${!done ? `<button class="btn btn-icon btn-icon-plain" data-dlcancel="${escapeHtml(d.id || '')}" aria-label="Cancel"><i class="ph ph-x"></i></button>` : ''}
                    </div>
                    <div class="bar" style="margin-top:10px"><span style="width:${pct}%"></span></div>
                    <div class="dl-stats"><span>${pct}%</span><span>${escapeHtml(status)}</span></div>
                  </div>`;
            }).join('')}
          </div>
          <div class="rule" style="margin:16px 0"></div>
          <div class="dl-foot">Pulling to the Pi at /data${free ? ` · ${escapeHtml(free)}` : ''}</div>`;
    } catch (e) {
        body.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Could not load downloads')}</div>`;
    }
}

/* Find is two steps: look the title up on Cinemeta for its IMDb id, then ask
   the provider for cached torrents against that id. */

async function renderFind(body) {
    const q = S.debrid.query;
    body.innerHTML = `
      <div class="search-field" style="margin-bottom:12px">
        <i class="ph ph-magnifying-glass"></i>
        <input type="search" id="debrid-query" class="input" placeholder="Film or show title"
               value="${escapeHtml(q)}" autocomplete="off" spellcheck="false">
      </div>
      <div id="debrid-results">
        ${S.debrid.title ? '' : '<div class="empty"><i class="ph ph-magnifying-glass"></i>Search for a film or show, then pick a release to pull to the Pi.</div>'}
      </div>`;
    const input = $('#debrid-query');
    input?.addEventListener('keydown', e => { if (e.key === 'Enter') searchTitles(input.value.trim()); });
    if (S.debrid.title) renderTorrents();
}

async function searchTitles(q) {
    S.debrid.query = q;
    const out = $('#debrid-results');
    if (!q || !out) return;
    out.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        const data = await api(`/debrid/search/title?q=${encodeURIComponent(q)}`);
        const list = data.results || [];
        if (!list.length) {
            out.innerHTML = `<div class="empty"><i class="ph ph-empty"></i>Nothing found for “${escapeHtml(q)}”.</div>`;
            return;
        }
        S.debrid.titles = list;
        out.innerHTML = `
          <div class="kicker" style="margin-bottom:10px">${list.length} title${list.length === 1 ? '' : 's'}</div>
          <div class="list">
            ${list.map((t, i) => `
              <button class="list-row row-rule" data-title="${i}">
                <div class="list-thumb list-thumb-poster">
                  ${t.poster ? `<img src="${escapeHtml(t.poster)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:6px" onerror="this.remove()">`
                             : `<i class="ph ph-film-slate"></i>`}
                </div>
                <div class="list-body">
                  <div class="list-title">${escapeHtml(t.title || '')}</div>
                  <div class="list-sub">${escapeHtml(String(t.year || ''))}${t.type === 'series' ? ' · Series' : ''}</div>
                </div>
                <i class="ph ph-caret-right list-caret"></i>
              </button>`).join('')}
          </div>`;
    } catch (e) {
        out.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Search failed')}</div>`;
    }
}

async function pickTitle(index) {
    const t = (S.debrid.titles || [])[index];
    if (!t) return;
    S.debrid.title = t;
    renderTorrents();
}

async function renderTorrents() {
    const t = S.debrid.title;
    const out = $('#debrid-results');
    if (!t || !out) return;
    const mediaType = t.type === 'series' ? 'series' : 'movie';
    out.innerHTML = `
      <button class="btn" id="debrid-back" style="margin-bottom:12px"><i class="ph ph-arrow-left"></i>${escapeHtml(t.title || '')}</button>
      <div class="empty"><div class="spinner"></div></div>`;
    $('#debrid-back')?.addEventListener('click', () => {
        S.debrid.title = null;
        searchTitles(S.debrid.query);
    });

    try {
        const qs = new URLSearchParams({ imdb_id: t.imdb_id || '', media_type: mediaType });
        if (mediaType === 'series') { qs.set('season', '1'); qs.set('episode', '1'); }
        const data = await api(`/debrid/search/torrents?${qs}`);
        const list = data.results || data.torrents || [];
        S.debrid.results = list;
        const head = `<button class="btn" id="debrid-back2" style="margin-bottom:12px"><i class="ph ph-arrow-left"></i>${escapeHtml(t.title || '')}</button>`;
        if (!list.length) {
            out.innerHTML = `${head}<div class="empty"><i class="ph ph-empty"></i>No cached releases available.</div>`;
        } else {
            out.innerHTML = `
              ${head}
              <div class="kicker" style="margin-bottom:10px">${list.length} release${list.length === 1 ? '' : 's'}</div>
              <div class="list">
                ${list.map((r, i) => `
                  <div class="torrent row-rule">
                    <div class="torrent-name">${escapeHtml(r.name || 'Unknown release')}</div>
                    <div class="torrent-row">
                      ${r.quality ? `<span class="tag tag-accent">${escapeHtml(r.quality)}</span>` : ''}
                      ${r.codec ? `<span class="tag">${escapeHtml(r.codec)}</span>` : ''}
                      <span class="torrent-size">${escapeHtml(r.size || '')}</span>
                      <span class="spacer"></span>
                      <button class="btn btn-primary" data-grab="${i}">To Pi</button>
                    </div>
                  </div>`).join('')}
              </div>`;
        }
        $('#debrid-back2')?.addEventListener('click', () => {
            S.debrid.title = null;
            searchTitles(S.debrid.query);
        });
    } catch (e) {
        out.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Could not load releases')}</div>`;
    }
}

/* Grabbing a release is a three-step chain, not one call:
     1. /debrid/magnet   — adds it to the provider and returns restricted links
     2. /debrid/unrestrict — turns a link into a direct URL
     3. /debrid/download   — tells the Pi to actually fetch that URL
   Stopping after step 1 (as this used to) leaves the file sitting on the
   provider with nothing queued on the Pi and no error to show for it. */

async function grabTorrent(index) {
    const r = (S.debrid.results || [])[index];
    const t = S.debrid.title;
    if (!r || !r.info_hash) { toast('That release has no usable hash', 'error'); return; }

    const isShow = !!(t && t.type === 'series');
    openSheet(`
      <div class="kicker" style="margin-bottom:10px">Adding to the Pi</div>
      <div style="font-size:14px;line-height:1.5;margin-bottom:14px;word-break:break-word">${escapeHtml(r.name || '')}</div>
      <div class="bar bar-lg"><span id="grab-bar" style="width:8%"></span></div>
      <div id="grab-status" style="font-size:13px;color:var(--text-70);margin-top:10px">Asking the provider for this release…</div>`);

    const setStatus = (msg, pct) => {
        const s = $('#grab-status'), b = $('#grab-bar');
        if (s) s.textContent = msg;
        if (b && pct != null) b.style.width = `${pct}%`;
    };

    try {
        const m = await api('/debrid/magnet', {
            method: 'POST',
            body: JSON.stringify({
                info_hash: r.info_hash,
                title: (t && t.title) || r.name || '',
                year: String((t && t.year) || ''),
                media_type: isShow ? 'series' : 'movie',
                season: 0, episode: 0,
            }),
        });

        const links = m.links || [];
        if (!links.length) {
            const why = m.status === 'processing'
                ? 'The provider is still caching this release. It is not instantly available — try a cached result, or add it again in a few minutes.'
                : (m.message || 'The provider returned no downloadable links for this release.');
            setStatus(why, 100);
            $('#grab-bar').style.background = 'var(--color-accent-400)';
            toast('Nothing to download yet', 'warn', 7000);
            return;
        }

        setStatus(`Resolving ${links.length} file${links.length === 1 ? '' : 's'}…`, 35);

        let queued = 0, failed = 0;
        for (let i = 0; i < links.length; i++) {
            try {
                const u = await api('/debrid/unrestrict', {
                    method: 'POST', body: JSON.stringify({ link: links[i] }),
                });
                if (!u.url) { failed++; continue; }
                await api('/debrid/download', {
                    method: 'POST',
                    body: JSON.stringify({
                        url: u.url,
                        filename: u.filename || m.filename || r.name || 'download',
                        category: isShow ? 'shows' : 'movies',
                        is_show: isShow,
                    }),
                });
                queued++;
            } catch { failed++; }
            setStatus(`Queued ${queued} of ${links.length}…`, 35 + Math.round((i + 1) / links.length * 60));
        }

        if (queued) {
            closeSheet();
            toast(`${queued} file${queued === 1 ? '' : 's'} downloading to the Pi`, 'success', 5000);
            S.dl = 'active';
            goTab('downloads');
        } else {
            setStatus(`Could not start any downloads (${failed} failed). Check the provider key in Server › API keys.`, 100);
            toast('Download could not be started', 'error', 7000);
        }
    } catch (e) {
        setStatus(e.message || 'Could not add that release.', 100);
        toast(e.message || 'Could not add that release', 'error', 7000);
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   Server
   ══════════════════════════════════════════════════════════════════════════ */

async function loadServer() {
    const body = $('#server-body');
    body.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;

    let s = {};
    try { s = await api('/system/stats'); S.stats = s; } catch {}
    let status = {};
    try { status = await api('/system/status'); } catch {}

    $('#server-name').textContent = s.hostname || 'Nomad Pi';
    $('#server-sub').textContent = [
        location.host,
        status.version ? `v${status.version}` : '',
        fmtUptime(s.uptime),
    ].filter(Boolean).join(' · ');

    const diskPct = Math.round(Number(s.disk_percent || 0));
    const memPct = Math.round(Number(s.memory_percent || 0));
    const cpu = Math.round(Number(s.cpu || 0));
    const temp = s.temp ? Math.round(s.temp) : null;

    body.innerHTML = `
      <div class="stat-grid">
        <div class="stat">
          <div class="stat-label">Storage</div>
          <div class="stat-value">${escapeHtml(fmtSize(s.disk_free) || '—')}</div>
          <div class="bar"><span style="width:${diskPct}%"></span></div>
          <div class="stat-note">of ${escapeHtml(fmtSize(s.disk_total) || '—')} free</div>
        </div>
        <div class="stat">
          <div class="stat-label">Temp</div>
          <div class="stat-value">${temp != null ? `${temp}°C` : '—'}</div>
          <div class="bar"><span style="width:${temp ? Math.min(100, (temp / 90) * 100) : 0}%"></span></div>
          <div class="stat-note">${temp == null ? 'not reported' : temp >= 80 ? 'throttling likely' : temp >= 70 ? 'running warm' : 'normal range'}</div>
        </div>
        <div class="stat">
          <div class="stat-label">CPU</div>
          <div class="stat-value">${cpu}%</div>
          <div class="bar"><span style="width:${cpu}%"></span></div>
          <div class="stat-note">${s.cores ? `${s.cores} cores` : ''}</div>
        </div>
        <div class="stat">
          <div class="stat-label">RAM</div>
          <div class="stat-value">${escapeHtml(fmtSize(s.memory_used) || '—')}</div>
          <div class="bar"><span style="width:${memPct}%"></span></div>
          <div class="stat-note">of ${escapeHtml(fmtSize(s.memory_total) || '—')} used</div>
        </div>
      </div>

      <div class="card card-lg" style="margin-top:22px">
        <div class="health-head">
          <div>
            <div class="health-title">Health check</div>
            <div class="health-note" id="health-note">DNS, disk, temperature, tools</div>
          </div>
          <button class="btn btn-primary" id="health-run" style="min-height:44px;flex:none">Run</button>
        </div>
        <div id="health-results"></div>
      </div>

      <div style="margin-top:24px">
        <div class="kicker" style="margin-bottom:6px">Network</div>
        <div class="list">
          <button class="list-row list-row-tall row-rule" data-admin="wifi">
            <i class="ph ph-wifi-high list-icon"></i>
            <div class="list-body"><div class="list-title">Wi-Fi</div></div>
            <span class="list-value" id="net-wifi">—</span>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="tailscale">
            <i class="ph ph-shield-check list-icon"></i>
            <div class="list-body"><div class="list-title">Tailscale</div></div>
            <span class="list-value" id="net-ts">—</span>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
        </div>
      </div>

      <div style="margin-top:24px">
        <div class="kicker" style="margin-bottom:6px">Library maintenance</div>
        <div class="list">
          <button class="list-row list-row-tall row-rule" data-act="scan">
            <i class="ph ph-arrows-clockwise list-icon"></i>
            <div class="list-body"><div class="list-title">Scan library</div><div class="list-sub">Index new and changed files</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="organize">
            <i class="ph ph-folders list-icon"></i>
            <div class="list-body"><div class="list-title">Organize media</div><div class="list-sub">Preview or apply moves and renames</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="duplicates">
            <i class="ph ph-copy list-icon"></i>
            <div class="list-body"><div class="list-title">Find duplicates</div><div class="list-sub">By name, size, or IMDb ID</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="upload">
            <i class="ph ph-upload-simple list-icon"></i>
            <div class="list-body"><div class="list-title">Upload from phone</div><div class="list-sub">Photos, video, or any file</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="storage">
            <i class="ph ph-hard-drive list-icon"></i>
            <div class="list-body"><div class="list-title">Storage &amp; drives</div><div class="list-sub">Mount, eject and free space</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
        </div>
      </div>

      <div style="margin-top:24px">
        <div class="kicker" style="margin-bottom:6px">People &amp; data</div>
        <div class="list">
          <button class="list-row list-row-tall row-rule" data-admin="users">
            <i class="ph ph-users-three list-icon"></i>
            <div class="list-body"><div class="list-title">Users</div><div class="list-sub">Accounts and administrators</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="backup">
            <i class="ph ph-file-archive list-icon"></i>
            <div class="list-body"><div class="list-title">Backup &amp; restore</div><div class="list-sub">Database, mounts and settings</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="keys">
            <i class="ph ph-key list-icon"></i>
            <div class="list-body"><div class="list-title">API keys</div><div class="list-sub">OMDb, OpenSubtitles, Debrid</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
          <button class="list-row list-row-tall row-rule" data-admin="logs">
            <i class="ph ph-file-text list-icon"></i>
            <div class="list-body"><div class="list-title">Server logs</div><div class="list-sub">Recent journal output</div></div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>
        </div>
      </div>

      <div style="margin-top:26px;display:flex;flex-direction:column;gap:8px">
        <button class="btn btn-primary btn-block" data-act="update" style="min-height:48px">
          <i class="ph ph-cloud-arrow-down" style="font-size:17px"></i>Update from GitHub
        </button>
        <div class="btn-row">
          <button class="btn" data-act="reboot" style="min-height:48px"><i class="ph ph-arrow-clockwise" style="font-size:16px"></i>Reboot</button>
          <button class="btn" data-act="shutdown" style="min-height:48px"><i class="ph ph-power" style="font-size:16px"></i>Shut down</button>
        </div>
        <button class="btn btn-block" data-go="settings" style="min-height:48px;margin-top:6px">
          <i class="ph ph-user-circle" style="font-size:17px"></i>Your profile &amp; app settings
        </button>
      </div>`;

    if (S.health) renderHealth(S.health);
    loadNetworkRows();
}

async function loadNetworkRows() {
    try {
        const w = await api('/system/wifi/info');
        $('#net-wifi').textContent = w.mode === 'hotspot' ? 'Hotspot' : (w.ssid || 'Not connected');
    } catch { $('#net-wifi').textContent = '—'; }
    try {
        const t = await api('/system/tailscale/status');
        $('#net-ts').textContent = t.connected ? 'Connected' : (t.message ? 'Off' : 'Off');
    } catch { $('#net-ts').textContent = '—'; }
}

async function runHealthCheck() {
    if (S.healthRunning) return;
    S.healthRunning = true;
    const btn = $('#health-run');
    const out = $('#health-results');
    if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
    out.innerHTML = `<div style="margin-top:13px"><div class="spinner"></div></div>`;
    try {
        const data = await api('/system/diagnostics');
        S.health = data;
        renderHealth(data);
    } catch (e) {
        out.innerHTML = `<div class="health-results"><div class="health-item"><i class="ph-fill ph-x-circle health-fail"></i><div><div class="health-label">Health check failed</div><div class="health-detail">${escapeHtml(e.message || '')}</div></div></div></div>`;
    } finally {
        S.healthRunning = false;
        if (btn) { btn.disabled = false; btn.textContent = 'Re-run'; }
    }
}

function renderHealth(data) {
    const out = $('#health-results');
    const note = $('#health-note');
    if (!out) return;
    const checks = data.checks || [];
    const bad = checks.filter(c => c.status === 'fail').length;
    const warn = checks.filter(c => c.status === 'warn').length;
    if (note) {
        note.textContent = bad ? `${bad} problem${bad === 1 ? '' : 's'} found`
                         : warn ? `${warn} thing${warn === 1 ? '' : 's'} worth a look`
                         : 'Everything looks healthy';
    }
    const icon = { ok: 'ph-fill ph-check-circle health-ok', warn: 'ph-fill ph-warning-circle health-warn',
                   fail: 'ph-fill ph-x-circle health-fail', info: 'ph-fill ph-info health-ok' };
    out.innerHTML = `<div class="health-results">${checks.map(c => `
        <div class="health-item">
          <i class="${icon[c.status] || icon.info}"></i>
          <div>
            <div class="health-label">${escapeHtml(c.name)}</div>
            <div class="health-detail">${escapeHtml(c.message)}</div>
          </div>
        </div>`).join('')}</div>`;
}

async function serverAction(act) {
    if (act === 'scan') {
        try { await api('/media/scan', { method: 'POST' }); toast('Library scan started', 'success'); }
        catch (e) { toast(e.message || 'Could not start scan', 'error'); }
        return;
    }
    if (act === 'duplicates') {
        try {
            const d = await api('/media/duplicates');
            const n = (d.file_duplicates?.length || 0) + (d.content_duplicates?.length || 0);
            toast(n ? `${n} duplicate group${n === 1 ? '' : 's'} found` : 'No duplicates found', n ? 'warn' : 'success', 6000);
        } catch (e) { toast(e.message || 'Scan failed', 'error'); }
        return;
    }
    if (act === 'storage') {
        try {
            const d = await api('/system/storage/info');
            const disks = d.disks || [];
            openSheet(`
              <div class="kicker" style="margin-bottom:10px">Storage &amp; drives</div>
              <div class="list">
                ${disks.length ? disks.map(x => `
                  <div class="list-row row-rule">
                    <i class="ph ph-hard-drive list-icon"></i>
                    <div class="list-body">
                      <div class="list-title">${escapeHtml(x.mountpoint || x.device || 'Drive')}</div>
                      <div class="list-sub">${escapeHtml(fmtSize(x.free))} free of ${escapeHtml(fmtSize(x.total))}</div>
                    </div>
                  </div>`).join('') : '<div class="empty">No drives reported.</div>'}
              </div>`);
        } catch (e) { toast(e.message || 'Could not read storage', 'error'); }
        return;
    }
    if (act === 'update') {
        const ok = await confirmDialog('Update from GitHub?',
            'The server pulls the latest version, installs dependencies and restarts. It will be unavailable for a minute or two.', 'Update');
        if (!ok) return;
        try {
            await api('/system/control/update', { method: 'POST' });
            openUpdateProgress();
        } catch (e) { toast(e.message || 'Update failed to start', 'error'); }
        return;
    }
    if (act === 'reboot' || act === 'shutdown') {
        const isShut = act === 'shutdown';
        const ok = await confirmDialog(
            isShut ? 'Shut down the Pi?' : 'Reboot the Pi?',
            isShut ? 'Playback and any active downloads will stop. You will need physical access to power it back on.'
                   : 'Playback and any active downloads will stop. The server comes back in about 40 seconds.',
            isShut ? 'Shut down' : 'Reboot');
        if (!ok) return;
        try {
            await api(`/system/control/${act}`, { method: 'POST' });
            toast(isShut ? 'Shutting down…' : 'Rebooting…', 'info', 8000);
        } catch (e) { toast(e.message || 'Command failed', 'error'); }
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   Search
   ══════════════════════════════════════════════════════════════════════════ */

let _searchTimer = null;

async function runSearch(q) {
    const body = $('#search-body');
    if (!q || q.length < 2) {
        body.innerHTML = `<div class="empty"><i class="ph ph-magnifying-glass"></i>Type at least two characters.</div>`;
        return;
    }
    body.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        const data = await api(`/media/search?q=${encodeURIComponent(q)}&limit=40`);
        const results = data.results || [];
        if (!results.length) {
            body.innerHTML = `<div class="empty"><i class="ph ph-empty"></i>Nothing matches “${escapeHtml(q)}”.</div>`;
            return;
        }
        const iconFor = c => ({ movies: 'ph ph-film-slate', shows: 'ph ph-television', music: 'ph ph-music-note',
                                books: 'ph ph-book-open', gallery: 'ph ph-images' }[c] || 'ph ph-file');
        body.innerHTML = `
          <div class="kicker" style="margin-bottom:10px">${results.length} match${results.length === 1 ? '' : 'es'}</div>
          <div class="list">
            ${results.map(r => `
              <button class="list-row row-rule" data-open="${escapeHtml(r.path)}">
                <div class="list-thumb list-thumb-poster"><i class="${escapeHtml(iconFor(r.category))}"></i></div>
                <div class="list-body">
                  <div class="list-title">${escapeHtml(stripExt(r.title || r.name || baseName(r.path)))}</div>
                  <div class="list-sub">${escapeHtml(r.category || '')}${r.year ? ` · ${escapeHtml(String(r.year))}` : ''}</div>
                </div>
                <i class="ph ph-caret-right list-caret"></i>
              </button>`).join('')}
          </div>`;
    } catch (e) {
        body.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Search failed')}</div>`;
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   Install (PWA)
   ══════════════════════════════════════════════════════════════════════════ */

let _installPrompt = null;

const isStandalone = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;

const isIOS = () =>
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

function canOfferInstall() {
    return !isStandalone() && (!!_installPrompt || isIOS());
}

async function runInstall() {
    if (_installPrompt) {
        _installPrompt.prompt();
        try {
            const { outcome } = await _installPrompt.userChoice;
            if (outcome === 'accepted') toast('Installing Nomad Pi…', 'success');
        } catch {}
        _installPrompt = null;
        loadSettings();
        return;
    }
    if (isIOS()) {
        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Add to Home Screen</div>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:var(--text-70)">
            iOS installs web apps from the Share menu rather than a prompt.
          </p>
          <div class="list">
            <div class="list-row row-rule">
              <i class="ph ph-export list-icon"></i>
              <div class="list-body"><div class="list-title">1 · Tap Share</div>
              <div class="list-sub">The square with an arrow, in the Safari toolbar</div></div>
            </div>
            <div class="list-row row-rule">
              <i class="ph ph-plus-square list-icon"></i>
              <div class="list-body"><div class="list-title">2 · Add to Home Screen</div>
              <div class="list-sub">Scroll down the share sheet to find it</div></div>
            </div>
            <div class="list-row row-rule">
              <i class="ph ph-check list-icon"></i>
              <div class="list-body"><div class="list-title">3 · Add</div>
              <div class="list-sub">Nomad Pi opens full screen, without the browser bars</div></div>
            </div>
          </div>`);
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   Settings
   ══════════════════════════════════════════════════════════════════════════ */

function loadSettings() {
    const p = S.profile || {};
    const name = p.name || p.username || 'You';
    const initials = name.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
    $('#settings-body').innerHTML = `
      <div style="display:flex;align-items:center;gap:13px;padding-bottom:18px" class="row-rule">
        <div style="width:52px;height:52px;border-radius:50%;background:var(--color-neutral-800);display:flex;align-items:center;justify-content:center;font-weight:500;font-size:18px">${escapeHtml(initials)}</div>
        <div>
          <div style="font-weight:500;font-size:16px">${escapeHtml(name)}</div>
          <div style="font-size:12px;color:var(--text-50);margin-top:2px">${Number(p.parental_controls || 0) ? 'Restricted profile' : 'All access'}</div>
        </div>
      </div>
      <div class="list" style="margin-top:18px">
        ${canOfferInstall() ? `
          <button class="list-row list-row-tall row-rule" data-set="install">
            <i class="ph ph-device-mobile list-icon"></i>
            <div class="list-body">
              <div class="list-title">Install Nomad Pi</div>
              <div class="list-sub">Run full screen, without the browser bars</div>
            </div>
            <i class="ph ph-caret-right list-caret"></i>
          </button>` : ''}
        ${isStandalone() ? `
          <div class="list-row list-row-tall row-rule">
            <i class="ph ph-check-circle list-icon" style="color:var(--color-accent)"></i>
            <div class="list-body"><div class="list-title">Installed</div>
            <div class="list-sub">Running as an app on this device</div></div>
          </div>` : ''}
        <button class="list-row list-row-tall row-rule" data-set="password">
          <i class="ph ph-lock-key list-icon"></i>
          <div class="list-body"><div class="list-title">Change password</div></div>
          <i class="ph ph-caret-right list-caret"></i>
        </button>
        <div class="list-row list-row-tall row-rule">
          <i class="ph ph-info list-icon"></i>
          <div class="list-body"><div class="list-title">About</div></div>
          <span class="list-value" id="about-version">—</span>
        </div>
      </div>
      <button class="btn btn-block" id="signout-btn" style="margin-top:24px;min-height:48px">Sign out</button>`;

    api('/system/status').then(s => {
        const el = $('#about-version');
        if (el && s.version) el.textContent = `v${s.version}`;
    }).catch(() => {});
}

function openPasswordSheet() {
    openSheet(`
      <div class="kicker" style="margin-bottom:12px">Change password</div>
      <div style="display:flex;flex-direction:column;gap:10px">
        <input type="password" class="input input-plain" id="pw-current" placeholder="Current password" autocomplete="current-password">
        <input type="password" class="input input-plain" id="pw-new" placeholder="New password" autocomplete="new-password">
        <input type="password" class="input input-plain" id="pw-confirm" placeholder="Confirm new password" autocomplete="new-password">
        <div id="pw-status" style="font-size:12.5px;color:var(--text-45);min-height:18px"></div>
        <button class="btn btn-primary btn-block" id="pw-save" style="min-height:48px">Update password</button>
      </div>`);

    $('#pw-save').addEventListener('click', async () => {
        const cur = $('#pw-current').value;
        const nw = $('#pw-new').value;
        const cf = $('#pw-confirm').value;
        const st = $('#pw-status');
        if (!cur || !nw || !cf) { st.textContent = 'Fill in all three fields.'; return; }
        if (nw !== cf) { st.textContent = 'New passwords do not match.'; return; }
        st.textContent = 'Updating…';
        try {
            await api('/auth/change-password', {
                method: 'POST',
                body: JSON.stringify({ current_password: cur, new_password: nw }),
            });
            closeSheet();
            toast('Password updated', 'success');
        } catch (e) {
            st.textContent = e.message || 'Could not update password.';
        }
    });
}

/* ══════════════════════════════════════════════════════════════════════════
   Delegated events
   ══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-tab],[data-go],[data-back],[data-quick],[data-open],[data-play],[data-lib],[data-sort],[data-view],[data-dl],[data-title],[data-grab],[data-dlcancel],[data-act],[data-net],[data-set],[data-remux],[data-download],[data-watchlist],[data-watched]');
    if (!t) return;

    if (t.dataset.back !== undefined) { back(); return; }
    if (t.dataset.tab)  { goTab(t.dataset.tab); return; }

    if (t.dataset.go === 'search') {
        push('search');
        setTimeout(() => $('#search-input')?.focus(), 60);
        return;
    }
    if (t.dataset.go === 'settings') { push('settings'); loadSettings(); return; }

    if (t.dataset.open) {
        const p = t.dataset.open;
        // Audio in a library list plays straight away and queues its siblings
        if (S.screen === 'library' && kindOf(p, S.lib) === 'audio') {
            const tracks = sortedLibItems().map(i => i.path).filter(x => kindOf(x, S.lib) === 'audio');
            S.audio.queue = tracks;
            S.audio.index = Math.max(0, tracks.indexOf(p));
            playAudio(p);
            return;
        }
        openDetail(p);
        return;
    }
    if (t.dataset.play) { playVideo(t.dataset.play, Number(t.dataset.at || 0)); return; }

    if (t.dataset.quick) {
        const k = t.dataset.quick;
        if (k === 'files') { goTab('library'); renderLibTabs(); openFiles('/data'); return; }
        S.lib = k; S.libView = 'grid'; goTab('library'); return;
    }
    if (t.dataset.lib) {
        if (t.dataset.lib === 'files') { renderLibTabs(); openFiles('/data'); return; }
        S.lib = t.dataset.lib; S.libView = 'grid'; loadLibrary(); return;
    }
    if (t.dataset.sort) { S.libSort = t.dataset.sort; closeSheet(); renderLibItems(); $('#lib-sort-label').textContent = SORTS.find(s => s.key === S.libSort)?.label.replace(/ \(.*\)/, ''); return; }
    if (t.dataset.view) { S.libView = t.dataset.view; closeSheet(); renderLibItems(); return; }

    if (t.dataset.dl) { S.dl = t.dataset.dl; loadDownloads(); return; }
    if (t.dataset.title) { pickTitle(Number(t.dataset.title)); return; }
    if (t.dataset.grab) { grabTorrent(Number(t.dataset.grab)); return; }
    if (t.dataset.dlcancel) {
        try { await api(`/debrid/download/${encodeURIComponent(t.dataset.dlcancel)}`, { method: 'DELETE' }); loadDownloads(); }
        catch (err) { toast(err.message || 'Could not cancel', 'error'); }
        return;
    }

    if (t.dataset.act) { serverAction(t.dataset.act); return; }
    if (t.dataset.net) { toast('Manage this from the Server tab on a desktop browser for now.', 'info'); return; }
    if (t.dataset.set === 'password') { openPasswordSheet(); return; }
    if (t.dataset.set === 'install') { runInstall(); return; }

    if (t.dataset.remux) { startRemux(t.dataset.remux); return; }
    if (t.dataset.download) { downloadFile(t.dataset.download); return; }

    if (t.dataset.watchlist) {
        const on = t.getAttribute('aria-pressed') === 'true';
        try {
            await api('/media/watchlist', {
                method: on ? 'DELETE' : 'POST',
                body: JSON.stringify({ path: t.dataset.watchlist }),
            });
            setToggle(t, !on, 'ph-heart');
            toast(on ? 'Removed from watchlist' : 'Added to watchlist', 'success', 2200);
        } catch (err) { toast(err.message || 'Could not update watchlist', 'error'); }
        return;
    }
    if (t.dataset.watched) {
        const on = t.getAttribute('aria-pressed') === 'true';
        try {
            await api('/media/mark_watched', {
                method: 'POST',
                body: JSON.stringify({ path: t.dataset.watched, watched: on ? 0 : 1 }),
            });
            setToggle(t, !on, 'ph-check-circle');
            toast(on ? 'Marked as unwatched' : 'Marked as watched', 'success', 2200);
        } catch (err) { toast(err.message || 'Could not mark watched', 'error'); }
    }
});

/* ══════════════════════════════════════════════════════════════════════════
   Wiring
   ══════════════════════════════════════════════════════════════════════════ */

function wire() {
    $('#login-form')?.addEventListener('submit', login);

    $('#lib-sort-btn')?.addEventListener('click', openSortSheet);
    $('#sheet-scrim')?.addEventListener('click', closeSheet);

    $('#dialog-cancel')?.addEventListener('click', () => closeDialog(false));
    $('#dialog-confirm')?.addEventListener('click', () => closeDialog(true));

    $('#search-input')?.addEventListener('input', e => {
        clearTimeout(_searchTimer);
        const q = e.target.value.trim();
        _searchTimer = setTimeout(() => runSearch(q), 250);
    });

    // Player transport
    $('#player-play')?.addEventListener('click', () => {
        const v = V.el; if (!v) return;
        if (v.paused) v.play().catch(() => {}); else v.pause();
    });
    $('#player-back15')?.addEventListener('click', () => { if (V.el) V.el.currentTime = Math.max(0, V.el.currentTime - 15); });
    $('#player-fwd30')?.addEventListener('click', () => { if (V.el) V.el.currentTime = Math.min(V.el.duration || 0, V.el.currentTime + 30); });
    $('#player-scrubber')?.addEventListener('click', e => {
        const v = V.el; if (!v || !v.duration) return;
        const track = $('#player-scrubber .scrub-track');
        const r = track.getBoundingClientRect();
        v.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * v.duration;
    });
    $('#player-full')?.addEventListener('click', async () => {
        const wrap = $('#screen-player');
        try {
            if (document.fullscreenElement || document.webkitFullscreenElement) {
                await (document.exitFullscreen?.() || document.webkitExitFullscreen?.());
            } else if (V.el?.webkitEnterFullscreen && !wrap.requestFullscreen) {
                V.el.webkitEnterFullscreen();          // iPhone: video-element only
            } else {
                await (wrap.requestFullscreen?.() || wrap.webkitRequestFullscreen?.());
                try { await screen.orientation?.lock?.('landscape'); } catch {}
            }
        } catch { toast('Fullscreen is not available here', 'warn'); }
    });
    document.addEventListener('fullscreenchange', () => {
        const on = !!document.fullscreenElement;
        const i = $('#player-full i');
        if (i) i.className = on ? 'ph ph-corners-in' : 'ph ph-corners-out';
        if (!on) { try { screen.orientation?.unlock?.(); } catch {} }
    });

    $('#player-cast')?.addEventListener('click', async () => {
        const v = V.el; if (!v) return;
        try {
            if (document.pictureInPictureElement) await document.exitPictureInPicture();
            else if (v.requestPictureInPicture) await v.requestPictureInPicture();
            else toast('Picture-in-picture is not supported here', 'warn');
        } catch { toast('Picture-in-picture is not available', 'warn'); }
    });
    $('#player-subs')?.addEventListener('click', () => openSubtitlePicker());
    $('#player-audio')?.addEventListener('click', () => toast('Audio track switching needs the desktop player for now.', 'info', 5000));
    $('#player-speed')?.addEventListener('click', () => {
        const v = V.el; if (!v) return;
        const rates = [1, 1.25, 1.5, 2, 0.75];
        const next = rates[(rates.indexOf(v.playbackRate) + 1) % rates.length];
        v.playbackRate = next;
        $('#player-speed').innerHTML = `<i class="ph ph-gauge" style="font-size:17px"></i>${next.toFixed(2).replace(/0$/, '')}×`;
    });

    // Audio transport
    $('#mini-player')?.addEventListener('click', e => {
        if (e.target.closest('#mini-play')) { toggleAudio(); return; }
        $('#now-playing-sheet').classList.remove('hidden');
    });
    $('#np-close')?.addEventListener('click', () => $('#now-playing-sheet').classList.add('hidden'));
    $('#np-play')?.addEventListener('click', toggleAudio);
    $('#np-prev')?.addEventListener('click', prevTrack);
    $('#np-next')?.addEventListener('click', nextTrack);
    $('#np-stop')?.addEventListener('click', stopAudio);
    $('#np-scrubber')?.addEventListener('click', e => {
        const a = S.audio.el; if (!a || !a.duration) return;
        const track = $('#np-scrubber .scrub-track');
        const r = track.getBoundingClientRect();
        a.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * a.duration;
    });

    document.addEventListener('click', e => {
        if (e.target.closest('#health-run')) runHealthCheck();
        if (e.target.closest('#signout-btn')) logout();
    });

    // Hardware/browser back pops the stack rather than leaving the app
    history.replaceState({ nomad: true }, '');
    window.addEventListener('popstate', () => {
        history.pushState({ nomad: true }, '');
        if (S.stack.length) back();
    });
    history.pushState({ nomad: true }, '');

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            if (!$('#dialog-wrap').classList.contains('hidden')) return closeDialog(false);
            if (!$('#sheet').classList.contains('hidden')) return closeSheet();
            if (!$('#now-playing-sheet').classList.contains('hidden')) return $('#now-playing-sheet').classList.add('hidden');
            if (S.stack.length) back();
        }
    });

    // Persist progress when the page goes away
    const flush = () => { if (V.el) saveProgress(); };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); });
}

/* ══════════════════════════════════════════════════════════════════════════
   Boot
   ══════════════════════════════════════════════════════════════════════════ */

/* Manifest shortcuts and shared links arrive as /#library, /#downloads,
   /#server, /#search — route them instead of dumping the user on Home. */
function routeFromHash() {
    const h = (location.hash || '').replace(/^#/, '').toLowerCase();
    if (!h) return false;
    if (TAB_SCREENS[h]) { goTab(h); return true; }
    if (h === 'search') {
        goTab('home');
        push('search');
        setTimeout(() => $('#search-input')?.focus(), 80);
        return true;
    }
    if (h === 'settings') { goTab('server'); push('settings'); loadSettings(); return true; }
    return false;
}

async function startApp() {
    $('#login-screen').classList.add('hidden');
    $('#app-shell').classList.remove('hidden');
    try { S.profile = await api('/auth/profile'); } catch { S.profile = null; }
    try {
        const st = await (await fetch(`${API}/system/setup/status`)).json();
        S.omdb = !!st.omdb_configured;
    } catch { S.omdb = null; }
    const dev = $('#home-device');
    if (dev) dev.textContent = 'Nomad Pi';
    if (!routeFromHash()) goTab('home');
}

async function boot() {
    wire();

    // First-run: the server tells us whether an admin exists yet
    try {
        const setup = await (await fetch(`${API}/system/setup/status`)).json();
        if (setup && setup.has_default_password) {
            $('#setup-hint').textContent = 'First run — sign in with the admin password printed by setup.sh.';
            $('#setup-hint').classList.remove('hidden');
        }
    } catch {}

    if (!token()) {
        $('#login-screen').classList.remove('hidden');
        return;
    }
    try {
        await api('/auth/check');
        await startApp();
    } catch {
        localStorage.removeItem(TOKEN_KEY);
        $('#login-screen').classList.remove('hidden');
    }
}

// Chrome/Edge fire this instead of showing their own prompt; stash it so the
// Settings row can trigger the real install dialog on demand.
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    _installPrompt = e;
    if (S.screen === 'settings') loadSettings();
});
window.addEventListener('appinstalled', () => {
    _installPrompt = null;
    toast('Nomad Pi installed', 'success');
    if (S.screen === 'settings') loadSettings();
});

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}

document.addEventListener('DOMContentLoaded', boot);
