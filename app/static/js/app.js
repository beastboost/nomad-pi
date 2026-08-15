/* Nomad Pi app compatibility bootstrap. */
(() => {
    const version = '2.0.0-playback-core';
    document.write(`<script src="js/app_legacy.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/playback-core.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/replacement-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/track-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/subtitle-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/quality-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/device-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/music2-player.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/music2-fallback.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/media-exclusivity.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/stream-keep-control.js?v=${encodeURIComponent(version)}"><\/script>`);
})();
