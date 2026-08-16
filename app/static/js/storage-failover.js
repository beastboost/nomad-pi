/* Nomad Pi external-storage failover controls. */
(() => {
    if (typeof api !== 'function' || typeof renderStorage !== 'function') return;

    const human = bytes => typeof fmtSize === 'function' ? fmtSize(bytes || 0) : `${bytes || 0}`;

    async function injectStoragePolicy(body) {
        let policy;
        try { policy = await api('/system/storage/policy'); }
        catch { return; }

        const card = document.createElement('div');
        card.id = 'storage-failover-card';
        card.className = 'card card-lg';
        card.style.marginBottom = '18px';
        const candidates = policy.candidates || [];
        const selected = policy.configured_mount || candidates[0]?.mountpoint || '';
        const free = Number(policy.primary?.free_percent || 0).toFixed(1);
        const threshold = Number(policy.threshold_free_percent || 20);

        card.innerHTML = `
          <div class="health-head">
            <div>
              <div class="health-title">Automatic storage failover</div>
              <div class="health-note">Protect the system/data drive and move new media plus playback caches to a selected external volume when needed.</div>
            </div>
            <label style="display:flex;align-items:center;gap:7px;font-size:13px">
              <input type="checkbox" id="storage-failover-enabled" ${policy.enabled ? 'checked' : ''}
                     style="width:20px;height:20px;accent-color:var(--color-accent)"> On
            </label>
          </div>
          <div class="facts-note" style="text-align:left;margin:12px 0">
            Internal/data filesystem: <strong>${escapeHtml(free)}% free</strong>${policy.failover_active ? ' · <strong style="color:var(--color-accent)">failover active</strong>' : ''}
          </div>
          <label class="field">
            <span>External failover volume</span>
            <select id="storage-failover-mount" class="input input-plain" style="padding-left:12px">
              <option value="">Choose a mounted volume…</option>
              ${candidates.map(item => `<option value="${escapeHtml(item.mountpoint)}" ${item.mountpoint === selected ? 'selected' : ''}>${escapeHtml(item.mountpoint)} · ${escapeHtml(human(item.free))} free (${escapeHtml(String(item.free_percent))}%)</option>`).join('')}
            </select>
          </label>
          <label class="field" style="margin-top:12px">
            <span>Protect this much internal free space</span>
            <div style="display:flex;align-items:center;gap:10px">
              <input type="range" id="storage-failover-threshold" min="5" max="50" step="1" value="${threshold}" style="flex:1;accent-color:var(--color-accent)">
              <strong id="storage-failover-threshold-label" style="min-width:42px;text-align:right">${threshold}%</strong>
            </div>
          </label>
          <button class="btn btn-primary btn-block" id="storage-failover-save" style="margin-top:14px;min-height:46px">Save failover policy</button>
          <div class="facts-note" style="text-align:left;margin-top:10px">
            At 20%, Nomad preserves roughly the last 20% of the internal/data filesystem. New Movies, Shows, Music, Books, Gallery and Files then use matching folders on the selected external volume. HLS, Stream + Keep HLS and adaptive playback caches use the same safety policy. For a large local movie, Nomad preflights the likely cache footprint and can choose the external cache early if writing it internally would breach the reserve.
          </div>`;

        body.prepend(card);
        const slider = card.querySelector('#storage-failover-threshold');
        slider?.addEventListener('input', () => {
            const label = card.querySelector('#storage-failover-threshold-label');
            if (label) label.textContent = `${slider.value}%`;
        });
        card.querySelector('#storage-failover-save')?.addEventListener('click', async () => {
            const enabled = !!card.querySelector('#storage-failover-enabled')?.checked;
            const failover_mount = card.querySelector('#storage-failover-mount')?.value || '';
            const threshold_free_percent = Number(slider?.value || 20);
            try {
                const result = await api('/system/storage/policy', {
                    method: 'POST',
                    body: JSON.stringify({ enabled, failover_mount, threshold_free_percent }),
                });
                const p = result.policy || {};
                toast(p.enabled
                    ? `Storage and playback-cache failover enabled at ${p.threshold_free_percent}% free`
                    : 'Storage failover disabled', 'success', 3500);
                refreshSub();
            } catch (err) {
                toast(err.message || 'Could not save storage failover policy', 'error', 6000);
            }
        });
    }

    const previousRenderStorage = renderStorage;
    renderStorage = async function nomadRenderStorage(body) {
        await previousRenderStorage(body);
        await injectStoragePolicy(body);
    };
})();