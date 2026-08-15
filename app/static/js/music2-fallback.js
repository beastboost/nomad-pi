/* Keep the original file-based music rows usable while Music 2 metadata fills. */
(() => {
    const M = window.NomadMusic;
    if (!M) return;

    function renderFallbackIfNeeded() {
        if (typeof S === 'undefined' || S.lib !== 'music' || M.tracks?.length || !M.fallback?.length) return;
        const body = $('#lib-body');
        if (!body || body.dataset.music2Fallback === '1') return;
        body.dataset.music2Fallback = '1';
        const state = M.indexState || {};
        const total = Number(state.discovered || 0);
        const done = Number(state.processed || 0);
        const pct = total ? Math.round(done / total * 100) : 0;
        body.innerHTML = `
          <div class="chip-scroller" style="padding:0 0 14px">
            <button class="chip active">Songs</button>
            <button class="chip" disabled style="opacity:.45">Albums</button>
            <button class="chip" disabled style="opacity:.45">Artists</button>
          </div>
          <div class="card" style="margin-bottom:14px">
            <div class="dl-title">Reading music metadata · ${pct}%</div>
            <div class="dl-meta">${done} / ${total || '…'} tracks · songs remain playable while album/artist data is built</div>
            <div class="bar" style="margin-top:8px"><span style="width:${pct}%"></span></div>
          </div>
          <div class="list">${M.fallback.map(item => {
              const path = item.path;
              const title = stripExt(item.title || item.name || baseName(path));
              return `<button class="list-row row-rule" data-play="${escapeHtml(path)}">
                <div class="list-thumb"><i class="ph ph-music-note"></i></div>
                <div class="list-body">
                  <div class="list-title">${escapeHtml(title)}</div>
                  <div class="list-sub">${escapeHtml(item.folder || (item.size ? fmtSize(item.size) : 'Indexing metadata…'))}</div>
                </div>
                <i class="ph-fill ph-play list-caret"></i>
              </button>`;
          }).join('')}</div>`;
    }

    const body = $('#lib-body');
    if (body && window.MutationObserver) {
        new MutationObserver(() => {
            if (M.tracks?.length) {
                delete body.dataset.music2Fallback;
                return;
            }
            renderFallbackIfNeeded();
        }).observe(body, { childList: true, subtree: false });
    }
    setTimeout(renderFallbackIfNeeded, 250);
})();
