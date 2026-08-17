/* Nomad Photos — profile-private, swipeable gallery inspired by phone photo apps. */
(() => {
    if (typeof loadLibrary !== 'function' || typeof api !== 'function') return;

    const previousLoadLibrary = loadLibrary;
    const G = {
        items: [],
        profile: null,
        index: -1,
        observer: null,
        pointerId: null,
        startX: 0,
        dragX: 0,
        dragging: false,
        chrome: true,
    };
    window.NomadGallery = G;

    function profileId() {
        try {
            const id = typeof nomadProfileId === 'function' ? nomadProfileId() : S?.profile?.id;
            const n = Number(id);
            return Number.isInteger(n) && n > 0 ? n : null;
        } catch { return null; }
    }

    function itemUrl(item) {
        const t = typeof token === 'function' ? token() : localStorage.getItem('nomad_auth_token');
        const pid = profileId();
        const params = new URLSearchParams();
        if (t) params.set('token', t);
        if (pid) params.set('profile_id', String(pid));
        return `${API}/playback/gallery/item/${encodeURIComponent(item.id)}?${params.toString()}`;
    }

    function fmtDate(value, options = {}) {
        const d = new Date(value || 0);
        if (!Number.isFinite(d.getTime())) return '';
        return d.toLocaleDateString(undefined, options);
    }

    function dayKey(item) {
        const d = new Date(item.taken_at || (Number(item.mtime || 0) * 1000));
        if (!Number.isFinite(d.getTime())) return 'Unknown date';
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const then = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        const days = Math.round((today - then) / 86400000);
        if (days === 0) return 'Today';
        if (days === 1) return 'Yesterday';
        if (days < 7 && days > 1) return d.toLocaleDateString(undefined, { weekday: 'long' });
        return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }

    function ensureViewer() {
        let viewer = document.querySelector('#nomad-photo-viewer');
        if (viewer) return viewer;
        viewer = document.createElement('div');
        viewer.id = 'nomad-photo-viewer';
        viewer.className = 'nomad-photo-viewer hidden';
        viewer.innerHTML = `
          <div class="photo-viewer-stage" id="photo-viewer-stage">
            <div class="photo-viewer-media" id="photo-viewer-media"></div>
          </div>
          <div class="photo-viewer-top" id="photo-viewer-top">
            <button class="btn btn-icon photo-viewer-close" id="photo-viewer-close" aria-label="Close"><i class="ph ph-x"></i></button>
            <div class="photo-viewer-copy">
              <div class="photo-viewer-title" id="photo-viewer-title"></div>
              <div class="photo-viewer-sub" id="photo-viewer-sub"></div>
            </div>
            <button class="btn btn-icon" id="photo-viewer-more" aria-label="Photo actions"><i class="ph ph-dots-three"></i></button>
          </div>
          <button class="photo-viewer-nav photo-viewer-prev" id="photo-viewer-prev" aria-label="Previous"><i class="ph ph-caret-left"></i></button>
          <button class="photo-viewer-nav photo-viewer-next" id="photo-viewer-next" aria-label="Next"><i class="ph ph-caret-right"></i></button>
          <div class="photo-viewer-count" id="photo-viewer-count"></div>`;
        document.body.appendChild(viewer);
        return viewer;
    }

    function preload(index) {
        for (const i of [index - 1, index + 1]) {
            const item = G.items[i];
            if (!item || item.kind !== 'image') continue;
            const image = new Image();
            image.src = itemUrl(item);
        }
    }

    function renderViewer(direction = 0) {
        const viewer = ensureViewer();
        const item = G.items[G.index];
        if (!item) return closeViewer();
        const media = viewer.querySelector('#photo-viewer-media');
        const src = itemUrl(item);
        media.classList.remove('slide-next', 'slide-prev');
        media.innerHTML = item.kind === 'video'
            ? `<video src="${escapeHtml(src)}" controls playsinline preload="metadata"></video>`
            : `<img src="${escapeHtml(src)}" alt="${escapeHtml(item.name || '')}" draggable="false">`;
        if (direction) {
            void media.offsetWidth;
            media.classList.add(direction > 0 ? 'slide-next' : 'slide-prev');
        }
        viewer.querySelector('#photo-viewer-title').textContent = item.name || 'Photo';
        viewer.querySelector('#photo-viewer-sub').textContent = fmtDate(item.taken_at || Number(item.mtime || 0) * 1000, { dateStyle: 'medium', timeStyle: 'short' });
        viewer.querySelector('#photo-viewer-count').textContent = `${G.index + 1} / ${G.items.length}`;
        viewer.querySelector('#photo-viewer-prev').disabled = G.index <= 0;
        viewer.querySelector('#photo-viewer-next').disabled = G.index >= G.items.length - 1;
        media.style.transform = '';
        preload(G.index);
    }

    function openViewer(index) {
        if (!G.items[index]) return;
        G.index = index;
        G.chrome = true;
        const viewer = ensureViewer();
        viewer.classList.remove('hidden', 'chrome-hidden');
        document.documentElement.classList.add('photo-viewer-open');
        renderViewer();
    }

    function closeViewer() {
        const viewer = document.querySelector('#nomad-photo-viewer');
        viewer?.classList.add('hidden');
        const video = viewer?.querySelector('video');
        if (video) { try { video.pause(); } catch {} }
        document.documentElement.classList.remove('photo-viewer-open');
        G.index = -1;
        G.dragging = false;
        G.pointerId = null;
    }

    function move(delta) {
        const next = G.index + delta;
        if (next < 0 || next >= G.items.length) return;
        const video = document.querySelector('#photo-viewer-media video');
        if (video) { try { video.pause(); } catch {} }
        G.index = next;
        renderViewer(delta);
    }

    function toggleChrome() {
        const viewer = document.querySelector('#nomad-photo-viewer');
        if (!viewer) return;
        G.chrome = !G.chrome;
        viewer.classList.toggle('chrome-hidden', !G.chrome);
    }

    function lazyImages() {
        G.observer?.disconnect();
        G.observer = new IntersectionObserver(entries => {
            for (const entry of entries) {
                if (!entry.isIntersecting) continue;
                const img = entry.target;
                const src = img.dataset.src;
                if (src) { img.src = src; delete img.dataset.src; }
                G.observer.unobserve(img);
            }
        }, { rootMargin: '500px 0px' });
        document.querySelectorAll('#lib-body img[data-gallery-lazy]').forEach(img => G.observer.observe(img));
    }

    function renderGrid() {
        const body = document.querySelector('#lib-body');
        if (!body) return;
        document.querySelector('#lib-count').textContent = `${G.items.length} photo${G.items.length === 1 ? '' : 's'}`;

        if (!G.items.length) {
            body.innerHTML = `
              <div class="gallery-empty">
                <i class="ph ph-images-square"></i>
                <h3>No photos yet</h3>
                <p>This is ${escapeHtml(G.profile?.name || 'this profile')}'s private photo library.</p>
                <button class="btn btn-primary" data-gallery-upload><i class="ph ph-cloud-arrow-up"></i>Add photos</button>
              </div>`;
            return;
        }

        const groups = new Map();
        G.items.forEach((item, index) => {
            const key = dayKey(item);
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push({ item, index });
        });

        body.innerHTML = `
          <div class="gallery-profile-strip">
            <div><strong>${escapeHtml(G.profile?.name || 'Profile')}</strong><span>Private photo library</span></div>
            <button class="btn" data-gallery-upload><i class="ph ph-plus"></i>Add</button>
          </div>
          <div class="gallery-timeline">
            ${[...groups.entries()].map(([label, entries]) => `
              <section class="gallery-day">
                <div class="gallery-day-head">${escapeHtml(label)}</div>
                <div class="gallery-photo-grid">
                  ${entries.map(({ item, index }) => {
                      const src = itemUrl(item);
                      if (item.kind === 'video') {
                          return `<button class="gallery-thumb gallery-video-thumb" data-gallery-open="${index}" aria-label="${escapeHtml(item.name)}"><i class="ph-fill ph-play-circle"></i><span>${escapeHtml(item.name)}</span></button>`;
                      }
                      return `<button class="gallery-thumb" data-gallery-open="${index}" aria-label="${escapeHtml(item.name)}"><img data-gallery-lazy data-src="${escapeHtml(src)}" alt="" decoding="async"><span class="gallery-thumb-loader"></span></button>`;
                  }).join('')}
                </div>
              </section>`).join('')}
          </div>`;
        lazyImages();
    }

    async function loadGallery() {
        if (typeof renderLibTabs === 'function') renderLibTabs();
        const body = document.querySelector('#lib-body');
        if (!body) return;
        body.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
        try {
            const data = await api('/playback/gallery?limit=1500');
            G.items = Array.isArray(data.items) ? data.items : [];
            G.profile = data.profile || null;
            S.libItems = [];
            renderGrid();
        } catch (err) {
            body.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(err.message || 'Could not load photos')}</div>`;
            document.querySelector('#lib-count').textContent = '';
        }
    }

    loadLibrary = async function galleryAwareLoadLibrary(...args) {
        if (typeof S !== 'undefined' && S.lib === 'gallery') return loadGallery();
        closeViewer();
        return previousLoadLibrary.apply(this, args);
    };

    function chooseFiles() {
        let input = document.querySelector('#nomad-gallery-file-input');
        if (!input) {
            input = document.createElement('input');
            input.id = 'nomad-gallery-file-input';
            input.type = 'file';
            input.multiple = true;
            input.accept = 'image/*,video/mp4,video/quicktime,video/webm';
            input.className = 'hidden';
            document.body.appendChild(input);
            input.addEventListener('change', () => uploadFiles(input.files));
        }
        input.value = '';
        input.click();
    }

    async function uploadFiles(fileList) {
        const files = Array.from(fileList || []);
        if (!files.length) return;
        const form = new FormData();
        files.slice(0, 200).forEach(file => form.append('files', file, file.name));
        const t = typeof token === 'function' ? token() : localStorage.getItem('nomad_auth_token');
        const pid = profileId();
        const headers = {};
        if (t) headers.Authorization = `Bearer ${t}`;
        if (pid) headers['X-Nomad-Profile-ID'] = String(pid);
        if (typeof toast === 'function') toast(`Uploading ${files.length} item${files.length === 1 ? '' : 's'}…`, 'info', 3000);
        try {
            const res = await fetch(`${API}/playback/gallery/upload${pid ? `?profile_id=${encodeURIComponent(pid)}` : ''}`, {
                method: 'POST', headers, body: form,
            });
            if (!res.ok) {
                let message = `Upload failed (${res.status})`;
                try { const data = await res.json(); message = data.detail || message; } catch {}
                throw new Error(message);
            }
            const data = await res.json();
            if (typeof toast === 'function') toast(`${data.count || 0} item${data.count === 1 ? '' : 's'} added`, 'success', 2200);
            await loadGallery();
        } catch (err) {
            if (typeof toast === 'function') toast(err.message || 'Photo upload failed', 'error', 4500);
        }
    }

    async function openActions() {
        const item = G.items[G.index];
        if (!item || typeof openSheet !== 'function') return;
        openSheet(`
          <div class="kicker" style="margin-bottom:8px">Photo</div>
          <div class="list-sub" style="margin-bottom:12px">${escapeHtml(item.name || '')}</div>
          <div class="list">
            <a class="sheet-option row-rule" href="${escapeHtml(itemUrl(item))}" target="_blank" rel="noopener"><span>Open original</span><i class="ph ph-arrow-square-out"></i></a>
            ${item.legacy ? '' : `<button class="sheet-option row-rule" data-gallery-delete><span>Delete from this profile</span><i class="ph ph-trash"></i></button>`}
          </div>`);
    }

    async function deleteCurrent() {
        const item = G.items[G.index];
        if (!item) return;
        const ok = typeof confirmDialog === 'function'
            ? await confirmDialog('Delete photo?', 'This removes it from this profile’s private library.', 'Delete')
            : confirm('Delete this photo?');
        if (!ok) return;
        try {
            await api(`/playback/gallery/item/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
            const old = G.index;
            G.items.splice(old, 1);
            if (!G.items.length) closeViewer();
            else { G.index = Math.min(old, G.items.length - 1); renderViewer(); }
            closeSheet?.();
            renderGrid();
            toast?.('Photo deleted', 'success', 1800);
        } catch (err) { toast?.(err.message || 'Could not delete photo', 'error', 4000); }
    }

    document.addEventListener('click', event => {
        const thumb = event.target.closest?.('[data-gallery-open]');
        if (thumb) {
            event.preventDefault();
            event.stopImmediatePropagation();
            openViewer(Number(thumb.dataset.galleryOpen));
            return;
        }
        if (event.target.closest?.('[data-gallery-upload]')) {
            event.preventDefault(); event.stopImmediatePropagation(); chooseFiles(); return;
        }
        if (event.target.closest?.('#photo-viewer-close')) { event.preventDefault(); closeViewer(); return; }
        if (event.target.closest?.('#photo-viewer-prev')) { event.preventDefault(); move(-1); return; }
        if (event.target.closest?.('#photo-viewer-next')) { event.preventDefault(); move(1); return; }
        if (event.target.closest?.('#photo-viewer-more')) { event.preventDefault(); openActions(); return; }
        if (event.target.closest?.('[data-gallery-delete]')) { event.preventDefault(); deleteCurrent(); return; }
        if (event.target.closest?.('#photo-viewer-media') && !event.target.closest('video')) toggleChrome();
    }, true);

    document.addEventListener('pointerdown', event => {
        const stage = event.target.closest?.('#photo-viewer-stage');
        if (!stage || event.target.closest('video')) return;
        G.pointerId = event.pointerId;
        G.startX = event.clientX;
        G.dragX = 0;
        G.dragging = true;
        try { stage.setPointerCapture(event.pointerId); } catch {}
    }, true);
    document.addEventListener('pointermove', event => {
        if (!G.dragging || event.pointerId !== G.pointerId) return;
        G.dragX = event.clientX - G.startX;
        const media = document.querySelector('#photo-viewer-media');
        if (media) media.style.transform = `translate3d(${G.dragX}px,0,0) scale(${Math.max(0.94, 1 - Math.abs(G.dragX) / 1800)})`;
    }, true);
    document.addEventListener('pointerup', event => {
        if (!G.dragging || event.pointerId !== G.pointerId) return;
        const dx = G.dragX;
        G.dragging = false;
        G.pointerId = null;
        const media = document.querySelector('#photo-viewer-media');
        if (media) media.style.transform = '';
        if (Math.abs(dx) >= 55) move(dx < 0 ? 1 : -1);
    }, true);
    document.addEventListener('pointercancel', () => {
        G.dragging = false; G.pointerId = null;
        const media = document.querySelector('#photo-viewer-media');
        if (media) media.style.transform = '';
    }, true);

    document.addEventListener('keydown', event => {
        const viewer = document.querySelector('#nomad-photo-viewer');
        if (!viewer || viewer.classList.contains('hidden')) return;
        if (event.key === 'ArrowLeft') move(-1);
        if (event.key === 'ArrowRight') move(1);
        if (event.key === 'Escape') closeViewer();
    });
})();
