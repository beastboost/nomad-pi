/* Nomad Pi persistent reader progress, EPUB CFI, bookmarks and annotations. */
(() => {
    if (typeof api !== 'function') return;

    const RS = {
        path: null,
        saveTimer: null,
        periodic: null,
        restoring: false,
        epubLocation: null,
        epubBoundTo: null,
        marks: new Map(),
    };
    window.NomadReaderState = RS;

    function epubPosition() {
        if (typeof R === 'undefined' || R?.kind !== 'epub' || !R?.rendition) return null;
        let loc = RS.epubLocation;
        try { loc = R.rendition.currentLocation?.() || loc; } catch {}
        if (Array.isArray(loc)) loc = loc[0];
        const start = loc?.start || {};
        const end = loc?.end || {};
        const pctRaw = Number(start.percentage);
        const pct = Number.isFinite(pctRaw)
            ? Math.max(0, Math.min(1, pctRaw))
            : Math.max(0, Math.min(1, Number(R.index || 0)));
        if (!start.cfi && !start.href && !Number.isFinite(pct)) return null;
        return {
            kind: 'epub',
            cfi: start.cfi || null,
            end_cfi: end.cfi || null,
            href: start.href || null,
            percentage: pct,
            displayed_page: Number(start.displayed?.page || 0) || null,
            displayed_total: Number(start.displayed?.total || 0) || null,
            location: Number(start.location || 0) || null,
        };
    }

    function position() {
        const epub = epubPosition();
        if (epub) return epub;
        const range = $('#reader-range');
        const value = Number(range?.value || 1);
        const max = Math.max(1, Number(range?.max || 1));
        return {
            kind: (typeof R !== 'undefined' && R?.kind) || 'paged',
            page: Math.max(1, value),
            total_pages: max,
        };
    }

    function percentFromPosition(pos) {
        if (pos?.kind === 'epub') {
            const pct = Number(pos.percentage);
            return Number.isFinite(pct) ? Math.max(0, Math.min(100, pct * 100)) : 0;
        }
        return pos?.total_pages > 0
            ? Math.max(0, Math.min(100, (Number(pos.page || 1) / Number(pos.total_pages)) * 100))
            : 0;
    }

    function percent() {
        return percentFromPosition(position());
    }

    function locationLabel(pos) {
        if (pos?.kind === 'epub') {
            const pct = Math.round(percentFromPosition(pos));
            const page = Number(pos.displayed_page || 0);
            const total = Number(pos.displayed_total || 0);
            if (page && total) return `${pct}% · page ${page}/${total}`;
            return `${pct}% through book`;
        }
        return `Page ${Number(pos?.page || 1)} of ${Number(pos?.total_pages || 1)}`;
    }

    function shortLocationLabel(pos) {
        if (pos?.kind === 'epub') return `${Math.round(percentFromPosition(pos))}%`;
        return `Page ${Number(pos?.page || 1)}`;
    }

    function scheduleSave(delay = 800) {
        if (!RS.path || RS.restoring) return;
        clearTimeout(RS.saveTimer);
        RS.saveTimer = setTimeout(saveProgress, delay);
    }

    async function saveProgress() {
        if (!RS.path) return;
        const pos = position();
        try {
            await api('/playback/reader/progress', {
                method: 'POST',
                body: JSON.stringify({
                    path: RS.path,
                    position: pos,
                    percent: percentFromPosition(pos),
                }),
            });
        } catch {}
    }

    function bindEpubRendition() {
        if (typeof R === 'undefined' || R?.kind !== 'epub' || !R?.rendition) return false;
        if (RS.epubBoundTo === R.rendition) return true;
        RS.epubBoundTo = R.rendition;
        try {
            R.rendition.on('relocated', loc => {
                RS.epubLocation = Array.isArray(loc) ? loc[0] : loc;
                scheduleSave(250);
            });
        } catch {}
        return true;
    }

    async function restoreEpub(saved) {
        RS.restoring = true;
        let attempts = 0;
        const timer = setInterval(async () => {
            attempts += 1;
            if (bindEpubRendition() && R?.rendition) {
                clearInterval(timer);
                try {
                    if (saved.cfi) await R.rendition.display(saved.cfi);
                    else if (saved.href) await R.rendition.display(saved.href);
                    RS.epubLocation = R.rendition.currentLocation?.() || null;
                    toast(`Resumed at ${Math.round(percentFromPosition(saved))}%`, 'info', 1800);
                } catch (err) {
                    console.debug('[Nomad reader] EPUB restore failed:', err);
                } finally {
                    RS.restoring = false;
                }
            } else if (attempts > 50) {
                clearInterval(timer);
                RS.restoring = false;
            }
        }, 200);
    }

    async function restoreProgress() {
        if (!RS.path) return;
        let data;
        try { data = await api(`/playback/reader/progress?path=${encodeURIComponent(RS.path)}`); }
        catch { return; }
        const saved = data.progress?.position;
        if (!saved) return;
        if (saved.kind === 'epub' && (saved.cfi || saved.href)) {
            restoreEpub(saved);
            return;
        }
        const page = Number(saved.page || 0);
        if (page <= 1) return;
        RS.restoring = true;
        let attempts = 0;
        const timer = setInterval(() => {
            attempts += 1;
            const range = $('#reader-range');
            const max = Number(range?.max || 1);
            if (range && max > 1) {
                clearInterval(timer);
                const target = Math.max(1, Math.min(max, page));
                range.value = String(target);
                range.dispatchEvent(new Event('input', { bubbles: true }));
                range.dispatchEvent(new Event('change', { bubbles: true }));
                RS.restoring = false;
                toast(`Resumed at page ${target}`, 'info', 1800);
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
        RS.marks = new Map(marks.map(mark => [String(mark.id), mark]));
        const pos = position();
        openSheet(`
          <div class="kicker" style="margin-bottom:8px">Bookmarks & notes</div>
          <div class="list-sub" style="margin-bottom:12px">${escapeHtml(locationLabel(pos))}</div>
          <div class="btn-row" style="margin-bottom:14px">
            <button class="btn" data-reader-add="bookmark"><i class="ph ph-bookmark-simple"></i>Bookmark</button>
            <button class="btn" data-reader-add="annotation"><i class="ph ph-note-pencil"></i>Add note</button>
          </div>
          <div class="list">${marks.map(mark => `
            <div class="list-row row-rule">
              <button class="list-body" data-reader-mark-jump="${escapeHtml(mark.id)}" style="background:none;border:none;text-align:left;color:inherit;cursor:pointer">
                <div class="list-title">${escapeHtml(mark.label || (mark.kind === 'annotation' ? 'Note' : 'Bookmark'))}</div>
                <div class="list-sub">${escapeHtml(shortLocationLabel(mark.position))}${mark.note ? ` · ${escapeHtml(mark.note)}` : ''}</div>
              </button>
              <button class="btn btn-icon btn-icon-plain" data-reader-delete="${escapeHtml(mark.id)}"><i class="ph ph-trash"></i></button>
            </div>`).join('') || '<div class="facts-note">No bookmarks or notes yet.</div>'}</div>`);
    }

    async function addMark(kind) {
        if (!RS.path) return;
        const pos = position();
        if (kind === 'annotation') {
            openSheet(`
              <div class="kicker" style="margin-bottom:8px">Note · ${escapeHtml(shortLocationLabel(pos))}</div>
              <textarea id="reader-note-text" class="input input-plain" rows="5" placeholder="Write a note…" style="resize:vertical"></textarea>
              <button class="btn btn-primary btn-block" id="reader-note-save" style="margin-top:12px">Save note</button>`);
            $('#reader-note-save')?.addEventListener('click', async () => {
                const note = $('#reader-note-text')?.value.trim() || '';
                if (!note) return;
                await createMark('annotation', shortLocationLabel(pos), note, pos);
            }, { once: true });
            return;
        }
        await createMark('bookmark', shortLocationLabel(pos), '', pos);
    }

    async function createMark(kind, label, note, pos) {
        try {
            await api('/playback/reader/marks', {
                method: 'POST',
                body: JSON.stringify({ path: RS.path, kind, label, note, position: pos }),
            });
            toast(kind === 'bookmark' ? 'Location bookmarked' : 'Note saved', 'success', 1800);
            openMarks();
        } catch (err) {
            toast(err.message || 'Could not save reader mark', 'error', 4500);
        }
    }

    async function jumpPosition(pos) {
        if (pos?.kind === 'epub' && (pos.cfi || pos.href)) {
            if (!bindEpubRendition() || !R?.rendition) return;
            try {
                await R.rendition.display(pos.cfi || pos.href);
                RS.epubLocation = R.rendition.currentLocation?.() || null;
                closeSheet();
                scheduleSave(100);
            } catch (err) { toast('Could not jump to that EPUB location', 'error'); }
            return;
        }
        const range = $('#reader-range');
        if (!range) return;
        const max = Math.max(1, Number(range.max || 1));
        range.value = String(Math.max(1, Math.min(max, Number(pos?.page) || 1)));
        range.dispatchEvent(new Event('input', { bubbles: true }));
        range.dispatchEvent(new Event('change', { bubbles: true }));
        closeSheet();
        scheduleSave(100);
    }

    async function deleteMark(id) {
        try {
            await api(`/playback/reader/marks/${encodeURIComponent(id)}`, { method: 'DELETE' });
            RS.marks.delete(String(id));
            openMarks();
        } catch (err) { toast(err.message || 'Could not delete reader mark', 'error'); }
    }

    function activate(path) {
        RS.path = path;
        RS.epubLocation = null;
        RS.epubBoundTo = null;
        installButton();
        clearInterval(RS.periodic);
        RS.periodic = setInterval(() => {
            if (S?.screen === 'reader') {
                bindEpubRendition();
                scheduleSave(0);
            }
        }, 10000);
        setTimeout(restoreProgress, 250);
    }

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
            RS.epubLocation = null;
            RS.epubBoundTo = null;
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
        const jumpTo = event.target.closest('[data-reader-mark-jump]');
        if (jumpTo) {
            event.preventDefault();
            const mark = RS.marks.get(String(jumpTo.dataset.readerMarkJump));
            if (mark) jumpPosition(mark.position);
            return;
        }
        const del = event.target.closest('[data-reader-delete]');
        if (del) { event.preventDefault(); deleteMark(del.dataset.readerDelete); }
    }, true);
})();
