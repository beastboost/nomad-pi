/* Nomad Pi embedded subtitle controls layered over the existing subtitle UI. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function' || typeof openSheet !== 'function') return;

    const active = {
        path: null,
        streamIndex: null,
        language: null,
        title: null,
        sessionId: null,
        offset: null,
        refreshing: false,
    };

    function subtitleLabel(track) {
        const bits = [];
        bits.push(track.title || String(track.language || 'und').toUpperCase());
        if (track.codec) bits.push(String(track.codec).toUpperCase());
        if (track.forced) bits.push('Forced');
        if (track.default) bits.push('Default');
        return bits.filter(Boolean).join(' · ');
    }

    function removeEmbeddedTrack() {
        const video = V?.el;
        if (!video) return;
        video.querySelectorAll('track[data-nomad-embedded]').forEach(track => track.remove());
        Array.from(video.textTracks || []).forEach(track => { track.mode = 'disabled'; });
    }

    function clearSubtitle() {
        removeEmbeddedTrack();
        active.path = null;
        active.streamIndex = null;
        active.language = null;
        active.title = null;
        active.sessionId = null;
        active.offset = null;
        closeSheet();
        toast('Subtitles off', 'success', 1800);
    }

    async function attachSubtitle(track, quiet = false) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video || !V?.path) throw new Error('No active playback session');
        if (!track?.text_supported) throw new Error('This subtitle requires burn-in transcoding');

        active.refreshing = true;
        try {
            const ticketInfo = await api(`/playback/sessions/${encodeURIComponent(current.id)}/ticket`, {
                method: 'POST',
            });
            if (Core.current !== current || !V?.el) return;

            removeEmbeddedTrack();
            const el = document.createElement('track');
            el.kind = 'subtitles';
            el.srclang = track.language || 'und';
            el.label = track.title || String(track.language || 'Subtitle').toUpperCase();
            el.default = true;
            el.dataset.nomadEmbedded = '1';
            el.src = `/api/playback/sessions/${encodeURIComponent(current.id)}/subtitles/${Number(track.stream_index)}.vtt?ticket=${encodeURIComponent(ticketInfo.ticket)}`;
            el.addEventListener('load', () => {
                if (!V?.el) return;
                Array.from(V.el.textTracks || []).forEach(t => { t.mode = 'disabled'; });
                try { el.track.mode = 'showing'; } catch {}
            }, { once: true });
            el.addEventListener('error', () => {
                if (!quiet) toast('Could not load that subtitle track', 'error', 4500);
            }, { once: true });
            video.appendChild(el);

            active.path = V.path;
            active.streamIndex = Number(track.stream_index);
            active.language = track.language || 'und';
            active.title = track.title || '';
            active.sessionId = current.id;
            active.offset = Number(current.offset || 0);
            if (!quiet) {
                closeSheet();
                toast(`Subtitles: ${subtitleLabel(track)}`, 'success', 2500);
            }
        } finally {
            active.refreshing = false;
        }
    }

    async function openEmbeddedSubtitles() {
        const current = Core.current;
        if (!current || !V?.path) {
            toast('Start a video before choosing subtitles.', 'info', 3000);
            return;
        }

        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Subtitles</div>
          <div id="nomad-subtitle-list"><div class="empty"><div class="spinner"></div></div></div>
          <button class="btn btn-block" data-nomad-sub-search="1" style="min-height:44px;margin-top:14px">
            <i class="ph ph-magnifying-glass"></i> Search / download subtitles
          </button>`);

        try {
            const data = await api(`/playback/tracks?path=${encodeURIComponent(V.path)}`);
            const tracks = data.subtitles || [];
            const out = $('#nomad-subtitle-list');
            if (!out) return;

            const rows = [
                `<button class="sheet-option row-rule" data-nomad-sub-off="1">
                   <span>Off</span>
                   ${active.streamIndex === null ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>' : ''}
                 </button>`
            ];
            tracks.forEach(track => {
                const selected = active.path === V.path && active.streamIndex === Number(track.stream_index);
                if (track.text_supported) {
                    rows.push(`
                      <button class="sheet-option row-rule" data-nomad-sub="${Number(track.stream_index)}">
                        <span style="min-width:0;text-align:left">
                          <span style="display:block">${escapeHtml(subtitleLabel(track))}</span>
                        </span>
                        ${selected ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>' : ''}
                      </button>`);
                } else {
                    rows.push(`
                      <button class="sheet-option row-rule" disabled style="opacity:.55">
                        <span style="min-width:0;text-align:left">
                          <span style="display:block">${escapeHtml(subtitleLabel(track))}</span>
                          <span class="list-sub">Image subtitle · burn-in required</span>
                        </span>
                      </button>`);
                }
            });
            out.innerHTML = tracks.length
                ? `<div class="list">${rows.join('')}</div>`
                : `<div class="list">${rows[0]}</div><div class="facts-note" style="text-align:left;margin-top:10px">No embedded subtitle streams found.</div>`;
            out.dataset.tracks = JSON.stringify(tracks);
        } catch (err) {
            const out = $('#nomad-subtitle-list');
            if (out) out.innerHTML = `<div class="facts-note" style="text-align:left">${escapeHtml(err.message || 'Could not inspect subtitle tracks')}</div>`;
        }
    }

    function findRenderedTrack(streamIndex) {
        const out = $('#nomad-subtitle-list');
        if (!out?.dataset.tracks) return null;
        try {
            const tracks = JSON.parse(out.dataset.tracks);
            return tracks.find(track => Number(track.stream_index) === Number(streamIndex)) || null;
        } catch {
            return null;
        }
    }

    document.addEventListener('click', (event) => {
        const button = event.target.closest('#player-subs');
        if (button) {
            event.preventDefault();
            event.stopImmediatePropagation();
            openEmbeddedSubtitles();
            return;
        }

        if (event.target.closest('[data-nomad-sub-off]')) {
            event.preventDefault();
            event.stopImmediatePropagation();
            clearSubtitle();
            return;
        }

        const choice = event.target.closest('[data-nomad-sub]');
        if (choice) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const track = findRenderedTrack(Number(choice.dataset.nomadSub));
            if (track) attachSubtitle(track).catch(err => toast(err.message || 'Could not load subtitle', 'error', 5000));
            return;
        }

        if (event.target.closest('[data-nomad-sub-search]')) {
            event.preventDefault();
            event.stopImmediatePropagation();
            closeSheet();
            if (typeof openSubtitlePicker === 'function') openSubtitlePicker();
        }
    }, true);

    // HLS seeks and audio-track replacements change the source-time offset and
    // sometimes the playback session id. Refresh an active embedded subtitle
    // against the new session so its extracted cue timeline stays aligned.
    setInterval(() => {
        if (active.streamIndex === null || active.refreshing) return;
        const current = Core.current;
        if (!current || !V?.path) return;
        if (V.path !== active.path) {
            removeEmbeddedTrack();
            active.path = null;
            active.streamIndex = null;
            return;
        }
        const offset = Number(current.offset || 0);
        if (current.id === active.sessionId && Math.abs(offset - Number(active.offset || 0)) < 0.01) return;
        attachSubtitle({
            stream_index: active.streamIndex,
            language: active.language,
            title: active.title,
            text_supported: true,
        }, true).catch(() => {});
    }, 1000);
})();
