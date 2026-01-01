async function showMediaInfo(path, name) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) return;

    heading.textContent = `Technical Info: ${name}`;
    body.innerHTML = '<div class="loading">Analyzing file...</div>';
    modal.classList.remove('hidden');

    try {
        const res = await fetch(`${API_BASE}/media/info?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        
        if (data.error) {
            body.innerHTML = `<div style="padding:20px; color:var(--danger-color);">Error: ${data.error}</div>`;
            return;
        }

        const vComp = data.video.compatible ? '✅ Likely Compatible' : '⚠️ Potential Codec Issue (H.265/HEVC)';
        const aComp = data.audio.compatible ? '✅ Likely Compatible' : '⚠️ Potential Audio Issue (AC3/DTS)';

        body.innerHTML = `
            <div style="padding:20px; text-align:left; max-width:600px; margin:0 auto; color:var(--text-color);">
                <div style="margin-bottom:20px; padding:15px; border-radius:8px; background:rgba(255,255,255,0.05);">
                    <h3 style="margin-top:0;">Video Stream</h3>
                    <p>Codec: <strong>${data.video.codec}</strong></p>
                    <p>Resolution: <strong>${data.video.width}x${data.video.height}</strong></p>
                    <p>Compatibility: <strong>${vComp}</strong></p>
                </div>
                
                <div style="margin-bottom:20px; padding:15px; border-radius:8px; background:rgba(255,255,255,0.05);">
                    <h3 style="margin-top:0;">Audio Streams</h3>
                    <p>Codecs: <strong>${data.audio.codecs.join(', ')}</strong></p>
                    <p>Compatibility: <strong>${aComp}</strong></p>
                </div>

                <div style="padding:15px; border-radius:8px; background:rgba(255,165,0,0.1); border:1px solid rgba(255,165,0,0.2);">
                    <p style="margin:0; font-size:0.9em; color:#ffa500;">
                        <strong>Note:</strong> Browsers have limited support for H.265 (HEVC) and AC3/DTS audio. 
                        If you see a black screen or have no sound, try using Microsoft Edge or Safari, 
                        which generally have better native support for these formats.
                    </p>
                </div>
                
                <div style="margin-top:20px; text-align:center;">
                    <button class="primary" onclick="openVideoViewer('${path.replaceAll('\\', '\\\\')}', '${name.replaceAll("'", "\\'")}')">Try Playing Anyway</button>
                </div>
            </div>
        `;
    } catch (e) {
        body.innerHTML = `<div style="padding:20px;">Failed to fetch media info: ${e.message}</div>`;
    }
}
