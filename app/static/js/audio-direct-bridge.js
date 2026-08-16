/* Native-audio bridge.
 *
 * Music 2 historically called the generic /playback/start endpoint. That is
 * useful for genuinely incompatible audio, but wasteful for MP3/FLAC/M4A/WAV
 * and it allowed embedded album artwork to drag audio into video planning.
 * For formats the current browser explicitly reports as playable, return a
 * lightweight direct Range URL instead. Everything else still uses the normal
 * playback planner as a fallback.
 */
(() => {
    if (typeof api !== 'function') return;

    const originalApi = api;
    const mimeByExt = {
        mp3: 'audio/mpeg',
        flac: 'audio/flac',
        wav: 'audio/wav',
        m4a: 'audio/mp4',
        aac: 'audio/aac',
        ogg: 'audio/ogg',
        opus: 'audio/ogg; codecs="opus"',
    };

    function extension(path) {
        const m = String(path || '').match(/\.([a-z0-9]+)$/i);
        return m ? m[1].toLowerCase() : '';
    }

    function nativeAudio(path) {
        const mime = mimeByExt[extension(path)];
        if (!mime) return false;
        try {
            const audio = document.createElement('audio');
            return Boolean(audio.canPlayType(mime));
        } catch {
            return false;
        }
    }

    function directUrl(path) {
        const t = typeof token === 'function' ? token() : localStorage.getItem('nomad_auth_token');
        return `${API}/playback/music/stream?path=${encodeURIComponent(path)}${t ? `&token=${encodeURIComponent(t)}` : ''}`;
    }

    api = async function nomadAudioAwareApi(path, opts = {}) {
        if (path === '/playback/start' && opts?.body) {
            try {
                const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : opts.body;
                const mediaPath = String(body?.path || '');
                if (mediaPath && typeof kindOf === 'function' && kindOf(mediaPath) === 'audio' && nativeAudio(mediaPath)) {
                    return {
                        session: {
                            id: null,
                            path: mediaPath,
                            mode: 'direct_play',
                            quality: 'original',
                            duration: 0,
                            state: 'ready',
                        },
                        plan: {
                            mode: 'direct_play',
                            requires_ffmpeg: false,
                            reasons: ['browser-native audio Range playback'],
                            source: { container: extension(mediaPath), video_codec: null, audio_codec: null },
                            target: { container: extension(mediaPath), video_codec: null, audio_codec: null },
                        },
                        playback: { type: 'direct', url: directUrl(mediaPath) },
                        ticket_expires_in: 0,
                    };
                }
            } catch {}
        }
        return originalApi(path, opts);
    };

    // Register before music2-player's delegated capture handler. On an album
    // or artist sub-page, playing a track should queue that album rather than
    // the entire library. The actual playback function is supplied by
    // music2-player later in the bootstrap, so this stays a very small context
    // shim instead of duplicating the player engine.
    document.addEventListener('click', event => {
        const button = event.target.closest?.('[data-music-play]');
        if (!button) return;
        let onSub = false;
        try { onSub = typeof S !== 'undefined' && S.screen === 'sub'; } catch {}
        if (!onSub) return;

        const m = window.NomadMusic;
        const globalIndex = Number(button.dataset.musicPlay);
        const track = m?.tracks?.[globalIndex];
        if (!track || typeof playAudio !== 'function') return;

        const subTitle = document.querySelector('#sub-title')?.textContent?.trim() || '';
        let context = [];
        if (track.album && subTitle === String(track.album).trim()) {
            const artist = track.album_artist || track.artist || '';
            context = m.tracks.filter(item =>
                (item.album || '') === track.album &&
                (item.album_artist || item.artist || '') === artist
            );
        } else if (track.album && (subTitle === String(track.artist || '').trim() || subTitle === String(track.album_artist || '').trim())) {
            context = m.tracks.filter(item =>
                (item.album || '') === track.album &&
                (item.album_artist || item.artist || '') === (track.album_artist || track.artist || '')
            );
        }
        if (!context.length) return;

        const index = Math.max(0, context.findIndex(item => item.path === track.path));
        m.queue = context.slice();
        m.index = index;
        m.shuffleOrder = Array.from({ length: context.length }, (_, i) => i);
        m.shufflePos = index;
        try { localStorage.setItem('nomad_music2_queue', JSON.stringify(m.queue.slice(0, 2000))); } catch {}

        event.preventDefault();
        event.stopImmediatePropagation();
        playAudio(track.path);
    }, true);

    window.NomadAudioDirect = { nativeAudio, directUrl, originalApi };
})();
