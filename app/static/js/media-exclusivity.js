/* Keep Nomad to one foreground media player at a time. */
(() => {
    if (typeof playVideo === 'function') {
        const previousPlayVideo = playVideo;
        playVideo = function exclusiveVideo(path, at = 0) {
            if (kindOf(path) === 'video' && typeof stopAudio === 'function' && S?.audio?.playing) {
                stopAudio();
            }
            return previousPlayVideo(path, at);
        };
    }

    if (typeof playAudio === 'function') {
        const previousPlayAudio = playAudio;
        playAudio = function exclusiveAudio(path) {
            const video = typeof V !== 'undefined' ? V.el : null;
            if (video && !video.paused && typeof stopVideo === 'function') stopVideo();
            return previousPlayAudio(path);
        };
    }
})();
