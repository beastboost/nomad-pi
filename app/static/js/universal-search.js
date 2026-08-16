/* Nomad universal search: title -> Pi-safe release -> Play / Stream + Keep / Download. */
(() => {
    if (typeof api !== 'function' || typeof S === 'undefined') return;

    const U = {
        query: '',
        titles: [],
        entries: [],
        requestId: 0,
        remoteToken: null,
    };
    window.NomadUniversalSearch = U;

    function badge(text, cls = '') {
        return `<span class="universal-badge ${cls}">${escapeHtml(text)}</span>`;
    }

    function releaseBadges(release) {
        const bits = [];
        if (release.cached) bits.push(badge('Cached', 'is-cached'));
        if (release.lite_direct_candidate) bits.push(badge('Direct', 'is-direct'));
        else if (release.lite_compatible) bits.push(badge('Pi safe'));
        else bits.push(badge('Fallback', 'is-heavy'));
        if (release.quality) bits.push(badge(release.quality));
        if (release.codec) bits.push(badge(release.codec));
        if (release.size) bits.push(badge(release.size));
        return bits.join('');
    }

    function addEntry(title, release) {
        const index = U.entries.length;
        U.entries.push({ title, release });
        return index;
    }

    function releaseHtml(title, release) {
        const index = addEntry(title, release);
        const canPlay = release.cached === true && release.lite_direct_candidate === true;
        const reason = !release.lite_compatible && Array.isArray(release.lite_reasons)
            ? release.lite_reasons.slice(0, 3).join(' · ')
            : '';
        return `
          <div class="universal-release">
            <div class="universal-release-name">${escapeHtml(release.name || 'Release')}</div>
            <div class="universal-release-meta">${releaseBadges(release)}</div>
            ${reason ? `<div class="universal-release-meta">${escapeHtml(reason)}</div>` : ''}
            <div class="universal-actions">
              ${canPlay ? `<button class="btn btn-primary" type="button" data-universal-play="${index}"><i class="ph ph-play"></i>Play</button>` : ''}
              ${release.lite_compatible ? `<button class="btn" type="button" data-universal-keep="${index}"><i class="ph ph-play-circle"></i>Stream + Keep</button>` : ''}
              <button class="btn" type="button" data-universal-download="${index}"><i class="ph ph-download-simple"></i>Download</button>
            </div>
          </div>`;
    }

    function titleHtml(title, titleIndex) {
        const set = title.release_set || null;
        const releases = Array.isArray(set?.releases) ? set.releases : [];
        const poster = title.poster
            ? `<img src="${escapeHtml(title.poster)}" alt="" loading="lazy" onerror="this.remove()">`
            : '<i class="ph ph-film-slate"></i>';
        const summary = set
            ? `${Number(set.cached_count || 0)} cached · ${Number(set.safe_count || 0)} Pi-safe${set.heavy_count ? ` · ${set.heavy_count} hidden` : ''}`
            : 'Releases not loaded yet';
        const series = title.type === 'series';
        const releaseBody = releases.length
            ? releases.map(release => releaseHtml(title, release)).join('')
            : `<div class="universal-empty">${escapeHtml(set?.error || (set ? 'No Pi-friendly release found.' : 'Load releases for this title.'))}</div>`;

        return `
          <section class="universal-title-card" data-universal-title="${titleIndex}">
            <div class="universal-title-head">
              <div class="universal-poster">${poster}</div>
              <div>
                <div class="universal-title-name">${escapeHtml(title.title || '')}</div>
                <div class="universal-title-meta">
                  ${badge(title.type === 'series' ? 'Series' : 'Movie')}
                  ${title.year ? badge(String(title.year)) : ''}
                  <span>${escapeHtml(summary)}</span>
                </div>
              </div>
            </div>
            <div class="universal-release-list">${releaseBody}</div>
            <div class="universal-card-footer">
              ${series ? `
                <div class="universal-episode">
                  <span class="universal-badge">S</span>
                  <input class="input" type="number" min="1" max="999" value="${Number(title._season || 1)}" data-universal-season="${titleIndex}" aria-label="Season">
                  <span class="universal-badge">E</span>
                  <input class="input" type="number" min="1" max="9999" value="${Number(title._episode || 1)}" data-universal-episode-input="${titleIndex}" aria-label="Episode">
                  <button class="btn" type="button" data-universal-episode="${titleIndex}">Load</button>
                </div>` : '<span></span>'}
              <div style="display:flex;gap:6px">
                ${!set ? `<button class="btn" type="button" data-universal-load="${titleIndex}">Load releases</button>` : ''}
                ${set?.heavy_count ? `<button class="btn" type="button" data-universal-more="${titleIndex}">${title._showAll ? 'Pi-friendly only' : `Show all (${Number(set.heavy_count)})`}</button>` : ''}
              </div>
            </div>
          </section>`;
    }

    function renderUniversal() {
        const out = $('#debrid-results');
        if (!out) return;
        U.entries = [];
        if (!U.titles.length) {
            out.innerHTML = '<div class="empty"><i class="ph ph-magnifying-glass"></i>No matching films or shows.</div>';
            return;
        }
        const cached = U.titles.reduce((n, title) => n + Number(title.release_set?.cached_count || 0), 0);
        const safe = U.titles.reduce((n, title) => n + Number(title.release_set?.safe_count || 0), 0);
        out.innerHTML = `
          <div class="universal-shell">
            <div class="universal-summary">
              <span><strong>${escapeHtml(U.query)}</strong> · ${U.titles.length} title${U.titles.length === 1 ? '' : 's'}</span>
              <span>${cached} cached · ${safe} Pi-safe</span>
            </div>
            ${U.titles.map((title, index) => titleHtml(title, index)).join('')}
          </div>`;
    }

    async function loadReleaseSet(titleIndex, { showAll = false } = {}) {
        const title = U.titles[titleIndex];
        if (!title?.imdb_id) return;
        const card = $(`[data-universal-title="${titleIndex}"]`);
        card?.classList.add('is-loading');
        const season = Number(title._season || 1);
        const episode = Number(title._episode || 1);
        try {
            const qs = new URLSearchParams({
                imdb_id: title.imdb_id,
                media_type: title.type || 'movie',
                season: String(season),
                episode: String(episode),
                include_heavy: showAll ? 'true' : 'false',
                limit: showAll ? '24' : '8',
            });
            title.release_set = await api(`/debrid/universal/releases?${qs}`);
            title._showAll = showAll;
            renderUniversal();
        } catch (err) {
            toast(err?.message || 'Could not load releases', 'error', 6500);
        }
    }

    async function universalSearch(query) {
        const q = String(query || '').trim();
        S.debrid.query = q;
        S.debrid.title = null;
        U.query = q;
        const out = $('#debrid-results');
        if (!q || !out) return;
        const requestId = ++U.requestId;
        out.innerHTML = `
          <div class="universal-summary"><span>Searching for <strong>${escapeHtml(q)}</strong></span><span>Direct-play first</span></div>
          <div class="empty"><div class="spinner"></div></div>`;
        try {
            const data = await api(`/debrid/universal/search?q=${encodeURIComponent(q)}`);
            if (requestId !== U.requestId) return;
            U.titles = Array.isArray(data.titles) ? data.titles.map(title => ({
                ...title,
                _season: Number(data.season || 1),
                _episode: Number(data.episode || 1),
                _showAll: false,
            })) : [];
            renderUniversal();
        } catch (err) {
            if (requestId !== U.requestId) return;
            out.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(err?.message || 'Search failed')}</div>`;
        }
    }

    // Replace the legacy title-only step. renderFind already owns the search
    // box and calls this global function, so the rest of navigation stays intact.
    window.searchTitles = universalSearch;
    try { searchTitles = universalSearch; } catch {}

    function selectedVideo(magnet) {
        const links = Array.isArray(magnet?.links) ? magnet.links : [];
        const selected = (magnet?.files || []).filter(file => file?.selected !== false);
        const videoExt = /\.(mkv|mp4|m4v|webm|avi|mov|ts|m2ts|mts|wmv|mpg|mpeg)(?:$|[?#])/i;
        const candidates = selected
            .map((file, index) => ({ file, index }))
            .filter(item => videoExt.test(String(item.file?.path || item.file?.name || '')))
            .sort((a, b) => Number(b.file?.bytes || b.file?.size || 0) - Number(a.file?.bytes || a.file?.size || 0));
        const chosen = candidates[0] || (selected.length ? { file: selected[0], index: 0 } : null);
        let linkIndex = chosen?.index ?? 0;
        if (linkIndex >= links.length) linkIndex = 0;
        return { link: links[linkIndex] || links[0] || null, file: chosen?.file || null };
    }

    async function resolveRelease(entry, progress) {
        const release = entry.release;
        const title = entry.title;
        const infoHash = String(release.info_hash || release.hash || '').trim();
        if (!infoHash) throw new Error('That release has no usable info hash');
        progress?.('Opening cached release…', 20);
        const magnet = await api('/debrid/magnet', {
            method: 'POST',
            body: JSON.stringify({
                info_hash: infoHash,
                title: title.title || '',
                year: String(title.year || ''),
                media_type: title.type || 'movie',
                season: Number(title._season || 1),
                episode: Number(title._episode || 1),
            }),
        });
        const chosen = selectedVideo(magnet);
        if (!chosen.link) throw new Error('Provider returned no playable video link');
        progress?.('Opening direct media link…', 48);
        const unrestricted = await api('/debrid/unrestrict', {
            method: 'POST',
            body: JSON.stringify({ link: chosen.link }),
        });
        if (!unrestricted?.url) throw new Error('Provider did not return a media URL');
        const rawName = chosen.file?.path || chosen.file?.name || unrestricted.filename || release.name || title.title;
        const filename = String(rawName).split('/').pop() || `${title.title || 'media'}.mp4`;
        return { magnet, unrestricted, filename };
    }

    function preparationSheet(title) {
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Direct Play</div>
          <div style="font-size:16px;margin-bottom:8px">${escapeHtml(title || 'Preparing media')}</div>
          <div class="facts-note" id="universal-play-status" style="text-align:left">Resolving cached release…</div>
          <div class="bar" style="margin-top:14px"><span style="width:12%"></span></div>`);
    }

    function preparationProgress(message, pct) {
        const status = $('#universal-play-status');
        if (status) status.textContent = message;
        const bar = $('#sheet .bar span');
        if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(pct || 0)))}%`;
    }

    function openDirectRemotePlayer(result, title) {
        if (!result?.token || !result?.playback?.url) throw new Error('Direct proxy did not return a playable URL');
        if (typeof stopAudio === 'function' && S?.audio?.playing) stopAudio();
        stopVideo();
        U.remoteToken = result.token;
        push('player');
        V.path = null;
        V.url = result.playback.url;
        V.reconnects = 0;
        V.seekTo = 0;
        $('#player-title').textContent = title || 'Remote media';
        $('#player-sub').textContent = 'DIRECT · CACHED REMOTE';
        $('#player-ghost')?.classList.add('hidden');
        const stage = $('#player-stage');
        stage?.querySelector('video')?.remove();
        const video = document.createElement('video');
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.preload = 'metadata';
        stage?.insertBefore(video, stage.firstChild);
        V.el = video;
        video.addEventListener('loadedmetadata', () => typeof updateScrub === 'function' && updateScrub());
        video.addEventListener('timeupdate', () => typeof updateScrub === 'function' && updateScrub());
        video.addEventListener('play', () => {
            if (typeof setPlayIcon === 'function') setPlayIcon(true);
            if (typeof requestWake === 'function') requestWake();
            if (typeof showChrome === 'function') showChrome();
        });
        video.addEventListener('pause', () => {
            if (typeof setPlayIcon === 'function') setPlayIcon(false);
            if (typeof releaseWake === 'function') releaseWake();
        });
        video.addEventListener('ended', () => typeof setPlayIcon === 'function' && setPlayIcon(false));
        video.addEventListener('error', () => {
            if (video.error) toast('Direct remote stream stopped. Try Stream + Keep if the provider link is unstable.', 'error', 6500);
        });
        video.src = result.playback.url;
        video.load();
        video.play().catch(() => {});
    }

    async function playEntry(index) {
        const entry = U.entries[Number(index)];
        if (!entry) return;
        if (!entry.release?.cached || !entry.release?.lite_direct_candidate) {
            toast('Direct Play is reserved for cached MP4/AAC-compatible releases.', 'warn', 5000);
            return;
        }
        preparationSheet(entry.title.title || entry.release.name);
        try {
            const resolved = await resolveRelease(entry, preparationProgress);
            preparationProgress('Starting zero-transcode stream…', 78);
            const remote = await api('/debrid/universal/play', {
                method: 'POST',
                body: JSON.stringify({
                    url: resolved.unrestricted.url,
                    filename: resolved.filename,
                    mime_type: resolved.unrestricted.mimeType || null,
                }),
            });
            preparationProgress('Ready', 100);
            closeSheet();
            openDirectRemotePlayer(remote, entry.title.title || resolved.filename);
        } catch (err) {
            preparationProgress(err?.message || 'Could not start direct play', 100);
            toast(err?.message || 'Could not start direct play', 'error', 7500);
        }
    }

    function primeLegacyAction(index) {
        const entry = U.entries[Number(index)];
        if (!entry) return null;
        S.debrid.title = {
            ...entry.title,
            season: Number(entry.title._season || 1),
            episode: Number(entry.title._episode || 1),
        };
        S.debrid.results = [entry.release];
        return entry;
    }

    // Capture phase primes the legacy Download and Stream + Keep handlers before
    // their normal delegated bubble listeners inspect data-grab/data-streamkeep.
    document.addEventListener('click', event => {
        const keep = event.target.closest('[data-universal-keep]');
        if (keep) {
            if (primeLegacyAction(keep.dataset.universalKeep)) {
                keep.dataset.streamkeep = '0';
                setTimeout(() => delete keep.dataset.streamkeep, 0);
            }
            return;
        }
        const download = event.target.closest('[data-universal-download]');
        if (download) {
            if (primeLegacyAction(download.dataset.universalDownload)) {
                download.dataset.grab = '0';
                setTimeout(() => delete download.dataset.grab, 0);
            }
        }
    }, true);

    document.addEventListener('click', async event => {
        const play = event.target.closest('[data-universal-play]');
        if (play) {
            event.preventDefault();
            event.stopImmediatePropagation();
            await playEntry(play.dataset.universalPlay);
            return;
        }

        const load = event.target.closest('[data-universal-load]');
        if (load) {
            event.preventDefault();
            await loadReleaseSet(Number(load.dataset.universalLoad));
            return;
        }

        const more = event.target.closest('[data-universal-more]');
        if (more) {
            event.preventDefault();
            const index = Number(more.dataset.universalMore);
            const title = U.titles[index];
            await loadReleaseSet(index, { showAll: !title?._showAll });
            return;
        }

        const episodeButton = event.target.closest('[data-universal-episode]');
        if (episodeButton) {
            event.preventDefault();
            const index = Number(episodeButton.dataset.universalEpisode);
            const title = U.titles[index];
            if (!title) return;
            title._season = Math.max(1, Number($(`[data-universal-season="${index}"]`)?.value || 1));
            title._episode = Math.max(1, Number($(`[data-universal-episode-input="${index}"]`)?.value || 1));
            await loadReleaseSet(index, { showAll: false });
        }
    });

    const previousStopVideo = typeof stopVideo === 'function' ? stopVideo : null;
    if (previousStopVideo) {
        stopVideo = function universalStopVideo() {
            const token = U.remoteToken;
            U.remoteToken = null;
            if (token) {
                fetch(`${API}/debrid/universal/play/${encodeURIComponent(token)}`, {
                    method: 'DELETE',
                    headers: authHeaders(),
                    keepalive: true,
                }).catch(() => {});
            }
            return previousStopVideo();
        };
    }
})();
