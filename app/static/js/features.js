/* ══════════════════════════════════════════════════════════════════════════
   Nomad Pi — library depth

   The pieces the four tabs imply but do not themselves contain: the show →
   season → episode drill-down the design's Episodes panel calls for, folder
   navigation for Files, subtitle search, rename/delete, the update progress
   view, and the now-playing broadcast external displays listen to.
   ══════════════════════════════════════════════════════════════════════════ */

/* ══════════════════════════════════════════════════════════════════════════
   Shows → seasons → episodes
   ══════════════════════════════════════════════════════════════════════════ */

const SHOWS = { list: [], show: null, season: null };

async function loadShows() {
    const data = await api('/media/shows/library');
    SHOWS.list = data.shows || [];
    return SHOWS.list;
}

function renderShowsGrid(body) {
    if (!SHOWS.list.length) {
        body.innerHTML = `<div class="empty"><i class="ph ph-television"></i>No shows indexed yet.<br>Add media, then run a scan from the Server tab.</div>`;
        return;
    }
    body.innerHTML = (typeof artworkHint === 'function' ? artworkHint(SHOWS.list) : '')
        + `<div class="grid">${SHOWS.list.map((s, i) => {
        const poster = posterUrl(s.poster);
        const seasonList = s.seasons || [];
        const seasons = seasonList.length;
        const eps = seasonList.reduce((n, x) => n + (x.episodes?.length || 0), 0);
        return `
          <button class="grid-item" data-show="${i}">
            <div class="art">
              ${poster ? `<img src="${escapeHtml(poster)}" alt="" loading="lazy" onerror="this.remove()">`
                       : `<i class="ph ph-television"></i>`}
            </div>
            <div class="tile-title">${escapeHtml(s.name)}</div>
            <div class="tile-meta">${seasons} season${seasons === 1 ? '' : 's'} · ${eps} ep</div>
          </button>`;
    }).join('')}</div>`;
}

function openShow(index) {
    const show = SHOWS.list[index];
    if (!show) return;
    SHOWS.show = show;

    const seasonList = [...(show.seasons || [])].sort((a, b) => {
        const na = parseInt(String(a.name).replace(/\D/g, ''), 10);
        const nb = parseInt(String(b.name).replace(/\D/g, ''), 10);
        return (isNaN(na) ? 999 : na) - (isNaN(nb) ? 999 : nb);
    });
    const seasonNames = seasonList.map(x => x.name);
    SHOWS.season = seasonNames[0] || null;

    openSub(show.name, (body) => {
        const season = seasonList.find(x => x.name === SHOWS.season) || seasonList[0] || { episodes: [] };
        const eps = [...(season.episodes || [])].sort((a, b) => {
            const d = (a.ep_num ?? 999) - (b.ep_num ?? 999);
            return d !== 0 ? d : String(a.name).localeCompare(String(b.name), undefined, { numeric: true });
        });

        body.innerHTML = `
          ${seasonNames.length > 1 ? `
            <div class="chip-scroller pv" style="padding:0 0 14px">
              ${seasonNames.map(n => `
                <button class="chip${n === SHOWS.season ? ' active' : ''}" data-season="${escapeHtml(n)}">
                  ${escapeHtml(n)}
                </button>`).join('')}
            </div>` : ''}

          <div class="kicker" style="margin-bottom:10px">
            ${eps.length} episode${eps.length === 1 ? '' : 's'}
          </div>

          <div class="list">
            ${eps.map(e => {
                // get_shows_library nests playback state under e.progress;
                // reading it flat meant every episode showed no progress and
                // always restarted from zero.
                const pr = e.progress || {};
                const cur = Number(pr.current_time ?? e.current_time ?? 0);
                const dur = Number(pr.duration ?? e.duration ?? 0);
                const pct = dur > 0 ? Math.min(100, Math.round((cur / dur) * 100)) : 0;
                return `
                  <div class="ep-row row-rule">
                    <button class="ep-thumb" data-play="${escapeHtml(e.path)}" data-at="${cur}"
                            style="border:none;padding:0;cursor:pointer" aria-label="Play">
                      <i class="ph-fill ph-play"></i>
                      ${pct ? `<div class="art-progress"><span style="width:${pct}%"></span></div>` : ''}
                    </button>
                    <button class="list-body" data-play="${escapeHtml(e.path)}" data-at="${cur}"
                            style="background:none;border:none;text-align:left;cursor:pointer;color:inherit">
                      <div class="ep-title">${escapeHtml(stripExt(e.name))}</div>
                      <div class="ep-meta">${dur ? (pct >= 95 ? 'watched' : pct ? fmtLeft(dur - cur) : fmtTime(dur)) : ''}</div>
                    </button>
                    <button class="btn btn-icon btn-icon-plain" data-filemenu="${escapeHtml(e.path)}"
                            aria-label="Episode options"><i class="ph ph-dots-three-vertical"></i></button>
                  </div>`;
            }).join('')}
          </div>`;
    }, { desc: `${seasonNames.length} season${seasonNames.length === 1 ? '' : 's'}` });
}

