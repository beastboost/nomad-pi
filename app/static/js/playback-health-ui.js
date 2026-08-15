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
        const modes = data.playback_modes || {};
        const system = data.system || {};
        const candidates = ff.h264_encoder_candidates || [];
        const hw = ff.executor_hardware_encoders || [];
        const vendorOmx = !!gst.h264_encoder;
        const omxNote = vendorOmx && !hw.length
            ? 'A733 OpenMAX is installed through GStreamer, but this FFmpeg build does not expose a usable OMX encoder to Nomad yet.'
            : vendorOmx
                ? 'A733 OpenMAX hardware is present.'
                : 'No GStreamer OpenMAX H.264 encoder detected.';

        card.innerHTML = `
          <div class="health-head">
            <div>
              <div class="health-title">Playback diagnostics</div>
              <div class="health-note">${escapeHtml(system.model || 'This device')} · ${escapeHtml(String(system.memory_mb || '?'))} MB RAM</div>
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
            <div class="fact"><span class="fact-key">H.264 path</span><span class="fact-val">${escapeHtml(candidates.join(' → ') || 'none')}</span></div>
            <div class="fact"><span class="fact-key">FFmpeg hardware</span><span class="fact-val">${escapeHtml(hw.join(', ') || 'none')}</span></div>
            <div class="fact"><span class="fact-key">A733 OMX</span><span class="fact-val">${vendorOmx ? 'omxh264videoenc' : 'not detected'}</span></div>
          </div>
          <div class="facts-note" style="text-align:left;margin-top:12px">${escapeHtml(omxNote)}</div>`;
    }

    const previousLoadServer = loadServer;
    loadServer = async function playbackHealthLoadServer(...args) {
        const result = await previousLoadServer(...args);
        await injectPlaybackHealth();
        return result;
    };
})();
