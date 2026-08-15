/* Nomad Pi runtime quality selector for the Nocturne player. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function' || typeof openSheet !== 'function') return;

    const HLS_VERSION = '1.6.16';
    let hlsLoadPromise = null;

    const qualityButton = document.createElement('button');
    qualityButton.className = 'btn';
    qualityButton.id = 'player-quality';
    qualityButton.innerHTML = '<i class="ph ph-monitor-play" style="font-size:17px"></i>Auto';
    const speedButton = $('#player-speed');
    if (speedButton?.parentNode) speedButton.parentNode.insertBefore(qualityButton, speedButton);

    function currentPosition() {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) return 0;
        return Math.max(0, Number(current.offset || 0) + Number(video.currentTime || 0));
    }

    function nativeHls(video) {
        try {
            return Boolean(video.canPlayType('application/vnd.apple.mpegurl') ||
                           video.canPlayType('application/x-mpegURL'));
        } catch {
            return false;
        }
    }

    function loadHls() {
        if (window.Hls) return Promise.resolve(window.Hls);
        if (hlsLoadPromise) return hlsLoadPromise;
        hlsLoadPromise = new Promise((resolve, reject) => {
            const inject = (src, fallback) => {
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
            inject('/vendor/hls/hls.min.js', false);
        }).catch(err => {
            hlsLoadPromise = null;
            throw err;
        });
        return hlsLoadPromise;
    }

    async function attachResult(current, result, resumePosition, autoplay) {
        const video = V?.el;
        if (!video || Core.current !== current) return;
        if (current.hls) {
            try { current.hls.destroy(); } catch {}
            current.hls = null;
        }

        if (result.playback.type === 'direct') {
            current.type = 'direct';
            current.offset = 0;
            video.src = result.playback.url;
            video.load();
            if (resumePosition > 0) {
                video.addEventListener('loadedmetadata', () => {
                    try { video.currentTime = Math.min(resumePosition, video.duration || resumePosition); } catch {}
                    if (autoplay) video.play().catch(() => {});
                }, { once: true });
            } else if (autoplay) {
                video.play().catch(() => {});
            }
            return;
        }

        current.type = 'hls';
        current.offset = Number(result.source_offset || resumePosition || 0);
        if (nativeHls(video)) {
            video.src = result.playback.url;
            video.load();
            if (autoplay) video.play().catch(() => {});
            return;
        }

        const HlsCtor = await loadHls();
        if (!HlsCtor.isSupported()) throw new Error('This browser does not support MediaSource HLS playback');
        if (!V?.el || Core.current !== current) return;
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
        hls.on(HlsCtor.Events.MEDIA_ATTACHED, () => hls.loadSource(result.playback.url));
        hls.on(HlsCtor.Events.MANIFEST_PARSED, () => {
            if (autoplay && Core.current === current) video.play().catch(() => {});
        });
        hls.on(HlsCtor.Events.ERROR, (_event, data) => {
            if (!data?.fatal || Core.current !== current) return;
            if (data.type === HlsCtor.ErrorTypes.NETWORK_ERROR) hls.startLoad();
            else if (data.type === HlsCtor.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
            else {
                try { hls.destroy(); } catch {}
                current.hls = null;
                toast(`Quality stream failed: ${data.details || 'fatal HLS error'}`, 'error', 6000);
            }
        });
    }

    async function openQualityMenu() {
        const current = Core.current;
        if (!current) {
            toast('Start a video before changing quality.', 'info', 3000);
            return;
        }
        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Playback quality</div>
          <div id="nomad-quality-list"><div class="empty"><div class="spinner"></div></div></div>`);
        try {
            const data = await api('/playback/quality-profiles');
            const profiles = data.profiles || [];
            const selected = current.quality || 'auto';
            const out = $('#nomad-quality-list');
            if (!out) return;
            out.innerHTML = `<div class="list">${profiles.map(profile => `
              <button class="sheet-option row-rule" data-nomad-quality="${escapeHtml(profile.id)}">
                <span style="text-align:left">
                  <span style="display:block">${escapeHtml(profile.label)}</span>
                  ${profile.max_bitrate ? `<span class="list-sub">up to ${Math.round(profile.max_bitrate / 1e6)} Mbps</span>` : ''}
                </span>
                ${profile.id === selected ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>' : ''}
              </button>`).join('')}</div>`;
        } catch (err) {
            const out = $('#nomad-quality-list');
            if (out) out.innerHTML = `<div class="facts-note">${escapeHtml(err.message || 'Could not load quality profiles')}</div>`;
        }
    }

    async function switchQuality(quality) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) return;
        const absolute = currentPosition();
        const wasPlaying = !video.paused;
        closeSheet();
        toast(`Preparing ${quality}…`, 'info', 1800);

        try {
            const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/quality`, {
                method: 'POST',
                body: JSON.stringify({ quality, position: absolute }),
            });
            if (Core.current !== current) return;

            current.id = result.session.id;
            current.mode = result.session.mode;
            current.url = result.playback.url;
            current.quality = result.session.quality || quality;
            current.audioTrack = result.session.audio_track;
            V.url = current.url;
            V.nomadPlaybackSession = current.id;

            await attachResult(current, result, absolute, wasPlaying);
            V.nomadOffset = current.offset;
            if (typeof updateScrub === 'function') updateScrub();

            const label = current.quality === 'original'
                ? 'Original'
                : current.quality === 'auto'
                    ? 'Auto'
                    : current.quality;
            qualityButton.innerHTML = `<i class="ph ph-monitor-play" style="font-size:17px"></i>${escapeHtml(label)}`;
            toast(`Quality: ${label}`, 'success', 2500);
        } catch (err) {
            toast(err.message || 'Could not change playback quality', 'error', 6000);
        }
    }

    qualityButton.addEventListener('click', event => {
        event.preventDefault();
        openQualityMenu();
    });

    document.addEventListener('click', event => {
        const choice = event.target.closest('[data-nomad-quality]');
        if (!choice) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        switchQuality(choice.dataset.nomadQuality);
    }, true);
})();
