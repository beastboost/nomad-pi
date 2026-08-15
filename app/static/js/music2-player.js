/* Nomad Pi Music 2.0 — structured catalog + persistent Nocturne player. */
(() => {
    if (typeof loadLibrary !== 'function' || typeof playAudio !== 'function') return;

    const legacyLoadLibrary = loadLibrary;
    const QUEUE_KEY = 'nomad_music2_queue';
    const STATE_KEY = 'nomad_music2_state';
    const DEVICE_KEY = 'nomad_playback_device_id';
    const HLS_VERSION = '1.6.16';

    const M = {
        tracks: [],
        fallback: [],
        view: 'songs',
        queue: [],
        index: -1,
        shuffle: false,
        repeat: 'none',
        shuffleOrder: [],
        shufflePos: 0,
        sessionId: null,
        hls: null,
        hlsPromise: null,
        audioContext: null,
        sourceNode: null,
        gainNode: null,
        pollTimer: null,
        loaded: false,
    };
    window.NomadMusic = M;

    function restoreState() {
        try {
            const state = JSON.parse(localStorage.getItem(STATE_KEY) || '{}');
            M.shuffle = Boolean(state.shuffle);
            M.repeat = ['none', 'all', 'one'].includes(state.repeat) ? state.repeat : 'none';
            const q = JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]');
            if (Array.isArray(q)) M.queue = q.filter(x => x?.path).slice(0, 2000);
        } catch {}
    }

    function saveState() {
        try {
            localStorage.setItem(STATE_KEY, JSON.stringify({ shuffle: M.shuffle, repeat: M.repeat }));
            localStorage.setItem(QUEUE_KEY, JSON.stringify(M.queue.slice(0, 2000)));
        } catch {}
    }

    function artUrl(track) {
        if (!track?.has_artwork || !track.path) return '';
        const t = token();
        return `${API}/playback/music/artwork?path=${encodeURIComponent(track.path)}${t ? `&token=${encodeURIComponent(t)}` : ''}`;
    }

    function trackTitle(track) {
        return track?.title || stripExt(track?.name || baseName(track?.path || '')) || 'Unknown track';
    }

    function trackArtist(track) {
        return track?.artist || 'Unknown Artist';
    }

    function albumName(track) {
        return track?.album || 'Unknown Album';
    }

    function techLine(track) {
        const bits = [];
        if (track.codec) bits.push(String(track.codec).toUpperCase());
        if (track.sample_rate) bits.push(`${Math.round(Number(track.sample_rate) / 1000 * 10) / 10} kHz`);
        if (track.bit_depth) bits.push(`${track.bit_depth}-bit`);
        if (track.bitrate) bits.push(`${Math.round(Number(track.bitrate) / 1000)} kbps`);
        return bits.join(' · ');
    }

    function ensureAudio() {
        const a = S.audio;
        if (a.el) return a.el;
        a.el = new Audio();
        a.el.preload = 'auto';
        a.el.addEventListener('timeupdate', updateNowPlaying);
        a.el.addEventListener('play', () => { a.playing = true; setAudioIcons(); });
        a.el.addEventListener('pause', () => { a.playing = false; setAudioIcons(); });
        a.el.addEventListener('ended', onEnded);
        a.el.addEventListener('error', () => {
            if (a.el?.error) toast('Audio playback failed', 'error', 4500);
        });
        return a.el;
    }

    async function ensureGainGraph() {
        const audio = ensureAudio();
        if (!window.AudioContext && !window.webkitAudioContext) return null;
        if (!M.audioContext) {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            M.audioContext = new Ctx();
            M.sourceNode = M.audioContext.createMediaElementSource(audio);
            M.gainNode = M.audioContext.createGain();
            M.sourceNode.connect(M.gainNode);
            M.gainNode.connect(M.audioContext.destination);
        }
        try { if (M.audioContext.state === 'suspended') await M.audioContext.resume(); } catch {}
        return M.gainNode;
    }

    async function applyReplayGain(track) {
        const node = await ensureGainGraph().catch(() => null);
        if (!node) return;
        const db = Number(track?.replaygain_track_gain);
        const gain = Number.isFinite(db) ? Math.pow(10, db / 20) : 1;
        node.gain.value = Math.max(0.1, Math.min(4, gain));
    }

    function audioCapabilities() {
        const el = document.createElement('audio');
        const can = mime => {
            try { return Boolean(el.canPlayType(mime)); } catch { return false; }
        };
        const containers = [];
        const codecs = [];
        if (can('audio/mpeg')) { containers.push('mp3'); codecs.push('mp3'); }
        if (can('audio/mp4')) containers.push('m4a', 'mp4');
        if (can('audio/mp4; codecs="mp4a.40.2"')) codecs.push('aac');
        if (can('audio/flac')) { containers.push('flac'); codecs.push('flac'); }
        if (can('audio/ogg')) containers.push('ogg');
        if (can('audio/ogg; codecs="opus"')) { containers.push('opus'); codecs.push('opus'); }
        if (can('audio/ogg; codecs="vorbis"')) codecs.push('vorbis');
        if (can('audio/wav')) containers.push('wav');
        return {
            containers: [...new Set(containers)],
            video_codecs: [],
            audio_codecs: [...new Set(codecs)],
            subtitle_formats: [],
            max_width: null,
            max_height: null,
            max_bitrate: null,
        };
    }

    function loadHls() {
        if (window.Hls) return Promise.resolve(window.Hls);
        if (M.hlsPromise) return M.hlsPromise;
        M.hlsPromise = new Promise((resolve, reject) => {
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
        }).catch(err => { M.hlsPromise = null; throw err; });
        return M.hlsPromise;
    }

    function destroyHls() {
        if (!M.hls) return;
        try { M.hls.destroy(); } catch {}
        M.hls = null;
    }

    async function attachAudioSource(playback) {
        const audio = ensureAudio();
        destroyHls();
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
        if (playback.type !== 'hls') {
            audio.src = playback.url;
            audio.load();
            return;
        }
        const native = Boolean(audio.canPlayType('application/vnd.apple.mpegurl') || audio.canPlayType('application/x-mpegURL'));
        if (native) {
            audio.src = playback.url;
            audio.load();
            return;
        }
        const HlsCtor = await loadHls();
        if (!HlsCtor.isSupported()) throw new Error('This browser cannot play the required audio HLS stream');
        M.hls = new HlsCtor({ enableWorker: true, lowLatencyMode: false, maxBufferLength: 60 });
        M.hls.attachMedia(audio);
        await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Audio HLS manifest timed out')), 12000);
            M.hls.on(HlsCtor.Events.MEDIA_ATTACHED, () => M.hls.loadSource(playback.url));
            M.hls.on(HlsCtor.Events.MANIFEST_PARSED, () => { clearTimeout(timer); resolve(); });
            M.hls.on(HlsCtor.Events.ERROR, (_event, data) => {
                if (!data?.fatal) return;
                clearTimeout(timer);
                reject(new Error(data.details || 'Audio HLS failed'));
            });
        });
    }

    async function stopPlaybackSession() {
        const id = M.sessionId;
        M.sessionId = null;
        if (!id) return;
        try {
            await fetch(`${API}/playback/sessions/${encodeURIComponent(id)}`, {
                method: 'DELETE', headers: authHeaders(), keepalive: true,
            });
        } catch {}
    }

    function updateArtwork(track) {
        const art = artUrl(track);
        const mini = $('#mini-player .mini-art');
        const large = $('#now-playing-sheet .np-art');
        const html = art
            ? `<img src="${escapeHtml(art)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit" onerror="this.parentElement.innerHTML='<i class=&quot;ph ph-music-note&quot;></i>'">`
            : '<i class="ph ph-music-note"></i>';
        if (mini) mini.innerHTML = html;
        if (large) large.innerHTML = html.replace('ph-music-note', 'ph-music-notes');
    }

    function updateMetadataUI(track) {
        const title = trackTitle(track);
        const artist = trackArtist(track);
        $('#mini-title').textContent = title;
        $('#mini-sub').textContent = artist;
        $('#np-title').textContent = title;
        $('#np-artist').textContent = [artist, track.album].filter(Boolean).join(' · ');
        $('#mini-player').classList.remove('hidden');
        if (S.screen === 'player') $('#mini-player').style.bottom = '20px';
        updateArtwork(track);
        updateMediaSession2(track);
        updateMusicControls();
    }

    async function playTrackAt(index) {
        if (index < 0 || index >= M.queue.length) return;
        M.index = index;
        const track = M.queue[index];
        S.audio.queue = M.queue.map(x => x.path);
        S.audio.index = index;
        saveState();
        updateMetadataUI(track);

        await stopPlaybackSession();
        let result;
        try {
            result = await api('/playback/start', {
                method: 'POST',
                body: JSON.stringify({
                    path: track.path,
                    capabilities: audioCapabilities(),
                    device_id: localStorage.getItem(DEVICE_KEY) || null,
                    quality: 'auto',
                    position: 0,
                }),
            });
            M.sessionId = result.session.id;
            await attachAudioSource(result.playback);
        } catch (err) {
            console.warn('[Music2] signed/adaptive audio path failed, falling back:', err);
            result = null;
            const audio = ensureAudio();
            destroyHls();
            audio.src = streamUrl(track.path);
            audio.load();
        }

        await applyReplayGain(track);
        const audio = ensureAudio();
        audio.play().catch(() => {});
    }

    function queueForTrack(path) {
        const visible = M.tracks.length ? M.tracks : M.fallback.map(x => ({
            path: x.path,
            name: x.name,
            title: stripExt(x.title || x.name || baseName(x.path)),
            artist: '', album: '', has_artwork: false,
        }));
        const index = visible.findIndex(x => x.path === path);
        if (index >= 0) {
            M.queue = visible.slice();
            M.index = index;
        } else {
            M.queue = [{ path, title: stripExt(baseName(path)), artist: '', album: '' }];
            M.index = 0;
        }
        rebuildShuffle(M.index);
        saveState();
    }

    playAudio = function music2PlayAudio(path) {
        const current = M.queue[M.index];
        if (!current || current.path !== path) queueForTrack(path);
        playTrackAt(M.index).catch(err => toast(err.message || 'Could not play track', 'error', 5500));
    };

    stopAudio = function music2StopAudio() {
        const audio = S.audio.el;
        if (audio) {
            audio.pause();
            audio.removeAttribute('src');
            audio.load();
        }
        destroyHls();
        stopPlaybackSession();
        S.audio.playing = false;
        $('#mini-player').classList.add('hidden');
        $('#now-playing-sheet').classList.add('hidden');
    };

    toggleAudio = function music2Toggle() {
        const audio = ensureAudio();
        if (!audio.src && !M.hls) return;
        if (audio.paused) {
            ensureGainGraph().then(() => audio.play().catch(() => {}));
        } else audio.pause();
    };

    function rebuildShuffle(startIndex = M.index) {
        M.shuffleOrder = Array.from({ length: M.queue.length }, (_, i) => i);
        for (let i = M.shuffleOrder.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [M.shuffleOrder[i], M.shuffleOrder[j]] = [M.shuffleOrder[j], M.shuffleOrder[i]];
        }
        const currentPos = M.shuffleOrder.indexOf(startIndex);
        if (currentPos > 0) [M.shuffleOrder[0], M.shuffleOrder[currentPos]] = [M.shuffleOrder[currentPos], M.shuffleOrder[0]];
        M.shufflePos = 0;
    }

    nextTrack = function music2Next() {
        if (!M.queue.length) return;
        if (M.shuffle) {
            M.shufflePos += 1;
            if (M.shufflePos >= M.shuffleOrder.length) {
                if (M.repeat !== 'all') return stopAtQueueEnd();
                rebuildShuffle(M.index);
                M.shufflePos = 0;
            }
            return playTrackAt(M.shuffleOrder[M.shufflePos]);
        }
        const next = M.index + 1;
        if (next < M.queue.length) return playTrackAt(next);
        if (M.repeat === 'all') return playTrackAt(0);
        stopAtQueueEnd();
    };

    prevTrack = function music2Prev() {
        const audio = S.audio.el;
        if (audio?.currentTime > 3) { audio.currentTime = 0; return; }
        if (!M.queue.length) return;
        if (M.shuffle) {
            M.shufflePos = Math.max(0, M.shufflePos - 1);
            return playTrackAt(M.shuffleOrder[M.shufflePos]);
        }
        if (M.index > 0) return playTrackAt(M.index - 1);
        if (M.repeat === 'all') return playTrackAt(M.queue.length - 1);
        if (audio) audio.currentTime = 0;
    };

    function onEnded() {
        if (M.repeat === 'one') {
            const audio = ensureAudio();
            audio.currentTime = 0;
            audio.play().catch(() => {});
            return;
        }
        nextTrack();
    }

    function stopAtQueueEnd() {
        S.audio.playing = false;
        setAudioIcons();
    }

    function updateNowPlaying() {
        const audio = S.audio.el;
        if (!audio || !audio.duration || !isFinite(audio.duration)) return;
        const pct = (audio.currentTime / audio.duration) * 100;
        $('#np-fill').style.width = `${pct}%`;
        $('#np-knob').style.left = `${pct}%`;
        $('#np-elapsed').textContent = fmtTime(audio.currentTime);
        $('#np-remaining').textContent = `-${fmtTime(Math.max(0, audio.duration - audio.currentTime))}`;
    }

    function updateMediaSession2(track) {
        if (!('mediaSession' in navigator)) return;
        try {
            const art = artUrl(track);
            navigator.mediaSession.metadata = new MediaMetadata({
                title: trackTitle(track),
                artist: trackArtist(track),
                album: albumName(track),
                artwork: art ? [{ src: art, sizes: '512x512', type: 'image/jpeg' }] : [],
            });
            navigator.mediaSession.setActionHandler('play', toggleAudio);
            navigator.mediaSession.setActionHandler('pause', toggleAudio);
            navigator.mediaSession.setActionHandler('nexttrack', nextTrack);
            navigator.mediaSession.setActionHandler('previoustrack', prevTrack);
            navigator.mediaSession.setActionHandler('seekto', details => {
                const audio = S.audio.el;
                if (audio && Number.isFinite(details.seekTime)) audio.currentTime = details.seekTime;
            });
        } catch {}
    }

    function ensureMusicControls() {
        const transport = $('#now-playing-sheet .np-transport');
        if (!transport || $('#music2-controls')) return;
        const controls = document.createElement('div');
        controls.id = 'music2-controls';
        controls.className = 'btn-row';
        controls.style.marginTop = '18px';
        controls.innerHTML = `
          <button class="btn" id="music2-shuffle"><i class="ph ph-shuffle"></i>Shuffle</button>
          <button class="btn" id="music2-repeat"><i class="ph ph-repeat"></i>Repeat</button>
          <button class="btn" id="music2-queue"><i class="ph ph-list-numbers"></i>Queue</button>`;
        transport.parentNode.insertBefore(controls, transport.nextSibling);
    }

    function updateMusicControls() {
        ensureMusicControls();
        $('#music2-shuffle')?.classList.toggle('btn-primary', M.shuffle);
        const repeat = $('#music2-repeat');
        if (repeat) {
            repeat.classList.toggle('btn-primary', M.repeat !== 'none');
            repeat.innerHTML = `<i class="ph ${M.repeat === 'one' ? 'ph-repeat-once' : 'ph-repeat'}"></i>${M.repeat === 'none' ? 'Repeat' : M.repeat === 'one' ? 'One' : 'All'}`;
        }
    }

    function toggleShuffle() {
        M.shuffle = !M.shuffle;
        if (M.shuffle) rebuildShuffle(M.index);
        saveState();
        updateMusicControls();
        toast(`Shuffle ${M.shuffle ? 'on' : 'off'}`, 'success', 1800);
    }

    function cycleRepeat() {
        const modes = ['none', 'all', 'one'];
        M.repeat = modes[(modes.indexOf(M.repeat) + 1) % modes.length];
        saveState();
        updateMusicControls();
        toast(`Repeat ${M.repeat}`, 'success', 1800);
    }

    function openQueue() {
        openSheet(`
          <div class="kicker" style="margin-bottom:8px">Up next</div>
          <div class="list-sub" style="margin-bottom:12px">${M.queue.length} track${M.queue.length === 1 ? '' : 's'}</div>
          <div class="list">${M.queue.map((track, index) => `
            <div class="list-row row-rule${index === M.index ? ' active' : ''}">
              <button class="list-body" data-music-queue-play="${index}" style="background:none;border:none;text-align:left;color:inherit;cursor:pointer">
                <div class="list-title">${escapeHtml(trackTitle(track))}</div>
                <div class="list-sub">${escapeHtml(trackArtist(track))}</div>
              </button>
              ${index === M.index ? '<i class="ph ph-speaker-high" style="color:var(--color-accent)"></i>' : `<button class="btn btn-icon btn-icon-plain" data-music-queue-remove="${index}"><i class="ph ph-x"></i></button>`}
            </div>`).join('') || '<div class="facts-note">Queue is empty.</div>'}</div>`);
    }

    function albumGroups() {
        const map = new Map();
        for (const track of M.tracks) {
            const artist = track.album_artist || track.artist || 'Unknown Artist';
            const album = track.album || 'Unknown Album';
            const key = `${artist}\u0000${album}`;
            if (!map.has(key)) map.set(key, { artist, album, year: track.year, art: track.has_artwork ? track : null, tracks: [] });
            const group = map.get(key);
            group.tracks.push(track);
            if (!group.art && track.has_artwork) group.art = track;
        }
        return [...map.values()].sort((a, b) => `${a.artist} ${a.album}`.localeCompare(`${b.artist} ${b.album}`, undefined, { numeric: true }));
    }

    function artistGroups() {
        const map = new Map();
        for (const track of M.tracks) {
            const artist = track.artist || track.album_artist || 'Unknown Artist';
            if (!map.has(artist)) map.set(artist, { artist, tracks: [], albums: new Set(), art: null });
            const group = map.get(artist);
            group.tracks.push(track);
            if (track.album) group.albums.add(track.album);
            if (!group.art && track.has_artwork) group.art = track;
        }
        return [...map.values()].sort((a, b) => a.artist.localeCompare(b.artist, undefined, { numeric: true }));
    }

    function viewHeader() {
        return `<div class="chip-scroller" style="padding:0 0 14px">
          ${['songs','albums','artists'].map(view => `<button class="chip${M.view === view ? ' active' : ''}" data-music-view="${view}">${view[0].toUpperCase() + view.slice(1)}</button>`).join('')}
        </div>`;
    }

    function indexBanner() {
        const state = M.indexState || {};
        if (!state.running) return '';
        const total = Number(state.discovered || 0);
        const done = Number(state.processed || 0);
        const pct = total ? Math.round(done / total * 100) : 0;
        return `<div class="card" style="margin-bottom:14px">
          <div class="dl-title">Reading music metadata · ${pct}%</div>
          <div class="dl-meta">${done} / ${total || '…'} tracks · the file library remains usable while this runs</div>
          <div class="bar" style="margin-top:8px"><span style="width:${pct}%"></span></div>
        </div>`;
    }

    function renderMusic() {
        const body = $('#lib-body');
        if (!body || S.lib !== 'music') return;
        const tracks = M.tracks;
        $('#lib-count').textContent = `${tracks.length || M.fallback.length} track${(tracks.length || M.fallback.length) === 1 ? '' : 's'}`;
        if (!tracks.length) {
            body.innerHTML = `${viewHeader()}${indexBanner()}<div class="facts-note" style="text-align:left">Rich music metadata is still being indexed. Your existing file list will return automatically when you leave this view.</div>`;
            return;
        }

        if (M.view === 'albums') {
            const albums = albumGroups();
            body.innerHTML = `${viewHeader()}${indexBanner()}<div class="grid">${albums.map((group, i) => {
                const art = artUrl(group.art);
                return `<button class="grid-item" data-music-album="${i}">
                  <div class="art">${art ? `<img src="${escapeHtml(art)}" alt="" loading="lazy" onerror="this.remove()">` : '<i class="ph ph-vinyl-record"></i>'}</div>
                  <div class="tile-title">${escapeHtml(group.album)}</div>
                  <div class="tile-meta">${escapeHtml(group.artist)}${group.year ? ` · ${group.year}` : ''}</div>
                </button>`;
            }).join('')}</div>`;
            body.dataset.musicAlbums = JSON.stringify(albums.map(g => ({ artist: g.artist, album: g.album })));
            return;
        }

        if (M.view === 'artists') {
            const artists = artistGroups();
            body.innerHTML = `${viewHeader()}${indexBanner()}<div class="list">${artists.map((group, i) => `
              <button class="list-row row-rule" data-music-artist="${i}">
                <div class="list-thumb">${group.art ? `<img src="${escapeHtml(artUrl(group.art))}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:6px" onerror="this.remove()">` : '<i class="ph ph-user-sound"></i>'}</div>
                <div class="list-body"><div class="list-title">${escapeHtml(group.artist)}</div><div class="list-sub">${group.albums.size} album${group.albums.size === 1 ? '' : 's'} · ${group.tracks.length} tracks</div></div>
                <i class="ph ph-caret-right list-caret"></i>
              </button>`).join('')}</div>`;
            body.dataset.musicArtists = JSON.stringify(artists.map(g => g.artist));
            return;
        }

        body.innerHTML = `${viewHeader()}${indexBanner()}<div class="list">${tracks.map((track, i) => `
          <button class="list-row row-rule" data-music-play="${i}">
            <div class="list-thumb">${track.has_artwork ? `<img src="${escapeHtml(artUrl(track))}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:6px" loading="lazy" onerror="this.remove()">` : '<i class="ph ph-music-note"></i>'}</div>
            <div class="list-body">
              <div class="list-title">${escapeHtml(trackTitle(track))}</div>
              <div class="list-sub">${escapeHtml([trackArtist(track), track.album, techLine(track)].filter(Boolean).join(' · '))}</div>
            </div>
            <span class="list-sub">${track.duration ? fmtTime(track.duration) : ''}</span>
          </button>`).join('')}</div>`;
    }

    function openAlbum(index) {
        const groups = albumGroups();
        const group = groups[index];
        if (!group) return;
        const render = body => {
            body.innerHTML = `<div class="list">${group.tracks.map(track => {
                const globalIndex = M.tracks.findIndex(x => x.path === track.path);
                return `<button class="list-row row-rule" data-music-play="${globalIndex}">
                  <div class="list-body"><div class="list-title">${track.track_number ? `${track.track_number}. ` : ''}${escapeHtml(trackTitle(track))}</div><div class="list-sub">${escapeHtml(techLine(track))}</div></div>
                  <span class="list-sub">${track.duration ? fmtTime(track.duration) : ''}</span>
                </button>`;
            }).join('')}</div>`;
        };
        if (typeof openSub === 'function') openSub(group.album, render, { desc: `${group.artist} · ${group.tracks.length} tracks` });
        else {
            M.view = 'songs';
            renderMusic();
        }
    }

    function openArtist(index) {
        const groups = artistGroups();
        const group = groups[index];
        if (!group) return;
        if (typeof openSub !== 'function') return;
        const albums = [...group.albums];
        openSub(group.artist, body => {
            body.innerHTML = `<div class="list">${albums.map(album => {
                const tracks = group.tracks.filter(t => (t.album || 'Unknown Album') === album);
                const first = tracks.find(t => t.has_artwork);
                const firstIndex = M.tracks.findIndex(x => x.path === tracks[0]?.path);
                return `<button class="list-row row-rule" data-music-play="${firstIndex}">
                  <div class="list-thumb">${first ? `<img src="${escapeHtml(artUrl(first))}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:6px">` : '<i class="ph ph-vinyl-record"></i>'}</div>
                  <div class="list-body"><div class="list-title">${escapeHtml(album)}</div><div class="list-sub">${tracks.length} tracks</div></div>
                  <i class="ph ph-play list-caret"></i>
                </button>`;
            }).join('')}</div>`;
        }, { desc: `${albums.length} albums · ${group.tracks.length} tracks` });
    }

    async function fetchCatalog() {
        const tracks = [];
        let offset = 0;
        for (let page = 0; page < 10; page += 1) {
            const data = await api(`/playback/music/catalog?offset=${offset}&limit=1000`);
            tracks.push(...(data.items || []));
            M.indexState = data.index || {};
            if (!data.has_more) break;
            offset = data.next_offset;
        }
        M.tracks = tracks;
        M.loaded = true;
        return tracks;
    }

    async function refreshMusicView() {
        try {
            await fetchCatalog();
            renderMusic();
            if (M.indexState?.running && !M.pollTimer) {
                M.pollTimer = setInterval(async () => {
                    if (S.lib !== 'music') return;
                    try {
                        await fetchCatalog();
                        renderMusic();
                        if (!M.indexState?.running) {
                            clearInterval(M.pollTimer);
                            M.pollTimer = null;
                        }
                    } catch {}
                }, 3500);
            }
        } catch (err) {
            console.debug('[Music2] catalog not ready:', err);
        }
    }

    loadLibrary = async function music2LoadLibrary() {
        if (S.lib !== 'music') return legacyLoadLibrary();
        await legacyLoadLibrary();
        M.fallback = [...(S.libItems || [])];
        refreshMusicView();
    };

    document.addEventListener('click', event => {
        const view = event.target.closest('[data-music-view]');
        if (view) {
            event.preventDefault();
            event.stopImmediatePropagation();
            M.view = view.dataset.musicView;
            renderMusic();
            return;
        }
        const play = event.target.closest('[data-music-play]');
        if (play) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const index = Number(play.dataset.musicPlay);
            if (Number.isInteger(index) && M.tracks[index]) {
                M.queue = M.tracks.slice();
                M.index = index;
                rebuildShuffle(index);
                saveState();
                playTrackAt(index).catch(err => toast(err.message || 'Could not play track', 'error', 5000));
            }
            return;
        }
        const album = event.target.closest('[data-music-album]');
        if (album) { event.preventDefault(); event.stopImmediatePropagation(); openAlbum(Number(album.dataset.musicAlbum)); return; }
        const artist = event.target.closest('[data-music-artist]');
        if (artist) { event.preventDefault(); event.stopImmediatePropagation(); openArtist(Number(artist.dataset.musicArtist)); return; }
        const qplay = event.target.closest('[data-music-queue-play]');
        if (qplay) {
            event.preventDefault(); event.stopImmediatePropagation();
            closeSheet();
            playTrackAt(Number(qplay.dataset.musicQueuePlay));
            return;
        }
        const remove = event.target.closest('[data-music-queue-remove]');
        if (remove) {
            event.preventDefault(); event.stopImmediatePropagation();
            const index = Number(remove.dataset.musicQueueRemove);
            if (index >= 0 && index < M.queue.length && index !== M.index) {
                M.queue.splice(index, 1);
                if (index < M.index) M.index -= 1;
                rebuildShuffle(M.index);
                saveState();
                openQueue();
            }
            return;
        }
        if (event.target.closest('#music2-shuffle')) { event.preventDefault(); toggleShuffle(); return; }
        if (event.target.closest('#music2-repeat')) { event.preventDefault(); cycleRepeat(); return; }
        if (event.target.closest('#music2-queue')) { event.preventDefault(); openQueue(); return; }
    }, true);

    restoreState();
    ensureMusicControls();
    updateMusicControls();
})();
