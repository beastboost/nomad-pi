/* ══════════════════════════════════════════════════════════════════════════
   Nomad Pi — reader

   Comics (CBZ/CBR) page through server-extracted images; PDFs use the
   browser's own viewer; EPUBs render through epub.js when it is available
   and fall back to a download otherwise; images open in a zoomable frame.

   Reading position is stored against the same /media/progress endpoint the
   video player uses, so "continue" works across every media type.
   ══════════════════════════════════════════════════════════════════════════ */

const R = {
    kind: null,      // 'comic' | 'pdf' | 'epub' | 'image'
    path: null,
    pages: [],
    index: 0,
    book: null,      // epub.js book
    rendition: null,
};

function openReader(path, startAt = 0) {
    const e = ext(path);
    stopReaderInternals();

    R.path = path;
    R.index = 0;
    R.pages = [];

    push('reader');
    $('#reader-title').textContent = stripExt(baseName(path));
    $('#reader-sub').textContent = e.toUpperCase();
    const stage = $('#reader-stage');
    stage.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;

    if (['cbz', 'cbr'].includes(e))       { R.kind = 'comic'; loadComic(path, startAt); }
    else if (e === 'pdf')                 { R.kind = 'pdf';   loadPdf(path); }
    else if (e === 'epub')                { R.kind = 'epub';  loadEpub(path, startAt); }
    else if (IMAGE_EXT.includes(e))       { R.kind = 'image'; loadImage(path); }
    else                                  { R.kind = 'other'; loadFallback(path); }
}

function stopReaderInternals() {
    try { R.rendition?.destroy(); } catch {}
    try { R.book?.destroy(); } catch {}
    R.rendition = null;
    R.book = null;
}

function closeReader() {
    saveReadingProgress();
    stopReaderInternals();
    $('#reader-stage').innerHTML = '';
}

/* ── Comics ────────────────────────────────────────────────────────────── */

