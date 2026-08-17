/* Keep the profile Photos experience separate from the generic file-library chrome. */
(() => {
    if (typeof loadLibrary !== 'function') return;

    const previous = loadLibrary;
    function syncChrome() {
        let photos = false;
        try { photos = typeof S !== 'undefined' && S.lib === 'gallery'; } catch {}
        document.querySelector('#lib-sort-btn')?.classList.toggle('hidden', photos);
        const title = document.querySelector('#screen-library .screen-head h1');
        if (title) title.textContent = photos ? 'Photos' : 'Library';
    }

    loadLibrary = function photoChromeLoadLibrary(...args) {
        syncChrome();
        return previous.apply(this, args);
    };

    document.addEventListener('click', event => {
        let photos = false;
        try { photos = typeof S !== 'undefined' && S.lib === 'gallery'; } catch {}
        if (!photos || !event.target.closest('#lib-sort-btn')) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    }, true);

    setTimeout(syncChrome, 0);
})();
