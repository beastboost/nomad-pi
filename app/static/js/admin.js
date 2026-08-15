/* ══════════════════════════════════════════════════════════════════════════
   Nomad Pi — administration screens

   Everything the old Admin dashboard carried, rebuilt on the Nocturne
   sub-page shell: Wi-Fi, Tailscale, users, storage, backup, API keys,
   uploads, library maintenance and logs.

   Each screen is a render function that fills #sub-body. Rows are built with
   data-* attributes and read back via dataset — no user string ever lands in
   an inline handler.
   ══════════════════════════════════════════════════════════════════════════ */

/* ── Sub-page helpers ──────────────────────────────────────────────────── */

let _subRender = null;

function openSub(title, renderFn, opts = {}) {
    _subRender = renderFn;
    push('sub');
    $('#sub-title').textContent = title;
    $('#sub-desc').textContent = opts.desc || '';
    const act = $('#sub-action');
    if (opts.action) {
        act.classList.remove('hidden');
        act.innerHTML = `<i class="${opts.action.icon || 'ph ph-plus'}"></i>`;
        act.setAttribute('aria-label', opts.action.label || 'Action');
        act.onclick = opts.action.onClick;
    } else {
        act.classList.add('hidden');
        act.onclick = null;
    }
    refreshSub();
}

async function refreshSub() {
    if (!_subRender) return;
    const body = $('#sub-body');
    body.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        await _subRender(body);
    } catch (e) {
        body.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Could not load')}</div>`;
    }
}

/* Small builders shared by the admin screens */

const field = (id, label, opts = {}) => `
  <label class="field">
    <span>${escapeHtml(label)}</span>
    <input class="input input-plain" id="${id}" type="${opts.type || 'text'}"
           placeholder="${escapeHtml(opts.placeholder || '')}"
           value="${escapeHtml(opts.value || '')}"
           ${opts.autocomplete ? `autocomplete="${opts.autocomplete}"` : 'autocomplete="off"'}
           ${opts.attrs || ''}>
  </label>`;

const sectionLabel = (text) => `<div class="kicker" style="margin:22px 0 8px">${escapeHtml(text)}</div>`;

const infoRow = (label, value, icon) => `
  <div class="list-row list-row-tall row-rule">
    ${icon ? `<i class="${escapeHtml(icon)} list-icon"></i>` : ''}
    <div class="list-body"><div class="list-title">${escapeHtml(label)}</div></div>
    <span class="list-value">${escapeHtml(String(value ?? '—'))}</span>
  </div>`;

/* ══════════════════════════════════════════════════════════════════════════
   Wi-Fi
   ══════════════════════════════════════════════════════════════════════════ */

async function renderWifi(body) {
    let status = {}, info = {};
    try { status = await api('/system/wifi/status'); } catch {}
    try { info = await api('/system/wifi/info'); } catch {}

    const enabled = status.enabled !== false && status.status !== 'unsupported';
    const mode = info.mode || '';
    const connected = mode === 'wifi' && info.ssid;

    body.innerHTML = `
      <div class="card card-lg">
        <div class="health-head">
          <div style="min-width:0">
            <div class="health-title">${connected ? escapeHtml(info.ssid) : mode === 'hotspot' ? 'Hotspot mode' : 'Not connected'}</div>
            <div class="health-note">${connected
                ? escapeHtml([info.ip, info.bitrate, info.frequency].filter(Boolean).join(' · '))
                : mode === 'hotspot' ? 'Serving the NomadPi hotspot at 10.42.0.1' : 'No wireless network joined'}</div>
          </div>
          <button class="btn ${enabled ? '' : 'btn-primary'}" id="wifi-toggle" style="min-height:44px;flex:none">
            ${enabled ? 'Turn off' : 'Turn on'}
          </button>
        </div>
      </div>

      <div class="btn-row" style="margin-top:12px">
        <button class="btn" id="wifi-rescan"><i class="ph ph-arrows-clockwise"></i>Scan</button>
        <button class="btn" id="wifi-restart"><i class="ph ph-power"></i>Restart Wi-Fi</button>
      </div>

      ${sectionLabel('Available networks')}
      <div id="wifi-list"><div class="empty"><div class="spinner"></div></div></div>

      <div class="card" style="margin-top:20px">
        <div class="facts-note" style="text-align:left;line-height:1.6">
          Joining a network drops the hotspot. If you are connected over
          <strong>NomadPi</strong> right now, this device will disconnect —
          rejoin on the new network or the hotspot to carry on.
        </div>
      </div>`;

    $('#wifi-toggle').addEventListener('click', async () => {
        if (!enabled) {
            try {
                await api('/system/wifi/toggle?enable=true', { method: 'POST' });
                toast('Wi-Fi turned on', 'success');
                refreshSub();
            } catch (e) { toast(e.message || 'Could not turn Wi-Fi on', 'error'); }
            return;
        }

        // Switching the radio off is how you lose the box: on a headless Pi
        // Wi-Fi is usually the only route in, and the off state survives a
        // reboot. Say so plainly, then rely on the server's auto-revert.
        const ok = await confirmDialog(
            'Turn Wi-Fi off?',
            'Wi-Fi is normally the only way to reach this box, so you will be '
            + 'disconnected immediately and cannot turn it back on from here.\n\n'
            + 'As a safety net the radio switches itself back on after 5 minutes. '
            + 'Only continue if you have Ethernet plugged in, or you want it off briefly.',
            'Turn off anyway');
        if (!ok) return;

        try {
            const r = await api('/system/wifi/toggle?enable=false&confirm=true', { method: 'POST' });
            const mins = Math.round((r.revert_in_seconds || 300) / 60);
            toast(`Wi-Fi off — switching back on automatically in ${mins} min`, 'warn', 9000);
            refreshSub();
        } catch (e) { toast(e.message || 'Could not turn Wi-Fi off', 'error', 8000); }
    });
    $('#wifi-restart').addEventListener('click', async () => {
        if (!await confirmDialog('Restart Wi-Fi?', 'All wireless connections drop briefly while the adapter restarts.', 'Restart')) return;
        try { await api('/system/wifi/restart', { method: 'POST' }); toast('Wi-Fi restarting…', 'info'); }
        catch (e) { toast(e.message || 'Restart failed', 'error'); }
    });
    $('#wifi-rescan').addEventListener('click', () => loadWifiNetworks());

    loadWifiNetworks();
}

