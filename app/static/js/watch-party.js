/* Nomad Pi Watch Together — same-account synchronized playback rooms. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function' || typeof openSheet !== 'function') return;

    const DEVICE_KEY = 'nomad_playback_device_id';
    const DEVICE_NAME_KEY = 'nomad_playback_device_name';
    const WP = {
        party: null,
        host: false,
        pollTimer: null,
        publishTimer: null,
        syncing: false,
        lastHardSync: 0,
    };
    window.NomadWatchTogether = WP;

    function deviceId() {
        let id = localStorage.getItem(DEVICE_KEY);
        if (!id) {
            id = window.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            localStorage.setItem(DEVICE_KEY, id);
        }
        return id;
    }

    function deviceName() {
        const saved = localStorage.getItem(DEVICE_NAME_KEY);
        if (saved) return saved;
        const ua = navigator.userAgent || '';
        const platform = /iPhone/i.test(ua) ? 'iPhone' : /iPad/i.test(ua) ? 'iPad' :
            /Android/i.test(ua) ? 'Android' : /Windows/i.test(ua) ? 'Windows' :
            /Macintosh|Mac OS X/i.test(ua) ? 'Mac' : /Linux/i.test(ua) ? 'Linux' : 'Web';
        return `${platform} device`;
    }

    function absolutePosition() {
        if (typeof Core.absolutePosition === 'function') return Core.absolutePosition();
        return Math.max(0, Number(Core.current?.offset || 0) + Number(V?.el?.currentTime || 0));
    }

    function playerState() {
        const video = V?.el;
        return video && !video.paused && !video.ended ? 'playing' : 'paused';
    }

    function currentSettings() {
        const current = Core.current || {};
        return {
            quality: current.quality || 'auto',
            adaptive: Boolean(current.adaptive || current.quality === 'adaptive'),
            audio_track: current.audioTrack ?? null,
            subtitle_track: current.subtitleTrack ?? null,
            subtitle_burned: Boolean(current.subtitleBurned),
        };
    }

    function installButton() {
        if ($('#player-watch-together')) return;
        const extras = $('#screen-player .player-extras');
        if (!extras) return;
        const button = document.createElement('button');
        button.className = 'btn';
        button.id = 'player-watch-together';
        button.innerHTML = '<i class="ph ph-users-three" style="font-size:17px"></i>Together';
        extras.appendChild(button);
    }

    function stopTimers() {
        clearInterval(WP.pollTimer);
        clearInterval(WP.publishTimer);
        WP.pollTimer = null;
        WP.publishTimer = null;
    }

    function updatedTarget(party) {
        let position = Math.max(0, Number(party.position || 0));
        if (party.state === 'playing') {
            const updated = Date.parse(party.updated_at || '');
            if (Number.isFinite(updated)) {
                const elapsed = Math.max(0, (Date.now() - updated) / 1000);
                position += elapsed * Math.max(0.25, Number(party.rate || 1));
            }
        }
        return position;
    }

    async function attachTextSubtitle(streamIndex) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) return;
        const tracks = await api(`/playback/tracks?path=${encodeURIComponent(V.path)}`);
        const selected = (tracks.subtitles || []).find(x => Number(x.stream_index) === Number(streamIndex));
        if (!selected?.text_supported) return;
        const ticket = await api(`/playback/sessions/${encodeURIComponent(current.id)}/ticket`, { method: 'POST' });
        video.querySelectorAll('track[data-nomad-party]').forEach(x => x.remove());
        const el = document.createElement('track');
        el.kind = 'subtitles';
        el.srclang = selected.language || 'und';
        el.label = selected.title || String(selected.language || 'Subtitle').toUpperCase();
        el.default = true;
        el.dataset.nomadParty = '1';
        el.src = `/api/playback/sessions/${encodeURIComponent(current.id)}/subtitles/${Number(streamIndex)}.vtt?ticket=${encodeURIComponent(ticket.ticket)}`;
        el.addEventListener('load', () => {
            Array.from(video.textTracks || []).forEach(track => { track.mode = 'disabled'; });
            try { el.track.mode = 'showing'; } catch {}
        }, { once: true });
        video.appendChild(el);
        current.subtitleTrack = Number(streamIndex);
        current.subtitleBurned = false;
    }

    async function applyInitialSettings(party) {
        let current = Core.current;
        if (!current || !V?.el) return;
        const desiredQuality = party.adaptive ? 'adaptive' : (party.quality || 'auto');
        if (desiredQuality && desiredQuality !== 'auto' && typeof Core.applyReplacement === 'function') {
            const absolute = absolutePosition();
            const endpoint = desiredQuality === 'adaptive'
                ? `/playback/sessions/${encodeURIComponent(current.id)}/adaptive`
                : `/playback/sessions/${encodeURIComponent(current.id)}/quality`;
            const body = desiredQuality === 'adaptive'
                ? { position: absolute }
                : { quality: desiredQuality, position: absolute };
            try {
                const result = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
                await Core.applyReplacement(result, { autoplay: false, absolute });
                current = Core.current;
            } catch (err) { console.debug('[Watch Together] quality sync:', err); }
        }

        if (party.audio_track != null && current && typeof Core.applyReplacement === 'function') {
            try {
                const absolute = absolutePosition();
                const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/audio`, {
                    method: 'POST',
                    body: JSON.stringify({ stream_index: Number(party.audio_track), position: absolute }),
                });
                await Core.applyReplacement(result, { autoplay: false, absolute });
                current = Core.current;
            } catch (err) { console.debug('[Watch Together] audio sync:', err); }
        }

        if (party.subtitle_track != null && current) {
            try {
                if (party.subtitle_burned && typeof Core.applyReplacement === 'function') {
                    const absolute = absolutePosition();
                    const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/subtitles/burn`, {
                        method: 'POST',
                        body: JSON.stringify({ stream_index: Number(party.subtitle_track), position: absolute }),
                    });
                    await Core.applyReplacement(result, { autoplay: false, absolute });
                    Core.current.subtitleTrack = Number(party.subtitle_track);
                    Core.current.subtitleBurned = true;
                } else {
                    await attachTextSubtitle(Number(party.subtitle_track));
                }
            } catch (err) { console.debug('[Watch Together] subtitle sync:', err); }
        }
    }

    async function hardSync(target, shouldPlay) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video || WP.syncing) return;
        WP.syncing = true;
        try {
            if (current.type === 'hls' && typeof Core.applyReplacement === 'function') {
                const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/seek`, {
                    method: 'POST', body: JSON.stringify({ position: Math.max(0, target) }),
                });
                await Core.applyReplacement(result, { autoplay: shouldPlay, absolute: target });
            } else {
                video.currentTime = Math.max(0, target);
            }
            WP.lastHardSync = Date.now();
        } catch (err) {
            console.debug('[Watch Together] hard sync failed:', err);
        } finally {
            WP.syncing = false;
        }
    }

    async function synchronize(party) {
        const video = V?.el;
        if (!video || !Core.current || WP.host) return;
        const target = updatedTarget(party);
        const current = absolutePosition();
        const drift = target - current;
        const hostRate = Math.max(0.25, Number(party.rate || 1));
        const shouldPlay = party.state === 'playing';

        if (Math.abs(drift) > 1.5 && Date.now() - WP.lastHardSync > 1800) {
            await hardSync(target, shouldPlay);
        } else if (Math.abs(drift) >= 0.35) {
            const correction = drift > 0 ? 0.03 : -0.03;
            video.playbackRate = Math.max(0.25, Math.min(4, hostRate + correction));
        } else {
            video.playbackRate = hostRate;
        }

        if (shouldPlay && video.paused && !video.ended) video.play().catch(() => {});
        if (!shouldPlay && !video.paused) video.pause();
    }

    async function ensurePartyMedia(party) {
        if (!party?.path) throw new Error('Room has no media path');
        if (!Core.current || V?.path !== party.path) {
            await playVideo(party.path, Math.max(0, Number(party.position || 0)));
            if (!Core.current) throw new Error('This profile/device could not start the room media');
            await applyInitialSettings(party);
        }
        await synchronize(party);
    }

    async function publishHostState() {
        if (!WP.party || !WP.host || !Core.current || !V?.el) return;
        const settings = currentSettings();
        try {
            const data = await api(`/playback/watch-party/${encodeURIComponent(WP.party.id)}/state`, {
                method: 'POST',
                body: JSON.stringify({
                    device_id: deviceId(),
                    position: absolutePosition(),
                    state: playerState(),
                    rate: Number(V.el.playbackRate || 1),
                    ...settings,
                }),
            });
            WP.party = data.party;
        } catch (err) {
            if (err?.status === 404 || err?.status === 403) endLocalParty('Watch Together room ended.');
        }
    }

    async function pollFollower() {
        if (!WP.party || WP.host) return;
        try {
            const qs = new URLSearchParams({ device_id: deviceId(), revision: String(WP.party.revision || 0) });
            const data = await api(`/playback/watch-party/${encodeURIComponent(WP.party.id)}?${qs}`);
            WP.party = data.party;
            await ensurePartyMedia(data.party);
        } catch (err) {
            if (err?.status === 404 || err?.status === 409) endLocalParty('Watch Together room ended.');
        }
    }

    function startLoops() {
        stopTimers();
        if (WP.host) {
            publishHostState();
            WP.publishTimer = setInterval(publishHostState, 1000);
        } else {
            pollFollower();
            WP.pollTimer = setInterval(pollFollower, 1000);
        }
    }

    function endLocalParty(message) {
        stopTimers();
        if (V?.el && !WP.host) V.el.playbackRate = 1;
        WP.party = null;
        WP.host = false;
        if (message) toast(message, 'info', 2600);
    }

    async function createParty() {
        const current = Core.current;
        if (!current || !V?.el) {
            toast('Start a video before creating a Watch Together room.', 'info', 3000);
            return;
        }
        try {
            const data = await api('/playback/watch-party', {
                method: 'POST',
                body: JSON.stringify({
                    session_id: current.id,
                    device_id: deviceId(),
                    device_name: deviceName(),
                    position: absolutePosition(),
                    state: playerState(),
                    rate: Number(V.el.playbackRate || 1),
                }),
            });
            WP.party = data.party;
            WP.host = true;
            startLoops();
            openPartyStatus(data);
            toast(`Watch Together room ${data.party.id} started`, 'success', 2800);
        } catch (err) { toast(err.message || 'Could not start Watch Together', 'error', 5000); }
    }

    function openJoin() {
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Join Watch Together</div>
          <div class="list-sub" style="margin-bottom:12px">Enter the six-character room code shown on another device signed into this account.</div>
          <input id="watch-party-code" class="input input-plain" maxlength="6" autocapitalize="characters" spellcheck="false" placeholder="ABC234" style="text-transform:uppercase;letter-spacing:.16em">
          <button class="btn btn-primary btn-block" id="watch-party-join-submit" style="margin-top:12px">Join room</button>`);
        const input = $('#watch-party-code');
        setTimeout(() => input?.focus(), 50);
        const submit = () => joinParty(input?.value || '');
        $('#watch-party-join-submit')?.addEventListener('click', submit, { once: true });
        input?.addEventListener('keydown', event => { if (event.key === 'Enter') submit(); });
    }

    async function joinParty(code) {
        const normalized = String(code || '').trim().toUpperCase();
        if (!/^[A-Z2-9]{6}$/.test(normalized)) { toast('Enter a valid six-character room code.', 'warn'); return; }
        try {
            const data = await api(`/playback/watch-party/${encodeURIComponent(normalized)}/join`, {
                method: 'POST',
                body: JSON.stringify({ device_id: deviceId(), device_name: deviceName() }),
            });
            WP.party = data.party;
            WP.host = data.party.host_device_id === deviceId();
            try {
                await ensurePartyMedia(data.party);
            } catch (err) {
                await api(`/playback/watch-party/${encodeURIComponent(normalized)}/leave`, {
                    method: 'POST', body: JSON.stringify({ device_id: deviceId() }),
                }).catch(() => {});
                endLocalParty();
                throw err;
            }
            startLoops();
            closeSheet();
            toast(`Joined Watch Together ${normalized}`, 'success', 2600);
        } catch (err) { toast(err.message || 'Could not join Watch Together', 'error', 5500); }
    }

    function memberRows(data) {
        const members = data?.members || [];
        return members.map(member => `
          <div class="list-row row-rule">
            <div class="list-body"><div class="list-title">${escapeHtml(member.name || 'Device')}${member.device_id === data.party.host_device_id ? ' · Host' : ''}</div><div class="list-sub">${member.online ? 'Online' : 'Away'}</div></div>
            <span class="status-dot${member.online ? '' : ' down'}"></span>
          </div>`).join('');
    }

    async function openPartyStatus(existing = null) {
        if (!WP.party) return;
        let data = existing;
        try {
            if (!data?.members) {
                data = await api(`/playback/watch-party/${encodeURIComponent(WP.party.id)}?device_id=${encodeURIComponent(deviceId())}&revision=${Number(WP.party.revision || 0)}`);
                WP.party = data.party;
            }
        } catch {}
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Watch Together</div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
            <div style="font-size:28px;font-weight:700;letter-spacing:.16em;flex:1">${escapeHtml(WP.party.id)}</div>
            <button class="btn" data-watch-copy="${escapeHtml(WP.party.id)}"><i class="ph ph-copy"></i>Copy</button>
          </div>
          <div class="list-sub" style="margin-bottom:10px">Only devices signed into this Nomad account can use this code.</div>
          <div class="list">${memberRows(data || {party:WP.party,members:[]})}</div>
          <button class="btn btn-block" data-watch-leave="1" style="margin-top:14px"><i class="ph ph-sign-out"></i>${WP.host ? 'End room' : 'Leave room'}</button>`);
    }

    async function leaveParty() {
        if (!WP.party) return;
        const id = WP.party.id;
        try {
            await api(`/playback/watch-party/${encodeURIComponent(id)}/leave`, {
                method: 'POST', body: JSON.stringify({ device_id: deviceId() }),
            });
        } catch {}
        endLocalParty(WP.host ? 'Watch Together room ended.' : 'Left Watch Together.');
        closeSheet();
    }

    function openMenu() {
        if (WP.party) { openPartyStatus(); return; }
        openSheet(`
          <div class="kicker" style="margin-bottom:8px">Watch Together</div>
          <div class="list">
            <button class="sheet-option row-rule" data-watch-create="1" ${Core.current ? '' : 'disabled'}>
              <span style="text-align:left"><span style="display:block">Start a room</span><span class="list-sub">This device becomes the playback host</span></span><i class="ph ph-broadcast"></i>
            </button>
            <button class="sheet-option row-rule" data-watch-join="1">
              <span style="text-align:left"><span style="display:block">Join with code</span><span class="list-sub">Sync to another signed-in device</span></span><i class="ph ph-users-three"></i>
            </button>
          </div>`);
    }

    installButton();
    document.addEventListener('click', event => {
        if (event.target.closest('#player-watch-together')) { event.preventDefault(); openMenu(); return; }
        if (event.target.closest('[data-watch-create]')) { event.preventDefault(); event.stopImmediatePropagation(); createParty(); return; }
        if (event.target.closest('[data-watch-join]')) { event.preventDefault(); event.stopImmediatePropagation(); openJoin(); return; }
        if (event.target.closest('[data-watch-leave]')) { event.preventDefault(); event.stopImmediatePropagation(); leaveParty(); return; }
        const copy = event.target.closest('[data-watch-copy]');
        if (copy) {
            event.preventDefault();
            navigator.clipboard?.writeText(copy.dataset.watchCopy).then(() => toast('Room code copied', 'success', 1800)).catch(() => {});
        }
    }, true);

    // If the player DOM was not ready when this script evaluated, retry once.
    setTimeout(installButton, 300);
    window.addEventListener('pagehide', () => {
        if (WP.party) {
            fetch(`${API}/playback/watch-party/${encodeURIComponent(WP.party.id)}/leave`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: deviceId() }),
                keepalive: true,
            }).catch(() => {});
        }
    });
})();
