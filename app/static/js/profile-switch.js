/* Nomad Pi household profiles and optional PIN-gated switching. */
(() => {
    if (typeof api !== 'function' || typeof openSheet !== 'function') return;

    const HP = { profiles: [], current: null, loading: false };
    window.NomadHouseholdProfiles = HP;

    function profileLabel(profile) {
        return profile?.name || 'Profile';
    }

    function applyProfile(profile, { reload = true } = {}) {
        if (!profile) return;
        HP.current = profile;
        S.profile = profile;
        renderButton();
        if (!reload) return;
        try {
            if (S.screen === 'player' && typeof stopVideo === 'function') stopVideo();
            if (S.screen === 'reader' && typeof closeReader === 'function') closeReader();
        } catch {}
        if (S.tab === 'library') loadLibrary();
        else if (S.tab === 'downloads') loadDownloads();
        else if (S.tab === 'server') loadServer();
        else loadHome();
    }

    function ensureButton() {
        let button = $('#nomad-profile-switcher');
        if (button) return button;
        const head = $('#screen-home .head-row');
        const search = head?.querySelector('[data-go="search"]');
        if (!head || !search) return null;
        button = document.createElement('button');
        button.className = 'btn';
        button.id = 'nomad-profile-switcher';
        button.style.cssText = 'max-width:150px;min-width:0';
        button.setAttribute('aria-label', 'Switch profile');
        head.insertBefore(button, search);
        return button;
    }

    function renderButton() {
        const button = ensureButton();
        if (!button) return;
        const profile = HP.current || S.profile;
        button.innerHTML = `<i class="ph ph-user-circle"></i><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(profileLabel(profile))}</span>`;
    }

    async function refreshProfiles({ bindDefault = true } = {}) {
        if (HP.loading || !token()) return HP;
        HP.loading = true;
        try {
            const data = await api('/playback/profiles');
            HP.profiles = data.profiles || [];
            HP.current = data.current || HP.profiles[0] || null;
            if (HP.current && bindDefault) applyProfile(HP.current, { reload: false });
            renderButton();
        } finally {
            HP.loading = false;
        }
        return HP;
    }

    function profileSubtitle(profile) {
        const policy = profile.parental_controls || {};
        const bits = [];
        if (profile.pin_required) bits.push('PIN locked');
        if (policy.enabled) {
            if (policy.max_age != null) bits.push(`up to age ${policy.max_age}`);
            if (policy.allow_debrid === false) bits.push('remote off');
            if (!bits.length) bits.push('restricted');
        }
        if (profile.is_default) bits.push('default');
        return bits.join(' · ') || 'Household profile';
    }

    async function openProfiles() {
        try { await refreshProfiles(); }
        catch (err) { toast(err.message || 'Could not load profiles', 'error'); return; }
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Who's watching?</div>
          <div class="list-sub" style="margin-bottom:12px">Profile restrictions are enforced by the server for this login session.</div>
          <div class="list">
            ${HP.profiles.map(profile => `
              <button class="sheet-option row-rule" data-profile-switch="${profile.id}">
                <span style="text-align:left;min-width:0;flex:1">
                  <span style="display:block">${escapeHtml(profile.name)}${HP.current?.id === profile.id ? ' ✓' : ''}</span>
                  <span class="list-sub">${escapeHtml(profileSubtitle(profile))}</span>
                </span>
                <i class="ph ${profile.pin_required ? 'ph-lock-key' : 'ph-user-circle'}"></i>
              </button>`).join('')}
          </div>
          <div class="btn-row" style="margin-top:14px">
            <button class="btn" data-profile-add="1"><i class="ph ph-user-plus"></i>Add profile</button>
            ${HP.current ? `<button class="btn" data-profile-pin="${HP.current.id}"><i class="ph ph-key"></i>PIN</button>` : ''}
          </div>`);
    }

    function openPinPrompt(profile) {
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Unlock ${escapeHtml(profile.name)}</div>
          <div class="list-sub" style="margin-bottom:12px">Enter this profile's PIN.</div>
          <input id="nomad-profile-pin-input" class="input input-plain" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="off" placeholder="PIN">
          <button class="btn btn-primary btn-block" id="nomad-profile-pin-submit" style="margin-top:12px">Switch profile</button>`);
        const input = $('#nomad-profile-pin-input');
        setTimeout(() => input?.focus(), 50);
        const submit = async () => {
            const pin = input?.value || '';
            try {
                const data = await api('/playback/profiles/switch', {
                    method: 'POST', body: JSON.stringify({ profile_id: profile.id, pin }),
                });
                closeSheet();
                applyProfile(data.profile);
                toast(`Switched to ${data.profile.name}`, 'success', 2200);
            } catch (err) {
                toast(err.message || 'Could not unlock profile', 'error', 4200);
                if (input) { input.value = ''; input.focus(); }
            }
        };
        $('#nomad-profile-pin-submit')?.addEventListener('click', submit, { once: true });
        input?.addEventListener('keydown', event => { if (event.key === 'Enter') submit(); });
    }

    async function switchProfile(profileId) {
        const profile = HP.profiles.find(item => Number(item.id) === Number(profileId));
        if (!profile || HP.current?.id === profile.id) { closeSheet(); return; }
        if (profile.pin_required) { openPinPrompt(profile); return; }
        try {
            const data = await api('/playback/profiles/switch', {
                method: 'POST', body: JSON.stringify({ profile_id: profile.id }),
            });
            closeSheet();
            applyProfile(data.profile);
            toast(`Switched to ${data.profile.name}`, 'success', 2200);
        } catch (err) {
            toast(err.message || 'Could not switch profile', 'error', 4500);
        }
    }

    function openAddProfile() {
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">Add household profile</div>
          <input id="profile-new-name" class="input input-plain" maxlength="100" placeholder="Profile name">
          <label class="list-sub" for="profile-new-age" style="display:block;margin:12px 0 5px">Content age limit</label>
          <select id="profile-new-age" class="input input-plain">
            <option value="">No restriction</option>
            <option value="8">PG / age 8</option>
            <option value="12">Age 12</option>
            <option value="15">Age 15</option>
            <option value="18">Age 18</option>
          </select>
          <div class="facts-note" style="text-align:left;margin:10px 0">Restricted profiles also disable debrid acquisition, downloads, offline preparation, deletion and Library Health by default.</div>
          <input id="profile-owner-password" class="input input-plain" type="password" autocomplete="current-password" placeholder="Account password">
          <button class="btn btn-primary btn-block" id="profile-new-save" style="margin-top:12px">Create profile</button>`);
        setTimeout(() => $('#profile-new-name')?.focus(), 50);
        $('#profile-new-save')?.addEventListener('click', async () => {
            const name = $('#profile-new-name')?.value.trim() || '';
            const password = $('#profile-owner-password')?.value || '';
            const ageRaw = $('#profile-new-age')?.value || '';
            if (!name || !password) { toast('Enter a profile name and account password.', 'warn'); return; }
            const age = ageRaw ? Number(ageRaw) : null;
            const parental = age == null ? {} : {
                enabled: true,
                max_age: age,
                block_unrated: true,
                allowed_libraries: ['movies','shows','music','books'],
                allow_debrid: false,
                allow_downloads: false,
                allow_offline_sync: false,
                allow_delete: false,
                allow_library_health: false,
            };
            try {
                await api('/playback/profiles', {
                    method: 'POST',
                    body: JSON.stringify({ name, account_password: password, parental_controls: parental }),
                });
                await refreshProfiles({ bindDefault: false });
                toast(`${name} created`, 'success', 2200);
                openProfiles();
            } catch (err) { toast(err.message || 'Could not create profile', 'error', 4500); }
        }, { once: true });
    }

    function openPinManager(profileId) {
        const profile = HP.profiles.find(item => Number(item.id) === Number(profileId));
        if (!profile) return;
        openSheet(`
          <div class="kicker" style="margin-bottom:6px">${profile.pin_required ? 'Change or clear' : 'Set'} profile PIN</div>
          <div class="list-sub" style="margin-bottom:12px">This controls switching into ${escapeHtml(profile.name)}. Account password is required to change it.</div>
          <input id="profile-pin-owner-password" class="input input-plain" type="password" autocomplete="current-password" placeholder="Account password">
          <input id="profile-pin-new" class="input input-plain" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="off" placeholder="${profile.pin_required ? 'New PIN — leave blank to clear' : '4–8 digit PIN'}" style="margin-top:8px">
          <button class="btn btn-primary btn-block" id="profile-pin-save" style="margin-top:12px">${profile.pin_required ? 'Update PIN' : 'Set PIN'}</button>`);
        $('#profile-pin-save')?.addEventListener('click', async () => {
            const password = $('#profile-pin-owner-password')?.value || '';
            const pin = $('#profile-pin-new')?.value || '';
            if (!password) { toast('Enter the account password.', 'warn'); return; }
            if (pin && !/^\d{4,8}$/.test(pin)) { toast('PIN must be 4–8 digits.', 'warn'); return; }
            try {
                await api(`/playback/profiles/${encodeURIComponent(profile.id)}/pin`, {
                    method: 'POST', body: JSON.stringify({ account_password: password, pin: pin || null }),
                });
                await refreshProfiles({ bindDefault: false });
                toast(pin ? 'Profile PIN updated' : 'Profile PIN cleared', 'success', 2200);
                openProfiles();
            } catch (err) { toast(err.message || 'Could not update profile PIN', 'error', 4500); }
        }, { once: true });
    }

    // Run after the legacy startApp has authenticated and rendered the shell.
    if (typeof startApp === 'function') {
        const previousStartApp = startApp;
        startApp = async function householdStartApp(...args) {
            const result = await previousStartApp.apply(this, args);
            try { await refreshProfiles(); } catch (err) { console.debug('[Nomad profiles]', err); }
            return result;
        };
    }

    document.addEventListener('click', event => {
        if (event.target.closest('#nomad-profile-switcher')) { event.preventDefault(); openProfiles(); return; }
        const item = event.target.closest('[data-profile-switch]');
        if (item) { event.preventDefault(); event.stopImmediatePropagation(); switchProfile(item.dataset.profileSwitch); return; }
        if (event.target.closest('[data-profile-add]')) { event.preventDefault(); event.stopImmediatePropagation(); openAddProfile(); return; }
        const pin = event.target.closest('[data-profile-pin]');
        if (pin) { event.preventDefault(); event.stopImmediatePropagation(); openPinManager(pin.dataset.profilePin); }
    }, true);

    // If the app has already started before this module evaluated, recover by
    // checking for a visible authenticated shell.
    setTimeout(() => {
        if (token() && !$('#app-shell')?.classList.contains('hidden')) refreshProfiles().catch(() => {});
    }, 250);
})();
