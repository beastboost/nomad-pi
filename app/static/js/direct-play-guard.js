/* Direct-play failure guard.
 * Healthy direct MP4 playback remains entirely native. Only after a direct
 * stream drops do we ask the server whether the source storage is still alive.
 * A dead USB disk therefore cannot trigger the legacy eight-retry loop.
 */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof reconnectVideo !== 'function' || typeof api !== 'function') return;

    const previousReconnect = reconnectVideo;
    let checking = false;

    function haltDirectRequests() {
        const video = V?.el;
        if (!video) return;
        try { video.pause(); } catch {}
        try {
            video.removeAttribute('src');
            video.load();
        } catch {}
    }

    reconnectVideo = async function guardedDirectReconnect() {
        const current = Core.current;
        if (!current || current.type !== 'direct' || !current.path) {
            return previousReconnect();
        }
        if (checking) return;
        checking = true;
        try {
            await api(`/playback/storage/source-health?path=${encodeURIComponent(current.path)}`);
        } catch (err) {
            haltDirectRequests();
            toast(
                `Storage unavailable — playback stopped instead of retrying the drive. ${err?.message || ''}`.trim(),
                'error',
                9000,
            );
            return;
        } finally {
            checking = false;
        }

        // Two reconnects are enough to recover a transient Wi-Fi hiccup without
        // turning a direct stream failure into continuous network/disk churn.
        if (Number(V?.reconnects || 0) >= 2) {
            haltDirectRequests();
            toast('Direct stream is still dropping after two retries. Playback stopped.', 'error', 7500);
            return;
        }
        return previousReconnect();
    };
})();