async function loadWifiNetworks() {
    const out = $('#wifi-list');
    if (!out) return;
    out.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        const data = await api('/system/wifi/scan');
        const nets = (data.networks || []).filter(n => n.ssid);
        if (!nets.length) {
            out.innerHTML = `<div class="empty"><i class="ph ph-wifi-slash"></i>No networks found.</div>`;
            return;
        }
        out.innerHTML = `<div class="list">${nets.map((n, i) => {
            const sig = Number(n.signal || 0);
            const icon = sig >= 66 ? 'ph-wifi-high' : sig >= 33 ? 'ph-wifi-medium' : 'ph-wifi-low';
            const locked = n.security && n.security !== 'None' && n.security !== '--';
            return `
              <button class="list-row list-row-tall row-rule" data-wifi="${i}">
                <i class="ph ${icon} list-icon"></i>
                <div class="list-body">
                  <div class="list-title">${escapeHtml(n.ssid)}${n.active ? ' · connected' : ''}</div>
                  <div class="list-sub">${sig}%${locked ? ` · ${escapeHtml(n.security)}` : ' · open'}</div>
                </div>
                ${locked ? '<i class="ph ph-lock-simple list-caret"></i>' : ''}
                <i class="ph ph-caret-right list-caret"></i>
              </button>`;
        }).join('')}</div>`;
        _wifiNetworks = nets;
    } catch (e) {
        out.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Scan failed')}</div>`;
    }
}

let _wifiNetworks = [];

function openWifiJoin(index) {
    const n = _wifiNetworks[index];
    if (!n) return;
    const locked = n.security && n.security !== 'None' && n.security !== '--';
    openSheet(`
      <div class="kicker" style="margin-bottom:4px">Join network</div>
      <div style="font-size:17px;font-weight:500;margin-bottom:14px">${escapeHtml(n.ssid)}</div>
      ${locked ? `
        <input type="password" class="input input-plain" id="wifi-pw" placeholder="Password"
               autocomplete="current-password" style="margin-bottom:10px">` : ''}
      <div id="wifi-join-status" style="font-size:12.5px;color:var(--text-45);min-height:18px;margin-bottom:8px"></div>
      <button class="btn btn-primary btn-block" id="wifi-join" style="min-height:48px">Connect</button>
      <div class="facts-note" style="margin-top:10px;text-align:left">
        You will lose this connection if you are on the hotspot.
      </div>`);

    $('#wifi-join').addEventListener('click', async () => {
        const pw = $('#wifi-pw')?.value || '';
        const st = $('#wifi-join-status');
        if (locked && !pw) { st.textContent = 'Enter the network password.'; return; }
        st.textContent = 'Connecting… this can take up to a minute.';
        $('#wifi-join').disabled = true;
        try {
            const r = await api('/system/wifi/connect', {
                method: 'POST',
                body: JSON.stringify({ ssid: n.ssid, password: pw }),
            });
            closeSheet();
            toast(r.message || `Connected to ${n.ssid}`, 'success', 6000);
            refreshSub();
        } catch (e) {
            // A dropped connection mid-switch is expected and not a failure
            st.textContent = e.message?.includes('Failed to fetch')
                ? 'Connection dropped while switching — rejoin on the new network to confirm.'
                : (e.message || 'Could not join that network.');
            $('#wifi-join').disabled = false;
        }
    });
}

