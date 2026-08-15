/* Nomad Pi persistent reader progress, bookmarks and annotations. */
(() => {
    if (typeof api !== 'function') return;

    const RS = { path: null, saveTimer: null, periodic: null, restoring: false };
    window.NomadReaderState = RS;

    function position() {
        const range = $('#reader-range');
        const value = Number(range?.value || 1);
        const max = Math.max(1, Number(range?.max || 1));
        return { page: Math.max(1, value), total_pages: max };
    }

    function percent() {
        const p = position();
        return p.total_pages > 0 ? Math.max(0, Math.min(100, (p.page / p.total_pages) * 100)) : 0;
    }

    function scheduleSave(delay = 800) {
        if (!RS.path || RS.restoring) return;
        clearTimeout(RS.saveTimer);
        RS.saveTimer = setTimeout(saveProgress, delay);
    }

    async function saveProgress() {
        if (!RS.path) return;
        try {
            await api('/playback/reader/progress', {
                method: 'POST',
                body: JSON.stringify({ path: RS.path, position: position(), percent: percent() }),
            });
        } catch {}
    }

    async function restoreProgress() {
        if (!RS.path) return;
        let data;
        try { data = await api(`/playback/reader/progress?path=${encodeURIComponent(RS.path)}`); }
        catch { return; }
        const saved = data.progress?.position;
        const page = Number(saved?.page || 0);
        if (page <= 1) return;
        RS.restoring = true;
        let attempts = 0;
        const timer = setInterval(() => {
            attempts += 1;
            const range = $('#reader-range');
            const max = Number(range?.max || 1);
            if (range && max > 1) {
                clearInterval(timer);
                range.value = String(Math.max(1, Math.min(max, page)));
                range.dispatchEvent(new Event('input', { bubbles: true }));
                range.dispatchEvent(new Event('change', { bubbles: true }));
                RS.restoring = false;
                toast(`Resumed at page ${Math.max(1, Math.min(max, page))}`, 'info', 1800);
            } else if (attempts > 30) {
                clearInterval(timer);
                RS.restoring = false;
            }
        }, 200);
    }

    function installButton() {
        const top = $('#reader-top');
        const menu = $('#reader-menu');
        if (!top || !menu || $('#reader-marks')) return;
        const button = document.createElement('button');
        button.className = 'btn btn-icon';
        button.id = 'reader-marks';
        button.setAttribute('aria-label', 'Bookmarks and notes');
        button.innerHTML = '<i class="ph ph-bookmark-simple"></i>';
        top.insertBefore(button, menu);
    }

    async function openMarks() {
        if (!RS.path) return;
        let marks = [];
        try { marks = (await api(`/playback/reader/marks?path=${encodeURIComponent(RS.path)}`)).items || []; }
        catch {}
        const pos = position();
        openSheet(`
          <div class="kicker" style="margin-bottom:8px">Bookmarks & notes</div>
          <div class="list-sub" style="margin-bottom:12px">Page ${pos.page} of ${pos.total_pages}</div>
          <div class="btn-row" style="margin-bottom:14px">
            <button class="btn" data-reader-add="bookmark"><i class="ph ph-bookmark-simple"></i>Bookmark</button>
            <button class="btn" data-reader-add="annotation"><i class="ph ph-note-pencil"></i>Add note</button>
          </div>
          <div class="list">${marks.map(mark => `
            <div class="list-row row-rule">
              <button class="list-body" data-reader-jump="${Number(mark.position?.page || 1)}" style="background:none;border:none;text-align:left;color:inherit;cursor:pointer">
                <div class="list-title">${escapeHtml(mark.label || (mark.kind === 'annotation' ? 'Note' : 'Bookmark'))}</div>
                <div class="list-sub">Page ${Number(mark.position?.page || 1)}${mark.note ? ` · ${escapeHtml(mark.note)}` : ''}</div>
              </button>
              <button class="btn btn-icon btn-icon-plain" data-reader-delete="${escapeHtml(mark.id)}"><i class="ph ph-trash"></i></button>
            </div>`).join('') || '<div class="facts-note">No bookmarks or notes yet.</div>'}</div>`);
    }

    async function addMark(kind) {
        if (!RS.path) return;
        const pos = position();
        if (kind === 'annotation') {
            openSheet(`
              <div class="kicker" style="margin-bottom:8px">Note · page ${pos.page}</div>
              <textarea id="reader-note-text" class="input input-plain" rows="5" placeholder="Write a note…" style="resize:vertical"></textarea>
              <button class="btn btn-primary btn-block" id="reader-note-save" style="margin-top:12px">Save note</button>`);
            $('#reader-note-save')?.addEventListener('click', async () => {
                const note = $('#reader-note-text')?.value.trim() || '';
                if (!note) return;
                await createMark('annotation', `Page ${pos.page}`, note, pos);
            }, { once: true });
            return;
        }
        await createMark('bookmark', `Page ${pos.page}`, '', pos);
    }

    async function createMark(kind, label, note, pos) {
        try {
            await api('/playback/reader/marks', {
                method: 'POST',
                body: JSON.stringify({ path: RS.path, kind, label, note, position: pos }),
            });
            toast(kind === 'bookmark' ? 'Page bookmarked' : 'Note saved', 'success', 1800);
            openMarks();
        } catch (err) {
            toast(err.message || 'Could not save reader mark', 'error', 4500);
        }
    }

    function jump(page) {
        const range = $('#reader-range');
        if (!range) return;
        const max = Math.max(1, Number(range.max || 1));
        range.value = String(Math.max(1, Math.min(max, Number(page) || 1)));
        range.dispatchEvent(new Event('input', { bubbles: true }));
        range.dispatchEvent(new Event('change', { bubbles: true }));
        closeSheet();
        scheduleSave(200);
    }

    async function deleteMark(id) {
        try {
            await api(`/playback/reader/marks/${encodeURIComponent(id)}`, { method: 'DELETE' });
            openMarks();
        } catch (err) { toast(err.message || 'Could not delete mark', 'error'); }
    }

    function activate(path) {
        RS.path = path;
        installButton();
        clearInterval(RS.periodic);
        RS.periodic = setInterval(() => {
            if (S?.screen === 'reader') scheduleSave(0);
        }, 15000);
        setTimeout(restoreProgress, 250);
    }

    // The reader has changed names over its lifetime; patch whichever public
    // opener exists and keep this module inert if a build uses none of them.
    ['openReader', 'openBook', 'readBook'].forEach(name => {
        const fn = window[name];
        if (typeof fn !== 'function' || fn.__nomadReaderState) return;
        const wrapped = function(...args) {
            const result = fn.apply(this, args);
            const path = args.find(arg => typeof arg === 'string' && arg.includes('/'));
            if (path) activate(path);
            return result;
        };
        wrapped.__nomadReaderState = true;
        window[name] = wrapped;
        try { eval(`${name} = wrapped`); } catch {}
    });

    if (typeof closeReader === 'function') {
        const oldClose = closeReader;
        closeReader = function readerStateClose(...args) {
            saveProgress();
            clearInterval(RS.periodic);
            RS.periodic = null;
            RS.path = null;
            return oldClose.apply(this, args);
        };
    }

    document.addEventListener('input', event => {
        if (event.target?.id === 'reader-range') scheduleSave();
    }, true);
    document.addEventListener('change', event => {
        if (event.target?.id === 'reader-range') scheduleSave(100);
    }, true);
    document.addEventListener('click', event => {
        if (event.target.closest('#reader-marks')) { event.preventDefault(); openMarks(); return; }
        const add = event.target.closest('[data-reader-add]');
        if (add) { event.preventDefault(); addMark(add.dataset.readerAdd); return; }
        const jumpTo = event.target.closest('[data-reader-jump]');
        if (jumpTo) { event.preventDefault(); jump(jumpTo.dataset.readerJump); return; }
        const del = event.target.closest('[data-reader-delete]');
        if (del) { event.preventDefault(); deleteMark(del.dataset.readerDelete); }
    }, true);
})();
