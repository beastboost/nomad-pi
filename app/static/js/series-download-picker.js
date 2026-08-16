/* Nomad series manifest picker: inspect -> choose episodes -> queue structured downloads. */
(() => {
    if (typeof api !== 'function') return;

    const state = {
        entry: null,
        manifest: null,
        selected: new Set(),
        busy: false,
    };

    const videoExt = /\.(mkv|mp4|m4v|webm|avi|mov|ts|m2ts|mts|wmv|flv|mpg|mpeg|mpe|3gp|vob)(?:$|[?#])/i;

    function bytesLabel(bytes) {
        const value = Number(bytes || 0);
        if (!value) return 'size unknown';
        if (typeof fmtSize === 'function') return fmtSize(value);
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let n = value, i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return `${n.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
    }

    function filePath(file) {
        return String(file?.path || file?.name || file?.filename || '');
    }

    function isVideo(file) {
        return file?.video === true || videoExt.test(filePath(file));
    }

    function coversEpisode(file, season, episode) {
        const fileSeason = Number(file?.season || 0);
        const start = Number(file?.episode || 0);
        const end = Number(file?.episode_end || start || 0);
        return fileSeason === Number(season) && start > 0 && Number(episode) >= start && Number(episode) <= end;
    }

    function episodeText(file) {
        const season = Number(file?.season || 0);
        const episode = Number(file?.episode || 0);
        const end = Number(file?.episode_end || 0);
        if (season && episode) {
            return end && end !== episode
                ? `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}-E${String(end).padStart(2, '0')}`
                : `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;
        }
        return 'Video';
    }

    function selectedFiles() {
        const files = Array.isArray(state.manifest?.files) ? state.manifest.files : [];
        return files.filter(file => state.selected.has(Number(file.id)));
    }

    function selectedBytes() {
        return selectedFiles().reduce((sum, file) => sum + Number(file.bytes || 0), 0);
    }

    function updateSummary() {
        const files = selectedFiles();
        const el = $('#series-picker-summary');
        if (el) {
            el.textContent = `${files.length} episode${files.length === 1 ? '' : 's'} selected · ${bytesLabel(selectedBytes())}`;
        }
        const btn = $('#series-picker-download');
        if (btn) {
            btn.disabled = state.busy || !files.length;
            btn.innerHTML = state.busy
                ? '<span class="spinner" style="width:16px;height:16px"></span>Queuing…'
                : `<i class="ph ph-download-simple"></i>Download ${files.length || ''}`;
        }
    }

    function applySelection(predicate) {
        state.selected.clear();
        for (const file of state.manifest?.files || []) {
            if (isVideo(file) && predicate(file)) state.selected.add(Number(file.id));
        }
        $$('#series-picker-files input[type="checkbox"]').forEach(input => {
            input.checked = state.selected.has(Number(input.dataset.fileId));
        });
        updateSummary();
    }

    function defaultSelection(entry, manifest) {
        state.selected.clear();
        const files = (manifest.files || []).filter(isVideo);
        const wantedSeason = Number(entry.title?._season || manifest.requested_season || 1);
        const wantedEpisode = Number(entry.title?._episode || manifest.requested_episode || 1);
        const exact = files.filter(file => coversEpisode(file, wantedSeason, wantedEpisode));
        if (exact.length) {
            exact.forEach(file => state.selected.add(Number(file.id)));
            return;
        }

        // If a provider did not expose parseable episode names, do not silently
        // queue an entire season. Select one video only and let the user decide.
        const largest = [...files].sort((a, b) => Number(b.bytes || 0) - Number(a.bytes || 0))[0];
        if (largest) state.selected.add(Number(largest.id));
    }

    function pickerSheet(entry, manifest) {
        state.entry = entry;
        state.manifest = manifest;
        state.busy = false;
        defaultSelection(entry, manifest);

        const title = entry.title || {};
        const season = Number(title._season || manifest.requested_season || 1);
        const episode = Number(title._episode || manifest.requested_episode || 1);
        const files = (manifest.files || []).filter(isVideo);
        const releaseTotal = files.reduce((sum, file) => sum + Number(file.bytes || 0), 0);
        const libraryTitle = `${title.title || 'Series'}${title.year ? ` (${String(title.year).match(/\d{4}/)?.[0] || title.year})` : ''}`;

        openSheet(`
          <div class="kicker" style="margin-bottom:5px">Choose episodes</div>
          <div style="font-size:17px;font-weight:600;line-height:1.3">${escapeHtml(title.title || entry.release?.name || 'Series')}</div>
          <div class="facts-note" style="text-align:left;margin-top:6px">
            ${files.length} video file${files.length === 1 ? '' : 's'} · ${escapeHtml(bytesLabel(releaseTotal))} in release
            <br>Saves to <strong>Shows › ${escapeHtml(libraryTitle)} › Season ${String(season).padStart(2, '0')}</strong>
          </div>

          <div style="display:flex;gap:7px;flex-wrap:wrap;margin:14px 0 12px">
            <button class="btn" type="button" data-series-select="episode">S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}</button>
            <button class="btn" type="button" data-series-select="season">Season ${String(season).padStart(2, '0')}</button>
            <button class="btn" type="button" data-series-select="all">All video</button>
            <button class="btn" type="button" data-series-select="none">None</button>
          </div>

          <div id="series-picker-files" class="list" style="max-height:min(48vh,520px);overflow:auto;border-radius:12px">
            ${files.map(file => {
                const id = Number(file.id);
                const path = filePath(file);
                const name = path.split(/[\\/]/).pop() || path || `File ${id}`;
                return `
                  <label class="list-row row-rule" style="cursor:pointer;align-items:center;gap:11px;padding:11px 4px">
                    <input type="checkbox" data-file-id="${id}" ${state.selected.has(id) ? 'checked' : ''}
                           style="width:19px;height:19px;flex:none;accent-color:var(--color-accent)">
                    <div class="list-body" style="min-width:0">
                      <div class="list-title" style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">
                        <span class="tag tag-accent">${escapeHtml(episodeText(file))}</span>
                        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%">${escapeHtml(name)}</span>
                      </div>
                      <div class="list-sub">${escapeHtml(bytesLabel(file.bytes))}</div>
                    </div>
                  </label>`;
            }).join('') || '<div class="empty">No video files were exposed by this release.</div>'}
          </div>

          <div style="position:sticky;bottom:0;background:var(--bg, #0d0d0f);padding-top:13px;margin-top:8px">
            <div id="series-picker-summary" style="font-size:13px;color:var(--text-70);margin-bottom:9px"></div>
            <button class="btn btn-primary btn-block" id="series-picker-download" type="button" style="min-height:48px"></button>
          </div>`);
        updateSummary();
    }

    async function inspectEntry(entry) {
        const infoHash = String(entry?.release?.info_hash || entry?.release?.hash || '').trim();
        if (!infoHash) throw new Error('That release has no usable info hash');
        const title = entry.title || {};
        return api('/debrid/universal/manifest', {
            method: 'POST',
            body: JSON.stringify({
                info_hash: infoHash,
                title: title.title || '',
                year: String(title.year || ''),
                media_type: title.type || 'series',
                season: Number(title._season || 1),
                episode: Number(title._episode || 1),
            }),
        });
    }

    async function openPicker(index) {
        const U = window.NomadUniversalSearch;
        const entry = U?.entries?.[Number(index)];
        if (!entry) return;
        openSheet(`
          <div class="kicker" style="margin-bottom:7px">Inspecting release</div>
          <div style="font-size:16px;margin-bottom:10px">${escapeHtml(entry.title?.title || entry.release?.name || 'Series')}</div>
          <div class="facts-note" style="text-align:left">Reading the provider file manifest before anything is downloaded…</div>
          <div class="bar" style="margin-top:14px"><span style="width:35%"></span></div>`);
        try {
            const manifest = await inspectEntry(entry);
            pickerSheet(entry, manifest);
        } catch (err) {
            const sheet = $('#sheet');
            if (sheet) sheet.innerHTML = `
              <div class="kicker" style="margin-bottom:8px">Could not inspect release</div>
              <div class="facts-note" style="text-align:left">${escapeHtml(err?.message || 'Provider manifest failed')}</div>`;
            toast(err?.message || 'Could not inspect release', 'error', 7000);
        }
    }

    async function queueSelected() {
        if (state.busy) return;
        const chosen = selectedFiles();
        if (!chosen.length || !state.manifest?.torrent_id || !state.entry) return;
        state.busy = true;
        updateSummary();

        const status = $('#series-picker-summary');
        try {
            if (status) status.textContent = `Resolving ${chosen.length} selected file${chosen.length === 1 ? '' : 's'}…`;
            const selection = await api(`/debrid/universal/selection/${encodeURIComponent(state.manifest.torrent_id)}`, {
                method: 'POST',
                body: JSON.stringify({ file_ids: chosen.map(file => Number(file.id)) }),
            });
            const resolved = Array.isArray(selection.files) ? selection.files : [];
            if (!resolved.length) throw new Error('Provider returned no links for the selected files');

            const title = state.entry.title || {};
            let queued = 0;
            for (let i = 0; i < resolved.length; i++) {
                const file = resolved[i];
                if (status) status.textContent = `Preparing ${i + 1} of ${resolved.length}…`;
                const unrestricted = await api('/debrid/unrestrict', {
                    method: 'POST',
                    body: JSON.stringify({ link: file.link }),
                });
                if (!unrestricted?.url) continue;
                const rawPath = filePath(file);
                const rawName = rawPath.split(/[\\/]/).pop() || unrestricted.filename || state.entry.release?.name || 'media.mkv';
                const fallbackSingle = resolved.length === 1;
                const season = Number(file.season || (fallbackSingle ? title._season : 0) || 0);
                const episode = Number(file.episode || (fallbackSingle ? title._episode : 0) || 0);
                await api('/debrid/universal/library-download', {
                    method: 'POST',
                    body: JSON.stringify({
                        url: unrestricted.url,
                        filename: unrestricted.filename || rawName,
                        source_path: rawPath || rawName,
                        title: title.title || '',
                        year: String(title.year || ''),
                        media_type: 'series',
                        season,
                        episode,
                    }),
                });
                queued++;
            }

            closeSheet();
            toast(`${queued} episode${queued === 1 ? '' : 's'} queued with clean series folders`, 'success', 5000);
            if (queued && typeof goTab === 'function') {
                S.dl = 'active';
                goTab('downloads');
            }
        } catch (err) {
            state.busy = false;
            if (status) status.textContent = err?.message || 'Could not queue selected episodes';
            updateSummary();
            toast(err?.message || 'Could not queue selected episodes', 'error', 7000);
        }
    }

    document.addEventListener('change', event => {
        const input = event.target.closest('#series-picker-files input[data-file-id]');
        if (!input) return;
        const id = Number(input.dataset.fileId);
        if (input.checked) state.selected.add(id); else state.selected.delete(id);
        updateSummary();
    });

    document.addEventListener('click', event => {
        const selector = event.target.closest('[data-series-select]');
        if (selector) {
            event.preventDefault();
            const mode = selector.dataset.seriesSelect;
            const title = state.entry?.title || {};
            const wantedSeason = Number(title._season || state.manifest?.requested_season || 1);
            const wantedEpisode = Number(title._episode || state.manifest?.requested_episode || 1);
            if (mode === 'episode') applySelection(file => coversEpisode(file, wantedSeason, wantedEpisode));
            else if (mode === 'season') applySelection(file => Number(file.season || 0) === wantedSeason);
            else if (mode === 'all') applySelection(() => true);
            else applySelection(() => false);
            return;
        }
        if (event.target.closest('#series-picker-download')) {
            event.preventDefault();
            queueSelected();
        }
    });

    // Universal search's older compatibility shim turns Download into the
    // legacy data-grab path during capture. Intercept series only; movie
    // downloads continue through the established movie path.
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-universal-download]');
        if (!button) return;
        const U = window.NomadUniversalSearch;
        const entry = U?.entries?.[Number(button.dataset.universalDownload)];
        if (!entry || !['series', 'show'].includes(String(entry.title?.type || '').toLowerCase())) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        openPicker(button.dataset.universalDownload);
    }, true);
})();
