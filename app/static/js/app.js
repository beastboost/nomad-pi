/* Nomad Pi app compatibility bootstrap. */
(() => {
    const version = '2.0.4-radxa-hotfix';
    document.write(`<script src="js/app_legacy.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/playback-core.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/player-mobile-fix.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/replacement-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/track-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/subtitle-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/quality-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/device-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/watch-party.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/music2-player.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/music2-fallback.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/media-exclusivity.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/stream-keep-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/offline-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/download-live.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/library-health.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/storage-failover.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/playback-health-ui.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/profile-context.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/profile-switch.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/reader-state.js?v=${encodeURIComponent(version)}"><\/script>`);
})();
