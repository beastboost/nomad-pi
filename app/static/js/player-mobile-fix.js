/* Nomad Pi mobile player overlay compatibility fixes.
 * Keeps sheets/dialogs above the immersive player and makes touch input
 * reliably restore custom controls on iOS/Safari.
 */
(() => {
    const style = document.createElement('style');
    style.id = 'nomad-player-overlay-fix';
    style.textContent = `
      #sheet-scrim { z-index: 250 !important; position: fixed !important; }
      #sheet { z-index: 260 !important; position: fixed !important; }
      #dialog-wrap { z-index: 270 !important; position: fixed !important; }
      #toast-stack { z-index: 280 !important; position: fixed !important; }
      #now-playing-sheet { z-index: 240 !important; }
      #screen-player.chrome-hidden { cursor: auto !important; }
    `;
    document.head.appendChild(style);

    const wakeChrome = () => {
        const screen = document.querySelector('#screen-player');
        if (!screen || screen.classList.contains('hidden')) return;
        if (typeof showChrome === 'function') showChrome();
        else screen.classList.remove('chrome-hidden');
    };

    // Safari/iOS can consume taps as native video gestures without producing
    // the pointer sequence desktop browsers do. Listen to all useful paths.
    ['touchstart', 'click', 'pointerdown'].forEach(type => {
        document.addEventListener(type, event => {
            if (event.target?.closest?.('#screen-player')) wakeChrome();
        }, { passive: true, capture: true });
    });
})();