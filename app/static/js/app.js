// === TorBox Frontend Support (added to complete full integration) ===

async function saveTBKey() {
    const input = document.getElementById('tb-api-key-input');
    const key = input ? input.value.trim() : '';
    if (!key) { showToast('Please enter a TorBox API key', 'warning'); return; }

    try {
        const res = await fetch(`${API_BASE}/debrid/settings/tb-key`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to save TorBox key');
        }
        showToast('TorBox connected!', 'success');
        _debridProvider = 'tb';
        await debridSwitchProvider('tb');
    } catch (e) { showToast(e.message, 'error'); }
}

// Extend debridSwitchProvider to handle TorBox
if (typeof debridSwitchProvider === 'function') {
    const originalDebridSwitch = debridSwitchProvider;
    window.debridSwitchProvider = async function(provider) {
        _debridProvider = provider;
        _updateProviderTabs();
        
        // Show correct setup panel
        const setupRd = document.getElementById('debrid-setup');
        const setupAd = document.getElementById('debrid-setup-ad');
        const setupTb = document.getElementById('debrid-setup-tb');
        
        if (setupRd) setupRd.style.display = provider === 'rd' ? 'block' : 'none';
        if (setupAd) setupAd.style.display = provider === 'ad' ? 'block' : 'none';
        if (setupTb) setupTb.style.display = provider === 'tb' ? 'block' : 'none';
        
        try {
            await fetch(`${API_BASE}/debrid/settings/provider?provider=${provider}`, {
                method: 'POST', headers: getAuthHeaders(),
            });
        } catch (e) { /* ignore */ }
        await _checkDebridKey();
    };
}

// Extend _checkDebridKey to handle TorBox
if (typeof _checkDebridKey === 'function') {
    const originalCheck = _checkDebridKey;
    window._checkDebridKey = async function() {
        const setupRd = document.getElementById('debrid-setup');
        const setupAd = document.getElementById('debrid-setup-ad');
        const setupTb = document.getElementById('debrid-setup-tb');
        const main = document.getElementById('debrid-main');

        if (setupRd) setupRd.style.display = 'none';
        if (setupAd) setupAd.style.display = 'none';
        if (setupTb) setupTb.style.display = 'none';

        const endpoint = _debridProvider === 'tb' ? 'settings/tb-key' : 
                       _debridProvider === 'ad' ? 'settings/ad-key' : 'settings/key';
        
        try {
            const res = await fetch(`${API_BASE}/debrid/${endpoint}`, { headers: getAuthHeaders() });
            if (!res.ok) { 
                if (setupRd) setupRd.style.display = _debridProvider === 'rd' ? 'block' : 'none';
                if (setupAd) setupAd.style.display = _debridProvider === 'ad' ? 'block' : 'none';
                if (setupTb) setupTb.style.display = _debridProvider === 'tb' ? 'block' : 'none';
                return; 
            }
            const data = await res.json();

            if (data.configured && (data.user || data.valid !== false)) {
                if (main) main.style.display = 'block';
            } else {
                if (setupRd) setupRd.style.display = _debridProvider === 'rd' ? 'block' : 'none';
                if (setupAd) setupAd.style.display = _debridProvider === 'ad' ? 'block' : 'none';
                if (setupTb) setupTb.style.display = _debridProvider === 'tb' ? 'block' : 'none';
            }
        } catch (e) {
            if (setupRd) setupRd.style.display = _debridProvider === 'rd' ? 'block' : 'none';
            if (setupAd) setupAd.style.display = _debridProvider === 'ad' ? 'block' : 'none';
            if (setupTb) setupTb.style.display = _debridProvider === 'tb' ? 'block' : 'none';
        }
    };
}

console.log("TorBox frontend support loaded");