async function loadComic(path, startAt) {
    const stage = $('#reader-stage');
    try {
        const data = await api(`/media/books/comic/pages?path=${encodeURIComponent(path)}`);
        R.pages = (data.pages || []).map(p => (typeof p === 'string' ? p : p.path)).filter(Boolean);
        if (!R.pages.length) throw new Error('No pages could be extracted from this file.');
        if (data.title) $('#reader-title').textContent = data.title;
        R.index = Math.min(Math.max(0, Math.floor(startAt) || 0), R.pages.length - 1);

        stage.innerHTML = `<div class="reader-page" id="comic-page"><img id="comic-img" alt=""></div>`;
        $('#reader-bar').classList.remove('hidden');
        bindReaderSwipe(stage);
        showComicPage(R.index);
    } catch (e) {
        stage.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>
            ${escapeHtml(e.message || 'Could not open this comic')}<br>
            <span style="font-size:12px">CBR files need <strong>unar</strong> or <strong>7z</strong> on the Pi — check Server &rsaquo; Health check.</span></div>`;
        $('#reader-bar').classList.add('hidden');
    }
}

function showComicPage(i) {
    if (!R.pages.length) return;
    R.index = Math.max(0, Math.min(i, R.pages.length - 1));
    const img = $('#comic-img');
    if (img) img.src = streamUrl(R.pages[R.index]);
    updateReaderBar(R.index + 1, R.pages.length);
    // Warm the next page so a tap feels instant
    if (R.index + 1 < R.pages.length) new Image().src = streamUrl(R.pages[R.index + 1]);
    saveReadingProgress();
}

/* ── PDF — the browser has a viewer; use it ────────────────────────────── */

function loadPdf(path) {
    const stage = $('#reader-stage');
    stage.innerHTML = `
      <iframe class="reader-frame" src="${escapeHtml(streamUrl(path))}#view=FitH"
              title="PDF"></iframe>`;
    $('#reader-bar').classList.add('hidden');

    // Some mobile browsers refuse to render PDFs inline — offer a way out.
    setTimeout(() => {
        const f = stage.querySelector('iframe');
        if (!f) return;
        let blank = false;
        try { blank = !f.contentDocument && !f.contentWindow; } catch { blank = false; }
        if (blank) loadFallback(path, 'This browser will not display PDFs inline.');
    }, 2500);
}

/* ── EPUB ──────────────────────────────────────────────────────────────── */

async function loadEpub(path, startAt) {
    const stage = $('#reader-stage');
    if (typeof window.ePub !== 'function') {
        loadFallback(path, 'The EPUB engine is not installed on this box.');
        return;
    }
    try {
        stage.innerHTML = `<div class="reader-epub" id="epub-host"></div>`;
        R.book = window.ePub(streamUrl(path));
        R.rendition = R.book.renderTo('epub-host', {
            width: '100%', height: '100%', spread: 'none', flow: 'paginated',
        });
        R.rendition.themes.register('nocturne', {
            body: { background: '#161826', color: '#e9e9ed', 'font-family': 'Inter, system-ui, sans-serif' },
            'a, a:visited': { color: '#9184d9' },
        });
        R.rendition.themes.select('nocturne');
        R.rendition.themes.fontSize('105%');

        await R.rendition.display(startAt ? undefined : undefined);
        $('#reader-bar').classList.remove('hidden');

        R.rendition.on('relocated', (loc) => {
            const pct = loc?.start?.percentage;
            if (typeof pct === 'number') {
                updateReaderBar(Math.round(pct * 100), 100, `${Math.round(pct * 100)}%`);
                R.index = pct;
                saveReadingProgress();
            }
        });
        bindReaderSwipe(stage);
    } catch (e) {
        loadFallback(path, e.message || 'Could not open this EPUB.');
    }
}

/* ── Images ────────────────────────────────────────────────────────────── */

function loadImage(path) {
    $('#reader-stage').innerHTML = `
      <div class="reader-page"><img src="${escapeHtml(streamUrl(path))}" alt="" id="img-view"></div>`;
    $('#reader-bar').classList.add('hidden');
}

/* ── Anything else ─────────────────────────────────────────────────────── */

function loadFallback(path, reason) {
    $('#reader-stage').innerHTML = `
      <div class="empty">
        <i class="ph ph-file-arrow-down"></i>
        ${escapeHtml(reason || 'This file type has no in-app viewer.')}<br>
        <a class="btn btn-primary" style="margin-top:14px;display:inline-flex"
           href="${escapeHtml(streamUrl(path, '&download=true'))}">
          <i class="ph ph-download-simple"></i>Download to this device
        </a>
      </div>`;
    $('#reader-bar').classList.add('hidden');
}

/* ── Shared chrome ─────────────────────────────────────────────────────── */

function updateReaderBar(current, total, label) {
    const range = $('#reader-range');
    const count = $('#reader-count');
    if (range) { range.max = String(Math.max(1, total)); range.value = String(Math.max(1, current)); }
    if (count) count.textContent = label || `${current} / ${total}`;
}

function readerStep(delta) {
    if (R.kind === 'comic') return showComicPage(R.index + delta);
    if (R.kind === 'epub' && R.rendition) return delta > 0 ? R.rendition.next() : R.rendition.prev();
}

function bindReaderSwipe(el) {
    if (el._swipeBound) return;
    let x0 = null;
    el.addEventListener('touchstart', e => { x0 = e.changedTouches[0].screenX; }, { passive: true });
    el.addEventListener('touchend', e => {
        if (x0 == null) return;
        const dx = e.changedTouches[0].screenX - x0;
        if (Math.abs(dx) > 50) readerStep(dx < 0 ? 1 : -1);
        x0 = null;
    }, { passive: true });
    el._swipeBound = true;
}

async function saveReadingProgress() {
    if (!R.path) return;
    const total = R.kind === 'comic' ? R.pages.length : 100;
    const current = R.kind === 'comic' ? R.index : Math.round((R.index || 0) * 100);
    if (!total) return;
    try {
        await fetch(`${API}/media/progress`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: R.path, current_time: current, duration: total }),
            keepalive: true,
        });
    } catch {}
}

/* ── Wiring ────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
    $('#reader-prev')?.addEventListener('click', () => readerStep(-1));
    $('#reader-next')?.addEventListener('click', () => readerStep(1));
    $('#reader-range')?.addEventListener('input', e => {
        if (R.kind === 'comic') showComicPage(Number(e.target.value) - 1);
    });
    $('#reader-menu')?.addEventListener('click', () => {
        if (!R.path) return;
        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Reader</div>
          <div class="list">
            ${R.kind === 'comic' ? `
              <button class="sheet-option row-rule" id="rd-first"><span>Go to first page</span></button>
              <button class="sheet-option row-rule" id="rd-last"><span>Go to last page</span></button>` : ''}
            <a class="sheet-option row-rule" href="${escapeHtml(streamUrl(R.path, '&download=true'))}">
              <span>Download this file</span><i class="ph ph-download-simple"></i>
            </a>
          </div>`);
        $('#rd-first')?.addEventListener('click', () => { showComicPage(0); closeSheet(); });
        $('#rd-last')?.addEventListener('click', () => { showComicPage(R.pages.length - 1); closeSheet(); });
    });

    document.addEventListener('keydown', e => {
        if (S.screen !== 'reader') return;
        if (e.key === 'ArrowLeft') readerStep(-1);
        if (e.key === 'ArrowRight') readerStep(1);
    });
});
