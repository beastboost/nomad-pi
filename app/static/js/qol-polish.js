/* Nomad Pi lightweight quality-of-life layer: queue controls, Photos selection/albums and small navigation niceties. */
(() => {
    if (typeof api !== 'function') return;

    const Q = {
        selection: false,
        selected: new Set(),
        albums: [],
        itemAlbums: {},
        activeAlbum: '',
        longPress: null,
        longPressed: false,
        downloadBusy: false,
    };
    window.NomadQol = Q;

    const terminalDownloadStates = new Set(['completed', 'failed', 'error', 'cancelled']);
    const validLibraries = new Set(['movies', 'shows', 'music', 'books', 'gallery', 'files']);

    function photosActive() {
        try { return S.tab === 'library' && S.lib === 'gallery'; } catch { return false; }
    }

    function currentProfileId() {
        try {
            const id = typeof nomadProfileId === 'function' ? nomadProfileId() : S?.profile?.id;
            const n = Number(id);
            return Number.isInteger(n) && n > 0 ? n : 0;
        } catch { return 0; }
    }

    function albumKey() {
        return `nomad_gallery_album_${currentProfileId() || 'default'}`;
    }

    function setLastLibrary(value) {
        if (validLibraries.has(value)) localStorage.setItem('nomad_last_library', value);
    }

    function restoreLastLibrary() {
        const value = localStorage.getItem('nomad_last_library');
        if (validLibraries.has(value) && typeof S !== 'undefined') S.lib = value;
    }

    restoreLastLibrary();

    /* ── Downloads ─────────────────────────────────────────────── */

    async function downloadSnapshot() {
        try { return (await api('/debrid/downloads')).downloads || []; }
        catch { return []; }
    }

    async function decorateDownloads(body) {
        if (!body || Q.downloadBusy) return;
        let active = false;
        try { active = S.tab === 'downloads' && S.dl === 'active'; } catch {}
        if (!active) return;
        Q.downloadBusy = true;
        try {
            const list = await downloadSnapshot();
            const running = list.filter(item => !terminalDownloadStates.has(String(item.status || '').toLowerCase()));
            const terminal = list.length - running.length;
            let bar = body.querySelector('#download-qol-bar');
            if (!bar) {
                bar = document.createElement('div');
                bar.id = 'download-qol-bar';
                bar.className = 'download-qol-bar';
                body.prepend(bar);
            }
            bar.innerHTML = `
              <div class="download-qol-copy">
                <strong>${running.length ? `${running.length} active` : 'Queue idle'}</strong>
                <span>${terminal ? `${terminal} finished / failed` : 'Nothing waiting to clear'}</span>
              </div>
              <div class="download-qol-actions">
                ${terminal ? '<button class="btn" data-qol-clear-finished><i class="ph ph-broom"></i>Clear finished</button>' : ''}
                ${list.length ? '<button class="btn" data-qol-clear-queue><i class="ph ph-trash"></i>Clear queue</button>' : ''}
              </div>`;
        } finally {
            Q.downloadBusy = false;
        }
    }

    async function redrawDownloads() {
        const body = document.querySelector('#dl-body');
        if (body && typeof renderActiveDownloads === 'function') await renderActiveDownloads(body);
    }

    async function clearFinished() {
        try {
            const result = await api('/debrid/downloads/clear', { method: 'POST' });
            if (typeof toast === 'function') toast(`${result.cleared || 0} queue item${result.cleared === 1 ? '' : 's'} cleared`, 'success', 2200);
            await redrawDownloads();
        } catch (err) {
            if (typeof toast === 'function') toast(err.message || 'Could not clear finished downloads', 'error', 4000);
        }
    }

    async function clearQueue() {
        const list = await downloadSnapshot();
        if (!list.length) return;
        const active = list.filter(item => !terminalDownloadStates.has(String(item.status || '').toLowerCase()));
        const question = active.length
            ? `Cancel ${active.length} active download${active.length === 1 ? '' : 's'} and remove all finished/failed queue entries? Downloaded media already completed on disk will not be deleted.`
            : 'Remove all finished, failed and cancelled entries from the queue? Downloaded media on disk will not be deleted.';
        const ok = typeof confirmDialog === 'function'
            ? await confirmDialog('Clear download queue?', question, active.length ? 'Cancel & clear' : 'Clear queue')
            : confirm(question);
        if (!ok) return;

        try {
            // Deliberately serial: avoid a burst of cancellation requests on tiny appliances.
            for (const item of active) {
                if (!item.id) continue;
                try { await api(`/debrid/download/${encodeURIComponent(item.id)}`, { method: 'DELETE' }); }
                catch {}
            }
            await api('/debrid/downloads/clear', { method: 'POST' });
            if (typeof toast === 'function') toast('Download queue cleared', 'success', 2200);
            await redrawDownloads();
        } catch (err) {
            if (typeof toast === 'function') toast(err.message || 'Could not clear download queue', 'error', 4200);
        }
    }

    if (typeof renderActiveDownloads === 'function') {
        const previousRenderDownloads = renderActiveDownloads;
        renderActiveDownloads = async function qolRenderDownloads(body, ...args) {
            const result = await previousRenderDownloads.call(this, body, ...args);
            await decorateDownloads(body);
            return result;
        };
    }

    /* ── Photos albums / multi-select ─────────────────────────── */

    async function refreshAlbums() {
        if (!photosActive() || !window.NomadGallery) return;
        try {
            const data = await api('/playback/gallery/albums');
            Q.albums = Array.isArray(data.albums) ? data.albums : [];
            Q.itemAlbums = data.item_albums || {};
            const saved = localStorage.getItem(albumKey()) || '';
            Q.activeAlbum = saved && Q.albums.some(item => item.name === saved) ? saved : '';
            injectPhotoTools();
            applyAlbumFilter();
        } catch (err) {
            console.debug('[Nomad Photos albums]', err);
        }
    }

    function injectPhotoTools() {
        const strip = document.querySelector('.gallery-profile-strip');
        const timeline = document.querySelector('.gallery-timeline');
        if (!strip || !timeline) return;

        let actions = strip.querySelector('.gallery-qol-actions');
        if (!actions) {
            actions = document.createElement('div');
            actions.className = 'gallery-qol-actions';
            actions.innerHTML = `
              <button class="btn" data-qol-photo-select><i class="ph ph-check-square"></i>Select</button>
              <button class="btn" data-qol-albums-manage><i class="ph ph-folders"></i>Albums</button>`;
            strip.appendChild(actions);
        }

        let bar = document.querySelector('#gallery-album-bar');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'gallery-album-bar';
            bar.className = 'gallery-album-bar';
            timeline.before(bar);
        }
        bar.innerHTML = `
          <button class="chip${!Q.activeAlbum ? ' active' : ''}" data-qol-album-filter="">All photos</button>
          ${Q.albums.map(album => `<button class="chip${Q.activeAlbum === album.name ? ' active' : ''}" data-qol-album-filter="${escapeHtml(album.name)}">${escapeHtml(album.name)} <span>${album.count}</span></button>`).join('')}
          <button class="chip" data-qol-album-new><i class="ph ph-plus"></i>New album</button>`;
        renderSelectionBar();
    }

    function applyAlbumFilter() {
        if (!photosActive() || !window.NomadGallery) return;
        const items = window.NomadGallery.items || [];
        let visible = 0;
        document.querySelectorAll('.gallery-thumb[data-gallery-open]').forEach(thumb => {
            const index = Number(thumb.dataset.galleryOpen);
            const item = items[index];
            const album = item ? (Q.itemAlbums[item.id] || '') : '';
            const show = !Q.activeAlbum || album === Q.activeAlbum;
            thumb.hidden = !show;
            if (show) visible += 1;
        });
        document.querySelectorAll('.gallery-day').forEach(day => {
            const any = [...day.querySelectorAll('.gallery-thumb[data-gallery-open]')].some(thumb => !thumb.hidden);
            day.hidden = !any;
        });
        const count = document.querySelector('#lib-count');
        if (count) count.textContent = `${visible} photo${visible === 1 ? '' : 's'}${Q.activeAlbum ? ` · ${Q.activeAlbum}` : ''}`;
        document.querySelectorAll('[data-qol-album-filter]').forEach(button => {
            button.classList.toggle('active', (button.dataset.qolAlbumFilter || '') === Q.activeAlbum);
        });
    }

    function setAlbumFilter(name) {
        Q.activeAlbum = name || '';
        localStorage.setItem(albumKey(), Q.activeAlbum);
        exitSelection();
        applyAlbumFilter();
    }

    function enterSelection(index = null) {
        if (!photosActive() || !window.NomadGallery) return;
        Q.selection = true;
        if (Number.isInteger(index) && window.NomadGallery.items?.[index]) {
            Q.selected.add(window.NomadGallery.items[index].id);
        }
        document.documentElement.classList.add('gallery-selecting');
        syncSelectedThumbs();
        renderSelectionBar();
    }

    function exitSelection() {
        Q.selection = false;
        Q.selected.clear();
        document.documentElement.classList.remove('gallery-selecting');
        syncSelectedThumbs();
        renderSelectionBar();
    }

    function toggleSelected(index) {
        const item = window.NomadGallery?.items?.[index];
        if (!item) return;
        if (Q.selected.has(item.id)) Q.selected.delete(item.id);
        else Q.selected.add(item.id);
        syncSelectedThumbs();
        renderSelectionBar();
    }

    function syncSelectedThumbs() {
        const items = window.NomadGallery?.items || [];
        document.querySelectorAll('.gallery-thumb[data-gallery-open]').forEach(thumb => {
            const item = items[Number(thumb.dataset.galleryOpen)];
            thumb.classList.toggle('gallery-selected', !!item && Q.selected.has(item.id));
        });
    }

    function renderSelectionBar() {
        let bar = document.querySelector('#gallery-selection-bar');
        if (!Q.selection || !photosActive()) {
            bar?.remove();
            return;
        }
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'gallery-selection-bar';
            bar.className = 'gallery-selection-bar';
            document.body.appendChild(bar);
        }
        bar.innerHTML = `
          <div class="gallery-selection-count"><strong>${Q.selected.size}</strong><span>selected</span></div>
          <button class="btn" data-qol-select-all>All</button>
          <button class="btn" data-qol-move-selected ${Q.selected.size ? '' : 'disabled'}><i class="ph ph-folder-notch-open"></i>Album</button>
          <button class="btn btn-danger" data-qol-delete-selected ${Q.selected.size ? '' : 'disabled'}><i class="ph ph-trash"></i>Delete</button>
          <button class="btn btn-icon" data-qol-select-cancel aria-label="Cancel selection"><i class="ph ph-x"></i></button>`;
    }

    function selectAllVisible() {
        const items = window.NomadGallery?.items || [];
        document.querySelectorAll('.gallery-thumb[data-gallery-open]').forEach(thumb => {
            if (thumb.hidden) return;
            const item = items[Number(thumb.dataset.galleryOpen)];
            if (item) Q.selected.add(item.id);
        });
        syncSelectedThumbs();
        renderSelectionBar();
    }

    function openNewAlbum(afterCreate = null) {
        if (typeof openSheet !== 'function') return;
        openSheet(`
          <div class="kicker" style="margin-bottom:7px">New photo album</div>
          <div class="list-sub" style="margin-bottom:12px">Albums are real folders inside this profile's private photo library.</div>
          <input class="input input-plain" id="qol-album-name" maxlength="120" placeholder="Album name" autocomplete="off">
          <button class="btn btn-primary btn-block" id="qol-album-create" style="margin-top:12px">Create album</button>`);
        setTimeout(() => document.querySelector('#qol-album-name')?.focus(), 60);
        const create = async () => {
            const name = document.querySelector('#qol-album-name')?.value.trim() || '';
            if (!name) return;
            try {
                await api('/playback/gallery/albums', { method: 'POST', body: JSON.stringify({ name }) });
                if (typeof closeSheet === 'function') closeSheet();
                await refreshAlbums();
                if (afterCreate) await afterCreate(name);
                else {
                    setAlbumFilter(name);
                    if (typeof toast === 'function') toast(`${name} created`, 'success', 1800);
                }
            } catch (err) {
                if (typeof toast === 'function') toast(err.message || 'Could not create album', 'error', 4000);
            }
        };
        document.querySelector('#qol-album-create')?.addEventListener('click', create, { once: true });
        document.querySelector('#qol-album-name')?.addEventListener('keydown', event => { if (event.key === 'Enter') create(); });
    }

    function openMoveSheet() {
        if (!Q.selected.size || typeof openSheet !== 'function') return;
        openSheet(`
          <div class="kicker" style="margin-bottom:7px">Move ${Q.selected.size} selected</div>
          <div class="list-sub" style="margin-bottom:12px">Choose an album. Moving changes the folder organization but keeps the photos in this profile.</div>
          <div class="list">
            <button class="sheet-option row-rule" data-qol-move-album=""><span>All photos · no album</span><i class="ph ph-images"></i></button>
            ${Q.albums.map(album => `<button class="sheet-option row-rule" data-qol-move-album="${escapeHtml(album.name)}"><span>${escapeHtml(album.name)}</span><span class="list-sub">${album.count}</span></button>`).join('')}
            <button class="sheet-option row-rule" data-qol-move-new><span>New album…</span><i class="ph ph-plus"></i></button>
          </div>`);
    }

    async function moveSelected(album) {
        if (!Q.selected.size) return;
        try {
            const result = await api('/playback/gallery/move', {
                method: 'POST', body: JSON.stringify({ item_ids: [...Q.selected], album: album || '' }),
            });
            if (typeof closeSheet === 'function') closeSheet();
            exitSelection();
            if (typeof loadLibrary === 'function') await loadLibrary();
            if (typeof toast === 'function') toast(`${result.moved || 0} item${result.moved === 1 ? '' : 's'} moved${album ? ` to ${album}` : ''}`, 'success', 2200);
        } catch (err) {
            if (typeof toast === 'function') toast(err.message || 'Could not move photos', 'error', 4200);
        }
    }

    async function deleteSelected() {
        if (!Q.selected.size) return;
        const count = Q.selected.size;
        const ok = typeof confirmDialog === 'function'
            ? await confirmDialog(`Delete ${count} photo${count === 1 ? '' : 's'}?`, 'This permanently removes the selected items from this profile’s private photo library.', 'Delete')
            : confirm(`Delete ${count} selected photo${count === 1 ? '' : 's'}?`);
        if (!ok) return;
        try {
            const result = await api('/playback/gallery/bulk-delete', {
                method: 'POST', body: JSON.stringify({ item_ids: [...Q.selected] }),
            });
            exitSelection();
            if (typeof loadLibrary === 'function') await loadLibrary();
            if (typeof toast === 'function') toast(`${result.deleted || 0} photo${result.deleted === 1 ? '' : 's'} deleted`, 'success', 2000);
        } catch (err) {
            if (typeof toast === 'function') toast(err.message || 'Could not delete photos', 'error', 4200);
        }
    }

    function openAlbumManager() {
        if (typeof openSheet !== 'function') return;
        openSheet(`
          <div class="kicker" style="margin-bottom:7px">Photo albums</div>
          <div class="list-sub" style="margin-bottom:12px">Folders belong only to the active profile.</div>
          <div class="list">
            ${Q.albums.length ? Q.albums.map(album => `<button class="sheet-option row-rule" data-qol-album-filter-sheet="${escapeHtml(album.name)}"><span>${escapeHtml(album.name)}</span><span class="list-sub">${album.count} items</span></button>`).join('') : '<div class="facts-note">No albums yet.</div>'}
          </div>
          <button class="btn btn-primary btn-block" data-qol-album-new style="margin-top:12px"><i class="ph ph-plus"></i>New album</button>`);
    }

    if (typeof loadLibrary === 'function') {
        const previousLoadLibrary = loadLibrary;
        loadLibrary = async function qolLoadLibrary(...args) {
            const result = await previousLoadLibrary.apply(this, args);
            if (photosActive()) setTimeout(refreshAlbums, 0);
            else exitSelection();
            return result;
        };
    }

    /* ── Small global niceties ─────────────────────────────────── */

    function scrollCurrentToTop() {
        const screen = document.querySelector(`.screen[data-screen="${S?.screen || ''}"]`);
        const scroller = screen?.querySelector('.screen-scroll, .lib-body, .dl-body') || screen;
        if (scroller?.scrollTo) scroller.scrollTo({ top: 0, behavior: 'smooth' });
    }

    window.addEventListener('offline', () => {
        if (typeof toast === 'function') toast('Internet connection lost — local Nomad media still works.', 'warn', 3500);
    });
    window.addEventListener('online', () => {
        if (typeof toast === 'function') toast('Internet connection restored', 'success', 2200);
    });

    window.addEventListener('pointerdown', event => {
        if (!photosActive() || Q.selection) return;
        const thumb = event.target.closest?.('.gallery-thumb[data-gallery-open]');
        if (!thumb) return;
        clearTimeout(Q.longPress);
        Q.longPressed = false;
        const index = Number(thumb.dataset.galleryOpen);
        Q.longPress = setTimeout(() => {
            Q.longPressed = true;
            enterSelection(index);
            try { navigator.vibrate?.(18); } catch {}
        }, 480);
    }, true);
    for (const name of ['pointerup', 'pointercancel', 'pointermove']) {
        window.addEventListener(name, () => clearTimeout(Q.longPress), true);
    }

    window.addEventListener('click', async event => {
        const lib = event.target.closest?.('[data-lib]');
        if (lib?.dataset.lib) setLastLibrary(lib.dataset.lib);

        const tab = event.target.closest?.('[data-tab]');
        if (tab?.dataset.tab && typeof S !== 'undefined' && S.tab === tab.dataset.tab && S.screen === (typeof TAB_SCREENS !== 'undefined' ? TAB_SCREENS[S.tab] : S.screen)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            scrollCurrentToTop();
            return;
        }

        if (event.target.closest?.('[data-qol-clear-finished]')) { event.preventDefault(); event.stopImmediatePropagation(); await clearFinished(); return; }
        if (event.target.closest?.('[data-qol-clear-queue]')) { event.preventDefault(); event.stopImmediatePropagation(); await clearQueue(); return; }

        if (!photosActive()) return;
        const thumb = event.target.closest?.('.gallery-thumb[data-gallery-open]');
        if (thumb && (Q.selection || Q.longPressed)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (!Q.longPressed) toggleSelected(Number(thumb.dataset.galleryOpen));
            Q.longPressed = false;
            return;
        }
        if (event.target.closest?.('[data-qol-photo-select]')) { event.preventDefault(); event.stopImmediatePropagation(); enterSelection(); return; }
        if (event.target.closest?.('[data-qol-select-cancel]')) { event.preventDefault(); event.stopImmediatePropagation(); exitSelection(); return; }
        if (event.target.closest?.('[data-qol-select-all]')) { event.preventDefault(); event.stopImmediatePropagation(); selectAllVisible(); return; }
        if (event.target.closest?.('[data-qol-move-selected]')) { event.preventDefault(); event.stopImmediatePropagation(); openMoveSheet(); return; }
        if (event.target.closest?.('[data-qol-delete-selected]')) { event.preventDefault(); event.stopImmediatePropagation(); await deleteSelected(); return; }
        const filter = event.target.closest?.('[data-qol-album-filter]');
        if (filter) { event.preventDefault(); event.stopImmediatePropagation(); setAlbumFilter(filter.dataset.qolAlbumFilter || ''); return; }
        const filterSheet = event.target.closest?.('[data-qol-album-filter-sheet]');
        if (filterSheet) {
            event.preventDefault(); event.stopImmediatePropagation();
            if (typeof closeSheet === 'function') closeSheet();
            setAlbumFilter(filterSheet.dataset.qolAlbumFilterSheet || '');
            return;
        }
        if (event.target.closest?.('[data-qol-album-new]')) { event.preventDefault(); event.stopImmediatePropagation(); openNewAlbum(); return; }
        if (event.target.closest?.('[data-qol-albums-manage]')) { event.preventDefault(); event.stopImmediatePropagation(); openAlbumManager(); return; }
        if (event.target.closest?.('[data-qol-move-new]')) {
            event.preventDefault(); event.stopImmediatePropagation();
            if (typeof closeSheet === 'function') closeSheet();
            openNewAlbum(async name => moveSelected(name));
            return;
        }
        const move = event.target.closest?.('[data-qol-move-album]');
        if (move) { event.preventDefault(); event.stopImmediatePropagation(); await moveSelected(move.dataset.qolMoveAlbum || ''); }
    }, true);

    window.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (Q.selection) { event.preventDefault(); exitSelection(); return; }
        const sheet = document.querySelector('#sheet');
        if (sheet && !sheet.classList.contains('hidden') && typeof closeSheet === 'function') {
            event.preventDefault(); closeSheet();
        }
    });

    setTimeout(() => {
        if (photosActive()) refreshAlbums();
        const body = document.querySelector('#dl-body');
        if (body) decorateDownloads(body);
    }, 700);
})();