/* ══════════════════════════════════════════════════════════════════════════
   Files — folder navigation
   ══════════════════════════════════════════════════════════════════════════ */

const FILES = { path: '/data', stack: [] };

async function renderFileBrowser(body, path) {
    FILES.path = path || '/data';
    const data = await api(`/media/browse?path=${encodeURIComponent(FILES.path)}`);
    const items = data.items || [];
    const up = FILES.path !== '/data';

    body.innerHTML = `
      <div class="list-row row-rule" style="gap:8px;padding-bottom:12px">
        <i class="ph ph-folder-open list-icon"></i>
        <div class="list-body"><div class="list-sub" style="white-space:normal">${escapeHtml(FILES.path)}</div></div>
      </div>
      ${up ? `
        <button class="list-row list-row-tall row-rule" data-fileup="1">
          <i class="ph ph-arrow-u-left-up list-icon"></i>
          <div class="list-body"><div class="list-title">Up one level</div></div>
        </button>` : ''}
      ${items.length ? `
        <div class="list">
          ${items.map(it => `
            <div class="list-row list-row-tall row-rule">
              <button class="list-body" style="display:flex;align-items:center;gap:12px;background:none;border:none;text-align:left;color:inherit;cursor:pointer"
                      ${it.is_dir ? `data-filedir="${escapeHtml(it.path)}"` : `data-fileopen="${escapeHtml(it.path)}"`}>
                <i class="ph ${it.is_dir ? 'ph-folder' : 'ph-file'} list-icon"></i>
                <span style="min-width:0;flex:1">
                  <span class="list-title" style="display:block">${escapeHtml(it.name)}</span>
                  <span class="list-sub" style="display:block">${it.is_dir ? 'Folder' : escapeHtml(fmtSize(it.size))}</span>
                </span>
              </button>
              ${!it.is_dir ? `
                <button class="btn btn-icon btn-icon-plain" data-filemenu="${escapeHtml(it.path)}"
                        aria-label="File options"><i class="ph ph-dots-three-vertical"></i></button>` : ''}
            </div>`).join('')}
        </div>`
        : '<div class="empty"><i class="ph ph-folder-open"></i>This folder is empty.</div>'}`;
}

function openFiles(path) {
    openSub('Files', (body) => renderFileBrowser(body, path), { desc: 'Browse everything on the Pi' });
}

/* ══════════════════════════════════════════════════════════════════════════
   File options — rename, delete, download
   ══════════════════════════════════════════════════════════════════════════ */

function openFileMenu(path) {
    const name = baseName(path);
    openSheet(`
      <div class="kicker" style="margin-bottom:4px">File</div>
      <div style="font-size:15px;margin-bottom:14px;word-break:break-word">${escapeHtml(name)}</div>
      <div class="list">
        <button class="sheet-option row-rule" data-frename="${escapeHtml(path)}">
          <span>Rename</span><i class="ph ph-pencil-simple"></i>
        </button>
        <a class="sheet-option row-rule" href="${escapeHtml(streamUrl(path, '&download=true'))}">
          <span>Download</span><i class="ph ph-download-simple"></i>
        </a>
        <button class="sheet-option row-rule" data-fdelete="${escapeHtml(path)}" style="color:#e0a1a1">
          <span>Delete</span><i class="ph ph-trash"></i>
        </button>
      </div>`);
}

