/* ══════════════════════════════════════════════════════════════════════════
   Nomad Pi — chapters, skip cues and scrub previews.

   Three things a media server is expected to do that a file server isn't:
   jump past the title sequence, show what you are scrubbing towards, and let
   you correct both when the rip's own metadata is wrong.

   Everything here attaches to the existing player rather than replacing any
   of it: the module reads V.el / V.path from the app shell and adds its own
   overlay, so a title with no chapters and no sprite sheet behaves exactly as
   it did before.
   ══════════════════════════════════════════════════════════════════════════ */

(() => {
    'use strict';

    const CUE = {
        path: null,
        intro: null,
        credits: null,
        chapters: [],
        trickplay: null,
        sheetImage: null,
        dismissed: new Set(),
        pollTimer: null,
    };

    const el = (id) => document.getElementById(id);
    const video = () => (typeof V !== 'undefined' ? V.el : null);

    function fmt(sec) {
        return typeof fmtTime === 'function' ? fmtTime(sec) : `${Math.round(sec)}s`;
    }

    async function get(path, opts) {
        return typeof api === 'function' ? api(path, opts) : (await fetch(`/api${path}`, opts)).json();
    }

    function notify(message, kind) {
        if (typeof toast === 'function') toast(message, kind || 'info', 2600);
    }

    /* ── Skip buttons ──────────────────────────────────────────────────── */

    function skipButton() {
        let button = el('player-skip');
        if (button) return button;
        button = document.createElement('button');
        button.id = 'player-skip';
        button.className = 'player-skip hidden';
        button.type = 'button';
        button.addEventListener('click', () => {
            const media = video();
            const target = Number(button.dataset.target || 0);
            if (!media || !target) return;
            // Land a beat before the marker ends so a slightly early marker
            // never clips the first line of dialogue.
            media.currentTime = Math.max(0, Math.min(target, (media.duration || target) - 0.5));
            CUE.dismissed.add(button.dataset.kind);
            hideSkip();
        });
        el('player-stage')?.appendChild(button);
        return button;
    }

    function showSkip(kind, label, target) {
        const button = skipButton();
        button.dataset.kind = kind;
        button.dataset.target = String(target);
        button.innerHTML = `<span>${label}</span><i class="ph ph-fast-forward"></i>`;
        button.classList.remove('hidden');
    }

    function hideSkip() {
        el('player-skip')?.classList.add('hidden');
    }

    function tickSkip() {
        const media = video();
        if (!media || !Number.isFinite(media.currentTime)) return;
        const now = media.currentTime;

        const intro = CUE.intro;
        if (intro && !CUE.dismissed.has('intro') && intro.end > intro.start &&
            now >= intro.start && now < intro.end - 1) {
            showSkip('intro', 'Skip intro', intro.end);
            return;
        }
        const credits = CUE.credits;
        if (credits && !CUE.dismissed.has('credits') && now >= credits.start) {
            // Nothing to skip *to* at the very end, so this becomes the manual
            // trigger for the next-episode handoff the shell already owns.
            const media_duration = media.duration || 0;
            if (media_duration && now < media_duration - 2) {
                showSkip('credits', 'Skip credits', media_duration - 0.5);
                return;
            }
        }
        hideSkip();
    }

    /* ── Scrub previews ────────────────────────────────────────────────── */

    function previewNode() {
        let node = el('player-preview');
        if (node) return node;
        node = document.createElement('div');
        node.id = 'player-preview';
        node.className = 'scrub-preview hidden';
        node.innerHTML = '<div class="scrub-preview-frame"></div><div class="scrub-preview-time"></div>';
        el('player-scrubber')?.appendChild(node);
        return node;
    }

    function showPreview(fraction, clientX) {
        const tp = CUE.trickplay;
        const scrubber = el('player-scrubber');
        if (!tp || !CUE.sheetImage || !scrubber) return;

        const seconds = fraction * (tp.duration || 0);
        const index = Math.max(0, Math.min(tp.count - 1, Math.floor(seconds / tp.interval)));
        const column = index % tp.columns;
        const row = Math.floor(index / tp.columns);

        const node = previewNode();
        const frame = node.querySelector('.scrub-preview-frame');
        frame.style.width = `${tp.tile_width}px`;
        frame.style.height = `${tp.tile_height}px`;
        frame.style.backgroundImage = `url("${CUE.sheetImage}")`;
        frame.style.backgroundSize = `${tp.tile_width * tp.columns}px ${tp.tile_height * tp.rows}px`;
        frame.style.backgroundPosition = `-${column * tp.tile_width}px -${row * tp.tile_height}px`;
        node.querySelector('.scrub-preview-time').textContent = fmt(seconds);

        // Keep the thumbnail inside the scrubber even at either extreme.
        const bounds = scrubber.getBoundingClientRect();
        const half = tp.tile_width / 2;
        const x = Math.max(half, Math.min(bounds.width - half, (clientX ?? bounds.left + fraction * bounds.width) - bounds.left));
        node.style.left = `${x}px`;
        node.classList.remove('hidden');
    }

    function hidePreview() {
        el('player-preview')?.classList.add('hidden');
    }

    function wirePreview() {
        const scrubber = el('player-scrubber');
        if (!scrubber || scrubber.dataset.cuePreview === '1') return;
        scrubber.dataset.cuePreview = '1';

        const fractionAt = (clientX) => {
            const track = scrubber.querySelector('.scrub-track') || scrubber;
            const bounds = track.getBoundingClientRect();
            if (!bounds.width) return 0;
            return Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width));
        };

        scrubber.addEventListener('pointermove', (event) => {
            if (!CUE.sheetImage) return;
            showPreview(fractionAt(event.clientX), event.clientX);
        });
        scrubber.addEventListener('pointerleave', hidePreview);
        scrubber.addEventListener('pointercancel', hidePreview);
        // Touch has no hover, so the preview lives for the length of the drag.
        scrubber.addEventListener('pointerup', () => setTimeout(hidePreview, 450));
    }

    async function loadTrickplay(path, { generate = false } = {}) {
        if (CUE.pollTimer) { clearTimeout(CUE.pollTimer); CUE.pollTimer = null; }
        let data;
        try {
            data = await get(`/playback/trickplay?path=${encodeURIComponent(path)}${generate ? '&generate=true' : ''}`);
        } catch {
            return null;
        }
        if (CUE.path !== path) return null;

        if (data.state === 'ready') {
            CUE.trickplay = data;
            // A CSS background cannot carry the Authorization header, so the
            // sheet is fetched with the same query token the stream URL uses.
            const t = typeof token === 'function' ? token() : '';
            CUE.sheetImage = t ? `${data.sheet}&token=${encodeURIComponent(t)}` : data.sheet;
            wirePreview();
            if (generate) notify('Scrub previews ready ✓', 'success');
            return data;
        }
        if ((data.state === 'queued' || data.state === 'running')) {
            CUE.pollTimer = setTimeout(() => loadTrickplay(path, { generate }), 4000);
        } else if (generate && data.error) {
            notify(data.error, 'error');
        }
        return data;
    }

    async function loadCues(path) {
        CUE.path = path;
        CUE.intro = CUE.credits = null;
        CUE.chapters = [];
        CUE.trickplay = CUE.sheetImage = null;
        CUE.dismissed = new Set();
        hideSkip();
        hidePreview();

        try {
            const data = await get(`/playback/cues?path=${encodeURIComponent(path)}`);
            if (CUE.path !== path) return;
            CUE.intro = data.intro || null;
            CUE.credits = data.credits || null;
            CUE.chapters = data.chapters || [];
        } catch {}

        // Never generate a sheet unasked — it is the one part of this module
        // that costs real CPU on the Pi.
        loadTrickplay(path);
    }

    /* ── Chapters sheet ────────────────────────────────────────────────── */

    function chaptersSheet() {
        const media = video();
        const path = CUE.path;
        if (!path || typeof openSheet !== 'function') return;
        const at = media ? media.currentTime || 0 : 0;
        const esc = typeof escapeHtml === 'function' ? escapeHtml : (s) => String(s);

        const chapterRows = CUE.chapters.length
            ? CUE.chapters.map((c, i) => `
                <button class="sheet-option row-rule" data-cue-seek="${c.start}">
                  <span>${esc(c.title || `Chapter ${i + 1}`)}</span>
                  <span style="color:var(--text-45);font-variant-numeric:tabular-nums">${fmt(c.start)}</span>
                </button>`).join('')
            : '<div style="font-size:13px;color:var(--text-45);padding:6px 0">This file has no embedded chapters.</div>';

        const introLine = CUE.intro
            ? `Intro ends at ${fmt(CUE.intro.end)} · ${CUE.intro.source}`
            : 'No intro marker yet';
        const creditsLine = CUE.credits
            ? `Credits start at ${fmt(CUE.credits.start)} · ${CUE.credits.source}`
            : 'No credits marker yet';
        const previewState = CUE.sheetImage
            ? 'Scrub previews ready'
            : 'Generate scrub previews';

        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Chapters</div>
          <div class="list" style="margin-bottom:18px">${chapterRows}</div>
          <div class="kicker" style="margin-bottom:8px">Markers</div>
          <div style="font-size:12.5px;color:var(--text-45);margin-bottom:10px">${esc(introLine)}<br>${esc(creditsLine)}</div>
          <div class="list">
            <button class="sheet-option row-rule" data-cue-mark="intro" data-cue-at="${at}">
              <span>Intro ends here (${fmt(at)})</span><i class="ph ph-scissors"></i>
            </button>
            <button class="sheet-option row-rule" data-cue-mark="credits" data-cue-at="${at}">
              <span>Credits start here (${fmt(at)})</span><i class="ph ph-scissors"></i>
            </button>
            <button class="sheet-option row-rule" data-cue-clear="1">
              <span>Clear markers for this season</span><i class="ph ph-eraser"></i>
            </button>
            <button class="sheet-option row-rule" data-cue-trickplay="1" ${CUE.sheetImage ? 'disabled' : ''}>
              <span>${previewState}</span><i class="ph ph-film-script"></i>
            </button>
          </div>
          <div style="font-size:12px;color:var(--text-45);margin-top:10px">
            Markers apply to every episode in this folder, so you only set them once per season.
          </div>`);
    }

    async function markCue(kind, at) {
        const media = video();
        const path = CUE.path;
        if (!path) return;
        const body = kind === 'intro'
            ? { path, kind, start: 0, end: at, scope: 'season' }
            : { path, kind, start: at, end: media?.duration || null, scope: 'season' };
        try {
            await get('/playback/cues/mark', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (kind === 'intro') CUE.intro = { start: 0, end: at, source: 'season' };
            else CUE.credits = { start: at, end: media?.duration || at, source: 'season' };
            CUE.dismissed.delete(kind);
            notify(`${kind === 'intro' ? 'Intro' : 'Credits'} marker saved for this season ✓`, 'success');
        } catch (err) {
            notify(err?.message || 'Could not save the marker', 'error');
        }
    }

    async function clearCues() {
        const path = CUE.path;
        if (!path) return;
        for (const kind of ['intro', 'credits']) {
            for (const scope of ['episode', 'season']) {
                try {
                    await get('/playback/cues/clear', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path, kind, scope }),
                    });
                } catch {}
            }
        }
        CUE.intro = CUE.credits = null;
        hideSkip();
        notify('Markers cleared', 'success');
    }

    /* ── Wiring ────────────────────────────────────────────────────────── */

    function addChaptersButton() {
        const extras = document.querySelector('.player-extras');
        if (!extras || el('player-chapters')) return;
        const button = document.createElement('button');
        button.className = 'btn';
        button.id = 'player-chapters';
        button.type = 'button';
        button.innerHTML = '<i class="ph ph-list-numbers" style="font-size:17px"></i>Chapters';
        button.addEventListener('click', chaptersSheet);
        extras.appendChild(button);
    }

    document.addEventListener('click', async (event) => {
        const seek = event.target.closest?.('[data-cue-seek]');
        if (seek) {
            const media = video();
            if (media) media.currentTime = Number(seek.dataset.cueSeek || 0);
            closeSheet?.();
            return;
        }
        const mark = event.target.closest?.('[data-cue-mark]');
        if (mark) {
            closeSheet?.();
            await markCue(mark.dataset.cueMark, Number(mark.dataset.cueAt || 0));
            return;
        }
        if (event.target.closest?.('[data-cue-clear]')) {
            closeSheet?.();
            await clearCues();
            return;
        }
        if (event.target.closest?.('[data-cue-trickplay]')) {
            closeSheet?.();
            notify('Building scrub previews in the background…', 'info');
            loadTrickplay(CUE.path, { generate: true });
        }
    });

    // The shell recreates the <video> element for every title, so watch the
    // stage rather than binding to one element that is about to be replaced.
    function observePlayer() {
        const stage = el('player-stage');
        if (!stage) return;
        addChaptersButton();

        let lastPath = null;
        setInterval(() => {
            const path = typeof V !== 'undefined' ? V.path : null;
            const media = video();
            if (path && path !== lastPath && media) {
                lastPath = path;
                loadCues(path);
            } else if (!path && lastPath) {
                lastPath = null;
                CUE.path = null;
                hideSkip();
                hidePreview();
            }
            if (path) tickSkip();
        }, 1000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observePlayer);
    } else {
        observePlayer();
    }

    window.NomadCues = { load: loadCues, sheet: chaptersSheet, state: CUE };
})();
