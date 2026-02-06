/**
 * Enhanced Music Player for Nomad Pi
 * Features: Album art, queue management, album/artist views, playlists
 */

class MusicPlayer {
    constructor() {
        this.queue = [];
        this.currentIndex = -1;
        this.shuffle = false;
        this.repeat = 'none'; // 'none', 'all', 'one'
        this.shuffleOrder = [];
        this.shufflePos = 0;
        this.audio = null;
        this.isInitialized = false;
        this.albums = new Map(); // Store albums with tracks
        this.artists = new Map(); // Store artists with albums
        this.currentView = 'tracks'; // 'tracks', 'albums', 'artists'

        this.initializePlayer();
    }

    initializePlayer() {
        if (this.isInitialized) return;

        this.audio = document.getElementById('global-audio');
        if (!this.audio) {
            console.error('Audio element not found');
            return;
        }

        // Set up audio event listeners
        this.audio.addEventListener('timeupdate', () => this.onTimeUpdate());
        this.audio.addEventListener('ended', () => this.onTrackEnded());
        this.audio.addEventListener('play', () => this.onPlay());
        this.audio.addEventListener('pause', () => this.onPause());
        this.audio.addEventListener('error', (e) => this.onError(e));

        // Set up control button listeners
        this.setupControls();

        this.isInitialized = true;
        console.log('Music player initialized');
    }

    setupControls() {
        const btnPlay = document.getElementById('player-play');
        const btnPrev = document.getElementById('player-prev');
        const btnNext = document.getElementById('player-next');
        const btnShuffle = document.getElementById('player-shuffle');
        const btnRepeat = document.getElementById('player-repeat');
        const btnQueue = document.getElementById('player-queue');
        const seek = document.getElementById('player-seek');
        const volume = document.getElementById('player-volume');
        const btnClose = document.getElementById('player-close');

        if (btnPlay) {
            btnPlay.addEventListener('click', () => this.togglePlay());
        }

        if (btnPrev) {
            btnPrev.addEventListener('click', () => this.playPrevious());
        }

        if (btnNext) {
            btnNext.addEventListener('click', () => this.playNext());
        }

        if (btnShuffle) {
            btnShuffle.addEventListener('click', () => this.toggleShuffle());
        }

        if (btnRepeat) {
            btnRepeat.addEventListener('click', () => this.cycleRepeat());
        }

        if (btnQueue) {
            btnQueue.addEventListener('click', () => this.toggleQueueView());
        }

        if (seek) {
            seek.addEventListener('input', (e) => this.seek(e.target.value));
        }

        if (volume) {
            volume.addEventListener('input', (e) => this.setVolume(e.target.value));
            // Restore saved volume
            const savedVolume = localStorage.getItem('nomadpi.musicVolume');
            if (savedVolume) {
                volume.value = savedVolume;
                this.audio.volume = parseFloat(savedVolume);
            }
        }

        if (btnClose) {
            btnClose.addEventListener('click', () => this.closePlayer());
        }
    }

    // Play a track at specific index
    playAt(index) {
        if (index < 0 || index >= this.queue.length) {
            console.error('Invalid track index:', index);
            return;
        }

        this.currentIndex = index;
        const track = this.queue[this.currentIndex];

        // Update UI
        this.updatePlayerUI(track);

        // Load and play audio
        const token = this.getCookie('auth_token');
        let streamUrl = `/api/media/stream?path=${encodeURIComponent(track.path)}`;
        if (token) {
            streamUrl += `&token=${token}`;
        }

        this.audio.pause();
        this.audio.src = streamUrl;
        this.audio.load();

        this.audio.play().then(() => {
            console.log('Playing:', track.name);
            this.updateProgress();
        }).catch(err => {
            console.error('Playback error:', err);
        });

        // Show player bar
        const bar = document.getElementById('player-bar');
        if (bar) {
            bar.classList.remove('hidden');
        }

        // Update Media Session API (for lockscreen controls)
        this.updateMediaSession(track);
    }

