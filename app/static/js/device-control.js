/* Nomad Pi live playback devices and two-phase playback handoff. */
(() => {
    const Core = window.NomadPlaybackCore;
    if (!Core || typeof api !== 'function' || typeof openSheet !== 'function') return;

    const DEVICE_KEY = 'nomad_playback_device_id';
    const DEVICE_NAME_KEY = 'nomad_playback_device_name';
    const REGISTER_MS = 15000;
    const POLL_MS = 3000;
    let registering = false;
    let polling = false;

    function deviceId() {
        let id = localStorage.getItem(DEVICE_KEY);
        if (!id) {
            id = window.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            localStorage.setItem(DEVICE_KEY, id);
        }
        return id;
    }

    function platformName() {
        const ua = navigator.userAgent || '';
        if (/iPhone/i.test(ua)) return 'iPhone';
        if (/iPad/i.test(ua)) return 'iPad';
        if (/Android/i.test(ua)) return 'Android';
        if (/Windows/i.test(ua)) return 'Windows';
        if (/Macintosh|Mac OS X/i.test(ua)) return 'Mac';
        if (/Linux/i.test(ua)) return 'Linux';
        return navigator.platform || 'Web device';
    }

    function browserName() {
        const ua = navigator.userAgent || '';
        if (/Edg\//.test(ua)) return 'Edge';
        if (/Firefox\//.test(ua)) return 'Firefox';
        if (/CriOS|Chrome\//.test(ua)) return 'Chrome';
        if (/Safari\//.test(ua)) return 'Safari';
        return 'Browser';
    }

    function deviceName() {
        const saved = localStorage.getItem(DEVICE_NAME_KEY);
        return saved || `${platformName()} · ${browserName()}`;
    }

    function deviceKind() {
        if (window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone) return 'pwa';
        return /iPhone|iPad|Android/i.test(navigator.userAgent || '') ? 'mobile-web' : 'desktop-web';
    }

    function currentSessionId() {
        return Core.current?.id || null;
    }

    async function registerDevice() {
        if (registering || !token()) return;
        registering = true;
        try {
            await api('/playback/devices/register', {
                method: 'POST',
                body: JSON.stringify({
                    device_id: deviceId(),
                    name: deviceName(),
                    kind: deviceKind(),
                    current_session_id: currentSessionId(),
                    capabilities: {
                        screen_width: window.screen?.width || null,
                        screen_height: window.screen?.height || null,
                        pixel_ratio: window.devicePixelRatio || 1,
                        standalone: Boolean(window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone),
                    },
                }),
            });
        } catch (err) {
            if (err?.status !== 401) console.debug('[Nomad devices] register failed:', err);
        } finally {
            registering = false;
        }
    }

    async function heartbeatDevice() {
        if (!token()) return;
        try {
            await api(`/playback/devices/${encodeURIComponent(deviceId())}/heartbeat`, {
                method: 'POST',
                body: JSON.stringify({ current_session_id: currentSessionId() }),
            });
        } catch (err) {
            if (err?.status === 404) await registerDevice();
        }
    }

    function absolutePosition() {
        if (typeof Core.absolutePosition === 'function') return Core.absolutePosition();
        const video = V?.el;
        return Math.max(0, Number(Core.current?.offset || 0) + Number(video?.currentTime || 0));
    }

    function currentSubtitleSelection() {
        const video = V?.el;
        const embedded = video?.querySelector?.('track[data-nomad-embedded]');
        if (embedded?.src) {
            const match = embedded.src.match(/\/subtitles\/(\d+)\.vtt(?:\?|$)/);
            if (match) return { track: Number(match[1]), burned: false };
        }
        const track = Core.current?.subtitleTrack;
        return track !== null && track !== undefined
            ? { track: Number(track), burned: true }
            : { track: null, burned: false };
    }

    async function attachTextSubtitle(streamIndex) {
        const current = Core.current;
        const video = V?.el;
        if (!current || !video) throw new Error('No target playback session');
        const tracks = await api(`/playback/tracks?path=${encodeURIComponent(V.path)}`);
        const selected = (tracks.subtitles || []).find(x => Number(x.stream_index) === Number(streamIndex));
        if (!selected) throw new Error('Transferred subtitle track no longer exists');
        if (!selected.text_supported) throw new Error('Transferred subtitle is image-based');
        const ticket = await api(`/playback/sessions/${encodeURIComponent(current.id)}/ticket`, { method: 'POST' });
        video.querySelectorAll('track[data-nomad-embedded]').forEach(x => x.remove());
        const el = document.createElement('track');
        el.kind = 'subtitles';
        el.srclang = selected.language || 'und';
        el.label = selected.title || String(selected.language || 'Subtitle').toUpperCase();
        el.default = true;
        el.dataset.nomadEmbedded = '1';
        el.src = `/api/playback/sessions/${encodeURIComponent(current.id)}/subtitles/${Number(streamIndex)}.vtt?ticket=${encodeURIComponent(ticket.ticket)}`;
        el.addEventListener('load', () => {
            Array.from(video.textTracks || []).forEach(t => { t.mode = 'disabled'; });
            try { el.track.mode = 'showing'; } catch {}
        }, { once: true });
        video.appendChild(el);
        current.subtitleTrack = Number(streamIndex);
        current.subtitleBurned = false;
    }

    async function applyTransferredSettings(payload) {
        let current = Core.current;
        if (!current) throw new Error('Target playback session did not start');
        const desiredQuality = payload.adaptive ? 'adaptive' : (payload.quality || 'auto');

        if (desiredQuality && desiredQuality !== 'auto') {
            const absolute = absolutePosition();
            const video = V?.el;
            const wasPlaying = !video?.paused;
            const endpoint = desiredQuality === 'adaptive'
                ? `/playback/sessions/${encodeURIComponent(current.id)}/adaptive`
                : `/playback/sessions/${encodeURIComponent(current.id)}/quality`;
            const body = desiredQuality === 'adaptive'
                ? { position: absolute }
                : { quality: desiredQuality, position: absolute };
            const result = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
            await Core.applyReplacement(result, { autoplay: wasPlaying, absolute });
            current = Core.current;
        }

        if (payload.audio_track !== null && payload.audio_track !== undefined) {
            const absolute = absolutePosition();
            const video = V?.el;
            const wasPlaying = !video?.paused;
            const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/audio`, {
                method: 'POST',
                body: JSON.stringify({ stream_index: Number(payload.audio_track), position: absolute }),
            });
            await Core.applyReplacement(result, { autoplay: wasPlaying, absolute });
            current = Core.current;
        }

        if (payload.subtitle_track !== null && payload.subtitle_track !== undefined) {
            if (payload.subtitle_burned) {
                const absolute = absolutePosition();
                const video = V?.el;
                const wasPlaying = !video?.paused;
                const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/subtitles/burn`, {
                    method: 'POST',
                    body: JSON.stringify({
                        stream_index: Number(payload.subtitle_track),
                        position: absolute,
                    }),
                });
                await Core.applyReplacement(result, { autoplay: wasPlaying, absolute });
                Core.current.subtitleTrack = Number(payload.subtitle_track);
                Core.current.subtitleBurned = true;
            } else {
                await attachTextSubtitle(Number(payload.subtitle_track));
            }
        }
    }

    async function executeHandoff(command) {
        const payload = command.payload || {};
        if (!payload.path) throw new Error('Handoff command has no media path');
        const existing = Core.current;
        if (existing && typeof stopVideo === 'function') stopVideo();

        await playVideo(payload.path, Number(payload.position || 0));
        if (!Core.current) throw new Error('Target could not start the media');
        await applyTransferredSettings(payload);
        await heartbeatDevice();
        toast('Playback transferred to this device', 'success', 3000);
        return {
            session_id: Core.current.id,
            position: absolutePosition(),
        };
    }

    async function acknowledge(command, status, result) {
        try {
            await api(`/playback/devices/${encodeURIComponent(deviceId())}/commands/${encodeURIComponent(command.id)}/ack`, {
                method: 'POST',
                body: JSON.stringify({ status, result: result || {} }),
            });
        } catch (err) {
            console.debug('[Nomad devices] command acknowledgement failed:', err);
        }
    }

    async function pollCommands() {
        if (polling || !token()) return;
        polling = true;
        try {
            const data = await api(`/playback/devices/${encodeURIComponent(deviceId())}/commands?limit=3`);
            for (const command of data.commands || []) {
                if (command.command !== 'handoff') {
                    await acknowledge(command, 'rejected', { detail: `Unknown command ${command.command}` });
                    continue;
                }
                try {
                    const result = await executeHandoff(command);
                    await acknowledge(command, 'completed', result);
                } catch (err) {
                    await acknowledge(command, 'failed', { detail: err?.message || String(err) });
                    toast(`Playback transfer failed: ${err?.message || err}`, 'error', 6500);
                }
            }
        } catch (err) {
            if (err?.status === 404) await registerDevice();
        } finally {
            polling = false;
        }
    }

    async function awaitHandoff(commandId, sourceSessionId, targetName) {
        for (let attempt = 0; attempt < 60; attempt += 1) {
            await new Promise(resolve => setTimeout(resolve, 750));
            let data;
            try { data = await api(`/playback/commands/${encodeURIComponent(commandId)}`); }
            catch { continue; }
            const command = data.command || {};
            if (command.status === 'completed') {
                if (Core.current?.id === sourceSessionId) stopVideo();
                toast(`Playback moved to ${targetName}`, 'success', 3000);
                return;
            }
            if (command.status === 'failed' || command.status === 'rejected') {
                toast(`Could not move playback to ${targetName}: ${command.result?.detail || command.status}`, 'error', 6500);
                return;
            }
        }
        toast(`${targetName} did not confirm the transfer; playback is still here.`, 'warn', 5000);
    }

    async function sendHandoff(targetId, targetName) {
        const current = Core.current;
        if (!current || !V?.el) return;
        const sourceSessionId = current.id;
        const subtitle = currentSubtitleSelection();
        closeSheet();
        toast(`Sending playback to ${targetName}…`, 'info', 2500);
        try {
            const result = await api(`/playback/sessions/${encodeURIComponent(current.id)}/handoff`, {
                method: 'POST',
                body: JSON.stringify({
                    target_device_id: targetId,
                    position: absolutePosition(),
                    quality: current.quality || 'auto',
                    audio_track: current.audioTrack ?? null,
                    subtitle_track: subtitle.track,
                    subtitle_burned: subtitle.burned,
                }),
            });
            awaitHandoff(result.command.id, sourceSessionId, targetName);
        } catch (err) {
            toast(err.message || 'Could not send playback to that device', 'error', 6000);
        }
    }

    async function togglePictureInPicture() {
        const video = V?.el;
        if (!video) return;
        try {
            if (document.pictureInPictureElement) await document.exitPictureInPicture();
            else if (video.requestPictureInPicture) await video.requestPictureInPicture();
            else toast('Picture-in-picture is not supported here', 'warn');
        } catch {
            toast('Picture-in-picture is not available', 'warn');
        }
    }

    async function openDevices() {
        const current = Core.current;
        if (!current) {
            toast('Start a video before choosing a playback device.', 'info', 3000);
            return;
        }
        openSheet(`
          <div class="kicker" style="margin-bottom:4px">Play on</div>
          <div class="list-sub" style="margin-bottom:12px">This device: ${escapeHtml(deviceName())}</div>
          <div id="nomad-device-list"><div class="empty"><div class="spinner"></div></div></div>`);
        try {
            await registerDevice();
            const data = await api('/playback/devices');
            const others = (data.devices || []).filter(d => d.device_id !== deviceId());
            const online = others.filter(d => d.online);
            const offline = others.filter(d => !d.online);
            const out = $('#nomad-device-list');
            if (!out) return;
            out.innerHTML = `<div class="list">
              <button class="sheet-option row-rule" data-nomad-pip="1">
                <span><span style="display:block">Picture in Picture</span><span class="list-sub">Keep playing on this device</span></span>
                <i class="ph ph-picture-in-picture"></i>
              </button>
              ${online.map(d => `
                <button class="sheet-option row-rule" data-nomad-device="${escapeHtml(d.device_id)}" data-nomad-device-name="${escapeHtml(d.name)}">
                  <span style="text-align:left"><span style="display:block">${escapeHtml(d.name)}</span><span class="list-sub">Online · ${escapeHtml(d.kind || 'device')}</span></span>
                  <i class="ph ph-broadcast" style="color:var(--color-accent)"></i>
                </button>`).join('')}
              ${offline.length ? `<div class="kicker" style="padding:14px 0 6px">Offline</div>${offline.map(d => `
                <div class="sheet-option row-rule" style="opacity:.45">
                  <span>${escapeHtml(d.name)}</span><i class="ph ph-minus-circle"></i>
                </div>`).join('')}` : ''}
            </div>${!online.length ? '<div class="facts-note" style="text-align:left;margin-top:12px">Open Nomad on another signed-in device and it will appear here automatically.</div>' : ''}`;
        } catch (err) {
            const out = $('#nomad-device-list');
            if (out) out.innerHTML = `<div class="facts-note">${escapeHtml(err.message || 'Could not load playback devices')}</div>`;
        }
    }

    document.addEventListener('click', event => {
        const cast = event.target.closest('#player-cast');
        if (cast) {
            event.preventDefault();
            event.stopImmediatePropagation();
            openDevices();
            return;
        }
        if (event.target.closest('[data-nomad-pip]')) {
            event.preventDefault();
            event.stopImmediatePropagation();
            closeSheet();
            togglePictureInPicture();
            return;
        }
        const target = event.target.closest('[data-nomad-device]');
        if (target) {
            event.preventDefault();
            event.stopImmediatePropagation();
            sendHandoff(target.dataset.nomadDevice, target.dataset.nomadDeviceName || 'device');
        }
    }, true);

    // Presence is independent of video playback: a second phone/tablet should
    // be discoverable before it starts its own session. Commands are polled at
    // a modest cadence to keep a Zero-class SBC and browser wakeups cheap.
    registerDevice();
    setInterval(() => {
        if (!token()) return;
        heartbeatDevice();
        pollCommands();
    }, POLL_MS);
    setInterval(registerDevice, REGISTER_MS);
})();
