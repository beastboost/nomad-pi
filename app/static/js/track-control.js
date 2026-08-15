/* Nomad Pi embedded audio-track controls for the Nocturne player. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function' || typeof openSheet !== 'function') return;

    const HLS_VERSION = '1.6.16';
    let hlsLoadPromise = null;

    function currentAbsolutePosition() {
        const current = Core.current;
        const video = typeof V !== 'undefined' ? V.el : null;
        if (!current || !video) return 0;
        return Math.max(0, Number(current.offset || 0) + Number(video.currentTime || 0));
    }

    function trackLabel(track) {
        const bits = [];
        const lang = String(track.language || 'und').toUpperCase();
        bits.push(track.title || lang);
        if (track.codec) bits.push(String(track.codec).toUpperCase());
        if (track.channel_layout) bits.push(track.channel_layout);
        else if (track.channels) bits.push(`${track.channels}ch`);
        if (track.default) bits.push('Default');
        if (track.visual_impaired) bits.push('Audio description');
        return bits.filter(Boolean).join(' · ');
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
                    if (!fallback) {
                        inject(`https://cdn.jsdelivr.net/npm/hls.js@${HLS_VERSION}/dist/hls.min.js`, true);
                    } else {
                        reject(new Error('Hls.js is unavailable'));
                    }
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

    async function attachReplacement(current, autoplay) {
        const video = V?.el;
        if (!video || Core.current !== current) return;
        if (current.hls) {
            try { current.hls.destroy(); } catch {}
            current.hls = null;
        }

        if (nativeHls(video)) {
            video.src = current.url;
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
        hls.on(HlsCtor.Events.MEDIA_ATTACHED, () => hls.loadSource(current.url));
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
                toast(`Audio stream failed: ${data.details || 'fatal HLS error'}`, 'error', 6000);
            }
        });
    }

    async function openAudioTracks() {
        const current = Core.current;
        if (!current || !V?.path) {
            toast('Start a video before choosing an audio track.', 'info', 3000);
            return;
        }

        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Audio track</div>
          <div id="nomad-audio-list"><div class="empty"><div class="spinner"></div></div></div>`);

        try {
            const data = await api(`/playback/tracks?path=${encodeURIComponent(V.path)}`);
            const tracks = data.audio || [];
            const out = $('#nomad-audio-list');
            if (!out) return;
            if (!tracks.length) {
                out.innerHTML = '<div class="facts-note" style="text-align:left">No audio streams found.</div>';
                return;
            }
            const active = Number(current.audioTrack ?? current.audio_track ?? -1);
            out.innerHTML = `<div class="list">${tracks.map((track, i) => {
                const selected = active === Number(track.stream_index) || (active < 0 && track.default) || (active < 0 && i === 0);
                return `
                  <button class="sheet-option row-rule" data-nomad-audio="${Number(track.stream_index)}">
                    <span style="min-width:0;text-align:left">
                      <span style="display:block">${escapeHtml(trackLabel(track))}</span>
                    </span>
                    ${selected ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>' : ''}
                  </button>`;
            }).join('')}</div>`;
        } catch (err) {
            const out = $('#nomad-audio-list');
            if (out) out.innerHTML = `<div class="facts-note" style="text-align:left">${escapeHtml(err.message || 'Could not inspect audio tracks')}</div>`;
        }
    }

    async function switchAudio(streamIndex) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) return;
        const wasPlaying = !video.paused;
        const absolute = currentAbsolutePosition();
        closeSheet();
        toast('Switching audio track…', 'info', 1800);

        try {
            const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/audio`, {
                method: 'POST',
                body: JSON.stringify({ stream_index: streamIndex, position: absolute }),
            });
            if (Core.current !== current) return;

            if (current.hls) {
                try { current.hls.destroy(); } catch {}
                current.hls = null;
            }
            current.id = result.session.id;
            current.type = 'hls';
            current.mode = result.session.mode;
            current.url = result.playback.url;
            current.offset = Number(result.source_offset || absolute || 0);
            current.audioTrack = Number(result.track.stream_index);
            V.url = current.url;
            V.nomadPlaybackSession = current.id;
            V.nomadOffset = current.offset;

            await attachReplacement(current, wasPlaying);
            if (typeof updateScrub === 'function') updateScrub();
            const button = $('#player-audio');
            if (button) {
                const lang = String(result.track.language || 'Audio').toUpperCase();
                button.innerHTML = `<i class="ph ph-speaker-high" style="font-size:17px"></i>${escapeHtml(lang)}`;
            }
            toast(`Audio: ${trackLabel(result.track)}`, 'success', 3000);
        } catch (err) {
            toast(err.message || 'Could not switch audio track', 'error', 6000);
        }
    }

    document.addEventListener('click', (event) => {
        const audioButton = event.target.closest('#player-audio');
        if (audioButton) {
            event.preventDefault();
            event.stopImmediatePropagation();
            openAudioTracks();
            return;
        }

        const choice = event.target.closest('[data-nomad-audio]');
        if (choice) {
            event.preventDefault();
            event.stopImmediatePropagation();
            switchAudio(Number(choice.dataset.nomadAudio));
        }
    }, true);
})();