    // Start playing a queue from a specific index
    startQueue(tracks, startIndex = 0) {
        if (!tracks || tracks.length === 0) {
            console.error('Empty track list');
            return;
        }

        this.queue = tracks.filter(t => t && t.path);
        if (this.queue.length === 0) {
            console.error('No valid tracks in queue');
            return;
        }

        this.currentIndex = -1;

        if (this.shuffle) {
            this.generateShuffleOrder(startIndex);
            this.playAt(this.shuffleOrder[0]);
        } else {
            this.playAt(Math.max(0, Math.min(startIndex, this.queue.length - 1)));
        }

        // Save queue to localStorage for persistence
        this.saveQueue();
    }

    // Add tracks to queue
    addToQueue(tracks) {
        const newTracks = Array.isArray(tracks) ? tracks : [tracks];
        this.queue.push(...newTracks.filter(t => t && t.path));
        this.saveQueue();
        this.showToast(`Added ${newTracks.length} track(s) to queue`);
    }

    // Remove track from queue
    removeFromQueue(index) {
        if (index < 0 || index >= this.queue.length) return;

        this.queue.splice(index, 1);

        // Adjust current index if needed
        if (index < this.currentIndex) {
            this.currentIndex--;
        } else if (index === this.currentIndex) {
            // Currently playing track was removed
            if (this.queue.length === 0) {
                this.closePlayer();
                return;
            }
            // Play next track (which is now at the same index)
            this.playAt(Math.min(this.currentIndex, this.queue.length - 1));
        }

        this.saveQueue();
        this.updateQueueUI();
    }

    // Clear queue
    clearQueue() {
        this.queue = [];
        this.currentIndex = -1;
        this.closePlayer();
        this.saveQueue();
    }

    // Toggle play/pause
    togglePlay() {
        if (!this.audio.src) return;

        if (this.audio.paused) {
            this.audio.play().catch(err => console.error('Play error:', err));
        } else {
            this.audio.pause();
        }
    }

    // Play next track
    playNext() {
        if (this.queue.length === 0) return;

        let nextIndex;
        if (this.shuffle) {
            this.shufflePos = (this.shufflePos + 1) % this.shuffleOrder.length;
            nextIndex = this.shuffleOrder[this.shufflePos];
        } else {
            nextIndex = (this.currentIndex + 1) % this.queue.length;
        }

        this.playAt(nextIndex);
    }

    // Play previous track
    playPrevious() {
        if (this.queue.length === 0) return;

        // If more than 3 seconds into track, restart current track
        if (this.audio.currentTime > 3) {
            this.audio.currentTime = 0;
            return;
        }

        let prevIndex;
        if (this.shuffle) {
            this.shufflePos = (this.shufflePos - 1 + this.shuffleOrder.length) % this.shuffleOrder.length;
            prevIndex = this.shuffleOrder[this.shufflePos];
        } else {
            prevIndex = (this.currentIndex - 1 + this.queue.length) % this.queue.length;
        }

        this.playAt(prevIndex);
    }

    // Toggle shuffle
    toggleShuffle() {
        this.shuffle = !this.shuffle;

        const btnShuffle = document.getElementById('player-shuffle');
        if (btnShuffle) {
            btnShuffle.classList.toggle('active', this.shuffle);
        }

        if (this.shuffle && this.queue.length > 0) {
            this.generateShuffleOrder(this.currentIndex);
        }

        this.showToast(`Shuffle ${this.shuffle ? 'on' : 'off'}`);
    }

    // Cycle repeat mode
    cycleRepeat() {
        const modes = ['none', 'all', 'one'];
        const currentIdx = modes.indexOf(this.repeat);
        this.repeat = modes[(currentIdx + 1) % modes.length];

        const btnRepeat = document.getElementById('player-repeat');
        if (btnRepeat) {
            switch (this.repeat) {
                case 'none':
                    btnRepeat.textContent = '🔁';
                    btnRepeat.classList.remove('active');
                    break;
                case 'all':
                    btnRepeat.textContent = '🔁';
                    btnRepeat.classList.add('active');
                    break;
                case 'one':
                    btnRepeat.textContent = '🔂';
                    btnRepeat.classList.add('active');
                    break;
            }
        }

        this.showToast(`Repeat ${this.repeat}`);
    }