function openRename(path) {
    const name = baseName(path);
    const base = stripExt(name);
    const e = ext(name);
    openSheet(`
      <div class="kicker" style="margin-bottom:12px">Rename</div>
      <input class="input input-plain" id="rn-name" value="${escapeHtml(base)}" autocomplete="off">
      <div style="font-size:12px;color:var(--text-45);margin-top:6px">${e ? `.${escapeHtml(e)} is kept` : ''}</div>
      <div id="rn-status" style="font-size:12.5px;color:var(--text-45);min-height:18px;margin-top:8px"></div>
      <button class="btn btn-primary btn-block" id="rn-save" style="min-height:48px;margin-top:6px">Rename</button>`);

    $('#rn-save').addEventListener('click', async () => {
        const next = $('#rn-name').value.trim();
        const st = $('#rn-status');
        if (!next) { st.textContent = 'Enter a name.'; return; }
        const dir = path.slice(0, path.lastIndexOf('/'));
        const newPath = `${dir}/${next}${e ? `.${e}` : ''}`;
        st.textContent = 'Renaming…';
        try {
            await api('/media/rename', { method: 'POST', body: JSON.stringify({ old_path: path, new_path: newPath }) });
            closeSheet();
            toast('Renamed', 'success');
            refreshAfterFileChange();
        } catch (err) { st.textContent = err.message || 'Could not rename.'; }
    });
}

