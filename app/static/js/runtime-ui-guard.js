/* Small runtime guards for integration failures that should never break playback. */
(() => {
    // playback-core historically labelled every HLS/remux/transcode startup
    // failure as "Adaptive playback unavailable". Only true ABR is adaptive;
    // use neutral wording and collapse duplicate errors from replacement paths.
    if (typeof window.toast === 'function') {
        const rawToast = window.toast;
        let lastKey = '';
        let lastAt = 0;
        window.toast = function nomadGuardedToast(message, type, duration, ...rest) {
            let text = String(message ?? '');
            if (text.startsWith('Adaptive playback unavailable:')) {
                text = `Optimized playback unavailable:${text.slice('Adaptive playback unavailable:'.length)}`;
            }
            const key = `${type || ''}:${text}`;
            const now = Date.now();
            if ((type === 'error' || type === 'warn') && key === lastKey && (now - lastAt) < 3000) {
                return;
            }
            lastKey = key;
            lastAt = now;
            return rawToast.call(this, text, type, duration, ...rest);
        };
    }

    // The legacy dashboard endpoint used to divide by duration directly. The
    // player can emit an early state update before metadata has populated
    // video.duration, so do not send a zero-duration progress sample. A later
    // timeupdate/playing event will publish the real session normally.
    if (typeof window.dashboardSession === 'function') {
        const rawDashboardSession = window.dashboardSession;
        window.dashboardSession = function guardedDashboardSession(path, title, state, current, duration) {
            const dur = Number(duration);
            if (!Number.isFinite(dur) || dur <= 0) return;
            return rawDashboardSession(path, title, state, current, dur);
        };
        try { dashboardSession = window.dashboardSession; } catch {}
    }
})();
