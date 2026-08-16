/* Make universal search a first-class Home action without duplicating screens. */
(() => {
    if (typeof loadHome !== 'function' || typeof goTab !== 'function') return;

    function injectFindAnything() {
        const grid = document.querySelector('[data-screen="home"] .quick-grid');
        if (!grid || grid.querySelector('[data-universal-find]')) return;
        const button = document.createElement('button');
        button.className = 'quick universal-find-quick';
        button.type = 'button';
        button.dataset.universalFind = '1';
        button.innerHTML = '<i class="ph ph-magnifying-glass"></i>Find anything';
        grid.prepend(button);
    }

    const previousLoadHome = loadHome;
    loadHome = async function universalHomeLoad(...args) {
        const result = await previousLoadHome(...args);
        injectFindAnything();
        return result;
    };

    document.addEventListener('click', event => {
        const button = event.target.closest('[data-universal-find]');
        if (!button) return;
        event.preventDefault();
        S.dl = 'find';
        goTab('downloads');
        requestAnimationFrame(() => document.querySelector('#debrid-query')?.focus());
    });

    setTimeout(injectFindAnything, 0);
})();