async function deleteFile(path) {
    if (!await confirmDialog('Delete this file?',
        `${baseName(path)} is removed from the Pi permanently. This cannot be undone.`, 'Delete')) return;
    try {
        await api(`/media/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
        closeSheet();
        toast('Deleted', 'success');
        refreshAfterFileChange();
    } catch (e) { toast(e.message || 'Could not delete that file', 'error'); }
}

function refreshAfterFileChange() {
    if (S.screen === 'sub') refreshSub();
    else if (S.screen === 'library') loadLibrary();
}

/* ══════════════════════════════════════════════════════════════════════════
   Subtitles
   ══════════════════════════════════════════════════════════════════════════ */

async function openSubtitlePicker() {
    const path = V.path;
    if (!path) return;
    const title = stripExt(baseName(path));

    openSheet(`
      <div class="kicker" style="margin-bottom:12px">Subtitles</div>
      <div id="sub-tracks"></div>
      <div class="search-field" style="margin:14px 0 10px">
        <i class="ph ph-magnifying-glass"></i>
        <input class="input" id="sub-q" value="${escapeHtml(title)}" placeholder="Search OpenSubtitles">
      </div>
      <button class="btn btn-block" id="sub-search" style="min-height:44px">Search</button>
      <div id="sub-results" style="margin-top:12px"></div>`);

    // Tracks already embedded in the file
    const v = V.el;
    const tracks = v ? Array.from(v.textTracks || []) : [];
    $('#sub-tracks').innerHTML = tracks.length ? `
      <div class="list">
        <button class="sheet-option row-rule" data-subtrack="-1"><span>Off</span></button>
        ${tracks.map((t, i) => `
          <button class="sheet-option row-rule" data-subtrack="${i}">
            <span>${escapeHtml(t.label || t.language || `Track ${i + 1}`)}</span>
            ${t.mode === 'showing' ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>' : ''}
          </button>`).join('')}
      </div>` : '<div class="facts-note" style="text-align:left">No embedded subtitle tracks in this file.</div>';

    $('#sub-search').addEventListener('click', () => searchSubtitles($('#sub-q').value.trim()));
}

async function searchSubtitles(q) {
    const out = $('#sub-results');
    if (!q || !out) return;
    out.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        const data = await api(`/media/subtitles/search?title=${encodeURIComponent(q)}`);
        if (data.error) { out.innerHTML = `<div class="facts-note" style="text-align:left">${escapeHtml(data.error)}</div>`; return; }
        const list = data.results || [];
        if (!list.length) { out.innerHTML = `<div class="facts-note" style="text-align:left">No subtitles found.</div>`; return; }
        _subResults = list;
        out.innerHTML = `<div class="list">${list.slice(0, 20).map((r, i) => `
          <button class="sheet-option row-rule" data-subget="${i}">
            <span style="min-width:0">
              <span style="display:block">${escapeHtml(r.release || r.file_name || r.name || 'Subtitle')}</span>
              <span class="list-sub">${escapeHtml(r.language || r.lang || '')}</span>
            </span>
            <i class="ph ph-download-simple"></i>
          </button>`).join('')}</div>`;
    } catch (e) {
        out.innerHTML = `<div class="facts-note" style="text-align:left">${escapeHtml(e.message || 'Search failed')}</div>`;
    }
}

let _subResults = [];

async function downloadSubtitle(index) {
    const r = _subResults[index];
    if (!r || !V.path) return;
    try {
        toast('Fetching subtitle…', 'info');
        const res = await api('/media/subtitles/download', {
            method: 'POST',
            body: JSON.stringify({ file_id: r.file_id || r.id, video_path: V.path, lang: r.language || r.lang || 'en' }),
        });
        closeSheet();
        if (res.path && V.el) {
            const track = document.createElement('track');
            track.kind = 'subtitles';
            track.label = r.language || 'Downloaded';
            track.src = `${API}/media/subtitle?path=${encodeURIComponent(res.path)}${ticketParam()}`;
            track.default = true;
            V.el.appendChild(track);
            track.addEventListener('load', () => { if (V.el.textTracks.length) V.el.textTracks[V.el.textTracks.length - 1].mode = 'showing'; });
        }
        toast('Subtitle added', 'success');
    } catch (e) { toast(e.message || 'Could not download that subtitle', 'error'); }
}

function selectSubtitleTrack(index) {
    const v = V.el;
    if (!v) return;
    Array.from(v.textTracks || []).forEach((t, i) => { t.mode = (i === index) ? 'showing' : 'disabled'; });
    closeSheet();
    toast(index < 0 ? 'Subtitles off' : 'Subtitles on', 'success', 2000);
}

/* ══════════════════════════════════════════════════════════════════════════
   Update progress
   ══════════════════════════════════════════════════════════════════════════ */

let _updatePoll = null;

function openUpdateProgress() {
    openSub('Updating', (body) => {
        body.innerHTML = `
          <div class="card card-lg">
            <div class="health-title" id="up-msg">Starting…</div>
            <div class="bar bar-lg" style="margin-top:12px"><span id="up-bar" style="width:0%"></span></div>
            <div class="stat-note" id="up-pct">0%</div>
          </div>
          <div class="kicker" style="margin:20px 0 8px">Log</div>
          <pre class="logbox" id="up-log">Waiting for output…</pre>
          <div class="facts-note" style="margin-top:14px;text-align:left">
            The server restarts when this finishes — the app will reconnect on its own.
          </div>`;
        pollUpdate();
    }, { desc: 'Pulling the latest version' });
}

function pollUpdate() {
    clearInterval(_updatePoll);
    _updatePoll = setInterval(async () => {
        if (S.screen !== 'sub') { clearInterval(_updatePoll); _updatePoll = null; return; }
        try {
            const s = await api('/system/update/status');
            const pct = Math.round(Number(s.progress || 0));
            const bar = $('#up-bar'), msg = $('#up-msg'), p = $('#up-pct');
            if (bar) bar.style.width = `${pct}%`;
            if (msg) msg.textContent = s.message || 'Working…';
            if (p) p.textContent = `${pct}%`;
            if (pct >= 100) {
                clearInterval(_updatePoll); _updatePoll = null;
                toast('Update complete — reconnecting…', 'success', 8000);
                waitForServerThenReload();
            }
        } catch {}
        try {
            const l = await api('/system/update/log');
            const box = $('#up-log');
            const text = Array.isArray(l.log) ? l.log.join('\n') : (l.log || l.output || '');
            if (box && text) { box.textContent = text; box.scrollTop = box.scrollHeight; }
        } catch {}
    }, 2000);
}

/* After an update the server restarts, so the open page is running the old
   bundle against a new backend. Poll until it answers again, then reload —
   the app used to just sit there until the user refreshed by hand. */
async function waitForServerThenReload(maxWaitMs = 180000) {
    const started = Date.now();
    const box = $('#up-msg');
    let sawDown = false;

    const tick = async () => {
        if (Date.now() - started > maxWaitMs) {
            if (box) box.textContent = 'Server is taking a while — refresh when it is back.';
            return;
        }
        let up = false;
        try {
            const r = await fetch(`${API}/system/status`, { cache: 'no-store' });
            up = r.ok;
        } catch { up = false; }

        if (!up) {
            sawDown = true;
            if (box) box.textContent = 'Server restarting…';
        } else if (sawDown) {
            // Came back after going away — this is the new build.
            if (box) box.textContent = 'Back up. Reloading…';
            // Drop caches so the reload picks up the new bundle, not the old one.
            try {
                const keys = await caches.keys();
                await Promise.all(keys.map(k => caches.delete(k)));
                const reg = await navigator.serviceWorker?.getRegistration();
                await reg?.update();
            } catch {}
            setTimeout(() => location.reload(true), 800);
            return;
        }
        setTimeout(tick, 2000);
    };
    setTimeout(tick, 3000);
}

/* ══════════════════════════════════════════════════════════════════════════
   Now-playing broadcast for external displays (DASHBOARD_API.md)
   ══════════════════════════════════════════════════════════════════════════ */

let _sessionId = null;

function dashboardSession(path, title, state, current, duration) {
    if (!_sessionId) _sessionId = `web_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    try {
        fetch(`${API}/dashboard/session/update`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: _sessionId, path, title, state,
                current_time: current || 0, duration: duration || 0,
                media_type: 'video', client: 'web',
            }),
            keepalive: true,
        }).catch(() => {});
    } catch {}
}

