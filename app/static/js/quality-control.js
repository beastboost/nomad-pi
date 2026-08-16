/* Nomad Pi runtime quality selector for the Nocturne player. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function' || typeof openSheet !== 'function') return;

    const qualityButton = document.createElement('button');
    qualityButton.className = 'btn';
    qualityButton.id = 'player-quality';
    qualityButton.innerHTML = '<i class="ph ph-monitor-play" style="font-size:17px"></i>Auto';
    const speedButton = $('#player-speed');
    if (speedButton?.parentNode) speedButton.parentNode.insertBefore(qualityButton, speedButton);

    let manualVideoQualityAvailable = true;

    function currentPosition() {
        if (typeof Core.absolutePosition === 'function') return Core.absolutePosition();
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) return 0;
        return Math.max(0, Number(current.offset || 0) + Number(video.currentTime || 0));
    }

    function displayLabel(quality) {
        if (quality === 'adaptive') return 'Adaptive';
        if (quality === 'original') return 'Original';
        if (quality === 'auto') return 'Auto';
        return quality || 'Auto';
    }

    function setButtonLabel(quality) {
        qualityButton.innerHTML = `<i class="ph ph-monitor-play" style="font-size:17px"></i>${escapeHtml(displayLabel(quality))}`;
    }

    function transcodeOnlyProfile(profile) {
        return !['auto', 'original'].includes(String(profile?.id || '').toLowerCase());
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
            const [qualityData, adaptive, health] = await Promise.all([
                api('/playback/quality-profiles'),
                api('/playback/adaptive/status').catch(err => ({ available: false, reason: err.message || 'Adaptive status unavailable' })),
                api('/playback/health').catch(() => ({ runtime_policy: {} })),
            ]);
            const profiles = qualityData.profiles || [];
            const selected = current.quality || 'auto';
            const out = $('#nomad-quality-list');
            if (!out) return;

            const runtime = health.runtime_policy || {};
            const lite = runtime.lite_playback === true;
            manualVideoQualityAvailable = runtime.automatic_live_video_transcode === true || !lite;

            const adaptiveRow = `
              <button class="sheet-option row-rule" data-nomad-quality="adaptive" ${adaptive.available ? '' : 'disabled'}
                      style="${adaptive.available ? '' : 'opacity:.55'}">
                <span style="text-align:left;min-width:0">
                  <span style="display:block">Adaptive</span>
                  <span class="list-sub">${escapeHtml(adaptive.available
                      ? 'Automatic bandwidth switching · 1080p / 720p / 480p'
                      : (adaptive.reason || 'Unavailable on this server'))}</span>
                </span>
                ${selected === 'adaptive'
                    ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>'
                    : '<i class="ph ph-waveform" style="color:var(--text-45)"></i>'}
              </button>`;

            out.innerHTML = `<div class="list">${adaptiveRow}${profiles.map(profile => {
                const requiresVideo = transcodeOnlyProfile(profile);
                const disabled = requiresVideo && !manualVideoQualityAvailable;
                const subtitle = disabled
                    ? 'Requires video conversion · disabled in Lite mode'
                    : profile.max_bitrate
                        ? `up to ${Math.round(profile.max_bitrate / 1e6)} Mbps`
                        : (profile.id === 'original' ? 'Use the source quality without resizing' : 'Best compatible source path');
                return `
                  <button class="sheet-option row-rule" data-nomad-quality="${escapeHtml(profile.id)}" ${disabled ? 'disabled' : ''}
                          style="${disabled ? 'opacity:.55' : ''}">
                    <span style="text-align:left;min-width:0">
                      <span style="display:block">${escapeHtml(profile.label)}</span>
                      <span class="list-sub">${escapeHtml(subtitle)}</span>
                    </span>
                    ${profile.id === selected ? '<i class="ph ph-check" style="color:var(--color-accent)"></i>' : ''}
                  </button>`;
            }).join('')}</div>`;
        } catch (err) {
            const out = $('#nomad-quality-list');
            if (out) out.innerHTML = `<div class="facts-note">${escapeHtml(err.message || 'Could not load quality profiles')}</div>`;
        }
    }

    async function switchQuality(quality) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) return;

        if (transcodeOnlyProfile({ id: quality }) && !manualVideoQualityAvailable) {
            toast('That quality needs video conversion, which Lite mode keeps disabled.', 'info', 4500);
            closeSheet();
            return;
        }

        if (typeof Core.applyReplacement !== 'function') {
            toast('Playback handover helper is unavailable', 'error', 5000);
            return;
        }
        const absolute = currentPosition();
        const wasPlaying = !video.paused;
        closeSheet();
        toast(`Preparing ${displayLabel(quality)}…`, 'info', 1800);

        try {
            const endpoint = quality === 'adaptive'
                ? `/playback/sessions/${encodeURIComponent(current.id)}/adaptive`
                : `/playback/sessions/${encodeURIComponent(current.id)}/quality`;
            const body = quality === 'adaptive'
                ? { position: absolute }
                : { quality, position: absolute };
            const result = await api(endpoint, {
                method: 'POST',
                body: JSON.stringify(body),
            });
            if (Core.current !== current) return;

            await Core.applyReplacement(result, { autoplay: wasPlaying, absolute });
            current.quality = result.session.quality || quality;
            current.audioTrack = result.session.audio_track;
            current.subtitleTrack = result.session.subtitle_track;
            setButtonLabel(current.quality);

            const label = displayLabel(current.quality);
            if (quality === 'adaptive') {
                const ladder = (result.adaptive?.renditions || []).map(x => x.name).join(' / ');
                toast(`Adaptive quality: ${ladder || 'automatic'}`, 'success', 3000);
            } else {
                toast(`Quality: ${label}`, 'success', 2500);
            }
        } catch (err) {
            toast(err.message || 'Could not change playback quality', 'error', 6500);
        }
    }

    qualityButton.addEventListener('click', event => {
        event.preventDefault();
        openQualityMenu();
    });

    document.addEventListener('click', event => {
        const choice = event.target.closest('[data-nomad-quality]');
        if (!choice || choice.disabled) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        switchQuality(choice.dataset.nomadQuality);
    }, true);
})();