    // Generate shuffle order
    generateShuffleOrder(startIndex) {
        this.shuffleOrder = Array.from({ length: this.queue.length }, (_, i) => i);

        // Fisher-Yates shuffle
        for (let i = this.shuffleOrder.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [this.shuffleOrder[i], this.shuffleOrder[j]] = [this.shuffleOrder[j], this.shuffleOrder[i]];
        }

        // Ensure current track is first if provided
        if (startIndex >= 0) {
            const startPos = this.shuffleOrder.indexOf(startIndex);
            if (startPos > 0) {
                [this.shuffleOrder[0], this.shuffleOrder[startPos]] = [this.shuffleOrder[startPos], this.shuffleOrder[0]];
            }
        }

        this.shufflePos = 0;
    }

    // Seek to position (0-100)
    seek(value) {
        if (!this.audio.duration || !isFinite(this.audio.duration)) return;

        const time = (parseFloat(value) / 100) * this.audio.duration;
        this.audio.currentTime = time;
    }

    // Set volume (0-1)
    setVolume(value) {
        const vol = parseFloat(value);
        this.audio.volume = vol;
        localStorage.setItem('nomadpi.musicVolume', vol);
    }

    // Close player
    closePlayer() {
        this.audio.pause();
        this.audio.currentTime = 0;
        this.audio.src = '';

        const bar = document.getElementById('player-bar');
        if (bar) {
            bar.classList.add('hidden');
        }

        this.queue = [];
        this.currentIndex = -1;
        this.saveQueue();
    }

    // Event handlers
    onTimeUpdate() {
        // Update progress bar
        const seek = document.getElementById('player-seek');
        if (seek && isFinite(this.audio.duration) && this.audio.duration > 0) {
            seek.value = (this.audio.currentTime / this.audio.duration) * 100;
        }

        // Update time display
        const currentTimeEl = document.getElementById('player-time-current');
        const durationTimeEl = document.getElementById('player-time-duration');

        if (currentTimeEl) {
            currentTimeEl.textContent = this.formatTime(this.audio.currentTime);
        }

        if (durationTimeEl) {
            durationTimeEl.textContent = this.formatTime(this.audio.duration);
        }

        // Update progress tracking in backend
        if (this.queue[this.currentIndex]) {
            this.updateProgress();
        }
    }

    onTrackEnded() {
        if (this.repeat === 'one') {
            this.audio.currentTime = 0;
            this.audio.play();
        } else if (this.repeat === 'all' || this.currentIndex < this.queue.length - 1) {
            this.playNext();
        } else {
            // End of queue, no repeat
            this.closePlayer();
        }
    }

    onPlay() {
        const btnPlay = document.getElementById('player-play');
        if (btnPlay) {
            btnPlay.textContent = '⏸';
        }
    }

    onPause() {
        const btnPlay = document.getElementById('player-play');
        if (btnPlay) {
            btnPlay.textContent = '▶';
        }
    }

    onError(e) {
        console.error('Audio error:', this.audio.error);
        const titleEl = document.getElementById('player-title');
        if (titleEl) {
            titleEl.textContent = 'Error playing track';
        }

        let msg = 'Unknown playback error';
        if (this.audio.error) {
            switch (this.audio.error.code) {
                case 1: msg = 'Playback aborted'; break;
                case 2: msg = 'Network error'; break;
                case 3: msg = 'Decoding error'; break;
                case 4: msg = 'Format not supported'; break;
            }
        }

        this.showToast(msg, 'error');
    }

    // UI Updates
    updatePlayerUI(track) {
        const titleEl = document.getElementById('player-title');
        const albumArtEl = document.getElementById('player-album-art');

        if (titleEl) {
            const title = this.cleanTitle(track.name);
            const artist = track.artist || 'Unknown Artist';
            titleEl.textContent = `${artist} - ${title}`;
        }

        if (albumArtEl) {
            // Try to get album art from metadata or use placeholder
            const artUrl = track.albumArt || '/icons/music-placeholder.svg';
            albumArtEl.src = artUrl;
            albumArtEl.alt = track.album || 'Album Art';
        }

        // Update queue UI to highlight current track
        this.updateQueueUI();
    }