/* ══════════════════════════════════════════════════════════════════════════
   Delegated events
   ══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-show],[data-season],[data-filedir],[data-fileup],[data-fileopen],[data-filemenu],[data-frename],[data-fdelete],[data-subtrack],[data-subget]');
    if (!t) return;

    if (t.dataset.show !== undefined)   { openShow(Number(t.dataset.show)); return; }
    if (t.dataset.season)               { SHOWS.season = t.dataset.season; refreshSub(); return; }

    if (t.dataset.fileup)               { const p = FILES.path.split('/').slice(0, -1).join('/') || '/data';
                                          refreshSubWith(body => renderFileBrowser(body, p)); return; }
    if (t.dataset.filedir)              { refreshSubWith(body => renderFileBrowser(body, t.dataset.filedir)); return; }
    if (t.dataset.fileopen)             { playVideo(t.dataset.fileopen, 0); return; }
    if (t.dataset.filemenu)             { openFileMenu(t.dataset.filemenu); return; }
    if (t.dataset.frename)              { openRename(t.dataset.frename); return; }
    if (t.dataset.fdelete)              { deleteFile(t.dataset.fdelete); return; }
    if (t.dataset.subtrack !== undefined) { selectSubtitleTrack(Number(t.dataset.subtrack)); return; }
    if (t.dataset.subget)               { downloadSubtitle(Number(t.dataset.subget)); return; }
});

/* Swap the sub-page renderer without pushing another entry on the stack */
function refreshSubWith(renderFn) {
    _subRender = renderFn;
    refreshSub();
}

/* ══════════════════════════════════════════════════════════════════════════
   Auto-play the next episode

   On 'ended', ask the server what comes next in the same show and offer it
   with a countdown. Cancelling stops the chain; closing the player kills it.
   ══════════════════════════════════════════════════════════════════════════ */

let _nextTimer = null;

function cancelNextEpisode() {
    if (_nextTimer) { clearInterval(_nextTimer); _nextTimer = null; }
    document.getElementById('next-ep')?.remove();
}

async function offerNextEpisode(path) {
    if (!path) return;
    let next = null;
    try {
        const r = await api(`/media/shows/next?path=${encodeURIComponent(path)}`);
        next = r.next;
    } catch { return; }
    if (!next || !next.path) return;
    if (S.screen !== 'player') return;   // user already left

    cancelNextEpisode();
    const title = stripExt(next.name || baseName(next.path));
    const card = document.createElement('div');
    card.id = 'next-ep';
    card.className = 'next-ep';
    card.innerHTML = `
      <div class="kicker" style="margin-bottom:6px">Up next</div>
      <div class="next-ep-title">${escapeHtml(title)}</div>
      <div class="next-ep-count">Playing in <span id="next-ep-n">10</span>s</div>
      <div class="btn-row" style="margin-top:14px">
        <button class="btn" id="next-ep-cancel">Cancel</button>
        <button class="btn btn-primary" id="next-ep-now">Play now</button>
      </div>`;
    $('#screen-player').appendChild(card);

    let n = 10;
    const go = () => { cancelNextEpisode(); playVideo(next.path, 0); };
    _nextTimer = setInterval(() => {
        n--;
        const el = document.getElementById('next-ep-n');
        if (el) el.textContent = String(n);
        if (n <= 0) go();
    }, 1000);

    document.getElementById('next-ep-cancel').onclick = cancelNextEpisode;
    document.getElementById('next-ep-now').onclick = go;
}