/* ══════════════════════════════════════════════════════════════════════════
   Tailscale
   ══════════════════════════════════════════════════════════════════════════ */

async function renderTailscale(body) {
    let s = {};
    try { s = await api('/system/tailscale/status'); } catch (e) { s = { error: e.message }; }

    if (!s.installed) {
        body.innerHTML = `<div class="empty"><i class="ph ph-shield-slash"></i>
          Tailscale is not installed on this box.<br>Run setup.sh or update.sh to install it.</div>`;
        return;
    }

    body.innerHTML = `
      <div class="card card-lg">
        <div class="health-head">
          <div style="min-width:0">
            <div class="health-title">${s.connected ? 'Connected' : 'Not connected'}</div>
            <div class="health-note">${escapeHtml(s.message || s.backend_state || '')}</div>
          </div>
          <button class="btn ${s.connected ? '' : 'btn-primary'}" id="ts-toggle" style="min-height:44px;flex:none">
            ${s.connected ? 'Disconnect' : 'Connect'}
          </button>
        </div>
      </div>

      ${s.self ? `
        <div class="list" style="margin-top:16px">
          ${infoRow('This device', s.self.name || s.self.hostname || '—', 'ph ph-desktop')}
          ${infoRow('Tailscale IP', (s.self.ips || [])[0] || s.self.ip || '—', 'ph ph-globe')}
          ${infoRow('Peers online', s.peer_count ?? '—', 'ph ph-users-three')}
          ${infoRow('MagicDNS', s.magic_dns ? 'On' : 'Off', 'ph ph-signpost')}
        </div>` : ''}

      ${sectionLabel('Auth key')}
      <div class="card">
        ${field('ts-key', 'Paste a Tailscale auth key to connect without a browser', { placeholder: 'tskey-auth-…' })}
        <button class="btn btn-block" id="ts-save-key" style="margin-top:10px">Save auth key</button>
      </div>`;

    $('#ts-toggle').addEventListener('click', async () => {
        const up = !s.connected;
        try {
            const r = await api(`/system/tailscale/${up ? 'up' : 'down'}`, { method: 'POST' });
            if (r.auth_url) {
                openSheet(`
                  <div class="kicker" style="margin-bottom:10px">Authorise this device</div>
                  <p style="font-size:14px;line-height:1.6;color:var(--text-70)">
                    Open this link on any signed-in device to add the Pi to your tailnet.</p>
                  <a class="btn btn-primary btn-block" href="${escapeHtml(r.auth_url)}" target="_blank" rel="noopener"
                     style="min-height:48px">Open Tailscale login</a>`);
            } else {
                toast(up ? 'Tailscale connecting…' : 'Tailscale disconnected', 'success');
                refreshSub();
            }
        } catch (e) { toast(e.message || 'Tailscale command failed', 'error'); }
    });

    $('#ts-save-key').addEventListener('click', async () => {
        const key = $('#ts-key').value.trim();
        if (!key) { toast('Paste an auth key first', 'warn'); return; }
        try {
            await api('/system/tailscale/set-auth-key', { method: 'POST', body: JSON.stringify({ auth_key: key }) });
            toast('Auth key saved', 'success');
            refreshSub();
        } catch (e) { toast(e.message || 'Could not save the key', 'error'); }
    });
}

/* ══════════════════════════════════════════════════════════════════════════
   Users
   ══════════════════════════════════════════════════════════════════════════ */

async function renderUsers(body) {
    const users = await api('/auth/users');
    const list = Array.isArray(users) ? users : (users.users || []);
    const me = S.profile?.user_id;

    body.innerHTML = `
      <div class="list">
        ${list.map(u => `
          <div class="list-row list-row-tall row-rule">
            <i class="ph ${u.is_admin ? 'ph-user-gear' : 'ph-user'} list-icon"></i>
            <div class="list-body">
              <div class="list-title">${escapeHtml(u.username)}${u.id === me ? ' · you' : ''}</div>
              <div class="list-sub">${u.is_admin ? 'Administrator' : 'Standard account'}</div>
            </div>
            ${u.id !== me ? `<button class="btn btn-icon btn-icon-plain" data-deluser="${u.id}"
                              data-username="${escapeHtml(u.username)}" aria-label="Delete user">
                              <i class="ph ph-trash"></i></button>` : ''}
          </div>`).join('')}
      </div>
      <button class="btn btn-primary btn-block" id="add-user" style="margin-top:20px;min-height:48px">
        <i class="ph ph-user-plus"></i>Add a user
      </button>`;

    $('#add-user').addEventListener('click', openAddUser);
}

