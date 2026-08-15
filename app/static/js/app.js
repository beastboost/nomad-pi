/* Nomad Pi app compatibility bootstrap. */
(() => {
    const version = '2.0.0-playback-core';
    document.write(`<script src="js/app_legacy.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/playback-core.js?v=${encodeURIComponent(version)}"><\/script>`);
})();
