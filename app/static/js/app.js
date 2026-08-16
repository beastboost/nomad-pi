/* Nomad Pi app compatibility bootstrap. */
(() => {
    // setup.sh/update.sh stamp the app.js URL with ?v=<git commit>. Propagate
    // that exact deploy id to every child module instead of maintaining a
    // second hand-bumped version string that can leave Safari/PWA clients one
    // release behind on the first reload.
    const currentSrc = document.currentScript?.src || '';
    let version = 'dev';
    try {
        version = new URL(currentSrc, location.href).searchParams.get('v') || 'dev';
    } catch {}

    document.write(`<link rel="stylesheet" href="css/appliance-polish.css?v=${encodeURIComponent(version)}">`);
    document.write(`<script src="js/app_legacy.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/playback-core.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/runtime-ui-guard.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/debrid-lite.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/player-mobile-fix.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/direct-play-guard.js?v=${encodeURIComponent(version)}"><\/script>`);
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
    document.write(`<script src="js/universal-search.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/offline-control.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/download-live.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/library-health.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/media-actions.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/storage-failover.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/playback-health-ui.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/profile-context.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/profile-switch.js?v=${encodeURIComponent(version)}"><\/script>`);
    document.write(`<script src="js/reader-state.js?v=${encodeURIComponent(version)}"><\/script>`);
})();