function openAddUser() {
    openSheet(`
      <div class="kicker" style="margin-bottom:12px">New user</div>
      <div style="display:flex;flex-direction:column;gap:10px">
        <input class="input input-plain" id="nu-name" placeholder="Username" autocomplete="off" autocapitalize="none">
        <input class="input input-plain" id="nu-pass" type="password" placeholder="Password" autocomplete="new-password">
        <label class="list-row" style="padding:6px 0;cursor:pointer">
          <i class="ph ph-user-gear list-icon"></i>
          <div class="list-body"><div class="list-title">Administrator</div>
            <div class="list-sub">Full access, including these settings</div></div>
          <input type="checkbox" id="nu-admin" style="width:20px;height:20px;accent-color:var(--color-accent)">
        </label>
        <div id="nu-status" style="font-size:12.5px;color:var(--text-45);min-height:18px"></div>
        <button class="btn btn-primary btn-block" id="nu-save" style="min-height:48px">Create user</button>
      </div>`);

    $('#nu-save').addEventListener('click', async () => {
        const username = $('#nu-name').value.trim();
        const password = $('#nu-pass').value;
        const is_admin = $('#nu-admin').checked;
        const st = $('#nu-status');
        if (!username || !password) { st.textContent = 'Username and password are both required.'; return; }
        st.textContent = 'Creating…';
        try {
            await api('/auth/users', { method: 'POST', body: JSON.stringify({ username, password, is_admin }) });
            closeSheet();
            toast(`User ${username} created`, 'success');
            refreshSub();
        } catch (e) { st.textContent = e.message || 'Could not create that user.'; }
    });
}

async function deleteUser(id, username) {
    if (!await confirmDialog('Delete this user?',
        `${username} loses access immediately and their sessions are revoked. Their watch history is removed.`,
        'Delete')) return;
    try {
        await api(`/auth/users/${encodeURIComponent(id)}`, { method: 'DELETE' });
        toast(`${username} deleted`, 'success');
        refreshSub();
    } catch (e) { toast(e.message || 'Could not delete that user', 'error'); }
}

/* ══════════════════════════════════════════════════════════════════════════
   Storage & drives
   ══════════════════════════════════════════════════════════════════════════ */

async function renderStorage(body) {
    let info = {}, drives = {};
    try { info = await api('/system/storage/info'); } catch {}
    try { drives = await api('/system/drives'); } catch {}

    const disks = info.disks || [];
    const blocks = (drives.blockdevices || []).filter(d => d.type === 'part' || d.type === 'disk');

    body.innerHTML = `
      <div class="card card-lg">
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:9px">
          <span>Total across mounted volumes</span>
          <span style="color:var(--color-accent)">${escapeHtml(fmtSize(info.used))} used</span>
        </div>
        <div class="bar bar-lg"><span style="width:${Math.round(info.percentage || 0)}%"></span></div>
        <div class="stat-note">${escapeHtml(fmtSize(info.total))} total</div>
      </div>

      ${sectionLabel('Mounted')}
      <div class="list">
        ${disks.length ? disks.map(d => `
          <div class="list-row list-row-tall row-rule">
            <i class="ph ph-hard-drive list-icon"></i>
            <div class="list-body">
              <div class="list-title">${escapeHtml(d.mountpoint || d.device || 'Volume')}</div>
              <div class="list-sub">${escapeHtml(fmtSize(d.free))} free of ${escapeHtml(fmtSize(d.total))}${d.fstype ? ` · ${escapeHtml(d.fstype)}` : ''}</div>
            </div>
            ${d.mountpoint && d.mountpoint.startsWith('/media') ? `
              <button class="btn btn-icon btn-icon-plain" data-unmount="${escapeHtml(d.mountpoint)}" aria-label="Eject">
                <i class="ph ph-eject"></i></button>` : ''}
          </div>`).join('') : '<div class="empty">No volumes reported.</div>'}
      </div>

      ${blocks.length ? `
        ${sectionLabel('All block devices')}
        <div class="list">
          ${blocks.map(b => `
            <div class="list-row list-row-tall row-rule">
              <i class="ph ${b.type === 'disk' ? 'ph-hard-drives' : 'ph-database'} list-icon"></i>
              <div class="list-body">
                <div class="list-title">${escapeHtml(b.name)}${b.label ? ` · ${escapeHtml(b.label)}` : ''}</div>
                <div class="list-sub">${escapeHtml(b.size || '')}${b.fstype ? ` · ${escapeHtml(b.fstype)}` : ''}${b.mountpoint ? ` · mounted at ${escapeHtml(b.mountpoint)}` : ' · not mounted'}</div>
              </div>
              ${!b.mountpoint && b.type === 'part' ? `
                <button class="btn" data-mount="${escapeHtml(b.name)}" style="min-height:38px;padding:0 12px;font-size:12px">Mount</button>` : ''}
            </div>`).join('')}
        </div>` : ''}

      <div class="facts-note" style="margin-top:18px;text-align:left">
        USB drives are mounted under <strong>/media</strong> and indexed into the
        library automatically. Eject before unplugging.
      </div>`;
}