    updateQueueUI() {
        const queueContainer = document.getElementById('music-queue-list');
        if (!queueContainer) return;

        queueContainer.innerHTML = '';

        if (this.queue.length === 0) {
            queueContainer.innerHTML = '<div class="empty-queue">Queue is empty</div>';
            return;
        }

        this.queue.forEach((track, index) => {
            const item = document.createElement('div');
            item.className = 'queue-item';
            if (index === this.currentIndex) {
                item.classList.add('active');
            }

            item.innerHTML = `
                <div class="queue-item-drag">⋮⋮</div>
                <div class="queue-item-info" onclick="window.musicPlayer.playAt(${index})">
                    <div class="queue-item-title">${this.cleanTitle(track.name)}</div>
                    <div class="queue-item-artist">${track.artist || 'Unknown Artist'}</div>
                </div>
                <button class="queue-item-remove" onclick="window.musicPlayer.removeFromQueue(${index})">×</button>
            `;

            queueContainer.appendChild(item);
        });
    }

    toggleQueueView() {
        const queuePanel = document.getElementById('music-queue-panel');
        if (queuePanel) {
            queuePanel.classList.toggle('open');
            this.updateQueueUI();
        }
    }

    // Media Session API (for lockscreen controls)
    updateMediaSession(track) {
        if ('mediaSession' in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: this.cleanTitle(track.name),
                artist: track.artist || 'Unknown Artist',
                album: track.album || 'Unknown Album',
                artwork: track.albumArt ? [{ src: track.albumArt, sizes: '512x512', type: 'image/png' }] : []
            });

            navigator.mediaSession.setActionHandler('play', () => this.togglePlay());
            navigator.mediaSession.setActionHandler('pause', () => this.togglePlay());
            navigator.mediaSession.setActionHandler('previoustrack', () => this.playPrevious());
            navigator.mediaSession.setActionHandler('nexttrack', () => this.playNext());
        }
    }

    // Progress tracking
    async updateProgress() {
        const track = this.queue[this.currentIndex];
        if (!track || !isFinite(this.audio.currentTime) || !isFinite(this.audio.duration)) return;

        try {
            await fetch('/api/media/progress', {
                method: 'POST',
                headers: {
                    ...this.getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    path: track.path,
                    current_time: this.audio.currentTime,
                    duration: this.audio.duration,
                    finished: false
                })
            });
        } catch (err) {
            console.error('Failed to update progress:', err);
        }
    }

    // Queue persistence
    saveQueue() {
        try {
            localStorage.setItem('nomadpi.musicQueue', JSON.stringify({
                queue: this.queue,
                currentIndex: this.currentIndex,
                shuffle: this.shuffle,
                repeat: this.repeat
            }));
        } catch (err) {
            console.error('Failed to save queue:', err);
        }
    }

    restoreQueue() {
        try {
            const saved = localStorage.getItem('nomadpi.musicQueue');
            if (saved) {
                const data = JSON.parse(saved);
                this.queue = data.queue || [];
                this.currentIndex = data.currentIndex || -1;
                this.shuffle = data.shuffle || false;
                this.repeat = data.repeat || 'none';

                // Update UI controls
                const btnShuffle = document.getElementById('player-shuffle');
                if (btnShuffle) {
                    btnShuffle.classList.toggle('active', this.shuffle);
                }

                this.cycleRepeat(); // Restore repeat mode UI
            }
        } catch (err) {
            console.error('Failed to restore queue:', err);
        }
    }

    // Utility functions
    cleanTitle(filename) {
        if (!filename) return 'Unknown';
        // Remove file extension
        let title = filename.replace(/\.[^/.]+$/, '');
        // Remove common patterns like track numbers, artist prefixes
        title = title.replace(/^\d+[-.)]\s*/, ''); // Remove leading track numbers
        title = title.replace(/^[^-]+-\s*/, ''); // Remove "Artist - " prefix
        return title.trim() || 'Unknown';
    }

    formatTime(seconds) {
        if (!isFinite(seconds) || seconds < 0) return '0:00';

        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);

        if (h > 0) {
            return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    getAuthHeaders() {
        const token = this.getCookie('auth_token');
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }

    showToast(message, type = 'info') {
        // Use existing toast system if available
        if (typeof showToast === 'function') {
            showToast(message);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }
}

// Initialize music player when script loads
if (typeof window !== 'undefined') {
    window.MusicPlayer = MusicPlayer;
}
