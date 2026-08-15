/* Nomad Pi Offline Sync — prepare portable travel copies on the server. */
(() => {
    if (typeof api !== 'function' || typeof openSheet !== 'function') return;

    const O = { pollTimer: null, activeJob: null };
    window.NomadOffline = O;

    function jobTitle(job) {
        return stripExt(baseName(job.source_path || job.metadata?.source_name || 'Offline media'));
    }

    function sizeLabel(bytes) {
        return bytes ? fmtSize(bytes) : '';
    }

    async function openQuality(path) {
        closeSheet();
        let profiles = [];
        try {
            const data = await api('/playback/offline/profiles');
            profiles = data.profiles || [];
        } catch {}
        if (!profiles.length) {
            profiles = [
                { id: 'original', label: 'Original' },
                { id: '1080p', label: '1080p', bitrate: 8000000 },
                { id: '720p', label: '720p', bitrate: 4000000 },
                { id: '480p', label: '480p', bitrate: 2000000 },
            ];
        }
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Prepare offline copy</div>
          <div style="font-size:15px;margin-bottom:12px;word-break:break-word">${escapeHtml(baseName(path))}</div>
          <div class="list">${profiles.map(p => `
            <button class="sheet-option row-rule" data-offline-quality="${escapeHtml(p.id)}" data-offline-path="${escapeHtml(path)}">
              <span style="text-align:left">
                <span style="display:block">${escapeHtml(p.label || p.id)}</span>
                <span class="list-sub">${p.id === 'original' ? 'Portable MP4 · keep source resolution when possible' : `Portable H.264/AAC${p.bitrate ? ` · up to ${Math.round(p.bitrate / 1e6)} Mbps` : ''}`}</span>
              </span>
              <i class="ph ph-download-simple"></i>
            </button>`).join('')}</div>`);
    }

    async function createJob(path, quality) {
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Offline Sync</div>
          <div style="font-size:15px;margin-bottom:8px">${escapeHtml(baseName(path))}</div>
          <div class="facts-note" id="offline-job-message" style="text-align:left">Creating ${escapeHtml(quality)} travel copy…</div>
          <div class="bar" style="margin-top:14px"><span id="offline-job-bar" style="width:2%"></span></div>
          <div id="offline-job-actions" style="margin-top:14px"></div>`);
        try {
            const data = await api('/playback/offline', {
                method: 'POST',
                body: JSON.stringify({ path, quality }),
            });
            O.activeJob = data.job?.id || null;
            if (!O.activeJob) throw new Error('Server did not create an offline job');
            pollJob(O.activeJob);
        } catch (err) {
            const msg = $('#offline-job-message');
            if (msg) msg.textContent = err.message || 'Could not create offline copy';
            toast(err.message || 'Could not create offline copy', 'error', 5500);
        }
    }

    function renderJobStatus(job) {
        const msg = $('#offline-job-message');
        const bar = $('#offline-job-bar');
        const actions = $('#offline-job-actions');
        if (!msg || !bar || !actions) return;
        const pct = Math.round(Number(job.progress || 0));
        bar.style.width = `${Math.max(2, Math.min(100, pct))}%`;
        if (job.status === 'ready' && job.ready) {
            msg.textContent = `Ready · ${job.quality} · ${sizeLabel(job.size_bytes)}`;
            actions.innerHTML = `
              <button class="btn btn-primary btn-block" data-offline-download="${escapeHtml(job.id)}"><i class="ph ph-download-simple"></i> Download travel copy</button>
              <button class="btn btn-block" data-offline-delete="${escapeHtml(job.id)}" style="margin-top:8px"><i class="ph ph-trash"></i> Delete prepared copy</button>`;
            return;
        }
        if (job.status === 'failed') {
            msg.textContent = `Failed: ${job.error || 'conversion failed'}`;
            actions.innerHTML = `<button class="btn btn-block" data-offline-retry="${escapeHtml(job.id)}"><i class="ph ph-arrow-clockwise"></i> Retry</button>`;
            return;
        }
        if (job.status === 'cancelled') {
            msg.textContent = 'Offline preparation cancelled.';
            actions.innerHTML = `<button class="btn btn-block" data-offline-retry="${escapeHtml(job.id)}"><i class="ph ph-arrow-clockwise"></i> Retry</button>`;
            return;
        }
        msg.textContent = `${String(job.status || 'working').replaceAll('_', ' ')} · ${pct}%`;
        actions.innerHTML = `<button class="btn btn-block" data-offline-delete="${escapeHtml(job.id)}"><i class="ph ph-x-circle"></i> Cancel</button>`;
    }

    function pollJob(jobId) {
        clearInterval(O.pollTimer);
        const tick = async () => {
            try {
                const data = await api(`/playback/offline/${encodeURIComponent(jobId)}`);
                const job = data.job;
                if (!job) return;
                renderJobStatus(job);
                if (['ready','failed','cancelled','deleted'].includes(job.status)) {
                    clearInterval(O.pollTimer);
                    O.pollTimer = null;
                    if (job.status === 'ready') toast('Offline travel copy is ready.', 'success', 3200);
                }
            } catch {}
        };
        tick();
        O.pollTimer = setInterval(tick, 1500);
    }

    async function downloadJob(jobId) {
        try {
            const ticket = await api(`/playback/offline/${encodeURIComponent(jobId)}/ticket`, { method: 'POST' });
            const a = document.createElement('a');
            a.href = ticket.url;
            a.download = ticket.filename || '';
            a.rel = 'noopener';
            a.target = '_blank';
            document.body.appendChild(a);
            a.click();
            a.remove();
            toast('Offline copy download started.', 'success', 2500);
        } catch (err) {
            toast(err.message || 'Could not download offline copy', 'error', 5000);
        }
    }

    async function deleteJob(jobId) {
        try {
            const data = await api(`/playback/offline/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
            toast(data.job?.status === 'deleted' ? 'Prepared copy deleted.' : 'Offline job cancelled.', 'success', 2200);
            if (S?.tab === 'downloads') renderOfflineDownloads();
            closeSheet();
        } catch (err) {
            toast(err.message || 'Could not remove offline copy', 'error', 5000);
        }
    }

    async function retryJob(jobId) {
        try {
            const data = await api(`/playback/offline/${encodeURIComponent(jobId)}/retry`, { method: 'POST' });
            O.activeJob = jobId;
            renderJobStatus(data.job || {});
            pollJob(jobId);
        } catch (err) {
            toast(err.message || 'Could not retry offline copy', 'error', 5000);
        }
    }

    async function renderOfflineDownloads() {
        const body = $('#dl-body');
        if (!body || S?.tab !== 'downloads') return;
        try {
            const data = await api('/playback/offline?limit=100');
            const jobs = (data.jobs || []).filter(j => j.status !== 'deleted');
            let section = $('#offline-downloads-section', body);
            if (!section) {
                section = document.createElement('div');
                section.id = 'offline-downloads-section';
                section.className = 'section';
                body.prepend(section);
            }
            if (!jobs.length) {
                section.innerHTML = '';
                return;
            }
            section.innerHTML = `
              <div class="kicker" style="margin-bottom:10px">Offline copies</div>
              <div class="list">${jobs.map(job => {
                  const pct = Math.round(Number(job.progress || 0));
                  const ready = job.status === 'ready' && job.ready;
                  return `<div class="list-row row-rule">
                    <div class="list-body">
                      <div class="list-title">${escapeHtml(jobTitle(job))}</div>
                      <div class="list-sub">${escapeHtml(job.quality)} · ${ready ? `${sizeLabel(job.size_bytes)} · ready` : `${String(job.status).replaceAll('_',' ')} · ${pct}%`}</div>
                      ${!ready && !['failed','cancelled'].includes(job.status) ? `<div class="bar" style="margin-top:6px"><span style="width:${Math.max(2,pct)}%"></span></div>` : ''}
                    </div>
                    ${ready ? `<button class="btn btn-icon" data-offline-download="${escapeHtml(job.id)}" aria-label="Download"><i class="ph ph-download-simple"></i></button>` : ''}
                    ${job.status === 'failed' || job.status === 'cancelled' ? `<button class="btn btn-icon" data-offline-retry="${escapeHtml(job.id)}" aria-label="Retry"><i class="ph ph-arrow-clockwise"></i></button>` : ''}
                    <button class="btn btn-icon btn-icon-plain" data-offline-delete="${escapeHtml(job.id)}" aria-label="Delete"><i class="ph ph-trash"></i></button>
                  </div>`;
              }).join('')}</div>`;
        } catch {}
    }

    // Add the action to the existing file options instead of forking the menu.
    if (typeof openFileMenu === 'function') {
        const previousOpenFileMenu = openFileMenu;
        openFileMenu = function offlineOpenFileMenu(path) {
            previousOpenFileMenu(path);
            if (kindOf(path) !== 'video') return;
            const list = $('#sheet .list');
            if (!list || list.querySelector('[data-offline-create]')) return;
            const button = document.createElement('button');
            button.className = 'sheet-option row-rule';
            button.dataset.offlineCreate = path;
            button.innerHTML = '<span>Prepare offline copy</span><i class="ph ph-airplane-tilt"></i>';
            list.appendChild(button);
        };
    }

    if (typeof loadDownloads === 'function') {
        const previousLoadDownloads = loadDownloads;
        loadDownloads = async function offlineLoadDownloads(...args) {
            const result = await previousLoadDownloads(...args);
            await renderOfflineDownloads();
            return result;
        };
    }

    document.addEventListener('click', event => {
        const create = event.target.closest('[data-offline-create]');
        if (create) { event.preventDefault(); event.stopImmediatePropagation(); openQuality(create.dataset.offlineCreate); return; }
        const quality = event.target.closest('[data-offline-quality]');
        if (quality) { event.preventDefault(); event.stopImmediatePropagation(); createJob(quality.dataset.offlinePath, quality.dataset.offlineQuality); return; }
        const download = event.target.closest('[data-offline-download]');
        if (download) { event.preventDefault(); event.stopImmediatePropagation(); downloadJob(download.dataset.offlineDownload); return; }
        const del = event.target.closest('[data-offline-delete]');
        if (del) { event.preventDefault(); event.stopImmediatePropagation(); deleteJob(del.dataset.offlineDelete); return; }
        const retry = event.target.closest('[data-offline-retry]');
        if (retry) { event.preventDefault(); event.stopImmediatePropagation(); retryJob(retry.dataset.offlineRetry); }
    }, true);

    setInterval(() => {
        if (S?.tab === 'downloads') renderOfflineDownloads();
    }, 4000);
})();