async function mountDrive(name) {
    const device = name.startsWith('/dev/') ? name : `/dev/${name}`;
    // The server rejects absolute mount points — it mounts under
    // data/external/<name> itself and wants just the bare name.
    const point = name.replace(/^\/dev\//, '');
    try {
        await api(`/system/mount?device=${encodeURIComponent(device)}&mount_point=${encodeURIComponent(point)}`, { method: 'POST' });
        toast(`Mounted ${point}`, 'success');
        refreshSub();
    } catch (e) { toast(e.message || 'Could not mount that device', 'error'); }
}

async function unmountDrive(target) {
    if (!await confirmDialog('Eject this volume?',
        `${target} is unmounted so it can be unplugged safely. Media on it disappears from the library until it is remounted.`,
        'Eject')) return;
    try {
        await api(`/system/unmount?target=${encodeURIComponent(target)}`, { method: 'POST' });
        toast('Ejected — safe to unplug', 'success');
        refreshSub();
    } catch (e) { toast(e.message || 'Could not eject', 'error'); }
}

/* ══════════════════════════════════════════════════════════════════════════
   Backup & restore
   ══════════════════════════════════════════════════════════════════════════ */

async function renderBackup(body) {
    body.innerHTML = `
      <div class="card card-lg">
        <div class="health-title">Download a backup</div>
        <div class="health-note" style="margin-bottom:12px">
          Database, mount configuration and environment — everything except the media itself.
        </div>
        <a class="btn btn-primary btn-block" id="backup-dl" style="min-height:48px"
           href="${escapeHtml(`${API}/system/backup?token=${encodeURIComponent(token() || '')}`)}">
          <i class="ph ph-download-simple"></i>Download backup
        </a>
      </div>

      ${sectionLabel('Restore')}
      <div class="card">
        <div class="health-note" style="margin-bottom:12px">
          Restoring replaces the current database. The existing one is copied to
          <strong>nomad.db.bak</strong> first, and the server needs a restart afterwards.
        </div>
        <input type="file" id="restore-file" accept=".zip" style="display:none">
        <button class="btn btn-block" id="restore-pick" style="min-height:48px">
          <i class="ph ph-upload-simple"></i>Choose a backup file
        </button>
        <div id="restore-status" style="font-size:12.5px;color:var(--text-45);margin-top:10px;min-height:18px"></div>
      </div>`;

    const file = $('#restore-file');
    $('#restore-pick').addEventListener('click', () => file.click());
    file.addEventListener('change', async () => {
        const f = file.files?.[0];
        if (!f) return;
        if (!await confirmDialog('Restore from this backup?',
            `${f.name} replaces the current database, users and settings. This cannot be undone from the UI.`,
            'Restore')) { file.value = ''; return; }
        const st = $('#restore-status');
        st.textContent = 'Uploading…';
        try {
            const fd = new FormData();
            fd.append('file', f);
            const res = await fetch(`${API}/system/restore`, { method: 'POST', headers: authHeaders(), body: fd });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Restore failed');
            st.textContent = data.message || 'Restored. Restart the server to apply.';
            toast('Backup restored — restart to apply', 'success', 8000);
        } catch (e) {
            st.textContent = e.message || 'Restore failed.';
        } finally { file.value = ''; }
    });
}

/* ══════════════════════════════════════════════════════════════════════════
   API keys — metadata and debrid providers
   ══════════════════════════════════════════════════════════════════════════ */

async function renderKeys(body) {
    let omdb = {}, provider = 'rd';
    try { omdb = await api('/system/settings/omdb'); } catch {}
    try { const p = await api('/debrid/provider'); provider = p.provider || p.value || 'rd'; } catch {}

    const providers = [
        { key: 'rd', label: 'Real-Debrid', endpoint: '/debrid/rd/key' },
        { key: 'ad', label: 'AllDebrid',   endpoint: '/debrid/ad/key' },
        { key: 'tb', label: 'TorBox',      endpoint: '/debrid/tb/key' },
    ];

    body.innerHTML = `
      ${sectionLabel('Metadata')}
      <div class="card">
        ${field('k-omdb', 'OMDb API key — posters, plots and ratings', {
            placeholder: omdb.key ? `${String(omdb.key).slice(0, 4)}••••` : 'Paste your key' })}
        <button class="btn btn-block" id="k-omdb-save" style="margin-top:10px">Save OMDb key</button>
      </div>

      <div class="card" style="margin-top:12px">
        ${field('k-osub', 'OpenSubtitles API key — subtitle search', { placeholder: 'Paste your key' })}
        <button class="btn btn-block" id="k-osub-save" style="margin-top:10px">Save OpenSubtitles key</button>
      </div>

      ${sectionLabel('Debrid provider')}
      <div class="chip-equal" style="margin-bottom:12px">
        ${providers.map(p => `<button class="chip${p.key === provider ? ' active' : ''}" data-provider="${p.key}">${escapeHtml(p.label)}</button>`).join('')}
      </div>
      ${providers.map(p => `
        <div class="card" style="margin-bottom:10px">
          ${field(`k-${p.key}`, `${p.label} API key`, { placeholder: 'Paste your key' })}
          <button class="btn btn-block" data-savekey="${p.key}" data-endpoint="${escapeHtml(p.endpoint)}"
                  style="margin-top:10px">Save ${escapeHtml(p.label)} key</button>
        </div>`).join('')}

      <div class="facts-note" style="margin-top:14px;text-align:left">
        Keys are stored on the Pi and never leave it except to the service they belong to.
      </div>`;

    $('#k-omdb-save').addEventListener('click', async () => {
        const key = $('#k-omdb').value.trim();
        if (!key) return toast('Paste a key first', 'warn');
        try { await api('/system/settings/omdb', { method: 'POST', body: JSON.stringify({ key }) });
              toast('OMDb key saved', 'success'); $('#k-omdb').value = ''; refreshSub(); }
        catch (e) { toast(e.message || 'Could not save', 'error'); }
    });
    $('#k-osub-save').addEventListener('click', async () => {
        const key = $('#k-osub').value.trim();
        if (!key) return toast('Paste a key first', 'warn');
        try { await api('/system/settings', { method: 'POST', body: JSON.stringify({ key: 'opensubtitles_key', value: key }) });
              toast('OpenSubtitles key saved', 'success'); $('#k-osub').value = ''; }
        catch (e) { toast(e.message || 'Could not save', 'error'); }
    });
}

async function saveDebridKey(which, endpoint) {
    const input = $(`#k-${which}`);
    const key = input?.value.trim();
    if (!key) return toast('Paste a key first', 'warn');
    try {
        await api(endpoint, { method: 'POST', body: JSON.stringify({ key }) });
        toast('Key saved', 'success');
        input.value = '';
    } catch (e) { toast(e.message || 'Could not save that key', 'error'); }
}

async function setProvider(p) {
    try {
        await api('/debrid/provider', { method: 'POST', body: JSON.stringify({ provider: p }) });
        toast('Provider switched', 'success');
        refreshSub();
    } catch (e) { toast(e.message || 'Could not switch provider', 'error'); }
}

/* ══════════════════════════════════════════════════════════════════════════
   Upload from phone
   ══════════════════════════════════════════════════════════════════════════ */

async function renderUpload(body) {
    const cats = ['movies', 'shows', 'music', 'books', 'gallery', 'files'];
    body.innerHTML = `
      <div class="kicker" style="margin-bottom:10px">Destination</div>
      <div class="chip-scroller pv" style="padding:0 0 14px" id="up-cats">
        ${cats.map((c, i) => `<button class="chip${i === 0 ? ' active' : ''}" data-upcat="${c}">${escapeHtml(c[0].toUpperCase() + c.slice(1))}</button>`).join('')}
      </div>

      <input type="file" id="up-file" multiple style="display:none">
      <button class="btn btn-primary btn-block" id="up-pick" style="min-height:52px">
        <i class="ph ph-upload-simple"></i>Choose files
      </button>
      <div class="facts-note" style="margin-top:10px;text-align:left">
        Photos, video, music or any file. Large files stream straight to disk —
        keep this screen open until each one finishes.
      </div>
      <div id="up-list" class="list" style="margin-top:18px;gap:10px"></div>`;

    let cat = 'movies';
    $('#up-cats').addEventListener('click', e => {
        const b = e.target.closest('[data-upcat]');
        if (!b) return;
        cat = b.dataset.upcat;
        $$('#up-cats .chip').forEach(c => c.classList.toggle('active', c === b));
    });

    const input = $('#up-file');
    $('#up-pick').addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
        Array.from(input.files || []).forEach(f => uploadOne(f, cat));
        input.value = '';
    });
}

