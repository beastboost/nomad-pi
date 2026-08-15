/* Carry the active Nocturne profile into backend policy enforcement. */
(() => {
    function profileId() {
        const value = (typeof S !== 'undefined' && S?.profile?.id) ||
                      (typeof S !== 'undefined' && S?.profile?.profile_id) ||
                      null;
        const parsed = Number(value);
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    }
    window.nomadProfileId = profileId;

    if (typeof api === 'function') {
        const previousApi = api;
        api = function profileAwareApi(path, opts = {}) {
            const pid = profileId();
            if (!pid) return previousApi(path, opts);
            return previousApi(path, {
                ...opts,
                headers: {
                    ...(opts.headers || {}),
                    'X-Nomad-Profile-ID': String(pid),
                },
            });
        };
    }

    if (typeof streamUrl === 'function') {
        const previousStreamUrl = streamUrl;
        streamUrl = function profileAwareStreamUrl(path, extra = '') {
            const url = previousStreamUrl(path, extra);
            const pid = profileId();
            if (!pid) return url;
            const separator = url.includes('?') ? '&' : '?';
            return `${url}${separator}profile_id=${encodeURIComponent(pid)}`;
        };
    }
})();
