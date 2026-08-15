/* Shared client-side handover for replacement playback sessions. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function') return;

    const HLS_VERSION = '1.6.16';
    let hlsPromise = null;

    function canPlay(video, mime) {
        try { return Boolean(video?.canPlayType?.(mime)); } catch { return false; }
    }

    function nativeHls(video) {
        return canPlay(video, 'application/vnd.apple.mpegurl') ||
               canPlay(video, 'application/x-mpegURL');
    }

    function loadHls() {
        if (window.Hls) return Promise.resolve(window.Hls);
        if (hlsPromise) return hlsPromise;
        hlsPromise = new Promise((resolve, reject) => {
            const inject = (src, fallback = false) => {
                const script = document.createElement('script');
                script.src = src;
                script.async = true;
                script.onload = () => window.Hls ? resolve(window.Hls) : reject(new Error('Hls.js did not initialise'));
                script.onerror = () => {
                    script.remove();
                    if (!fallback) inject(`https://cdn.jsdelivr.net/npm/hls.js@${HLS_VERSION}/dist/hls.min.js`, true);
                    else reject(new Error('Hls.js is unavailable'));
                };
                document.head.appendChild(script);
            };
            inject('/vendor/hls/hls.min.js');
        }).catch(err => {
            hlsPromise = null;
            throw err;
        });
        return hlsPromise;
    }

    function destroyHls(current) {
        if (!current?.hls) return;
        try { current.hls.destroy(); } catch {}
        current.hls = null;
    }

    function absolutePosition() {
        const current = Core.current;
        const video = typeof V !== 'undefined' ? V.el : null;
        if (!current || !video) return 0;
        return Math.max(0, Number(current.offset || 0) + Number(video.currentTime || 0));
    }

    async function attachHls(current, autoplay) {
        const video = V?.el;
        if (!video || Core.current !== current) return;
        if (nativeHls(video)) {
            video.src = current.url;
            video.load();
            if (autoplay) video.play().catch(() => {});
            return;
        }

        const HlsCtor = await loadHls();
        if (!V?.el || Core.current !== current) return;
        if (!HlsCtor.isSupported()) throw new Error('This browser does not support MediaSource HLS');
        destroyHls(current);
        video.pause();
        video.removeAttribute('src');
        video.load();

        const hls = new HlsCtor({
            enableWorker: true,
            lowLatencyMode: false,
            backBufferLength: 90,
            maxBufferLength: 60,
        });
        current.hls = hls;
        hls.attachMedia(video);
        hls.on(HlsCtor.Events.MEDIA_ATTACHED, () => hls.loadSource(current.url));
        hls.on(HlsCtor.Events.MANIFEST_PARSED, () => {
            if (autoplay && Core.current === current) video.play().catch(() => {});
        });
        hls.on(HlsCtor.Events.ERROR, (_event, data) => {
            if (!data?.fatal || Core.current !== current) return;
            if (data.type === HlsCtor.ErrorTypes.NETWORK_ERROR) hls.startLoad();
            else if (data.type === HlsCtor.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
            else {
                destroyHls(current);
                toast(`Playback stream failed: ${data.details || 'fatal HLS error'}`, 'error', 6000);
            }
        });
    }

    async function attachDirect(current, absolute, autoplay) {
        const video = V?.el;
        if (!video || Core.current !== current) return;
        destroyHls(current);
        video.pause();
        video.src = current.url;
        video.load();
        const seekTo = Math.max(0, Number(absolute || 0));
        if (seekTo > 0) {
            await new Promise(resolve => {
                const seek = () => {
                    try { video.currentTime = seekTo; } catch {}
                    resolve();
                };
                if (video.readyState >= 1) seek();
                else video.addEventListener('loadedmetadata', seek, { once: true });
            });
        }
        if (autoplay) video.play().catch(() => {});
    }

    Core.absolutePosition = absolutePosition;
    Core.applyReplacement = async function applyReplacement(result, options = {}) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video || !result?.session || !result?.playback?.url) {
            throw new Error('No active playback session to replace');
        }
        const autoplay = options.autoplay ?? !video.paused;
        const absolute = Number(options.absolute ?? result.session.position ?? absolutePosition() ?? 0);

        destroyHls(current);
        current.id = result.session.id;
        current.type = result.playback.type;
        current.mode = result.session.mode || result.plan?.mode || current.mode;
        current.url = result.playback.url;
        current.offset = current.type === 'hls' ? Number(result.source_offset ?? absolute ?? 0) : 0;
        current.sourceDuration = Number(result.session.duration || current.sourceDuration || 0);
        current.audioTrack = result.session.audio_track ?? current.audioTrack ?? null;
        current.subtitleTrack = result.session.subtitle_track ?? null;
        current.quality = result.session.quality || current.quality || 'auto';

        V.url = current.url;
        V.nomadPlaybackSession = current.id;
        V.nomadOffset = current.offset;

        if (current.type === 'hls') await attachHls(current, autoplay);
        else await attachDirect(current, absolute, autoplay);
        if (typeof updateScrub === 'function') updateScrub();
        return current;
    };
})();