function uploadOne(file, category) {
    const list = $('#up-list');
    const row = document.createElement('div');
    row.className = 'dl-card';
    row.innerHTML = `
      <div class="dl-top">
        <div style="min-width:0;flex:1">
          <div class="dl-title">${escapeHtml(file.name)}</div>
          <div class="dl-meta">${escapeHtml(fmtSize(file.size))} → /data/${escapeHtml(category)}</div>
        </div>
      </div>
      <div class="bar" style="margin-top:10px"><span style="width:0%"></span></div>
      <div class="dl-stats"><span class="pct">0%</span><span class="state">Starting…</span></div>`;
    list.prepend(row);

    const bar = row.querySelector('.bar > span');
    const pct = row.querySelector('.pct');
    const state = row.querySelector('.state');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/media/upload_stream/${encodeURIComponent(category)}?path=${encodeURIComponent(file.name)}`);
    const h = authHeaders();
    if (h.Authorization) xhr.setRequestHeader('Authorization', h.Authorization);
    xhr.setRequestHeader('x-file-path', file.name);
    xhr.upload.addEventListener('progress', e => {
        if (!e.lengthComputable) return;
        const p = Math.round((e.loaded / e.total) * 100);
        bar.style.width = `${p}%`;
        pct.textContent = `${p}%`;
        state.textContent = 'Uploading…';
    });
    xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
            bar.style.width = '100%'; pct.textContent = '100%';
            state.textContent = 'Done';
            toast(`${file.name} uploaded`, 'success', 3000);
        } else {
            state.textContent = `Failed (${xhr.status})`;
        }
    });
    xhr.addEventListener('error', () => { state.textContent = 'Failed'; });
    xhr.send(file);
}

/* ══════════════════════════════════════════════════════════════════════════
   Library maintenance — organize, duplicates, scan
   ══════════════════════════════════════════════════════════════════════════ */

async function renderOrganize(body) {
    body.innerHTML = `
      <div class="facts-note" style="text-align:left;margin-bottom:16px">
        Organising groups loose files into the standard
        <strong>Title (Year)/Title (Year).ext</strong> layout and can rename to
        match. Always preview first — the preview lists every move without
        touching a file.
      </div>

      ${['movies', 'shows'].map(kind => `
        <div class="card" style="margin-bottom:12px">
          <div class="health-title" style="margin-bottom:4px">${kind === 'movies' ? 'Movies' : 'Shows'}</div>
          <div class="health-note" style="margin-bottom:12px">
            ${kind === 'movies' ? 'Group films into their own folders.' : 'Group episodes into Season folders.'}
          </div>
          <div class="btn-row">
            <button class="btn" data-organize="${kind}" data-dry="1">Preview</button>
            <button class="btn btn-primary" data-organize="${kind}" data-dry="0">Apply</button>
          </div>
        </div>`).join('')}

      <div id="organize-out" style="margin-top:16px"></div>`;
}

async function runOrganize(kind, dry) {
    const out = $('#organize-out');
    if (!dry && !await confirmDialog(`Reorganise ${kind}?`,
        'Files are moved and renamed on disk. Run a preview first if you have not — this cannot be undone from the UI.',
        'Apply')) return;
    out.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
        const data = await api(`/media/organize/${kind}?dry_run=${dry ? 'true' : 'false'}`, { method: 'POST' });
        const moves = data.moves || data.planned || data.items || [];
        if (!moves.length) {
            out.innerHTML = `<div class="empty"><i class="ph ph-check-circle"></i>${escapeHtml(data.message || 'Nothing needed moving.')}</div>`;
            return;
        }
        out.innerHTML = `
          <div class="kicker" style="margin-bottom:10px">${moves.length} ${dry ? 'planned move' : 'move'}${moves.length === 1 ? '' : 's'}</div>
          <div class="list">
            ${moves.slice(0, 200).map(m => `
              <div class="list-row row-rule" style="align-items:flex-start">
                <i class="ph ph-arrow-elbow-down-right list-icon" style="margin-top:2px"></i>
                <div class="list-body">
                  <div class="list-title" style="white-space:normal">${escapeHtml(m.to || m.dest || m.new_path || '')}</div>
                  <div class="list-sub" style="white-space:normal">from ${escapeHtml(m.from || m.src || m.old_path || '')}</div>
                </div>
              </div>`).join('')}
          </div>
          ${moves.length > 200 ? `<div class="facts-note" style="margin-top:10px">…and ${moves.length - 200} more.</div>` : ''}`;
        if (!dry) toast('Library reorganised', 'success');
    } catch (e) {
        out.innerHTML = `<div class="empty"><i class="ph ph-warning-circle"></i>${escapeHtml(e.message || 'Organise failed')}</div>`;
    }
}

async function renderDuplicates(body) {
    const data = await api('/media/duplicates');
    const files = data.file_duplicates || [];
    const content = data.content_duplicates || [];
    const total = files.length + content.length;

    if (!total) {
        body.innerHTML = `<div class="empty"><i class="ph ph-check-circle"></i>No duplicates found.</div>`;
        return;
    }

    const group = (d, kind) => `
      <div class="card" style="margin-bottom:12px">
        <div class="dl-title">${escapeHtml(d.name || d.title || 'Unknown')}</div>
        <div class="dl-meta">${kind === 'file'
            ? `${escapeHtml(fmtSize(d.size))} · ${d.count} copies`
            : `IMDb ${escapeHtml(d.imdb_id || '—')} · ${d.count} copies`}</div>
        <div class="list" style="margin-top:8px">
          ${(d.paths || []).map((p, i) => `
            <div class="list-row" style="padding:6px 0">
              <i class="ph ${i === 0 ? 'ph-check-circle' : 'ph-x-circle'} list-icon"
                 style="color:${i === 0 ? 'var(--color-accent)' : 'var(--text-30)'}"></i>
              <div class="list-body"><div class="list-sub" style="white-space:normal">${escapeHtml(p)}</div></div>
            </div>`).join('')}
        </div>
      </div>`;

    body.innerHTML = `
      <div class="facts-note" style="text-align:left;margin-bottom:16px">
        The copy marked with a tick is kept; the rest are removed if you run the fix.
      </div>
      ${files.length ? `${sectionLabel(`Identical files (${files.length})`)}${files.map(d => group(d, 'file')).join('')}` : ''}
      ${content.length ? `${sectionLabel(`Same title (${content.length})`)}${content.map(d => group(d, 'content')).join('')}` : ''}
      <button class="btn btn-primary btn-block" id="fix-dupes" style="margin-top:18px;min-height:48px">
        <i class="ph ph-broom"></i>Remove ${total} duplicate group${total === 1 ? '' : 's'}
      </button>`;

    $('#fix-dupes').addEventListener('click', async () => {
        if (!await confirmDialog('Remove duplicates?',
            'The extra copies are deleted from disk. The first copy in each group is kept. This cannot be undone.',
            'Remove')) return;
        try {
            const r = await api('/media/fix_duplicates', { method: 'POST' });
            toast(r.message || 'Duplicate cleanup started', 'success');
            refreshSub();
        } catch (e) { toast(e.message || 'Cleanup failed', 'error'); }
    });
}

/* ══════════════════════════════════════════════════════════════════════════
   Logs
   ══════════════════════════════════════════════════════════════════════════ */

async function renderLogs(body) {
    const data = await api('/system/logs/all?lines=200');
    const lines = data.logs || [];
    body.innerHTML = lines.length
        ? `<pre class="logbox">${escapeHtml(lines.join('\n'))}</pre>`
        : `<div class="empty"><i class="ph ph-file-text"></i>No logs available.</div>`;
}

/* ══════════════════════════════════════════════════════════════════════════
   Delegated admin events
   ══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-admin],[data-wifi],[data-deluser],[data-mount],[data-unmount],[data-savekey],[data-provider],[data-organize]');
    if (!t) return;

    if (t.dataset.admin) {
        const screens = {
            wifi:       ['Wi-Fi', renderWifi, 'Join a network or run the hotspot'],
            tailscale:  ['Tailscale', renderTailscale, 'Reach this box from anywhere'],
            users:      ['Users', renderUsers, 'Who can sign in'],
            storage:    ['Storage & drives', renderStorage, 'Volumes, USB disks and free space'],
            backup:     ['Backup & restore', renderBackup, 'Database, mounts and settings'],
            keys:       ['API keys', renderKeys, 'Metadata and debrid providers'],
            upload:     ['Upload from phone', renderUpload, 'Send files to the Pi'],
            organize:   ['Organize media', renderOrganize, 'Tidy folders and filenames'],
            duplicates: ['Find duplicates', renderDuplicates, 'By name, size or IMDb id'],
            logs:       ['Server logs', renderLogs, 'Recent journal output'],
        };
        const s = screens[t.dataset.admin];
        if (s) openSub(s[0], s[1], { desc: s[2] });
        return;
    }

    if (t.dataset.wifi)     { openWifiJoin(Number(t.dataset.wifi)); return; }
    if (t.dataset.deluser)  { deleteUser(t.dataset.deluser, t.dataset.username || 'This user'); return; }
    if (t.dataset.mount)    { mountDrive(t.dataset.mount); return; }
    if (t.dataset.unmount)  { unmountDrive(t.dataset.unmount); return; }
    if (t.dataset.savekey)  { saveDebridKey(t.dataset.savekey, t.dataset.endpoint); return; }
    if (t.dataset.provider) { setProvider(t.dataset.provider); return; }
    if (t.dataset.organize) { runOrganize(t.dataset.organize, t.dataset.dry === '1'); return; }
});
