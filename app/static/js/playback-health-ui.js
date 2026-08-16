/* Nomad Pi playback diagnostics on the Server screen. */
(() => {
    if (typeof loadServer !== 'function' || typeof api !== 'function') return;

    function yesNo(value) { return value ? 'Yes' : 'No'; }

    async function injectPlaybackHealth() {
        const body = $('#server-body');
        if (!body || S?.tab !== 'server') return;
        let data;
        try { data = await api('/playback/health'); }
        catch { return; }

        let card = $('#playback-health-card', body);
        if (!card) {
            card = document.createElement('div');
            card.id = 'playback-health-card';
            card.className = 'card card-lg';
            const firstCard = body.querySelector('.card.card-lg');
            if (firstCard?.nextSibling) firstCard.parentNode.insertBefore(card, firstCard.nextSibling);
            else body.prepend(card);
        }

        const ff = data.ffmpeg || {};
        const gst = data.gstreamer_openmax || {};
        const gstBackend = gst.backend || {};
        const modes = data.playback_modes || {};
        const runtime = data.runtime_policy || {};
        const system = data.system || {};
        const candidates = ff.h264_encoder_candidates || [];
        const executionPath = ff.h264_execution_path || candidates;
        const advertised = ff.hardware_encoders_detected || [];
        const validated = ff.validated_hardware_encoders || [];
        const validation = ff.hardware_validation || {};
        const videoNodes = ff.video_devices || [];
        const vendorOmx = !!gst.h264_encoder;
        const gstExecutor = !!gst.executor_enabled;
        const primaryHardware = candidates.find(x => advertised.includes(x));
        const automaticVideo = runtime.automatic_live_video_transcode === true;
        const lite = runtime.lite_playback === true;

        let hwText = 'none';
        if (gstExecutor) {
            hwText = 'omxh264videoenc ✓ validated';
        } else if (primaryHardware) {
            if (validated.includes(primaryHardware)) hwText = `${primaryHardware} ✓ validated`;
            else if (validation[primaryHardware]) hwText = `${primaryHardware} · validation failed`;
            else hwText = `${primaryHardware} · advertised`;
        } else if (validated.length) {
            hwText = `${validated.join(', ')} ✓ validated`;
        } else if (advertised.length) {
            hwText = `${advertised.join(', ')} · advertised only`;
        }

        let platformVideoText = 'Generic FFmpeg path';
        let platformNote = '';
        if (system.is_allwinner_a733) {
            if (gstExecutor) {
                platformVideoText = automaticVideo ? 'A733 OMX ✓ available + enabled' : 'A733 OMX ✓ available';
                platformNote = automaticVideo
                    ? 'The Radxa/Allwinner OpenMAX encoder passed a real encode test and live video conversion is explicitly enabled.'
                    : 'The Radxa/Allwinner OpenMAX encoder passed a real encode test, but Lite mode keeps it idle during normal playback. Direct play and cheap fallbacks are preferred.';
            } else if (validated.includes('h264_v4l2m2m')) {
                platformVideoText = 'A733 V4L2 M2M ✓ available';
                platformNote = 'The Allwinner A733 V4L2 M2M encoder accepted a real test frame. It remains an optional execution path, not a normal playback requirement.';
            } else if (vendorOmx) {
                platformVideoText = 'A733 OMX detected';
                platformNote = gstBackend.detail || 'GStreamer exposes the A733 OpenMAX encoder, but its Nomad runtime validation has not passed.';
            } else if (primaryHardware) {
                platformVideoText = 'A733 hardware unvalidated';
                const detail = validation[primaryHardware]?.detail || gstBackend.detail || '';
                platformNote = detail
                    ? `No A733 backend has passed validation: ${detail}`
                    : `${primaryHardware} is advertised, but Nomad has not validated a working A733 hardware encode path.`;
            } else {
                platformVideoText = 'A733 direct-first';
                platformNote = 'No validated A733 hardware encoder is required for normal Nomad playback. Compatible media still direct-plays normally.';
            }
        } else if (primaryHardware && validated.includes(primaryHardware)) {
            platformVideoText = `${primaryHardware} ✓ available`;
            platformNote = automaticVideo
                ? 'The selected hardware encoder passed a runtime test frame and live video conversion is enabled.'
                : 'The selected hardware encoder passed a runtime test frame. Lite mode keeps it as an optional fallback rather than using it automatically.';
        }

        const nodeText = videoNodes.length
            ? videoNodes.map(n => `${n.device}${n.name ? ` (${n.name})` : ''}`).join(', ')
            : 'no /dev/video* codec nodes reported';
        const systemLine = [
            system.model || 'This device',
            system.architecture || system.machine,
            `${system.memory_mb || '?'} MB RAM`,
            system.memory_class ? `${system.memory_class} memory` : '',
        ].filter(Boolean).join(' · ');
        const omxText = gstExecutor
            ? (automaticVideo ? 'omxh264videoenc ✓ enabled' : 'omxh264videoenc ✓ standby')
            : vendorOmx
                ? 'omxh264videoenc · detected'
                : 'not detected';
        const policyText = lite
            ? 'Direct-first Lite mode'
            : 'Standard direct-first mode';

        card.innerHTML = `
          <div class="health-head">
            <div>
              <div class="health-title">Playback diagnostics</div>
              <div class="health-note">${escapeHtml(systemLine)}</div>
            </div>
            <span class="tag ${data.status === 'ok' ? 'tag-accent' : ''}">${escapeHtml(String(data.status || 'unknown').toUpperCase())}</span>
          </div>
          <div class="facts" style="margin-top:14px">
            <div class="fact"><span class="fact-key">Direct play</span><span class="fact-val">${yesNo(modes.direct_play)}</span></div>
            <div class="fact"><span class="fact-key">Remux HLS</span><span class="fact-val">${yesNo(modes.remux)}</span></div>
            <div class="fact"><span class="fact-key">Audio transcode</span><span class="fact-val">${yesNo(modes.audio_transcode)}</span></div>
            <div class="fact"><span class="fact-key">Video transcode</span><span class="fact-val">${yesNo(modes.video_transcode)}</span></div>
            <div class="fact"><span class="fact-key">Adaptive HLS</span><span class="fact-val">${yesNo(modes.adaptive_hls)}</span></div>
            <div class="facts-divider"></div>
            <div class="fact"><span class="fact-key">Runtime policy</span><span class="fact-val">${escapeHtml(policyText)}</span></div>
            <div class="fact"><span class="fact-key">Preferred media</span><span class="fact-val">${escapeHtml(runtime.preferred_acquisition || '1080p H.264 MP4/AAC')}</span></div>
            <div class="fact"><span class="fact-key">Platform family</span><span class="fact-val">${escapeHtml(system.family || 'generic-linux')}</span></div>
            <div class="fact"><span class="fact-key">H.264 execution</span><span class="fact-val">${escapeHtml(executionPath.join(' → ') || 'none')}</span></div>
            <div class="fact"><span class="fact-key">Hardware test</span><span class="fact-val">${escapeHtml(hwText)}</span></div>
            <div class="fact"><span class="fact-key">Platform video</span><span class="fact-val">${escapeHtml(platformVideoText)}</span></div>
            ${system.is_allwinner_a733 ? `<div class="fact"><span class="fact-key">A733 OMX</span><span class="fact-val">${escapeHtml(omxText)}</span></div>` : ''}
          </div>
          <div class="facts-note" style="text-align:left;margin-top:12px">
            ${escapeHtml(platformNote || 'Hardware acceleration is an optional optimisation; direct playback does not depend on it.')}
            <br><br><strong>Video devices:</strong> ${escapeHtml(nodeText)}
          </div>`;
    }

    const previousLoadServer = loadServer;
    loadServer = async function playbackHealthLoadServer(...args) {
        const result = await previousLoadServer(...args);
        await injectPlaybackHealth();
        return result;
    };
})();
