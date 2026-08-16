/* Reader UX hardening for EPUB, comics and PDFs. */
(() => {
    const FONT_KEY = 'nomad_reader_font_scale';
    const THEME_KEY = 'nomad_reader_theme';
    const COMIC_FIT_KEY = 'nomad_reader_comic_fit';
    let locationPromise = null;

    function readerReady() {
        return typeof R !== 'undefined' && typeof openSheet === 'function';
    }

    function fontScale() {
        const n = Number(localStorage.getItem(FONT_KEY) || 105);
        return Math.max(75, Math.min(180, Number.isFinite(n) ? n : 105));
    }

    function themeName() {
        const value = localStorage.getItem(THEME_KEY) || 'dark';
        return ['dark', 'paper', 'light'].includes(value) ? value : 'dark';
    }

    function comicFit() {
        return localStorage.getItem(COMIC_FIT_KEY) === 'page' ? 'page' : 'width';
    }

    function applyComicFit(mode = comicFit()) {
        const screen = document.querySelector('#screen-reader');
        if (!screen) return;
        screen.classList.toggle('comic-fit-page', mode === 'page');
        screen.classList.toggle('comic-fit-width', mode !== 'page');
        localStorage.setItem(COMIC_FIT_KEY, mode);
    }

    function registerEpubThemes() {
        if (!readerReady() || R.kind !== 'epub' || !R.rendition?.themes) return;
        try {
            R.rendition.themes.register('nomad-dark', {
                body: { background: '#161826 !important', color: '#e9e9ed !important', 'font-family': 'Inter, system-ui, sans-serif !important' },
                'a, a:visited': { color: '#a99ce8 !important' },
            });
            R.rendition.themes.register('nomad-paper', {
                body: { background: '#ede4d4 !important', color: '#2e2923 !important', 'font-family': 'Georgia, serif !important' },
                'a, a:visited': { color: '#66519d !important' },
            });
            R.rendition.themes.register('nomad-light', {
                body: { background: '#fafafa !important', color: '#1d1d1f !important', 'font-family': 'system-ui, sans-serif !important' },
                'a, a:visited': { color: '#5c4aa1 !important' },
            });
            R.rendition.themes.select(`nomad-${themeName()}`);
            R.rendition.themes.fontSize(`${fontScale()}%`);
        } catch {}
    }

    async function ensureEpubLocations() {
        if (!readerReady() || R.kind !== 'epub' || !R.book?.locations) return false;
        try {
            if (R.book.locations.length?.() > 0) return true;
        } catch {}
        if (!locationPromise) {
            locationPromise = Promise.resolve(R.book.ready)
                .then(() => R.book.locations.generate(1400))
                .then(() => true)
                .catch(err => {
                    console.debug('[Nomad reader] location generation failed:', err);
                    return false;
                })
                .finally(() => { locationPromise = null; });
        }
        return locationPromise;
    }

    async function seekEpubPercent(value) {
        if (!readerReady() || R.kind !== 'epub' || !R.rendition) return;
        const pct = Math.max(0, Math.min(1, Number(value || 0) / 100));
        const ready = await ensureEpubLocations();
        if (!ready) return;
        try {
            const cfi = R.book.locations.cfiFromPercentage(pct);
            if (cfi) await R.rendition.display(cfi);
        } catch (err) {
            if (typeof toast === 'function') toast('Could not jump to that EPUB location', 'error', 3500);
        }
    }

    function applyEpubAppearance() {
        registerEpubThemes();
        const scale = document.querySelector('#reader-font-value');
        if (scale) scale.textContent = `${fontScale()}%`;
    }

    function openReaderOptions() {
        if (!readerReady() || !R.path) return;
        if (R.kind === 'epub') {
            openSheet(`
              <div class="kicker" style="margin-bottom:10px">Reading appearance</div>
              <div class="reader-setting-row">
                <span>Text size</span>
                <div class="reader-stepper">
                  <button class="btn btn-icon" data-reader-font="-10" aria-label="Smaller text"><i class="ph ph-minus"></i></button>
                  <strong id="reader-font-value">${fontScale()}%</strong>
                  <button class="btn btn-icon" data-reader-font="10" aria-label="Larger text"><i class="ph ph-plus"></i></button>
                </div>
              </div>
              <div class="kicker" style="margin:18px 0 8px">Theme</div>
              <div class="chip-equal">
                ${['dark','paper','light'].map(name => `<button class="chip${themeName() === name ? ' active' : ''}" data-reader-theme="${name}">${name[0].toUpperCase() + name.slice(1)}</button>`).join('')}
              </div>
              <div class="list" style="margin-top:16px">
                <a class="sheet-option row-rule" href="${escapeHtml(streamUrl(R.path, '&download=true'))}" target="_blank" rel="noopener">
                  <span>Download EPUB</span><i class="ph ph-download-simple"></i>
                </a>
              </div>`);
            return;
        }

        if (R.kind === 'comic') {
            openSheet(`
              <div class="kicker" style="margin-bottom:10px">Comic reader</div>
              <div class="chip-equal" style="margin-bottom:14px">
                <button class="chip${comicFit() === 'width' ? ' active' : ''}" data-comic-fit="width">Fit width</button>
                <button class="chip${comicFit() === 'page' ? ' active' : ''}" data-comic-fit="page">Fit page</button>
              </div>
              <div class="list">
                <button class="sheet-option row-rule" data-reader-jump="first"><span>First page</span><i class="ph ph-skip-back"></i></button>
                <button class="sheet-option row-rule" data-reader-jump="last"><span>Last page</span><i class="ph ph-skip-forward"></i></button>
                <a class="sheet-option row-rule" href="${escapeHtml(streamUrl(R.path, '&download=true'))}" target="_blank" rel="noopener">
                  <span>Download comic</span><i class="ph ph-download-simple"></i>
                </a>
              </div>`);
            return;
        }

        const url = streamUrl(R.path);
        openSheet(`
          <div class="kicker" style="margin-bottom:10px">Reader</div>
          <div class="list">
            ${R.kind === 'pdf' ? `<a class="sheet-option row-rule" href="${escapeHtml(url)}" target="_blank" rel="noopener"><span>Open PDF in browser</span><i class="ph ph-arrow-square-out"></i></a>` : ''}
            <a class="sheet-option row-rule" href="${escapeHtml(streamUrl(R.path, '&download=true'))}" target="_blank" rel="noopener"><span>Download file</span><i class="ph ph-download-simple"></i></a>
          </div>`);
    }

    function installPdfToolbar(path) {
        const stage = document.querySelector('#reader-stage');
        if (!stage) return;
        const src = streamUrl(path);
        stage.innerHTML = `
          <div class="pdf-reader-shell">
            <div class="pdf-reader-tools">
              <span>PDF</span>
              <a class="btn" href="${escapeHtml(src)}" target="_blank" rel="noopener"><i class="ph ph-arrow-square-out"></i>Open</a>
              <a class="btn" href="${escapeHtml(streamUrl(path, '&download=true'))}" target="_blank" rel="noopener"><i class="ph ph-download-simple"></i>Save</a>
            </div>
            <iframe class="reader-frame" src="${escapeHtml(src)}#view=FitH" title="PDF"></iframe>
          </div>`;
        document.querySelector('#reader-bar')?.classList.add('hidden');
    }

    // Replace only the presentation of PDFs; the original loader has no page
    // state to preserve and mobile Safari benefits from an explicit escape
    // hatch when inline PDF rendering is unavailable in standalone PWAs.
    if (typeof loadPdf === 'function') {
        loadPdf = function nomadPdfReader(path) { installPdfToolbar(path); };
    }

    document.addEventListener('change', event => {
        if (event.target?.id === 'reader-range' && readerReady() && R.kind === 'epub') {
            seekEpubPercent(event.target.value);
        }
    }, true);

    document.addEventListener('click', event => {
        // Own the reader menu before reader.js's target-phase handler so every
        // format gets one coherent options sheet.
        if (event.target.closest('#reader-menu')) {
            event.preventDefault();
            event.stopImmediatePropagation();
            openReaderOptions();
            return;
        }

        const font = event.target.closest('[data-reader-font]');
        if (font && readerReady() && R.kind === 'epub') {
            event.preventDefault();
            const next = Math.max(75, Math.min(180, fontScale() + Number(font.dataset.readerFont || 0)));
            localStorage.setItem(FONT_KEY, String(next));
            applyEpubAppearance();
            return;
        }

        const theme = event.target.closest('[data-reader-theme]');
        if (theme && readerReady() && R.kind === 'epub') {
            event.preventDefault();
            localStorage.setItem(THEME_KEY, theme.dataset.readerTheme);
            applyEpubAppearance();
            openReaderOptions();
            return;
        }

        const fit = event.target.closest('[data-comic-fit]');
        if (fit && readerReady() && R.kind === 'comic') {
            event.preventDefault();
            applyComicFit(fit.dataset.comicFit);
            openReaderOptions();
            return;
        }

        const jump = event.target.closest('[data-reader-jump]');
        if (jump && readerReady() && R.kind === 'comic') {
            event.preventDefault();
            if (jump.dataset.readerJump === 'first') showComicPage(0);
            else showComicPage(Math.max(0, R.pages.length - 1));
            closeSheet();
            return;
        }

        // Comics also page by tapping the outer quarters of the image. The
        // centre remains inert so a normal tap does not unexpectedly advance.
        if (readerReady() && R.kind === 'comic') {
            const page = event.target.closest('#comic-page');
            if (page && !event.target.closest('button,a,input')) {
                const rect = page.getBoundingClientRect();
                const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
                if (ratio < 0.24) readerStep(-1);
                else if (ratio > 0.76) readerStep(1);
            }
        }
    }, true);

    // Detect rendition/page creation and apply the persisted presentation.
    const stage = document.querySelector('#reader-stage');
    if (stage) {
        new MutationObserver(() => {
            if (!readerReady()) return;
            if (R.kind === 'epub' && R.rendition) {
                applyEpubAppearance();
                ensureEpubLocations();
            }
            if (R.kind === 'comic') applyComicFit();
        }).observe(stage, { childList: true, subtree: true });
    }

    // Image errors are otherwise a blank black reader. Surface a useful error
    // while preserving the reader chrome and download option.
    document.addEventListener('error', event => {
        if (event.target?.id !== 'comic-img') return;
        const stage = document.querySelector('#reader-stage');
        if (!stage) return;
        stage.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>Could not load this comic page.<br><span style="font-size:12px">The archive may be damaged or the cached extraction may have disappeared.</span></div>`;
        if (typeof toast === 'function') toast('Comic page could not be read', 'error', 4500);
    }, true);

    applyComicFit();
})();
