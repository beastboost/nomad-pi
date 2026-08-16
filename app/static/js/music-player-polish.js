/* Nomad Music player polish — keeps the lightweight Music 2 engine but gives
 * the now-playing surface proper controls and feedback.
 */
(() => {
    const VOLUME_KEY = 'nomad_music_volume';
    const MUTED_KEY = 'nomad_music_muted';
    let boundAudio = null;
    let dragging = false;

    function music() { return window.NomadMusic || null; }
    function audio() {
        try { return typeof S !== 'undefined' ? S.audio?.el || null : null; }
        catch { return null; }
    }
    function currentTrack() {
        const m = music();
        return m && m.index >= 0 ? m.queue[m.index] : null;
    }
    function trackTitle(track) {
        return track?.title || track?.name || (typeof baseName === 'function' ? baseName(track?.path || '') : 'Track');
    }
    function tech(track) {
        const parts = [];
        if (track?.codec) parts.push(String(track.codec).toUpperCase());
        if (track?.sample_rate) parts.push(`${Math.round(Number(track.sample_rate) / 100) / 10} kHz`);
        if (track?.bit_depth) parts.push(`${track.bit_depth}-bit`);
        if (track?.bitrate) parts.push(`${Math.round(Number(track.bitrate) / 1000)} kbps`);
        return parts.join(' · ');
    }

    function ensureUi() {
        const sheet = document.querySelector('#now-playing-sheet');
        const body = document.querySelector('#now-playing-sheet .np-body');
        const artist = document.querySelector('#np-artist');
        const transport = document.querySelector('#now-playing-sheet .np-transport');
        if (!sheet || !body || !artist || !transport) return false;

        if (!document.querySelector('#music-player-bg')) {
            const bg = document.createElement('div');
            bg.id = 'music-player-bg';
            bg.className = 'music-player-bg';
            sheet.insertBefore(bg, sheet.firstChild);
        }

        if (!document.querySelector('#music-player-facts')) {
            const facts = document.createElement('div');
            facts.id = 'music-player-facts';
            facts.className = 'music-player-facts';
            facts.innerHTML = `
              <span id="music-player-position">—</span>
              <span class="music-fact-dot">•</span>
              <span id="music-player-tech">Direct audio</span>`;
            artist.insertAdjacentElement('afterend', facts);
        }

        if (!document.querySelector('#music-volume-row')) {
            const row = document.createElement('div');
            row.id = 'music-volume-row';
            row.className = 'music-volume-row';
            row.innerHTML = `
              <button class="btn btn-icon btn-icon-plain" id="music-volume-mute" aria-label="Mute">
                <i class="ph ph-speaker-high"></i>
              </button>
              <input id="music-volume" class="music-volume" type="range" min="0" max="1" step="0.01" value="1" aria-label="Volume">
              <button class="btn btn-icon btn-icon-plain hidden" id="music-airplay" aria-label="Choose audio output">
                <i class="ph ph-airplay"></i>
              </button>`;
            transport.insertAdjacentElement('afterend', row);
        }

        return true;
    }

    function restoreVolume(el) {
        if (!el) return;
        const saved = Number(localStorage.getItem(VOLUME_KEY));
        if (Number.isFinite(saved) && saved >= 0 && saved <= 1) el.volume = saved;
        el.muted = localStorage.getItem(MUTED_KEY) === '1';
        syncVolumeUi();
    }

    function syncVolumeUi() {
        const el = audio();
        const slider = document.querySelector('#music-volume');
        const icon = document.querySelector('#music-volume-mute i');
        if (!el) return;
        if (slider && !dragging) slider.value = String(el.volume);
        if (icon) {
            icon.className = el.muted || el.volume === 0
                ? 'ph ph-speaker-slash'
                : el.volume < 0.5 ? 'ph ph-speaker-low' : 'ph ph-speaker-high';
        }
    }

    function bindAudio() {
        const el = audio();
        if (!el || el === boundAudio) return;
        boundAudio = el;
        restoreVolume(el);
        ['loadedmetadata', 'durationchange', 'play', 'pause', 'volumechange', 'timeupdate'].forEach(name => {
            el.addEventListener(name, refresh, { passive: true });
        });
        el.addEventListener('error', () => {
            const err = el.error;
            if (err && typeof toast === 'function') toast(`Music playback error${err.code ? ` (${err.code})` : ''}`, 'error', 5000);
        });
    }

    function playbackLabel(el) {
        const src = String(el?.currentSrc || el?.src || '');
        if (src.includes('/playback/music/stream')) return 'Direct · Range';
        if (src.includes('/playback/hls/')) return 'Audio fallback · HLS';
        if (src.includes('/media/stream')) return 'Legacy direct';
        return 'Direct audio';
    }

    function refresh() {
        if (!ensureUi()) return;
        bindAudio();
        const m = music();
        const el = audio();
        const track = currentTrack();
        const pos = document.querySelector('#music-player-position');
        const techEl = document.querySelector('#music-player-tech');
        if (pos) {
            const index = Number(m?.index ?? -1);
            const total = Number(m?.queue?.length || 0);
            pos.textContent = index >= 0 && total ? `${index + 1} of ${total}` : 'Queue';
        }
        if (techEl) techEl.textContent = [playbackLabel(el), tech(track)].filter(Boolean).join(' · ');

        const art = document.querySelector('#now-playing-sheet .np-art img');
        const bg = document.querySelector('#music-player-bg');
        if (bg) bg.style.backgroundImage = art?.src ? `url("${art.src.replaceAll('"', '%22')}")` : '';

        const airplay = document.querySelector('#music-airplay');
        if (airplay && el && typeof el.webkitShowPlaybackTargetPicker === 'function') airplay.classList.remove('hidden');
        syncVolumeUi();
    }

    function seekFromEvent(event) {
        const el = audio();
        const scrub = document.querySelector('#np-scrubber .scrub-track');
        if (!el || !scrub || !Number.isFinite(el.duration) || el.duration <= 0) return;
        const rect = scrub.getBoundingClientRect();
        const x = event.clientX ?? event.touches?.[0]?.clientX;
        if (!Number.isFinite(x) || rect.width <= 0) return;
        const ratio = Math.max(0, Math.min(1, (x - rect.left) / rect.width));
        el.currentTime = ratio * el.duration;
        if ('mediaSession' in navigator && navigator.mediaSession.setPositionState) {
            try { navigator.mediaSession.setPositionState({ duration: el.duration, playbackRate: el.playbackRate || 1, position: el.currentTime }); } catch {}
        }
    }

    document.addEventListener('pointerdown', event => {
        if (!event.target.closest('#np-scrubber')) return;
        dragging = true;
        seekFromEvent(event);
        try { event.target.setPointerCapture?.(event.pointerId); } catch {}
    }, true);
    document.addEventListener('pointermove', event => {
        if (dragging) seekFromEvent(event);
    }, true);
    document.addEventListener('pointerup', event => {
        if (!dragging) return;
        seekFromEvent(event);
        dragging = false;
    }, true);

    document.addEventListener('input', event => {
        if (event.target?.id !== 'music-volume') return;
        const el = audio();
        if (!el) return;
        const value = Math.max(0, Math.min(1, Number(event.target.value) || 0));
        el.volume = value;
        if (value > 0) el.muted = false;
        localStorage.setItem(VOLUME_KEY, String(value));
        localStorage.setItem(MUTED_KEY, el.muted ? '1' : '0');
        syncVolumeUi();
    }, true);

    document.addEventListener('click', event => {
        if (event.target.closest('#music-volume-mute')) {
            event.preventDefault();
            const el = audio();
            if (!el) return;
            el.muted = !el.muted;
            localStorage.setItem(MUTED_KEY, el.muted ? '1' : '0');
            syncVolumeUi();
            return;
        }
        if (event.target.closest('#music-airplay')) {
            event.preventDefault();
            try { audio()?.webkitShowPlaybackTargetPicker?.(); } catch {}
        }
    }, true);

    const title = document.querySelector('#np-title');
    if (title) new MutationObserver(refresh).observe(title, { childList: true, characterData: true, subtree: true });
    document.addEventListener('DOMContentLoaded', () => { ensureUi(); setTimeout(refresh, 0); }, { once: true });
    setTimeout(refresh, 0);
})();
