/* Nomad Pi lightweight debrid search policy.
 *
 * Keep the existing Find -> title -> release flow and Stream + Keep actions,
 * but hide heavyweight releases by default. The backend annotates every
 * Torrentio result; this adapter presents the Pi-friendly subset and gives the
 * user an explicit Show all escape hatch instead of silently choosing HEVC/4K.
 */
(() => {
    if (typeof api !== 'function') return;

    const originalApi = api;
    const Lite = {
        showAll: false,
        searchKey: '',
        total: 0,
        safe: 0,
        maxGb: null,
    };
    window.NomadDebridLite = Lite;

    function isTorrentSearch(path) {
        return String(path || '').startsWith('/debrid/search/torrents?');
    }

    function searchKey(path) {
        try {
            const url = new URL(path, location.origin);
            return [
                url.searchParams.get('imdb_id') || '',
                url.searchParams.get('media_type') || 'movie',
                url.searchParams.get('season') || '',
                url.searchParams.get('episode') || '',
            ].join(':');
        } catch {
            return String(path || '');
        }
    }

    function sortLite(items) {
        return [...items].sort((a, b) => {
            const cachedA = a.cached === true ? 1 : 0;
            const cachedB = b.cached === true ? 1 : 0;
            if (cachedA !== cachedB) return cachedB - cachedA;
            const directA = a.lite_direct_candidate ? 1 : 0;
            const directB = b.lite_direct_candidate ? 1 : 0;
            if (directA !== directB) return directB - directA;
            const score = Number(b.lite_score || 0) - Number(a.lite_score || 0);
            if (score) return score;
            return Number(b.seeders || 0) - Number(a.seeders || 0);
        });
    }

    function decorateSoon() {
        setTimeout(decorateResults, 0);
        setTimeout(decorateResults, 60);
    }

    function decorateResults() {
        const out = document.querySelector('#debrid-results');
        if (!out) return;
        out.querySelector('.debrid-lite-note')?.remove();

        const note = document.createElement('div');
        note.className = 'facts-note debrid-lite-note';
        note.style.margin = '0 0 12px';
        note.style.textAlign = 'left';

        const max = Lite.maxGb ? ` · ≤${Lite.maxGb} GB` : '';
        if (Lite.showAll) {
            note.innerHTML = `Showing all ${Lite.total} releases. <button class="btn" id="debrid-lite-toggle" type="button">Pi-friendly only</button>`;
        } else if (Lite.safe > 0) {
            note.innerHTML = `Pi-friendly: ${Lite.safe} of ${Lite.total} · 1080p · H.264${max} · MP4/AAC preferred. <button class="btn" id="debrid-lite-toggle" type="button">Show all</button>`;
        } else if (Lite.total > 0) {
            note.innerHTML = `No Pi-friendly 1080p H.264 release matched${max}. Heavy/incompatible releases are hidden. <button class="btn" id="debrid-lite-toggle" type="button">Show all</button>`;
            const empty = out.querySelector('.empty');
            if (empty) empty.textContent = 'No Pi-friendly release found.';
        } else {
            return;
        }

        const firstList = out.querySelector('.list, .empty');
        if (firstList) out.insertBefore(note, firstList);
        else out.appendChild(note);

        out.querySelector('#debrid-lite-toggle')?.addEventListener('click', () => {
            Lite.showAll = !Lite.showAll;
            if (typeof renderTorrents === 'function') renderTorrents();
        }, { once: true });

        out.querySelectorAll('[data-grab]').forEach((button) => {
            const index = Number(button.dataset.grab);
            const result = window.S?.debrid?.results?.[index] || (typeof S !== 'undefined' ? S.debrid?.results?.[index] : null);
            if (!result) return;
            const row = button.closest('.torrent-row');
            if (!row || row.querySelector('.debrid-lite-badge')) return;
            const badge = document.createElement('span');
            badge.className = `tag debrid-lite-badge${result.lite_direct_candidate ? ' tag-accent' : ''}`;
            badge.textContent = result.lite_direct_candidate ? 'DIRECT PICK' : 'PI SAFE';
            row.insertBefore(badge, row.firstChild);
        });
    }

    api = async function nomadLiteApi(path, opts = {}) {
        const data = await originalApi(path, opts);
        if (!isTorrentSearch(path) || !data || !Array.isArray(data.results)) return data;

        const key = searchKey(path);
        if (key !== Lite.searchKey) {
            Lite.searchKey = key;
            Lite.showAll = false;
        }

        const all = sortLite(data.results);
        const safe = all.filter(item => item.lite_compatible === true);
        Lite.total = all.length;
        Lite.safe = safe.length;
        Lite.maxGb = safe[0]?.lite_max_size_gb || all[0]?.lite_max_size_gb || null;

        // The appliance defaults to releases that avoid live video conversion.
        // Keep result counts bounded so the mobile DOM and JSON payload remain
        // small even when Torrentio returns a very large catalog.
        data.results = (Lite.showAll ? all : safe).slice(0, Lite.showAll ? 30 : 15);
        data.lite_total = Lite.total;
        data.lite_safe = Lite.safe;
        data.lite_filtered = !Lite.showAll;
        decorateSoon();
        return data;
    };
})();
