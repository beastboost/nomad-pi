/* Nomad Pi Stream + Keep — play a debrid source now while saving it locally. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function') return;

    const SK = {
        current: null,
        pollTimer: null,
        legacyRenderTorrents: typeof renderTorrents === 'function' ? renderTorrents : null,
    };
    window.NomadStreamKeep = SK;

    function videoCapabilities() {
        const video = document.createElement('video');
        const audio = document.createElement('audio');
        const can = (el, mime) => {
            try { return Boolean(el.canPlayType(mime)); } catch { return false; }
        };
        const containers = [];
        const videoCodecs = [];
        const audioCodecs = [];
        if (can(video, 'video/mp4')) containers.push('mp4');
        if (can(video, 'video/webm')) containers.push('webm');
        if (can(video, 'video/mp4; codecs="avc1.42E01E"')) videoCodecs.push('h264');
        if (can(video, 'video/mp4; codecs="hvc1.1.6.L93.B0"')) videoCodecs.push('hevc');
        if (can(video, 'video/webm; codecs="vp9"')) videoCodecs.push('vp9');
        if (can(video, 'video/mp4; codecs="av01.0.05M.08"')) videoCodecs.push('av1');
        if (can(audio, 'audio/mp4; codecs="mp4a.40.2"')) audioCodecs.push('aac');
        if (can(audio, 'audio/mpeg')) audioCodecs.push('mp3');
        if (can(audio, 'audio/ogg; codecs="opus"')) audioCodecs.push('opus');
        if (window.MediaSource?.isTypeSupported?.('video/mp4; codecs="avc1.42E01E"')) {
            if (!containers.includes('mp4')) containers.push('mp4');
            if (!videoCodecs.includes('h264')) videoCodecs.push('h264');
        }
        if (window.MediaSource?.isTypeSupported?.('audio/mp4; codecs="mp4a.40.2"')) {
            if (!audioCodecs.includes('aac')) audioCodecs.push('aac');
        }
        return {
            containers,
            video_codecs: videoCodecs,
            audio_codecs: audioCodecs,
            subtitle_formats: ['vtt'],
            max_width: null,
            max_height: null,
            max_bitrate: null,
        };
    }

    function enhanceTorrentActions() {
        $$('#debrid-results [data-grab]').forEach(button => {
            const index = button.dataset.grab;
            const row = button.closest('.torrent-row');
            if (!row || row.querySelector(`[data-streamkeep="${CSS.escape(index)}"]`)) return;
            const stream = document.createElement('button');
            stream.className = 'btn';
            stream.dataset.streamkeep = index;
            stream.innerHTML = '<i class="ph ph-play-circle"></i> Stream + Keep';
            row.insertBefore(stream, button);
        });
    }

    if (SK.legacyRenderTorrents) {
        renderTorrents = async function streamKeepRenderTorrents(...args) {
            const value = await SK.legacyRenderTorrents(...args);
            enhanceTorrentActions();
            return value;
        };
        setTimeout(enhanceTorrentActions, 0);
    }

    function selectedVideo(magnet) {
        const links = Array.isArray(magnet?.links) ? magnet.links : [];
        const allSelected = (magnet?.files || []).filter(file => file?.selected !== false);
        const videoExt = /\.(mkv|mp4|m4v|webm|avi|mov|ts|m2ts|mts|wmv|mpg|mpeg)(?:$|[?#])/i;
        const candidates = allSelected
            .map((file, index) => ({ file, index }))
            .filter(item => videoExt.test(String(item.file?.path || item.file?.name || '')))
            .sort((a, b) => Number(b.file?.bytes || b.file?.size || 0) - Number(a.file?.bytes || a.file?.size || 0));
        const chosen = candidates[0] || (allSelected.length ? { file: allSelected[0], index: 0 } : null);
        let linkIndex = chosen?.index ?? 0;
        if (linkIndex >= links.length) linkIndex = 0;
        return {
            link: links[linkIndex] || links[0] || null,
            file: chosen?.file || null,
        };
    }

    function statusSheet(title, message) {
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Stream + Keep</div>
          <div style="font-size:16px;margin-bottom:8px">${escapeHtml(title || 'Preparing media')}</div>
          <div class="facts-note" id="stream-keep-status" style="text-align:left">${escapeHtml(message)}</div>
          <div class="bar" style="margin-top:14px"><span style="width:18%"></span></div>`);
    }

    function setPreparing(message, pct) {
        const text = $('#stream-keep-status');
        if (text) text.textContent = message;
        const bar = $('#sheet .bar span');
        if (bar && pct !== undefined) bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    }

    async function resolveStreamKeep(index) {
        const result = S.debrid.results?.[Number(index)];
        const title = S.debrid.title;
        if (!result || !title) return;
        statusSheet(result.name || title.title, 'Resolving cached release…');

        try {
            // Torrent search results use info_hash. Keep the old `hash` name as
            // a compatibility fallback for providers/older cached responses,
            // but never send an undefined field to FastAPI.
            const infoHash = String(result.info_hash || result.hash || '').trim();
            if (!infoHash) throw new Error('That release has no usable info hash');

            const magnet = await api('/debrid/magnet', {
                method: 'POST',
                body: JSON.stringify({
                    info_hash: infoHash,
                    title: title.title,
                    year: String(title.year || ''),
                    media_type: title.type || 'movie',
                    season: result.season || 1,
                    episode: result.episode || 1,
                }),
            });
            setPreparing('Opening the provider stream…', 32);
            const chosen = selectedVideo(magnet);
            if (!chosen.link) throw new Error('Provider returned no playable file link');

            const unrestricted = await api('/debrid/unrestrict', {
                method: 'POST',
                body: JSON.stringify({ link: chosen.link }),
            });
            if (!unrestricted?.url) throw new Error('Provider did not return a stream URL');
            setPreparing('Planning playback and starting the local copy…', 55);

            const rawName = chosen.file?.path || chosen.file?.name || unrestricted.filename || result.name || title.title;
            const filename = String(rawName).split('/').pop() || `${title.title}.mkv`;
            const isShow = title.type === 'series' || title.type === 'show';
            const started = await api('/playback/stream-keep/start', {
                method: 'POST',
                body: JSON.stringify({
                    url: unrestricted.url,
                    filename,
                    provider: magnet.provider || 'debrid',
                    category: isShow ? 'shows' : 'movies',
                    is_show: isShow,
                    position: 0,
                    capabilities: videoCapabilities(),
                    metadata: {
                        title: title.title,
                        year: title.year,
                        media_type: title.type || 'movie',
                        imdb_id: title.imdb_id || null,
                        info_hash: infoHash,
                        release: result.name || filename,
                        quality: result.quality || null,
                        codec: result.codec || null,
                    },
                }),
            });
            setPreparing('Starting playback…', 90);
            closeSheet();
            await openRemotePlayer(started, title.title || filename);
        } catch (err) {
            const text = $('#stream-keep-status');
            if (text) text.textContent = err?.message || 'Could not start Stream + Keep';
            const bar = $('#sheet .bar span');
            if (bar) bar.style.width = '100%';
            toast(err?.message || 'Could not start Stream + Keep', 'error', 7000);
        }
    }

    function setRemoteControls(on) {
        ['#player-quality', '#player-audio', '#player-subs', '#player-cast'].forEach(selector => {
            const el = $(selector);
            if (el) el.disabled = Boolean(on);
        });
    }

    function createRemoteVideoShell(title, result) {
        if (typeof stopAudio === 'function' && S?.audio?.playing) stopAudio();
        stopVideo();
        push('player');
        V.path = null;
        V.url = result.playback.url;
        V.reconnects = 0;
        V.seekTo = 0;
        $('#player-title').textContent = title || result.job?.filename || 'Remote media';
        $('#player-sub').textContent = 'STREAM + KEEP';
        const stage = $('#player-stage');
        $('#player-ghost')?.classList.add('hidden');
        const video = document.createElement('video');
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.preload = 'metadata';
        stage.insertBefore(video, stage.firstChild);
        V.el = video;
        video.addEventListener('loadedmetadata', updateScrub);
        video.addEventListener('timeupdate', updateScrub);
        video.addEventListener('play', () => {
            setPlayIcon(true);
            if (typeof requestWake === 'function') requestWake();
            if (typeof showChrome === 'function') showChrome();
        });
        video.addEventListener('pause', () => {
            setPlayIcon(false);
            if (typeof releaseWake === 'function') releaseWake();
        });
        video.addEventListener('ended', () => setPlayIcon(false));
        video.addEventListener('error', () => {
            if (video.error) toast('Remote stream stopped unexpectedly', 'error', 6000);
        });
        return video;
    }

    async function openRemotePlayer(result, title) {
        if (!result?.job?.id || !result?.playback?.url) throw new Error('Stream + Keep did not return a playable session');
        const video = createRemoteVideoShell(title, result);
        const source = result.plan?.source || result.job?.remote_playback?.source || {};
        const current = {
            id: result.job.id,
            streamKeepJob: result.job.id,
            path: null,
            type: result.playback.type,
            mode: result.plan?.mode,
            url: result.playback.url,
            offset: 0,
            sourceDuration: Number(source.duration || 0),
            quality: 'remote',
            audioTrack: null,
            subtitleTrack: null,
            hls: null,
        };
        Core.current = current;
        V.nomadPlaybackSession = null;
        V.nomadOffset = 0;
        setRemoteControls(true);

        await Core.applyReplacement({
            session: {
                id: result.job.id,
                mode: result.plan?.mode,
                duration: Number(source.duration || 0),
                position: 0,
                quality: 'remote',
                audio_track: null,
                subtitle_track: null,
            },
            playback: result.playback,
            source_offset: 0,
        }, { autoplay: true, absolute: 0 });

        // Prevent the normal HLS scrub handler from calling the local-session
        // seek route; Stream + Keep owns a separate remote seek endpoint.
        current.type = result.playback.type === 'hls' ? 'stream_keep_hls' : 'stream_keep_direct';
        SK.current = {
            jobId: result.job.id,
            title,
            localPath: null,
            completeNotified: false,
        };
        pollJob();
    }

    async function seekRemoteHls(target) {
        const active = SK.current;
        const current = Core.current;
        const video = V?.el;
        if (!active || !current || current.type !== 'stream_keep_hls' || !video) return;
        const wasPlaying = !video.paused;
        try {
            const result = await api(`/playback/stream-keep/${encodeURIComponent(active.jobId)}/seek`, {
                method: 'POST',
                body: JSON.stringify({ position: Math.max(0, Number(target) || 0) }),
            });
            if (!SK.current || SK.current.jobId !== active.jobId) return;
            const job = result.job || {};
            await Core.applyReplacement({
                session: {
                    id: active.jobId,
                    mode: job.remote_playback?.mode,
                    duration: Number(job.remote_playback?.source?.duration || current.sourceDuration || 0),
                    position: Number(result.source_offset || target || 0),
                    quality: 'remote',
                },
                playback: result.playback,
                source_offset: Number(result.source_offset || target || 0),
            }, { autoplay: wasPlaying, absolute: Number(target || 0) });
            current.type = 'stream_keep_hls';
        } catch (err) {
            toast(err?.message || 'Could not seek the remote stream', 'error', 5500);
        }
    }

    $('#player-scrubber')?.addEventListener('click', event => {
        const current = Core.current;
        if (!SK.current || current?.type !== 'stream_keep_hls') return;
        event.preventDefault();
        event.stopImmediatePropagation();
        const track = $('#player-scrubber .scrub-track');
        if (!track) return;
        const rect = track.getBoundingClientRect();
        const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
        const total = Number(current.sourceDuration || 0);
        if (total > 0) seekRemoteHls(total * fraction);
    }, true);

    async function pollJob() {
        clearInterval(SK.pollTimer);
        const tick = async () => {
            const active = SK.current;
            if (!active) return;
            try {
                const data = await api(`/playback/stream-keep/${encodeURIComponent(active.jobId)}`);
                const job = data.job || {};
                const pct = Math.round(Number(job.progress || 0));
                const sub = $('#player-sub');
                if (sub) {
                    sub.textContent = job.status === 'local_ready'
                        ? 'SAVED LOCALLY ✓'
                        : job.status === 'downloading'
                            ? `STREAM + KEEP · SAVING ${pct}%`
                            : `STREAM + KEEP · ${String(job.status || '').replaceAll('_', ' ').toUpperCase()}`;
                }
                if (job.status === 'local_ready') {
                    active.localPath = job.local_path;
                    if (!active.completeNotified) {
                        active.completeNotified = true;
                        toast('Local copy finished — future playback can use the Pi copy.', 'success', 4500);
                    }
                    clearInterval(SK.pollTimer);
                    SK.pollTimer = null;
                } else if (['failed', 'cancelled', 'interrupted'].includes(job.status)) {
                    toast(`Local copy ${job.status}: ${job.error || 'download stopped'}`, 'warn', 5500);
                    clearInterval(SK.pollTimer);
                    SK.pollTimer = null;
                }
            } catch {}
        };
        await tick();
        if (SK.current && !SK.pollTimer) SK.pollTimer = setInterval(tick, 2000);
    }

    const previousStopVideo = stopVideo;
    stopVideo = function streamKeepStopVideo() {
        const active = SK.current;
        if (!active) return previousStopVideo();
        SK.current = null;
        clearInterval(SK.pollTimer);
        SK.pollTimer = null;
        setRemoteControls(false);
        if (Core.current?.streamKeepJob === active.jobId) Core.current = null;
        fetch(`${API}/playback/stream-keep/${encodeURIComponent(active.jobId)}/playback`, {
            method: 'DELETE', headers: authHeaders(), keepalive: true,
        }).catch(() => {});
        return previousStopVideo();
    };

    document.addEventListener('click', event => {
        const button = event.target.closest('[data-streamkeep]');
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        resolveStreamKeep(Number(button.dataset.streamkeep));
    }, true);
})();
