/* Nomad Pi live download progress refresh.
 * The backend already updates download state continuously; the original
 * Downloads screen only fetched it when the tab was rendered. Keep the
 * visible Active tab fresh without forcing the user to tab away/back.
 */
(() => {
    if (typeof api !== 'function' || typeof renderActiveDownloads !== 'function') return;

    let timer = null;
    let busy = false;
    let lastIds = '';

    function visibleActiveDownloads() {
        return S?.tab === 'downloads' && S?.dl === 'active' && !document.hidden;
    }

    function cardsById(body) {
        const map = new Map();
        body.querySelectorAll('[data-dlcancel]').forEach(button => {
            const id = String(button.dataset.dlcancel || '');
            const card = button.closest('.dl-card');
            if (id && card) map.set(id, card);
        });
        return map;
    }

    function statusText(job) {
        const done = String(job.status || '') === 'completed';
        const failed = ['error', 'failed'].includes(String(job.status || ''));
        if (failed) return job.error || 'Failed';
        if (done) return 'Complete';
        if (job.speed) return `${fmtSize(job.speed)}/s`;
        return job.status || '';
    }

    async function tick() {
        if (!visibleActiveDownloads() || busy) return;
        const body = $('#dl-body');
        if (!body) return;
        busy = true;
        try {
            const data = await api('/debrid/downloads');
            const list = data.downloads || [];
            const ids = list.map(item => String(item.id || '')).filter(Boolean).sort().join('|');
            const cards = cardsById(body);

            // If the set of jobs changed (new/completed/removed), do one full
            // redraw so buttons and completed states are correct. Otherwise
            // update only progress/status nodes and avoid visible spinner flicker.
            const canPatch = ids && ids === lastIds && list.every(job => !job.id || cards.has(String(job.id)));
            if (!canPatch) {
                lastIds = ids;
                await renderActiveDownloads(body);
                if (typeof window.NomadOffline !== 'undefined' && typeof loadDownloads === 'function') {
                    // Offline Sync's wrapper/periodic renderer will re-add its
                    // section; do not block the live download path on it.
                }
                return;
            }

            for (const job of list) {
                const id = String(job.id || '');
                const card = cards.get(id);
                if (!card) continue;
                const pct = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0))));
                const bar = card.querySelector('.bar > span');
                const stats = card.querySelectorAll('.dl-stats > span');
                if (bar) bar.style.width = `${pct}%`;
                if (stats[0]) stats[0].textContent = `${pct}%`;
                if (stats[1]) stats[1].textContent = statusText(job);

                // Completion/failure changes controls, so redraw immediately.
                if (['completed', 'error', 'failed', 'cancelled'].includes(String(job.status || ''))) {
                    lastIds = '';
                    await renderActiveDownloads(body);
                    break;
                }
            }
        } catch {
            // Keep the current display on transient network errors.
        } finally {
            busy = false;
        }
    }

    function ensureTimer() {
        if (timer) return;
        timer = setInterval(tick, 1250);
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) tick();
    });
    document.addEventListener('click', event => {
        if (event.target.closest('[data-tab="downloads"], [data-dl="active"]')) {
            setTimeout(tick, 0);
        }
    }, true);

    ensureTimer();
    setTimeout(tick, 500);
})();
