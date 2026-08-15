/* Nomad Pi 2.x playback adapter.
 *
 * Loaded after app_legacy.js. It keeps the existing player controls/UI but
 * replaces media source selection with /api/playback/start, short-lived stream
 * tickets and HLS where required.
 */
(() => {
    if (typeof playVideo !== 'function' || typeof stopVideo !== 'function') return;

    const HLS_VERSION = '1.6.16';
    const DEVICE_KEY = 'nomad_playback_device_id';
    const legacyPlayVideo = playVideo;
    const legacyStopVideo = stopVideo;
    const legacyUpdateScrub = typeof updateScrub === 'function' ? updateScrub : null;
    const legacySaveProgress = typeof saveProgress === 'function' ? saveProgress : null;
    const legacyReconnectVideo = typeof reconnectVideo === 'function' ? reconnectVideo : null;

    const Core = {
        current: null,
        hlsPromise: null,
        seeking: false,
    };
    window.NomadPlaybackCore = Core;

    function deviceId() {
        let id = localStorage.getItem(DEVICE_KEY);
        if (!id) {
            id = (window.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`);
            localStorage.setItem(DEVICE_KEY, id);
        }
        return id;
    }

    function canPlay(el, mime) {
        try {
            const result = el.canPlayType(mime);
            return result === 'probably' || result === 'maybe';
        } catch {
            return false;
        }
    }

    function browserCapabilities() {
        const video = document.createElement('video');
        const audio = document.createElement('audio');
        const containers = new Set();
        const videoCodecs = new Set();
        const audioCodecs = new Set();

        if (canPlay(video, 'video/mp4')) containers.add('mp4');
        if (canPlay(video, 'video/webm')) containers.add('webm');
        if (canPlay(video, 'video/mp4; codecs="avc1.42E01E"')) videoCodecs.add('h264');
        if (canPlay(video, 'video/mp4; codecs="hvc1.1.6.L93.B0"')) videoCodecs.add('hevc');
        if (canPlay(video, 'video/webm; codecs="vp9"')) videoCodecs.add('vp9');
        if (canPlay(video, 'video/mp4; codecs="av01.0.05M.08"') ||
            canPlay(video, 'video/webm; codecs="av01.0.05M.08"')) videoCodecs.add('av1');

        if (canPlay(audio, 'audio/mp4')) containers.add('m4a');
        if (canPlay(audio, 'audio/mpeg')) containers.add('mp3');
        if (canPlay(audio, 'audio/flac')) containers.add('flac');
        if (canPlay(audio, 'audio/ogg')) containers.add('ogg');
        if (canPlay(audio, 'audio/ogg; codecs="opus"')) containers.add('opus');
        if (canPlay(audio, 'audio/wav')) containers.add('wav');

        if (canPlay(audio, 'audio/mp4; codecs="mp4a.40.2"')) audioCodecs.add('aac');
        if (canPlay(audio, 'audio/mpeg')) audioCodecs.add('mp3');
        if (canPlay(audio, 'audio/flac')) audioCodecs.add('flac');
        if (canPlay(audio, 'audio/ogg; codecs="opus"')) audioCodecs.add('opus');
        if (canPlay(audio, 'audio/ogg; codecs="vorbis"')) audioCodecs.add('vorbis');

        // H.264/AAC MP4 is the safe fallback target for MSE/Hls.js. If a
        // browser's canPlayType implementation is overly conservative but it
        // exposes MediaSource, advertise those baseline codecs.
        if (window.MediaSource?.isTypeSupported?.('video/mp4; codecs="avc1.42E01E"')) {
            containers.add('mp4');
            videoCodecs.add('h264');
        }
        if (window.MediaSource?.isTypeSupported?.('audio/mp4; codecs="mp4a.40.2"')) {
            audioCodecs.add('aac');
        }

        return {
            containers: Array.from(containers),
            video_codecs: Array.from(videoCodecs),
            audio_codecs: Array.from(audioCodecs),
            subtitle_formats: ['vtt'],
            max_width: null,
            max_height: null,
            max_bitrate: null,
        };
    }

    function nativeHlsSupported(video) {
        return canPlay(video, 'application/vnd.apple.mpegurl') ||
               canPlay(video, 'application/x-mpegURL');
    }

    function loadHlsLibrary() {
        if (window.Hls) return Promise.resolve(window.Hls);
        if (Core.hlsPromise) return Core.hlsPromise;

        Core.hlsPromise = new Promise((resolve, reject) => {
            const load = (src, fallback = false) => {
                const script = document.createElement('script');
                script.src = src;
                script.async = true;
                script.onload = () => window.Hls ? resolve(window.Hls) : reject(new Error('Hls.js did not initialise'));
                script.onerror = () => {
                    script.remove();
                    if (!fallback) {
                        load(`https://cdn.jsdelivr.net/npm/hls.js@${HLS_VERSION}/dist/hls.min.js`, true);
                    } else {
                        reject(new Error('Hls.js is unavailable offline; run the Nomad vendor-assets step while online'));
                    }
                };
                document.head.appendChild(script);
            };
            load('/vendor/hls/hls.min.js');
        }).catch(err => {
            Core.hlsPromise = null;
            throw err;
        });
        return Core.hlsPromise;
    }

    function absolutePosition() {
        const v = V?.el;
        if (!v) return 0;
        return Number(Core.current?.offset || 0) + Number(v.currentTime || 0);
    }

    function absoluteDuration() {
        const canonical = Number(Core.current?.sourceDuration || 0);
        if (canonical > 0 && isFinite(canonical)) return canonical;
        const v = V?.el;
        if (!v || !isFinite(v.duration)) return 0;
        return Number(Core.current?.offset || 0) + Number(v.duration || 0);
    }

    function stopHeartbeat(current) {
        if (current?.heartbeatTimer) {
            clearInterval(current.heartbeatTimer);
            current.heartbeatTimer = null;
        }
    }

    async function heartbeat(state) {
        const current = Core.current;
        const v = V?.el;
        if (!current || !v) return;
        try {
            const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/heartbeat`, {
                method: 'POST',
                body: JSON.stringify({
                    position: absolutePosition(),
                    duration: absoluteDuration(),
                    state: state || (v.paused ? 'paused' : 'playing'),
                }),
            });
            if (Core.current === current && !current.sourceDuration) {
                const duration = Number(result?.session?.duration || 0);
                if (duration > 0 && isFinite(duration)) current.sourceDuration = duration;
            }
        } catch {
            // Heartbeats must never interrupt playback.
        }
    }

    function startHeartbeat(current) {
        stopHeartbeat(current);
        current.heartbeatTimer = setInterval(() => heartbeat(), 15000);
        const v = V?.el;
        if (!v) return;
        v.addEventListener('playing', () => heartbeat('playing'));
        v.addEventListener('pause', () => heartbeat('paused'));
        v.addEventListener('ended', () => heartbeat('ended'));
    }

    function destroyHls(current) {
        if (!current?.hls) return;
        try { current.hls.destroy(); } catch {}
        current.hls = null;
    }

    async function attachHls(current, autoplay = true) {
        const video = V?.el;
        if (!video || !current || Core.current !== current) return;
        if (nativeHlsSupported(video)) {
            video.src = current.url;
            video.load();
            if (autoplay) video.play().catch(() => {});
            return;
        }

        const HlsCtor = await loadHlsLibrary();
        if (!V?.el || Core.current !== current) return;
        if (!HlsCtor.isSupported()) throw new Error('This browser does not expose MediaSource HLS support');

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
            if (data.type === HlsCtor.ErrorTypes.NETWORK_ERROR) {
                hls.startLoad();
            } else if (data.type === HlsCtor.ErrorTypes.MEDIA_ERROR) {
                hls.recoverMediaError();
            } else {
                toast(`Adaptive stream stopped: ${data.details || 'fatal HLS error'}`, 'error', 7000);
                destroyHls(current);
            }
        });
    }

    function runLegacyPlayer(path, url, at) {
        const originalStreamUrl = streamUrl;
        streamUrl = (candidate, extra = '') => {
            if (candidate === path && !extra) return url;
            return originalStreamUrl(candidate, extra);
        };
        try {
            legacyPlayVideo(path, at);
        } finally {
            streamUrl = originalStreamUrl;
        }
    }

    playVideo = async function nomadPlayVideo(path, at = 0) {
        const mediaKind = kindOf(path);
        if (mediaKind !== 'video') return legacyPlayVideo(path, at);

        try {
            const result = await api('/playback/start', {
                method: 'POST',
                body: JSON.stringify({
                    path,
                    capabilities: browserCapabilities(),
                    device_id: deviceId(),
                    quality: 'auto',
                    position: Math.max(0, Number(at) || 0),
                }),
            });

            const isHls = result.playback?.type === 'hls';
            const legacyStart = isHls ? 0 : Math.max(0, Number(at) || 0);
            runLegacyPlayer(path, result.playback.url, legacyStart);

            const sourceDuration = Number(result.session?.duration || result.plan?.source?.duration || 0);
            const current = {
                id: result.session.id,
                path,
                type: result.playback.type,
                mode: result.plan?.mode,
                url: result.playback.url,
                offset: isHls ? Math.max(0, Number(at) || 0) : 0,
                sourceDuration: sourceDuration > 0 && isFinite(sourceDuration) ? sourceDuration : 0,
                hls: null,
                heartbeatTimer: null,
            };
            Core.current = current;
            V.nomadPlaybackSession = current.id;
            V.nomadOffset = current.offset;

            if (isHls) {
                const modeLabel = String(current.mode || '').replaceAll('_', ' ');
                toast(`${modeLabel || 'Adaptive'} playback`, 'info', 1800);
                await attachHls(current, true);
            }
            startHeartbeat(current);
        } catch (err) {
            console.warn('[Nomad playback core] falling back to legacy stream:', err);
            toast(`Adaptive playback unavailable: ${err?.message || err}`, 'warn', 5000);
            legacyPlayVideo(path, at);
        }
    };

    stopVideo = function nomadStopVideo() {
        const retiring = Core.current;
        Core.current = null;
        if (retiring) {
            stopHeartbeat(retiring);
            destroyHls(retiring);
        }
        legacyStopVideo();
        if (retiring?.id) {
            fetch(`${API}/playback/sessions/${encodeURIComponent(retiring.id)}`, {
                method: 'DELETE',
                headers: authHeaders(),
                keepalive: true,
            }).catch(() => {});
        }
    };

    if (legacyReconnectVideo) {
        reconnectVideo = function nomadReconnectVideo() {
            const current = Core.current;
            if (current?.hls) {
                try { current.hls.startLoad(); } catch {}
                return;
            }
            return legacyReconnectVideo();
        };
    }

    if (legacyUpdateScrub) {
        updateScrub = function nomadUpdateScrub() {
            const current = Core.current;
            const v = V?.el;
            const total = absoluteDuration();
            if (!current || current.type !== 'hls' || !v || total <= 0) {
                return legacyUpdateScrub();
            }
            const elapsed = absolutePosition();
            const pct = Math.max(0, Math.min(100, (elapsed / total) * 100));
            $('#player-fill').style.width = `${pct}%`;
            $('#player-knob').style.left = `${pct}%`;
            $('#player-elapsed').textContent = fmtTime(elapsed);
            $('#player-remaining').textContent = `-${fmtTime(Math.max(0, total - elapsed))}`;
        };
    }

    if (legacySaveProgress) {
        saveProgress = async function nomadSaveProgress(finished = false) {
            const current = Core.current;
            const v = V?.el;
            const duration = absoluteDuration();
            if (!current || current.type !== 'hls' || !v || !V.path || duration <= 0) {
                return legacySaveProgress(finished);
            }
            const currentTime = finished ? duration : absolutePosition();
            try {
                await fetch(`${API}/media/progress`, {
                    method: 'POST',
                    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: V.path, current_time: currentTime, duration }),
                    keepalive: true,
                });
            } catch {}
        };
    }

    async function seekHls(target) {
        const current = Core.current;
        const video = V?.el;
        if (!current || current.type !== 'hls' || !video || Core.seeking) return;
        Core.seeking = true;
        const wasPlaying = !video.paused;
        try {
            const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/seek`, {
                method: 'POST',
                body: JSON.stringify({ position: Math.max(0, Number(target) || 0) }),
            });
            if (Core.current !== current) return;
            current.offset = Number(result.source_offset || 0);
            const duration = Number(result.session?.duration || 0);
            if (duration > 0 && isFinite(duration)) current.sourceDuration = duration;
            current.url = result.playback.url;
            V.url = current.url;
            V.nomadOffset = current.offset;
            await attachHls(current, wasPlaying);
            updateScrub();
            heartbeat(wasPlaying ? 'playing' : 'paused');
        } catch (err) {
            toast(`Could not seek: ${err?.message || err}`, 'error', 5000);
        } finally {
            Core.seeking = false;
        }
    }

    const scrubber = $('#player-scrubber');
    if (scrubber) {
        scrubber.addEventListener('click', (event) => {
            const current = Core.current;
            const video = V?.el;
            const total = absoluteDuration();
            if (!current || current.type !== 'hls' || !video || total <= 0) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            const track = $('#player-scrubber .scrub-track');
            const rect = track.getBoundingClientRect();
            const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
            seekHls(total * fraction);
        }, true);
    }
})();
