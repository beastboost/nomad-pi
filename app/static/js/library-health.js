/* Nomad Pi Library Intelligence / health dashboard. */
(() => {
    if (typeof api !== 'function' || typeof openSub !== 'function') return;

    const LH = { summary: null, view: 'overview', poll: null };
    window.NomadLibraryHealth = LH;

    function humanBytes(bytes) {
        return bytes ? fmtSize(bytes) : '0 B';
    }

    async function refreshServerCard() {
        const body = $('#server-body');
        if (!body) return;
        let card = $('#library-health-card', body);
        if (!card) {
            card = document.createElement('button');
            card.id = 'library-health-card';
            card.className = 'card card-lg';
            card.style.cssText = 'width:100%;text-align:left;color:inherit;border:0;cursor:pointer;margin-bottom:12px';
            body.prepend(card);
        }
        try {
            const s = await api('/playback/intelligence/summary');
            LH.summary = s;
            const scan = s.scan || {};
            const scanning = scan.running;
            card.innerHTML = `
              <div style="display:flex;align-items:center;gap:12px">
                <i class="ph ph-heartbeat" style="font-size:25px;color:var(--color-accent)"></i>
                <div style="min-width:0;flex:1">
                  <div class="list-title">Library health</div>
                  <div class="list-sub">${scanning ? `Scanning ${scan.processed || 0}/${scan.discovered || '…'}…` : `${s.files || 0} video files · ${s.broken || 0} broken · ${s.missing_episode_count || 0} missing episodes`}</div>
                </div>
                <i class="ph ph-caret-right" style="color:var(--text-45)"></i>
              </div>`;
        } catch {
            card.innerHTML = `<div class="list-title">Library health</div><div class="list-sub">Open to scan media quality and duplicates</div>`;
        }
    }

    function topMetric(label, value, icon) {
        return `<div class="card" style="min-width:0"><i class="ph ${icon}" style="font-size:20px;color:var(--color-accent)"></i><div style="font-size:21px;margin-top:8px">${escapeHtml(String(value))}</div><div class="list-sub">${escapeHtml(label)}</div></div>`;
    }

    function scanBanner(summary) {
        const scan = summary.scan || {};
        const pct = scan.discovered ? Math.round((Number(scan.processed || 0) / Number(scan.discovered)) * 100) : 0;
        return `<div class="card" style="margin-bottom:14px">
          <div style="display:flex;align-items:center;gap:10px">
            <div style="flex:1"><div class="list-title">${scan.running ? 'Library scan running' : 'Library scan cache'}</div><div class="list-sub">${scan.running ? `${scan.processed || 0} / ${scan.discovered || '…'} files · ${pct}%` : `${scan.cached || 0} unchanged · ${scan.probed || 0} reprobed`}</div></div>
            <button class="btn" data-health-scan="1"><i class="ph ph-arrows-clockwise"></i>${scan.running ? 'Running' : 'Scan now'}</button>
          </div>
          ${scan.running ? `<div class="bar" style="margin-top:10px"><span style="width:${Math.max(2,pct)}%"></span></div>` : ''}
        </div>`;
    }

    function tabs() {
        const items = [['overview','Overview'],['duplicates','Duplicates'],['missing','Missing TV'],['issues','Issues']];
        return `<div class="chip-scroller" style="padding:0 0 14px">${items.map(([id,label]) => `<button class="chip${LH.view === id ? ' active' : ''}" data-health-view="${id}">${label}</button>`).join('')}</div>`;
    }

    async function renderHealth(body) {
        body.innerHTML = '<div class="empty"><div class="spinner"></div></div>';
        try {
            if (LH.view === 'overview') return renderOverview(body);
            if (LH.view === 'duplicates') return renderDuplicates(body);
            if (LH.view === 'missing') return renderMissing(body);
            return renderIssues(body);
        } catch (err) {
            body.innerHTML = `${tabs()}<div class="facts-note">${escapeHtml(err.message || 'Could not load library health')}</div>`;
        }
    }

    async function renderOverview(body) {
        const s = await api('/playback/intelligence/summary');
        LH.summary = s;
        const issues = s.issue_counts || {};
        const res = s.resolutions || {};
        const codecs = s.video_codecs || {};
        body.innerHTML = `${tabs()}${scanBanner(s)}
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:16px">
            ${topMetric('Files', s.files || 0, 'ph-film-strip')}
            ${topMetric('Library size', humanBytes(s.bytes || 0), 'ph-hard-drives')}
            ${topMetric('Exact duplicate groups', s.exact_duplicate_groups || 0, 'ph-copy')}
            ${topMetric('Missing episodes', s.missing_episode_count || 0, 'ph-television')}
          </div>
          <div class="kicker" style="margin:16px 0 8px">Resolution</div>
          <div class="card"><div class="list-sub">${Object.entries(res).map(([k,v]) => `${escapeHtml(k)} ${v}`).join(' · ') || 'No probe data yet'}</div></div>
          <div class="kicker" style="margin:16px 0 8px">Video codecs</div>
          <div class="card"><div class="list-sub">${Object.entries(codecs).sort((a,b)=>b[1]-a[1]).map(([k,v]) => `${escapeHtml(k.toUpperCase())} ${v}`).join(' · ') || 'No probe data yet'}</div></div>
          <div class="kicker" style="margin:16px 0 8px">Attention</div>
          <div class="list">
            ${healthRow('Broken / unreadable', s.broken || 0, 'probe_failed')}
            ${healthRow('Below 720p', issues.low_resolution || 0, 'low_resolution')}
            ${healthRow('Legacy video codec', issues.legacy_video_codec || 0, 'legacy_video_codec')}
            ${healthRow('Missing audio stream', issues.no_audio_stream || 0, 'no_audio_stream')}
          </div>`;
        startPollIfScanning(body, s.scan);
    }

    function healthRow(label, count, kind) {
        return `<button class="list-row row-rule" data-health-issue="${kind}"><div class="list-body"><div class="list-title">${escapeHtml(label)}</div></div><span class="tag${count ? ' tag-accent' : ''}">${count}</span><i class="ph ph-caret-right list-caret"></i></button>`;
    }

    async function renderDuplicates(body) {
        const data = await api('/playback/intelligence/duplicates');
        const exact = data.exact || [];
        const versions = data.versions || [];
        body.innerHTML = `${tabs()}
          <div class="kicker" style="margin-bottom:8px">Exact duplicates · ${exact.length}</div>
          ${exact.length ? exact.map(group => groupCard('Same bytes', group.files)).join('') : '<div class="facts-note" style="margin-bottom:18px">No exact duplicate fingerprints found.</div>'}
          <div class="kicker" style="margin:18px 0 8px">Alternate versions · ${versions.length}</div>
          ${versions.length ? versions.slice(0,150).map(group => groupCard(group.media_key, group.files)).join('') : '<div class="facts-note">No alternate-version groups found.</div>'}`;
    }

    function groupCard(label, files) {
        return `<div class="card" style="margin-bottom:10px"><div class="list-title">${escapeHtml(String(label || 'Version group'))}</div><div class="list" style="margin-top:8px">${(files || []).map(file => `
          <div class="list-row row-rule">
            <div class="list-body"><div class="list-title">${escapeHtml(file.name)}</div><div class="list-sub">${escapeHtml([file.height ? `${file.height}p` : '', file.video_codec?.toUpperCase(), fmtSize(file.file_size || 0)].filter(Boolean).join(' · '))}</div></div>
            <button class="btn btn-icon btn-icon-plain" data-filemenu="${escapeHtml(file.path)}"><i class="ph ph-dots-three-vertical"></i></button>
          </div>`).join('')}</div></div>`;
    }

    async function renderMissing(body) {
        const data = await api('/playback/intelligence/missing-episodes');
        const groups = data.groups || [];
        body.innerHTML = `${tabs()}${groups.length ? `<div class="list">${groups.map(group => `
          <div class="list-row row-rule"><i class="ph ph-television list-icon"></i><div class="list-body"><div class="list-title">${escapeHtml(group.show)} · Season ${group.season}</div><div class="list-sub">Missing ${group.missing.map(ep => `E${String(ep).padStart(2,'0')}`).join(', ')} · have ${group.present} episodes between E${String(group.first).padStart(2,'0')}–E${String(group.last).padStart(2,'0')}</div></div></div>`).join('')}</div>` : '<div class="facts-note">No episode gaps detected within indexed season ranges.</div>'}`;
    }

    async function renderIssues(body, kind = '') {
        const data = await api(`/playback/intelligence/issues?limit=1000${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`);
        const items = data.items || [];
        body.innerHTML = `${tabs()}<div class="list-sub" style="margin-bottom:10px">${items.length} file${items.length === 1 ? '' : 's'} need attention${kind ? ` · ${escapeHtml(kind.replaceAll('_',' '))}` : ''}</div>
          ${items.length ? `<div class="list">${items.map(file => `
            <div class="list-row row-rule"><div class="list-body"><div class="list-title">${escapeHtml(file.name)}</div><div class="list-sub">${escapeHtml((file.issues || []).join(' · ').replaceAll('_',' '))}${file.probe_error ? ` · ${escapeHtml(file.probe_error)}` : ''}</div></div><button class="btn btn-icon btn-icon-plain" data-filemenu="${escapeHtml(file.path)}"><i class="ph ph-dots-three-vertical"></i></button></div>`).join('')}</div>` : '<div class="facts-note">No matching issues.</div>'}`;
    }

    function startPollIfScanning(body, scan) {
        clearInterval(LH.poll);
        LH.poll = null;
        if (!scan?.running) return;
        LH.poll = setInterval(async () => {
            if (S.screen !== 'sub' || LH.view !== 'overview') return;
            try {
                const next = await api('/playback/intelligence/summary');
                if (!next.scan?.running) {
                    clearInterval(LH.poll); LH.poll = null;
                    renderOverview(body);
                } else {
                    const pct = next.scan.discovered ? Math.round(next.scan.processed / next.scan.discovered * 100) : 0;
                    const bar = body.querySelector('.bar span'); if (bar) bar.style.width = `${Math.max(2,pct)}%`;
                    const row = body.querySelector('.card .list-sub'); if (row) row.textContent = `${next.scan.processed || 0} / ${next.scan.discovered || '…'} files · ${pct}%`;
                }
            } catch {}
        }, 2000);
    }

    function openHealth(view = 'overview', issueKind = '') {
        LH.view = view;
        openSub('Library health', body => {
            if (view === 'issues' && issueKind) renderIssues(body, issueKind);
            else renderHealth(body);
        }, { desc: 'Quality, duplicates, missing episodes and broken media' });
    }

    if (typeof loadServer === 'function') {
        const previousLoadServer = loadServer;
        loadServer = async function healthLoadServer(...args) {
            const result = await previousLoadServer(...args);
            refreshServerCard();
            return result;
        };
    }

    document.addEventListener('click', event => {
        if (event.target.closest('#library-health-card')) { event.preventDefault(); openHealth('overview'); return; }
        const view = event.target.closest('[data-health-view]');
        if (view) { event.preventDefault(); event.stopImmediatePropagation(); LH.view = view.dataset.healthView; const body=$('#sub-body'); if(body) renderHealth(body); return; }
        const issue = event.target.closest('[data-health-issue]');
        if (issue) { event.preventDefault(); event.stopImmediatePropagation(); LH.view='issues'; const body=$('#sub-body'); if(body) renderIssues(body, issue.dataset.healthIssue); return; }
        const scan = event.target.closest('[data-health-scan]');
        if (scan) {
            event.preventDefault(); event.stopImmediatePropagation();
            api('/playback/intelligence/scan?force=true', { method:'POST' }).then(() => {
                toast('Library health scan started', 'success', 2200);
                const body=$('#sub-body'); if(body) renderOverview(body);
            }).catch(err => toast(err.message || 'Could not start scan','error'));
        }
    }, true);
})();
