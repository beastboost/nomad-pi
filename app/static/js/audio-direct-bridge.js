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

    window.NomadAudioDirect = { nativeAudio, directUrl, originalApi };
})();
