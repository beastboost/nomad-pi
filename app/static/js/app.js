console.log("App v1.2 loaded - Plex-style UI & External Players");
const API_BASE = '/api';
const UP_NEXT_QUEUE_KEY = 'nomadpi.upNextQueue';
const UP_NEXT_QUEUE_LIMIT = 12;
let statsFailureCount = 0;
let statsNextAllowedAt = 0;
let statsLastErrorLogAt = 0;

async function checkPostUpdate() {
    try {
        const res = await fetch(`${API_BASE}/system/status`, {
            headers: getAuthHeaders()
        });
        const data = await res.json();

        if (!data.version) return;

        // Check both pre-update version (from update button) and last seen version
        const preUpdateVersion = localStorage.getItem('nomadpi_pre_update_version');
        const lastSeenVersion = localStorage.getItem('nomadpi_last_seen_version');

        // Determine if version changed
        const versionChanged = preUpdateVersion ?
            (data.version !== preUpdateVersion) :
            (lastSeenVersion && data.version !== lastSeenVersion);

        if (versionChanged) {
            // Version changed! Clear flags and show modal
            localStorage.removeItem('nomadpi_pre_update_version');
            localStorage.setItem('nomadpi_last_seen_version', data.version);

            // Update version tag in modal
            const versionTag = document.getElementById('new-version-tag');
            if (versionTag) versionTag.textContent = `v${data.version}`;

            // Fetch changelog
            const logRes = await fetch(`${API_BASE}/system/changelog`, {
                headers: getAuthHeaders()
            });
            const logData = await logRes.json();

            const list = document.getElementById('changelog-list');
            if (list && logData.changelog) {
                list.innerHTML = logData.changelog.map(item => `<li>${item}</li>`).join('');
            }

            // Show modal
            const modal = document.getElementById('what-is-new-modal');
            if (modal) modal.classList.remove('hidden');
        } else {
            // No change detected, just update last seen version
            if (!lastSeenVersion) {
                localStorage.setItem('nomadpi_last_seen_version', data.version);
            }
        }
    } catch (e) {
        console.error('Error checking post-update status:', e);
    }
}

function closeWhatIsNew() {
    const modal = document.getElementById('what-is-new-modal');
    if (modal) modal.classList.add('hidden');
    // Also clear the pre-update version to ensure it doesn't show again
    localStorage.removeItem('nomadpi_pre_update_version');
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

// Theme Management
function initTheme() {
    let savedTheme = localStorage.getItem('nomadpi_theme');

    // If no saved preference, detect system preference
    if (!savedTheme) {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            savedTheme = 'dark-theme';
        } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            savedTheme = 'light-theme';
        } else {
            savedTheme = 'default';
        }
    }

    applyTheme(savedTheme, false);

    // Listen for system theme changes (if user hasn't manually set a theme)
    if (window.matchMedia) {
        const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
        darkModeQuery.addEventListener('change', (e) => {
            // Only auto-switch if user hasn't manually set a theme
            const manualTheme = localStorage.getItem('nomadpi_theme');
            if (!manualTheme) {
                const newTheme = e.matches ? 'dark-theme' : 'light-theme';
                applyTheme(newTheme, true);
            }
        });
    }
}

function toggleTheme() {
    const currentTheme = localStorage.getItem('nomadpi_theme') || 'default';
    const themes = ['default', 'light-theme', 'dark-theme'];
    const currentIndex = themes.indexOf(currentTheme);
    const nextTheme = themes[(currentIndex + 1) % themes.length];

    applyTheme(nextTheme, true);
    localStorage.setItem('nomadpi_theme', nextTheme);
}

function applyTheme(theme, animate = false) {
    const body = document.body;
    const icon = document.getElementById('theme-icon');

    if (animate) {
        body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
        setTimeout(() => { body.style.transition = ''; }, 300);
    }

    // Remove all theme classes
    body.classList.remove('light-theme', 'dark-theme');

    // Apply new theme
    if (theme !== 'default') {
        body.classList.add(theme);
    }

    // Update icon
    if (icon) {
        if (theme === 'light-theme') {
            icon.className = 'fas fa-sun';
        } else if (theme === 'dark-theme') {
            icon.className = 'fas fa-moon';
        } else {
            icon.className = 'fas fa-adjust';
        }
    }
}

let currentMedia = null;
let currentProfile = null;
let driveScanInterval = null;
let statsInterval = null;
let comicPages = [];
let comicIndex = 0;
let comicZoom = 1;
let comicFit = 'width'; // 'width' or 'height'
let lastNetSample = null;
const mediaCache = {};
let showsLibraryCache = null;
let showsState = { level: 'shows', showName: null, seasonName: null };
const SHOWS_STATE_KEY = 'nomadpi.showsState';
let movieMetaObserver = null;
let movieMetaQueue = [];
let movieMetaActive = 0;
const MOVIE_META_CONCURRENCY = 2;
const mediaPageState = {};
const mediaState = { path: '/data' };
let activeVideoProgressInterval = null;
let activeVideoEl = null;
let activeVideoPath = null;
let playbackHeartbeatInstalled = false;
const progressDebugSent = new Set();

function getPageState(category) {
    if (!mediaPageState[category]) {
        mediaPageState[category] = { items: [], offset: 0, limit: 60, q: '', loading: false, hasMore: true };
    }
    return mediaPageState[category];
}

function getMovieMetaObserver() {
    if (movieMetaObserver) return movieMetaObserver;
    if (!('IntersectionObserver' in window)) return null;
    movieMetaObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            movieMetaObserver.unobserve(el);
            const file = el.__movieFile;
            if (file) enqueueMovieMetaFetch(file, el);
        });
    }, { root: null, rootMargin: '300px', threshold: 0.01 });
    return movieMetaObserver;
}

function enqueueMovieMetaFetch(file, el) {
    if (!file || !file.path) return;
    if (file._metaLoaded || file._metaLoading) return;
    file._metaLoading = true;
    movieMetaQueue.push({ file, el });
    pumpMovieMetaQueue();
}

function pumpMovieMetaQueue() {
    while (movieMetaActive < MOVIE_META_CONCURRENCY && movieMetaQueue.length > 0) {
        const task = movieMetaQueue.shift();
        movieMetaActive += 1;
        fetchMovieMeta(task.file).then((meta) => {
            if (meta) applyMovieMetaToCard(task.el, task.file, meta);
        }).catch(() => {}).finally(() => {
            task.file._metaLoading = false;
            task.file._metaLoaded = true;
            movieMetaActive -= 1;
            pumpMovieMetaQueue();
        });
    }
}

async function fetchMovieMeta(file) {
    try {
        const res = await fetch(`${API_BASE}/media/meta?path=${encodeURIComponent(file.path)}&fetch=1&media_type=movie`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return null; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.configured === false) return null;
        file.omdb = data;
        return data;
    } catch {
        return null;
    }
}

function applyMovieMetaToCard(cardEl, file, data) {
    if (!cardEl || !data) return;
    const titleEl = cardEl.querySelector('.card-title');
    const subEl = cardEl.querySelector('.card-subtitle');
    const shell = cardEl.querySelector('.poster-shell');

    const title = data.title || data.meta?.Title;
    if (titleEl && title) titleEl.textContent = title;

    const year = data.year || data.meta?.Year;
    const rated = data.rated || data.meta?.Rated;
    const runtime = data.runtime || data.meta?.Runtime;
    const parts = [year, rated, runtime].filter(v => v && v !== 'N/A');
    if (subEl && parts.length > 0) subEl.textContent = parts.join(' • ');

    if (shell && !file.poster) {
        const posterUrl = data.poster || data.meta?.Poster;
        if (posterUrl && posterUrl !== 'N/A') {
            const existingImg = shell.querySelector('img.poster-img');
            if (!existingImg) {
                const placeholder = shell.querySelector('.poster-placeholder');
                const img = document.createElement('img');
                img.className = 'poster-img';
                img.loading = 'lazy';
                img.alt = file?.name || 'Poster';
                img.src = posterUrl;
                if (placeholder) placeholder.replaceWith(img);
                else shell.prepend(img);
            }
        }
    }
}

function startStatsAutoRefresh() {
    if (statsInterval) return;
    statsInterval = setInterval(() => {
        loadStorageStats();
    }, 5000);
}

function stopStatsAutoRefresh() {
    if (!statsInterval) return;
    clearInterval(statsInterval);
    statsInterval = null;
}

function saveShowsState() {
    try {
        localStorage.setItem(SHOWS_STATE_KEY, JSON.stringify(showsState));
    } catch {}
}

function restoreShowsState() {
    try {
        const raw = localStorage.getItem(SHOWS_STATE_KEY);
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return false;

        const level = ['shows', 'seasons', 'episodes'].includes(parsed.level) ? parsed.level : 'shows';
        const showName = typeof parsed.showName === 'string' ? parsed.showName : null;
        const seasonName = typeof parsed.seasonName === 'string' ? parsed.seasonName : null;

        if (!showsLibraryCache || showsLibraryCache.length === 0) {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return false;
        }

        if (!showName) {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return true;
        }

        const show = showsLibraryCache.find(s => s.name === showName);
        if (!show) {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return true;
        }

        if (level === 'shows') {
            showsState = { level: 'shows', showName: null, seasonName: null };
            return true;
        }

        if (level === 'seasons') {
            showsState = { level: 'seasons', showName, seasonName: null };
            return true;
        }

        if (level === 'episodes') {
            const season = show.seasons?.find(se => se.name === seasonName);
            if (!season) {
                showsState = { level: 'seasons', showName, seasonName: null };
                return true;
            }
            showsState = { level: 'episodes', showName, seasonName };
            return true;
        }

        return false;
    } catch {
        return false;
    }
}

// Auth Functions
async function login() {
    const usernameInput = document.getElementById('username-input');
    const passwordInput = document.getElementById('password-input');
    if (!passwordInput) return;
    
    const username = usernameInput ? usernameInput.value : 'admin';
    const password = passwordInput.value;
    const errorMsg = document.getElementById('login-error');

    try {
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                username: username,
                password: password 
            })
        });

        if (res.ok) {
            const data = await res.json();
            if (data.token) {
                localStorage.setItem('nomad_auth_token', data.token);
            }
            if (errorMsg) {
                errorMsg.style.display = 'none';
                errorMsg.textContent = '';
            }
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('app').classList.remove('hidden');
            // Load initial data
            loadStorageStats();
            loadResume();
            loadUpNext();
            loadProfileUI();
            startStatsAutoRefresh();

            // Check if this is first login and show welcome screen
            checkAndShowWelcome();
            if (data.user && data.user.must_change_password) {
                showToast('Please change your password to continue', 'info');
                showSection('settings');
                setTimeout(() => {
                    const el = document.getElementById('change-pw-current');
                    if (el) el.focus();
                }, 50);
            }
        } else {
            const data = await res.json().catch(() => ({}));
            const msg =
                (data && (data.detail || data.message)) ||
                (res.status === 401 ? 'Invalid username or password' : `Login failed (${res.status})`);
            if (errorMsg) {
                errorMsg.textContent = msg;
                errorMsg.style.display = 'block';
            } else {
                showToast(msg, 'error');
            }
            passwordInput.value = '';
        }
    } catch (e) {
        console.error(e);
        showToast('Login failed. Please check your connection and try again.', 'error');
    }
}

async function logout() {
    const headers = getAuthHeaders();
    localStorage.removeItem('nomad_auth_token');
    await fetch(`${API_BASE}/auth/logout`, { 
        method: 'POST',
        headers: headers
    });
    location.reload();
}

async function checkAuth() {
    try {
        const res = await fetch(`${API_BASE}/auth/check`, {
            headers: getAuthHeaders()
        });
        const data = await res.json();
        if (data.authenticated) {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('app').classList.remove('hidden');
            loadStorageStats();
            loadResume();
            loadUpNext();
            loadProfileUI();
            startStatsAutoRefresh();
            if (data.user && data.user.must_change_password) {
                showToast('Please change your password', 'info');
                showSection('settings');
            }
        } else {
            // Ensure login screen is visible
            document.getElementById('login-screen').style.display = 'flex';
            document.getElementById('app').classList.add('hidden');
            stopStatsAutoRefresh();
        }
    } catch (e) {
        console.error("Auth check failed", e);
    }
}

// Enhanced Toast Notification System
const ToastManager = {
    container: null,
    toasts: [],
    maxToasts: 5,

    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'toast-stack';
            this.container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:12px;max-width:420px;pointer-events:none;';
            document.body.appendChild(this.container);
        }
    },

    show(message, type = 'info', options = {}) {
        this.init();

        const duration = options.duration || 4000;
        const dismissible = options.dismissible !== false;

        // Remove oldest if too many
        if (this.toasts.length >= this.maxToasts) {
            this.remove(this.toasts[0]);
        }

        // Create toast
        const toast = document.createElement('div');
        toast.className = 'toast-notification';
        toast.style.cssText = `
            background: rgba(26, 32, 44, 0.95);
            backdrop-filter: blur(12px);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            align-items: start;
            gap: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.1);
            transform: translateX(400px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            pointer-events: all;
            max-width: 420px;
            word-wrap: break-word;
        `;

        // Icon and colors
        const icons = {
            success: { icon: 'fa-check-circle', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' },
            error: { icon: 'fa-exclamation-circle', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' },
            warning: { icon: 'fa-exclamation-triangle', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' },
            info: { icon: 'fa-info-circle', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)' },
            loading: { icon: 'fa-spinner fa-spin', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.15)' }
        };

        const config = icons[type] || icons.info;

        // Build toast HTML
        toast.innerHTML = `
            <div style="flex-shrink:0;width:40px;height:40px;border-radius:8px;background:${config.bg};display:flex;align-items:center;justify-content:center;">
                <i class="fas ${config.icon}" style="color:${config.color};font-size:18px;"></i>
            </div>
            <div style="flex:1;color:#fff;font-size:14px;line-height:1.5;">${this.escapeHtml(message)}</div>
            ${dismissible ? `<button class="toast-close" style="flex-shrink:0;background:none;border:none;color:rgba(255,255,255,0.5);font-size:20px;cursor:pointer;padding:0;width:24px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:4px;transition:all 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)';this.style.color='#fff'" onmouseout="this.style.background='none';this.style.color='rgba(255,255,255,0.5)'">&times;</button>` : ''}
        `;

        // Add toast to container
        this.container.appendChild(toast);
        this.toasts.push(toast);

        // Trigger animation
        setTimeout(() => {
            toast.style.transform = 'translateX(0)';
            toast.style.opacity = '1';
        }, 10);

        // Close button
        if (dismissible) {
            const closeBtn = toast.querySelector('.toast-close');
            closeBtn.addEventListener('click', () => this.remove(toast));
        }

        // Pause on hover
        let timeout;
        const startTimer = () => {
            if (type !== 'loading') {
                timeout = setTimeout(() => this.remove(toast), duration);
            }
        };

        toast.addEventListener('mouseenter', () => clearTimeout(timeout));
        toast.addEventListener('mouseleave', startTimer);

        startTimer();

        return {
            dismiss: () => this.remove(toast),
            element: toast
        };
    },

    remove(toast) {
        if (!toast || !toast.parentNode) return;

        toast.style.transform = 'translateX(400px)';
        toast.style.opacity = '0';

        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            const index = this.toasts.indexOf(toast);
            if (index > -1) {
                this.toasts.splice(index, 1);
            }
        }, 300);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Legacy function for compatibility
function showToast(message, type = 'info', duration = 4000) {
    return ToastManager.show(message, type, { duration });
}

// Debounce utility for performance optimization
function debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Form Validation Helpers
const FormValidator = {
    // Validate email
    email(value) {
        const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return regex.test(value);
    },

    // Validate minimum length
    minLength(value, min) {
        return value.length >= min;
    },

    // Validate password strength
    passwordStrength(value) {
        const strength = {
            score: 0,
            feedback: []
        };

        if (value.length >= 8) strength.score++;
        if (value.length >= 12) strength.score++;
        if (/[a-z]/.test(value)) strength.score++;
        if (/[A-Z]/.test(value)) strength.score++;
        if (/\d/.test(value)) strength.score++;
        if (/[^a-zA-Z0-9]/.test(value)) strength.score++;

        if (!/[A-Z]/.test(value)) strength.feedback.push('Add uppercase letters');
        if (!/[a-z]/.test(value)) strength.feedback.push('Add lowercase letters');
        if (!/\d/.test(value)) strength.feedback.push('Add numbers');
        if (!/[^a-zA-Z0-9]/.test(value)) strength.feedback.push('Add special characters');
        if (value.length < 8) strength.feedback.push('Use at least 8 characters');

        return strength;
    },

    // Show inline error
    showError(input, message) {
        const errorId = `${input.id}-error`;
        let errorEl = document.getElementById(errorId);

        if (!errorEl) {
            errorEl = document.createElement('div');
            errorEl.id = errorId;
            errorEl.style.cssText = 'color:#ef4444;font-size:12px;margin-top:4px;';
            input.parentNode.insertBefore(errorEl, input.nextSibling);
        }

        errorEl.textContent = message;
        input.style.borderColor = '#ef4444';
    },

    // Clear error
    clearError(input) {
        const errorId = `${input.id}-error`;
        const errorEl = document.getElementById(errorId);
        if (errorEl) {
            errorEl.remove();
        }
        input.style.borderColor = '';
    }
};

// Welcome Screen Functions
function checkAndShowWelcome() {
    // Check if welcome screen has been shown before
    const hasSeenWelcome = localStorage.getItem('nomadpi_welcome_seen');

    if (!hasSeenWelcome) {
        // Delay showing welcome slightly to let the UI settle
        setTimeout(() => {
            showWelcome();
        }, 500);
    }
}

function showWelcome() {
    const modal = document.getElementById('welcome-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

function closeWelcome() {
    const modal = document.getElementById('welcome-modal');
    if (modal) {
        modal.classList.add('hidden');
        // Mark welcome as seen so it doesn't show again
        localStorage.setItem('nomadpi_welcome_seen', 'true');
    }
}

function handleLoginKey(e) {
    if (e.key === 'Enter') login();
}

function toggleMobileMenu() {
    const nav = document.getElementById('main-nav');
    const menuBtn = document.querySelector('.mobile-menu-btn');

    // Create backdrop if it doesn't exist
    let backdrop = document.getElementById('mobile-menu-backdrop');
    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.id = 'mobile-menu-backdrop';
        backdrop.className = 'mobile-menu-backdrop';
        backdrop.onclick = toggleMobileMenu;
        document.body.appendChild(backdrop);
    }

    const isOpen = nav && nav.classList.contains('mobile-menu-open');

    if (isOpen) {
        // Close menu
        nav.classList.remove('mobile-menu-open');
        backdrop.classList.remove('show');
        if (menuBtn) menuBtn.textContent = '☰';
        document.body.style.overflow = '';
        document.body.classList.remove('menu-open');
    } else if (nav) {
        // Open menu
        nav.classList.add('mobile-menu-open');
        backdrop.classList.add('show');
        if (menuBtn) menuBtn.textContent = '✕';
        document.body.style.overflow = 'hidden';
        document.body.classList.add('menu-open');
    }
}

function showSection(id) {
    // Close mobile menu when navigating
    const nav = document.getElementById('main-nav');
    if (nav && nav.classList.contains('mobile-menu-open')) {
        nav.classList.remove('mobile-menu-open');
        const menuBtn = document.querySelector('.mobile-menu-btn');
        if (menuBtn) {
            menuBtn.textContent = '☰';
        }
        const backdrop = document.getElementById('mobile-menu-backdrop');
        if (backdrop) {
            backdrop.classList.remove('show');
        }
        document.body.style.overflow = '';
        document.body.classList.remove('menu-open');
    }


    document.querySelectorAll('main > section').forEach(sec => {
        sec.classList.add('hidden');
        sec.style.display = 'none'; // Force hide
        sec.classList.remove('active', 'animate-fade');
    });

    // Update active nav button
    document.querySelectorAll('nav button').forEach(btn => {
        btn.classList.remove('active');
        if (btn.innerText.trim().toLowerCase() === id.toLowerCase()) {
            btn.classList.add('active');
        }
    });

    const target = document.getElementById(id);
    if (target) {
        target.classList.remove('hidden');
        target.style.display = 'block'; // Ensure display is set
        target.classList.add('active', 'animate-fade');
    }

    // Clear drive scan interval if leaving admin
    if (driveScanInterval) {
        clearInterval(driveScanInterval);
        driveScanInterval = null;
    }

    if (['movies', 'music', 'books', 'gallery'].includes(id)) loadMedia(id);
    if (id === 'files') loadMedia('files');
    if (id === 'shows') {
        showsLibraryCache = null;
        loadShowsLibrary();
    }
    if (id === 'home') {
        loadResume();
        loadRecent();
        loadStorageStats();
    }

    // Setup search listeners
    ['movies', 'shows', 'music', 'files'].forEach(cat => {
        const input = document.getElementById(`${cat}-search`);
        if (input && !input._listenerAttached) {
            let timeout = null;
            input.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    if (cat === 'movies') loadMovies(true);
                    else if (cat === 'shows') {
                        if (showsState.level === 'shows') loadShows(true);
                        else renderShows(); 
                    }
                    else if (cat === 'music' || cat === 'files') loadMedia(cat);
                }, 500);
            });
            input._listenerAttached = true;
        }
    });
    if (id === 'admin') {
        loadDrives();
        loadWifiStatus();
        loadUsers();
        // Auto-refresh drives every 5 seconds while in admin panel
        driveScanInterval = setInterval(() => {
            // Only refresh if we are not currently interacting (simple check)
            if (!document.querySelector('.drive-item button:disabled')) {
                loadDrives(true); // Pass true for silent update
            }
        }, 5000);
    }
    if (id === 'settings') {
        refreshTailscaleStatus();
    }
}

// Tailscale Functions
async function refreshTailscaleStatus() {
    const statusDiv = document.getElementById('tailscale-status');
    const controlsDiv = document.getElementById('tailscale-controls');
    const authDiv = document.getElementById('tailscale-auth-section');
    
    if (!statusDiv) return;

    statusDiv.innerHTML = '<div class="spinner-small"></div> Checking status...';

    try {
        const res = await fetch(`${API_BASE}/system/tailscale/status`, { headers: getAuthHeaders() });
        const status = await res.json();

        let html = '';
        let controlsHtml = '';
        let showAuth = false;

        // Header with state and refresh button
        const stateClass = status.connected ? 'success' : (status.backend_state === 'NeedsLogin' ? 'warning' : 'secondary');
        const stateIcon = status.connected ? 'check-circle' : (status.backend_state === 'NeedsLogin' ? 'key' : 'circle');
        
        html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div class="badge badge-${stateClass}"><i class="fas fa-${stateIcon}"></i> ${status.backend_state || 'Unknown'}</div>
            <button onclick="refreshTailscaleStatus()" class="secondary btn-sm" title="Refresh"><i class="fas fa-sync-alt"></i></button>
        </div>`;

        if (!status.installed) {
            html += `<p style="margin-top:10px; font-size:0.9em; color:var(--danger-color);"><i class="fas fa-exclamation-triangle"></i> Tailscale is not installed on this system.</p>`;
        } else if (!status.service_running) {
            html += `<p style="margin-top:10px; color:var(--text-muted);">The Tailscale system service is stopped.</p>`;
            controlsHtml = `<button onclick="controlTailscaleService('start')" class="success"><i class="fas fa-play"></i> Start Service</button>`;
        } else {
            // Service is running, show details
            if (status.ipv4) {
                 html += `<div style="margin-top:10px; font-family:monospace; background:rgba(0,0,0,0.2); padding:10px; border-radius:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span style="color:var(--text-muted); font-size:0.8em;">Tailscale IP</span>
                        <button onclick="copyToClipboard('${status.ipv4}')" class="secondary btn-sm" style="padding:2px 6px; font-size:0.7em;"><i class="fas fa-copy"></i></button>
                    </div>
                    <div style="font-size:1.1em; font-weight:bold; letter-spacing:0.5px;">${status.ipv4}</div>
                    ${status.magic_dns ? `<div style="font-size:0.8em; color:var(--text-muted); margin-top:4px;">${status.magic_dns}</div>` : ''}
                </div>`;
            }

            if (status.peer_count > 0) {
                 html += `<div style="margin-top:8px; font-size:0.9em; color:var(--text-muted);"><i class="fas fa-network-wired"></i> ${status.peer_count} Peer${status.peer_count === 1 ? '' : 's'} Connected</div>`;
            }

            if (status.connected) {
                controlsHtml = `<button onclick="disconnectTailscale()" class="warning"><i class="fas fa-unlink"></i> Disconnect</button>
                               <button onclick="controlTailscaleService('stop')" class="danger btn-sm" style="margin-left:8px;" title="Stop Service"><i class="fas fa-power-off"></i></button>`;
            } else {
                controlsHtml = `<button onclick="connectTailscale()" class="primary"><i class="fas fa-plug"></i> Connect</button>
                               <button onclick="controlTailscaleService('stop')" class="danger btn-sm" style="margin-left:8px;" title="Stop Service"><i class="fas fa-power-off"></i></button>`;
                showAuth = true;
            }
        }
        
        // Always allow showing auth key input if not connected (even if service stopped)
        // or if explicitly toggled (we could add a toggle later)
        if (!status.connected) {
            showAuth = true;
        }

        statusDiv.innerHTML = html;
        if (controlsDiv) controlsDiv.innerHTML = controlsHtml;
        if (authDiv) authDiv.style.display = showAuth ? 'block' : 'none';

    } catch (e) {
        console.error('Tailscale status error:', e);
        statusDiv.innerHTML = `<div class="badge badge-danger">Error</div><p style="margin-top:8px; font-size:0.8em;">${e.message}</p>
        <button onclick="refreshTailscaleStatus()" class="secondary btn-sm" style="margin-top:8px;">Try Again</button>`;
    }
}

async function connectTailscale() {
    showToast('Connecting to Tailscale...', 'info');
    try {
        const res = await fetch(`${API_BASE}/system/tailscale/up`, { 
            method: 'POST',
            headers: getAuthHeaders() 
        });
        const data = await res.json();

        if (data.status === 'success') {
            showToast('Connected to Tailscale!', 'success');
            refreshTailscaleStatus();
        } else if (data.status === 'needs_auth') {
            const urlMatch = data.output && data.output.match(/https:\/\/[^\s]+/);
            if (urlMatch) {
                if (confirm(`Authentication required. Open Tailscale login page?\n\n${urlMatch[0]}`)) {
                    window.open(urlMatch[0], '_blank');
                }
            } else {
                showToast('Authentication required. Check logs.', 'warning');
            }
        } else {
            showToast('Connection failed: ' + (data.detail || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Connection failed', 'error');
    }
}

async function disconnectTailscale() {
    if (!confirm('Disconnect from Tailscale VPN?')) return;
    try {
        await fetch(`${API_BASE}/system/tailscale/down`, { 
            method: 'POST',
            headers: getAuthHeaders() 
        });
        showToast('Disconnected', 'info');
        refreshTailscaleStatus();
    } catch (e) {
        showToast('Disconnect failed', 'error');
    }
}

async function controlTailscaleService(action) {
    if (!confirm(`${action === 'start' ? 'Start' : 'Stop'} Tailscale service?`)) return;
    showToast(`${action === 'start' ? 'Starting' : 'Stopping'} Tailscale service...`, 'info');
    
    try {
        const res = await fetch(`${API_BASE}/system/tailscale/service/${action}`, { 
            method: 'POST',
            headers: getAuthHeaders() 
        });
        
        if (res.ok) {
            showToast(`Service ${action}ed`, 'success');
            setTimeout(refreshTailscaleStatus, 2000); // Wait a bit for service to come up
        } else {
            const data = await res.json();
            showToast(`Failed: ${data.detail}`, 'error');
        }
    } catch (e) {
        showToast('Service control failed', 'error');
    }
}

async function saveTailscaleKey() {
    const input = document.getElementById('tailscale-auth-key');
    if (!input || !input.value) return;

    try {
        const res = await fetch(`${API_BASE}/system/tailscale/set-auth-key`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ auth_key: input.value })
        });
        if (res.ok) {
            showToast('Auth key saved', 'success');
            input.value = '';
        } else {
            showToast('Failed to save key', 'error');
        }
    } catch (e) {
        showToast('Error saving key', 'error');
    }
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard', 'success');
    }).catch(err => {
        console.error('Could not copy text: ', err);
    });
}

async function loadMedia(category) {
    if (category === 'files') {
        loadFileBrowser(mediaState.path || '/data');
        return;
    }
    await loadMediaPage(category, true);
}

async function loadFileBrowser(path) {
    console.log('loadFileBrowser called with path:', path);
    const container = document.getElementById('files-list');
    if (!container) return;

    container.innerHTML = '<div class="loading">Loading files...</div>';
    
    // Check if we should show drive list (Windows)
    if (path === 'DRIVES') {
        try {
            const res = await fetch(`${API_BASE}/system/drives`, {
                headers: getAuthHeaders()
            });
            const data = await res.json();
            container.innerHTML = '<h2>Available Drives</h2>';
            const drives = data.blockdevices || [];
            
            // Back to /data
            const backDiv = document.createElement('div');
            backDiv.className = 'media-item folder';
            backDiv.innerHTML = `
                <div class="media-card glass" onclick="loadFileBrowser('/data')">
                    <div class="media-info">
                        <h3>📁 .. (Back to /data)</h3>
                    </div>
                </div>
            `;
            container.appendChild(backDiv);

            drives.forEach(d => {
                const div = document.createElement('div');
                div.className = 'media-item folder';
                div.innerHTML = `
                    <div class="media-card glass" onclick="loadFileBrowser('${d.mountpoint.replaceAll('\\', '\\\\')}')">
                        <div class="media-info">
                            <h3>💽 Drive ${d.name} (${formatBytes(d.free)} free)</h3>
                            <p>${d.fstype} - ${d.mountpoint}</p>
                        </div>
                    </div>
                `;
                container.appendChild(div);
            });
            return;
        } catch (e) {
            console.error('Error loading drives:', e);
        }
    }

    try {
        const url = `${API_BASE}/media/browse?path=${encodeURIComponent(path)}`;
        const res = await fetch(url, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        
        container.innerHTML = '';
        
        // Add "Back" and "Drives" buttons
        const isWindows = path.includes(':');
        const isRoot = path === '/data' || (isWindows && (path.endsWith(':\\') || path.endsWith(':') || path.endsWith(':/')));

        if (!isRoot) {
            // Calculate parent path more robustly
            let parentPath = '';
            if (path.includes('\\')) {
                parentPath = path.substring(0, path.lastIndexOf('\\'));
                if (parentPath.endsWith(':')) parentPath += '\\';
            } else if (path.includes('/')) {
                parentPath = path.substring(0, path.lastIndexOf('/'));
                if (parentPath === '') parentPath = '/';
            } else {
                parentPath = '/data';
            }

            const backDiv = document.createElement('div');
            backDiv.className = 'media-item folder';
            backDiv.innerHTML = `
                <div class="media-card glass" onclick="loadFileBrowser('${(parentPath || '/data').replaceAll('\\', '\\\\')}')">
                    <div class="media-info">
                        <h3>📁 .. (Back)</h3>
                    </div>
                </div>
            `;
            container.appendChild(backDiv);
        } else if (path === '/data') {
            // Show "Browse Drives" button at /data root
            const driveDiv = document.createElement('div');
            driveDiv.className = 'media-item folder';
            driveDiv.innerHTML = `
                <div class="media-card glass" onclick="loadFileBrowser('DRIVES')">
                    <div class="media-info">
                        <h3>💽 Browse External Drives / Partitions</h3>
                    </div>
                </div>
            `;
            container.appendChild(driveDiv);
        } else if (isWindows && isRoot) {
            // At drive root, allow going back to drives list
            const backDiv = document.createElement('div');
            backDiv.className = 'media-item folder';
            backDiv.innerHTML = `
                <div class="media-card glass" onclick="loadFileBrowser('DRIVES')">
                    <div class="media-info">
                        <h3>📁 .. (Back to Drives)</h3>
                    </div>
                </div>
            `;
            container.appendChild(backDiv);
        }

        if (!data.items || data.items.length === 0) {
            container.innerHTML += '<p style="padding:20px; text-align:center; color:var(--text-muted);">This folder is empty.</p>';
        } else {
            data.items.forEach(item => {
                const div = document.createElement('div');
                div.className = 'media-item' + (item.is_dir ? ' folder' : '');
                const itemPath = item.path.replaceAll('\\', '\\\\');

                if (item.is_dir) {
                    div.innerHTML = `
                        <div class="media-card glass" onclick="loadFileBrowser('${itemPath}')">
                            <div class="media-info">
                                <h3>📁 ${escapeHtml(item.name)}</h3>
                            </div>
                        </div>
                    `;
                } else {
                    const ext = item.name.split('.').pop().toLowerCase();
                    let icon = '📄';
                    if (['mp4', 'mkv', 'avi', 'mov', 'webm'].includes(ext)) icon = '🎬';
                    if (['mp3', 'flac', 'wav', 'm4a'].includes(ext)) icon = '🎵';
                    if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) icon = '🖼️';
                    if (['pdf', 'epub', 'cbz', 'cbr'].includes(ext)) icon = '📚';

                    div.innerHTML = `
                        <div class="media-card glass" onclick="openFile('${itemPath}')">
                            <div class="media-info">
                                <h3>${icon} ${escapeHtml(item.name)}</h3>
                                <p>${formatBytes(item.size)}</p>
                            </div>
                        </div>
                    `;
                }
                container.appendChild(div);
            });
        }
        
        mediaState.path = path;
    } catch (e) {
        console.error('Error in loadFileBrowser:', e);
        container.innerHTML = `<p>Error loading directory: ${e.message}</p>`;
    }
}

function openFile(path) {
    const ext = path.split('.').pop().toLowerCase();
    if (['mp4', 'mkv', 'avi', 'mov', 'webm', 'm4v', 'ts', 'wmv', 'flv', '3gp', 'mpg', 'mpeg'].includes(ext)) {
        openVideoViewer(path);
    } else if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) {
        openImageViewer(path);
    } else if (['pdf', 'epub', 'cbz', 'cbr'].includes(ext)) {
        openComicViewer(path);
    } else if (['mp3', 'flac', 'wav', 'm4a'].includes(ext)) {
        playAudio(path);
    } else {
        window.open(path, '_blank');
    }
}

function playAudio(path) {
    console.log('playAudio called for:', path);
    // When playing from file browser, we don't have the full track list easily.
    // Create a temporary track object and start a queue with just this one file.
    const name = path.split('/').pop() || path;
    const track = {
        name: name,
        path: path
    };
    startMusicQueue([track], 0);
}

function renderMediaFromCache(category) {
    const files = mediaCache[category] || [];
    const searchInput = document.getElementById(`${category}-search`);
    const q = (searchInput?.value || '').trim().toLowerCase();
    const filtered = q ? files.filter(f => `${f.name} ${f.folder || ''}`.toLowerCase().includes(q)) : files;
    renderMediaList(category, filtered);
}

async function loadMediaPage(category, reset) {
    const container = document.getElementById(`${category}-list`);
    if (!container) return;

    const searchInput = document.getElementById(`${category}-search`);
    const sortSelect = document.getElementById(`${category}-sort`);
    const genreSelect = document.getElementById(`${category}-genre`);
    const yearSelect = document.getElementById(`${category}-year`);
    
    const q = (searchInput?.value || '').trim();
    const sort = sortSelect?.value || 'name';
    const genre = genreSelect?.value || '';
    const year = yearSelect?.value || '';
    
    const state = getPageState(category);
    if (reset) {
        state.items = [];
        state.offset = 0;
        state.q = q;
        state.sort = sort;
        state.genre = genre;
        state.year = year;
        state.hasMore = true;
        mediaCache[category] = null;
        container.innerHTML = '<div class="loading">Loading...</div>';
    }

    if (state.loading || !state.hasMore) return;
    state.loading = true;

    try {
        let url = `${API_BASE}/media/library/${category}?offset=${state.offset}&limit=${state.limit}&q=${encodeURIComponent(state.q || '')}`;
        if (state.sort) url += `&sort=${state.sort}`;
        if (state.genre) url += `&genre=${encodeURIComponent(state.genre)}`;
        if (state.year) url += `&year=${state.year}`;
        
        const res = await fetch(url, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) throw new Error(data?.detail || 'Failed to load media');

        const items = Array.isArray(data.items) ? data.items : [];
        state.items = state.items.concat(items);
        state.offset = Number(data.next_offset || (state.offset + items.length));
        state.hasMore = Boolean(data.has_more);
        mediaCache[category] = state.items;
        renderMediaListPaged(category, state.items, state.hasMore);
        
        // Populate filters if they are empty
        if (reset && (category === 'movies' || category === 'shows')) {
            updateFilters(category);
        }
    } catch (e) {
        console.error(e);
        container.innerHTML = '<p>Error loading media.</p>';
    } finally {
        state.loading = false;
    }
}

async function updateFilters(category) {
    const genreSelect = document.getElementById(`${category}-genre`);
    const yearSelect = document.getElementById(`${category}-year`);
    if (!genreSelect && !yearSelect) return;

    try {
        // Fetch genres
        if (genreSelect) {
            const gRes = await fetch(`${API_BASE}/media/genres?category=${category}`, {
                headers: getAuthHeaders()
            });
            if (gRes.ok) {
                const genres = await gRes.json();
                const currentGenre = genreSelect.value;
                genreSelect.innerHTML = '<option value="">All Genres</option>';
                genres.forEach(g => {
                    const opt = document.createElement('option');
                    opt.value = g;
                    opt.textContent = g;
                    if (g === currentGenre) opt.selected = true;
                    genreSelect.appendChild(opt);
                });
            }
        }

        // Fetch years
        if (yearSelect) {
            const yRes = await fetch(`${API_BASE}/media/years?category=${category}`, {
                headers: getAuthHeaders()
            });
            if (yRes.ok) {
                const years = await yRes.json();
                const currentYear = yearSelect.value;
                yearSelect.innerHTML = '<option value="">All Years</option>';
                years.forEach(y => {
                    const opt = document.createElement('option');
                    opt.value = y;
                    opt.textContent = y;
                    if (y === currentYear) opt.selected = true;
                    yearSelect.appendChild(opt);
                });
            }
        }
    } catch (e) {
        console.error("Failed to load filters", e);
    }
}

function loadMovies(reset) { loadMediaPage('movies', reset); }
function loadShows(reset) { 
    if (reset) {
        showsLibraryCache = null;
    }
    if (showsState.level === 'shows') {
        loadShowsLibrary(); 
    } else {
        renderShowsLevel();
    }
}

function renderMediaListPaged(category, files, hasMore) {
    renderMediaList(category, files);
    const container = document.getElementById(`${category}-list`);
    if (!container) return;

    const footerId = `${category}-load-more`;
    const existing = document.getElementById(footerId);
    if (existing) existing.remove();

    if (!hasMore) return;
    const btn = document.createElement('button');
    btn.id = footerId;
    btn.className = 'primary';
    btn.style.margin = '14px auto';
    btn.style.display = 'block';
    btn.textContent = 'Load more';
    btn.addEventListener('click', () => loadMediaPage(category, false));
    container.appendChild(btn);
}

function renderMediaList(category, files) {
    const container = document.getElementById(`${category}-list`);
    container.innerHTML = '';

    if (category === 'music' && files && files.length > 0) {
        const shuffleBtn = document.createElement('button');
        shuffleBtn.className = 'primary';
        shuffleBtn.style.marginBottom = '10px';
        shuffleBtn.textContent = 'Shuffle All';
        shuffleBtn.onclick = () => {
            const shuffled = [...files].sort(() => 0.5 - Math.random());
            startMusicQueue(shuffled, 0);
        };
        container.appendChild(shuffleBtn);
    }

    if (!files || files.length === 0) {
        container.innerHTML = '<p>No media found.</p>';
        return;
    }

    if (category !== 'movies' && category !== 'shows') {
        files.sort((a, b) => {
            if ((a.folder || '.') === (b.folder || '.')) return naturalCompare(a.name, b.name);
            return naturalCompare((a.folder || '.'), (b.folder || '.'));
        });
    }

    files.forEach(file => {
        const div = document.createElement('div');
        div.className = (category === 'music' || category === 'files') ? 'list-item' : 'media-item';
        div.style.position = 'relative';

        let folderHtml = '';
        if (file.folder && file.folder !== '.') {
            if (category === 'music' || category === 'files') {
                folderHtml = `<div style="color:#aaa;font-size:0.85em;">${file.folder}</div>`;
            } else {
                folderHtml = `<div class="folder-tag">${file.folder}</div>`;
            }
        }
        
        const deleteBtn = `<button class="delete-btn" style="background:none;border:none;cursor:pointer;font-size:1.2em;" title="Delete" onclick="deleteItem('${escapeHtml(file.path)}')">🗑️</button>`;
        const cardDeleteBtn = `<button class="delete-btn" style="position:absolute;top:5px;right:5px;z-index:10;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1.2em;line-height:1;" title="Delete" onclick="deleteItem('${escapeHtml(file.path)}')">×</button>`;

        if (category === 'music') {
            const title = escapeHtml(cleanTitle(file.name));
            div.innerHTML = `
                <div style="flex-grow:1;">
                    ${folderHtml}
                    <span>${title}</span>
                </div>
                <div style="display:flex;gap:10px;align-items:center;">
                    <button class="modal-close rename-btn" title="Rename">✏️</button>
                    <button class="modal-close music-play">Play</button>
                    ${deleteBtn}
                </div>
            `;
            const playBtn = div.querySelector('.music-play');
            if (playBtn) {
                playBtn.addEventListener('click', () => {
                    startMusicQueue(files, files.indexOf(file));
                });
            }
            const renameBtn = div.querySelector('.rename-btn');
            if (renameBtn) {
                renameBtn.addEventListener('click', () => {
                    promptRename(file.path, file.name, () => loadMediaPage('music', true));
                });
            }
        } else if (category === 'files') {
            div.innerHTML = `
                <div style="flex-grow:1;">
                    ${folderHtml}
                    <span>${file.name}</span>
                </div>
                <div style="display:flex;gap:10px;align-items:center;">
                    <button class="modal-close rename-btn" title="Rename">✏️</button>
                    <a href="${file.path}" target="_blank" class="download-btn">Open</a>
                    ${deleteBtn}
                </div>
            `;
            const renameBtn = div.querySelector('.rename-btn');
            if (renameBtn) {
                renameBtn.addEventListener('click', () => {
                    promptRename(file.path, file.name, () => loadMediaPage('files', true));
                });
            }
        } else if (category === 'gallery') {
            const renameBtnHtml = `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:10;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;" title="Rename">✏️</button>`;
            if (file.name.match(/\.(jpg|jpeg|png|gif)$/i)) {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${renameBtnHtml}
                    ${folderHtml}
                    <img src="${file.path}" loading="lazy" alt="${file.name}" onclick="openImageViewer('${escapeHtml(file.path)}', '${escapeHtml(file.name)}')">
                    <div class="caption">${file.name}</div>
                `;
            } else {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${renameBtnHtml}
                    ${folderHtml}
                    <video controls preload="metadata" src="${file.path}"></video>
                    <div class="caption">${file.name}</div>
                `;
            }
            const renameBtn = div.querySelector('.rename-btn-card');
            if (renameBtn) {
                renameBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    promptRename(file.path, file.name, () => loadMediaPage('gallery', true));
                });
            }
        } else if (category === 'books') {
            const isPdf = /\.pdf$/i.test(file.name || '');
            const isEpub = /\.epub$/i.test(file.name || '');
            const isCbz = /\.cbz$/i.test(file.name || '');
            const isCbr = /\.cbr$/i.test(file.name || '');
            const title = escapeHtml(cleanTitle(file.name));
            const folder = file.folder && file.folder !== '.' ? `<div style="color:#aaa;font-size:0.85em;">${escapeHtml(file.folder)}</div>` : '';
            const canView = isPdf || isEpub || isCbz || isCbr;
            const viewBtn = canView ? `<button class="modal-close view-btn">View</button>` : '';
            const renameBtnHtml = `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:10;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;" title="Rename">✏️</button>`;

            div.innerHTML = `
                ${cardDeleteBtn}
                ${renameBtnHtml}
                ${folder}
                <h3>${title}</h3>
                <div style="display:flex; gap:10px; padding: 0 10px 12px 10px; align-items:center; justify-content:space-between;">
                    <a href="${file.path}" target="_blank" class="download-btn">Open</a>
                    ${viewBtn}
                </div>
            `;

            const btn = div.querySelector('.view-btn');
            if (btn) {
                btn.addEventListener('click', () => {
                    if (window.ebookReader) {
                        // Use new eBook reader for all formats
                        window.ebookReader.open(file.path, file.name || 'Book');
                    } else {
                        // Fallback to old viewers
                        if (isPdf) openPdfViewer(file.path, file.name || 'PDF');
                        else if (isEpub) window.open(file.path, '_blank');
                        else openComicViewer(file.path, file.name || 'Comic');
                    }
                });
            }
            const renameBtn = div.querySelector('.rename-btn-card');
            if (renameBtn) {
                renameBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    promptRename(file.path, file.name, () => loadMediaPage('books', true));
                });
            }
        } else {
            // This is for movies, shows, etc.
            div.style.cursor = 'pointer';

            if (category === 'shows' && showsState.level === 'shows') {
                // Root level shows view (using data from query_shows)
                div.className = 'media-item media-card';
                const poster = file.poster 
                    ? `<img class="poster-img" src="${file.poster}" loading="lazy" alt="${escapeHtml(file.name)}">`
                    : `<div class="poster-placeholder"></div>`;
                
                const subtitle = `${file.episode_count || 0} episodes` + (file.year ? ` • ${file.year}` : '');
                
                div.innerHTML = `
                    <div class="poster-shell">
                        ${poster}
                        <div class="media-info">
                            <h3>${escapeHtml(file.name)}</h3>
                            <div class="media-details">${subtitle}</div>
                        </div>
                        <button class="poster-play">View Seasons</button>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(file.name)}</div>
                        <div class="card-subtitle">${subtitle}</div>
                    </div>
                `;

                div.addEventListener('click', (e) => {
                    if (e.target.closest('button')) return;
                    setShowsLevel('seasons', file.name);
                });

                const viewBtn = div.querySelector('.poster-play');
                if (viewBtn) {
                    viewBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        setShowsLevel('seasons', file.name);
                    });
                }
                container.appendChild(div);
                return; // Done with this item
            }

            const isVideo = /\.(mp4|webm|mkv|mov|avi|m4v|ts|wmv|flv|3gp|mpg|mpeg)$/i.test(file.name || '');
            
            // Add a default click listener for the whole card
            div.addEventListener('click', (e) => {
                if (e.target.closest('button')) return;
                if (isVideo) {
                    if (category === 'movies') openMovieDetails(file);
                    else openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0);
                } else {
                    openImageViewer(file.path, cleanTitle(file.name));
                }
            });

            let progressHtml = '';
            const duration = Number(file?.progress?.duration || 0);
            if (file.progress && file.progress.current_time > 0 && Number.isFinite(duration) && duration > 0) {
                const pct = (Number(file.progress.current_time || 0) / duration) * 100;
                progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
            }

            if (category === 'movies' && isVideo) {
                div.className = 'media-item media-card';
                const metaTitle = file.omdb?.title || file.omdb?.meta?.Title || cleanTitle(file.name);
                const metaYear = file.omdb?.year || file.omdb?.meta?.Year;
                const metaRated = file.omdb?.rated || file.omdb?.meta?.Rated;
                const metaRuntime = file.omdb?.runtime || file.omdb?.meta?.Runtime;
                const metaSubtitleParts = [metaYear, metaRated, metaRuntime].filter(v => v && v !== 'N/A');
                const subtitle = metaSubtitleParts.length ? escapeHtml(metaSubtitleParts.join(' • ')) : (file.folder && file.folder !== '.' ? escapeHtml(file.folder) : 'Movie');
                const metaPoster = (!file.poster && (file.omdb?.poster || file.omdb?.meta?.Poster) && (file.omdb?.poster || file.omdb?.meta?.Poster) !== 'N/A') ? (file.omdb?.poster || file.omdb?.meta?.Poster) : null;
                const poster = file.poster
                    ? `<img class="poster-img" src="${file.poster}" loading="lazy" alt="${escapeHtml(file.name)}">`
                    : (metaPoster ? `<img class="poster-img" src="${metaPoster}" loading="lazy" alt="${escapeHtml(file.name)}">` : `<div class="poster-placeholder"></div>`);
                
                const renameBtnHtml = `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:10;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;" title="Rename">✏️</button>`;
                const playLabel = Number(file?.progress?.current_time || 0) > 10 ? 'Resume' : 'Play';

                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${renameBtnHtml}
                    <div class="poster-shell">
                        ${poster}
                        <div class="media-info">
                            <h3>${escapeHtml(metaTitle)}</h3>
                            <div class="media-details">${subtitle}</div>
                        </div>
                        <button class="poster-play">${playLabel}</button>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(metaTitle)}</div>
                        <div class="card-subtitle">${subtitle}</div>
                    </div>
                    ${progressHtml}
                `;

                const playBtn = div.querySelector('.poster-play');
                if (playBtn) {
                    playBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0);
                    });
                }

                const renameBtn = div.querySelector('.rename-btn-card');
                if (renameBtn) {
                    renameBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        await promptRename(file.path, file.name, () => loadMediaPage(category, true));
                    });
                }

                div.__movieFile = file;
                const obs = getMovieMetaObserver();
                if (obs) obs.observe(div);
            } else if (isVideo) {
                const subtitle = file.folder && file.folder !== '.' ? escapeHtml(file.folder) : '';
                div.className = 'media-item media-card';
                const playLabel = Number(file?.progress?.current_time || 0) > 10 ? 'Resume' : 'Play';
                div.innerHTML = `
                    ${cardDeleteBtn}
                    <div class="poster-shell">
                        <div class="poster-placeholder"></div>
                        <div class="media-info">
                            <h3>${escapeHtml(cleanTitle(file.name))}</h3>
                            <div class="media-details">${subtitle || 'Video'}</div>
                        </div>
                        <button class="poster-play">${playLabel}</button>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(cleanTitle(file.name))}</div>
                        <div class="card-subtitle">${subtitle}</div>
                    </div>
                    ${progressHtml}
                `;
                const playBtn = div.querySelector('.poster-play');
                if (playBtn) {
                    playBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0);
                    });
                }
            } else {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${folderHtml}
                    <h3>${escapeHtml(cleanTitle(file.name))}</h3>
                    <button class="play-btn">View Image</button>
                `;
                const playBtn = div.querySelector('.play-btn');
                if (playBtn) {
                    playBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openImageViewer(file.path, cleanTitle(file.name));
                    });
                }
            }
        }
        container.appendChild(div);
    });
}

async function promptRename(oldPath, oldName, refreshCallback) {
    const dotIdx = oldName.lastIndexOf('.');
    const isFile = dotIdx !== -1 && dotIdx > oldName.lastIndexOf('/');
    const ext = isFile ? oldName.substring(dotIdx) : '';
    const base = isFile ? oldName.substring(0, dotIdx) : oldName;
    
    const newBase = prompt(`Rename ${isFile ? 'File' : 'Folder'} (extension will be preserved):`, base);
    if (!newBase || newBase === base) return;
    
    const newName = newBase + ext;
    const parts = oldPath.split('/');
    parts.pop();
    const newPath = `${parts.join('/')}/${newName}`.replaceAll('//', '/');
    
    try {
        await renameMediaPath(oldPath, newPath);
        if (refreshCallback) refreshCallback();
    } catch (err) {
        alert(err.message);
    }
}

async function promptRenameShowPart(oldPath, oldName) {
    const dotIdx = oldName.lastIndexOf('.');
    const isFile = dotIdx !== -1 && dotIdx > oldName.lastIndexOf('/');
    const ext = isFile ? oldName.substring(dotIdx) : '';
    const base = isFile ? oldName.substring(0, dotIdx) : oldName;
    
    const newBase = prompt(`Rename ${isFile ? 'File' : 'Folder'} (extension will be preserved):`, base);
    if (!newBase || newBase === base) return;
    
    const newName = newBase + ext;
    const parts = oldPath.split('/');
    parts.pop();
    const newPath = `${parts.join('/')}/${newName}`.replaceAll('//', '/');
    
    try {
        await renameMediaPath(oldPath, newPath);
        
        // If we renamed the current show or season, update the state
        if (showsState.level !== 'shows' && showsState.showName === oldName) {
            showsState.showName = newBase;
        } else if (showsState.level === 'episodes' && showsState.seasonName === oldName) {
            showsState.seasonName = newBase;
        }
        
        await loadShowsLibrary();
    } catch (err) {
        alert(err.message);
    }
}

async function renameMediaPath(oldPath, newPath) {
    const res = await fetch(`${API_BASE}/media/rename`, {
        method: 'POST',
        headers: { 
            ...getAuthHeaders(),
            'Content-Type': 'application/json' 
        },
        body: JSON.stringify({ old_path: oldPath, new_path: newPath })
    });
    if (res.status === 401) { logout(); return; }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'Rename failed');
    return data;
}

async function organizeShows(preview) {
    const out = document.getElementById('organize-status');
    if (out) out.textContent = preview ? 'Previewing…' : 'Organizing…';
    try {
        const renameToggle = document.getElementById('show-organize-rename-files');
        const renameFiles = renameToggle ? (renameToggle.checked ? 1 : 0) : 0;
        const res = await fetch(`${API_BASE}/media/organize/shows?dry_run=${preview ? 1 : 0}&rename_files=${renameFiles}&use_omdb=1&write_poster=1`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) throw new Error(data?.detail || 'Organize failed');
        const planned = Array.isArray(data.planned) ? data.planned : [];
        const lines = [];
        lines.push(`dry_run=${data.dry_run} moved=${data.moved} skipped=${data.skipped} errors=${data.errors}`);
        if (data.shows_metadata_fetched) lines.push(`Shows with metadata: ${data.shows_metadata_fetched}`);
        for (const it of planned.slice(0, 20)) {
            if (it?.from && it?.to) lines.push(`${it.from} -> ${it.to}`);
        }
        if (planned.length > 20) lines.push(`…and ${planned.length - 20} more`);
        if (out) out.textContent = lines.join('\n');
    } catch (e) {
        if (out) out.textContent = String(e?.message || e);
    }
}

async function organizeMovies(preview) {
    const out = document.getElementById('organize-status');
    if (out) out.textContent = preview ? 'Previewing…' : 'Organizing…';
    try {
        const res = await fetch(`${API_BASE}/media/organize/movies?dry_run=${preview ? 1 : 0}&use_omdb=1&write_poster=1`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) throw new Error(data?.detail || 'Organize failed');
        const planned = Array.isArray(data.planned) ? data.planned : [];
        const lines = [];
        lines.push(`dry_run=${data.dry_run} moved=${data.moved} skipped=${data.skipped} errors=${data.errors}`);
        for (const it of planned.slice(0, 20)) {
            if (it?.from && it?.to) lines.push(`${it.from} -> ${it.to}`);
        }
        if (planned.length > 20) lines.push(`…and ${planned.length - 20} more`);
        if (out) out.textContent = lines.join('\n');
    } catch (e) {
        if (out) out.textContent = String(e?.message || e);
    }
}

function naturalCompare(a, b) {
    const ax = String(a || '').toLowerCase().split(/(\d+)/).map(p => (p.match(/^\d+$/) ? Number(p) : p));
    const bx = String(b || '').toLowerCase().split(/(\d+)/).map(p => (p.match(/^\d+$/) ? Number(p) : p));
    const n = Math.max(ax.length, bx.length);
    for (let i = 0; i < n; i++) {
        if (ax[i] === undefined) return -1;
        if (bx[i] === undefined) return 1;
        if (ax[i] === bx[i]) continue;
        if (typeof ax[i] === 'number' && typeof bx[i] === 'number') return ax[i] - bx[i];
        return String(ax[i]).localeCompare(String(bx[i]));
    }
    return 0;
}

function cleanTitle(name) {
    let s = String(name || '');
    s = s.replace(/\.[^.]+$/, '');
    s = s.replace(/[\._]+/g, ' ');
    s = s.replace(/\s+/g, ' ').trim();
    s = s.replace(/\b(480p|720p|1080p|2160p|4k|hdr|hevc|x265|x264|h265|h264|aac|ac3|dts|web[- ]dl|webrip|bluray|brrip|dvdrip|remux)\b/ig, '').replace(/\s+/g, ' ').trim();
    s = s.replace(/[\[\(].*?[\]\)]/g, '').replace(/\s+/g, ' ').trim();
    return s || String(name || '');
}

function startMusicQueue(list, startIdx) {
    // Use new music player if available
    if (window.musicPlayer) {
        window.musicPlayer.startQueue(list, startIdx);
        return;
    }

    // Fallback to old player
    const audio = document.getElementById('global-audio');
    const bar = document.getElementById('player-bar');
    if (!audio || !bar) return;

    // Add error listeners if not already added
    if (!audio.dataset.listenersAdded) {
        audio.addEventListener('error', (e) => {
            console.error('Audio element error:', audio.error);
            let msg = 'Audio error occurred.';
            if (audio.error) {
                switch (audio.error.code) {
                    case 1: msg = 'Fetching aborted.'; break;
                    case 2: msg = 'Network error.'; break;
                    case 3: msg = 'Decoding failed.'; break;
                    case 4: msg = 'Source not supported.'; break;
                }
                msg += ' (Code ' + audio.error.code + ')';
            }
            alert(msg);
        });
        audio.addEventListener('stalled', () => console.warn('Audio stalled...'));
        audio.addEventListener('waiting', () => console.log('Audio waiting for data...'));
        audio.addEventListener('canplay', () => console.log('Audio can play now'));
        audio.dataset.listenersAdded = 'true';
    }

    musicQueue = (list || []).filter(f => f && f.path);
    if (musicQueue.length === 0) return;
    musicIndex = Math.max(0, Math.min(startIdx || 0, musicQueue.length - 1));
    if (musicShuffle) {
        musicShuffleOrder = shuffleOrder(musicQueue.length, musicIndex);
        musicShufflePos = 0;
    }
    bar.classList.remove('hidden');
    playMusicAt(musicIndex);
}

function shuffleOrder(n, start) {
    const arr = [];
    for (let i = 0; i < n; i++) arr.push(i);
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    if (n > 1 && arr[0] !== start) {
        const k = arr.indexOf(start);
        if (k > 0) { const t = arr[0]; arr[0] = arr[k]; arr[k] = t; }
    }
    return arr;
}

function playMusicAt(idx) {
    console.log('playMusicAt called with index:', idx);
    const audio = document.getElementById('global-audio');
    const titleEl = document.getElementById('player-title');
    const playBtn = document.getElementById('player-play');
    
    if (!audio || !musicQueue[idx]) {
        console.error('Audio element or track not found', { audio: !!audio, track: !!musicQueue[idx] });
        return;
    }
    
    musicIndex = idx;
    const track = musicQueue[musicIndex];
    if (titleEl) titleEl.textContent = cleanTitle(track.name);
    if (playBtn) playBtn.textContent = '⏳';
    
    const token = getCookie('auth_token');
    
    // Use the /api/media/stream endpoint for all playback to handle auth and external paths
    let streamUrl = `${API_BASE}/media/stream?path=${encodeURIComponent(track.path)}`;
    if (token) {
        streamUrl += '&token=' + token;
    }
    
    console.log('Playing track:', track.name, 'Stream URL:', streamUrl);

    // Reset audio state before loading new src
    audio.pause();
    audio.src = streamUrl;
    audio.load();

    const playPromise = audio.play();
    if (playPromise !== undefined) {
        playPromise.then(() => {
            console.log('Playback started successfully');
            if (playBtn) playBtn.textContent = '⏸';
        }).catch(err => {
            console.error('Audio play error:', err);
            if (playBtn) playBtn.textContent = '▶';
            
            if (err.name === 'NotAllowedError') {
                console.warn('Autoplay blocked. User interaction required.');
            } else if (err.name === 'AbortError') {
                console.log('Playback aborted');
            } else {
                alert('Playback failed: ' + err.message + '. Path: ' + track.path);
            }
        });
    }
}

function musicNext() {
    // Use new music player if available
    if (window.musicPlayer) {
        window.musicPlayer.playNext();
        return;
    }

    // Fallback to old player
    if (!musicQueue.length) return;
    if (musicShuffle) {
        if (!musicShuffleOrder.length) musicShuffleOrder = shuffleOrder(musicQueue.length, musicIndex);
        musicShufflePos = Math.min(musicShufflePos + 1, musicShuffleOrder.length - 1);
        playMusicAt(musicShuffleOrder[musicShufflePos]);
        return;
    }
    playMusicAt((musicIndex + 1) % musicQueue.length);
}

function musicPrev() {
    // Use new music player if available
    if (window.musicPlayer) {
        window.musicPlayer.playPrevious();
        return;
    }

    // Fallback to old player
    if (!musicQueue.length) return;
    if (musicShuffle) {
        musicShufflePos = Math.max(musicShufflePos - 1, 0);
        playMusicAt(musicShuffleOrder[musicShufflePos] ?? musicIndex);
        return;
    }
    playMusicAt((musicIndex - 1 + musicQueue.length) % musicQueue.length);
}

function openPdfViewer(path, title) {
    // Use new eBook reader if available
    if (window.ebookReader) {
        window.ebookReader.open(path, title || 'PDF');
        return;
    }

    // Fallback to simple iframe viewer
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    heading.textContent = title ? String(title) : 'PDF';
    const safeTitle = escapeHtml(title ? String(title) : 'PDF');
    const safePath = escapeHtml(path);
    body.innerHTML = `<iframe class="pdf-frame" src="${safePath}" title="${safeTitle}"></iframe>`;
    modal.classList.remove('hidden');
}

function closeViewer() {
    if (activeVideoProgressInterval) {
        clearInterval(activeVideoProgressInterval);
        activeVideoProgressInterval = null;
    }
    try { updateProgress(activeVideoEl, activeVideoPath, true, { keepalive: true }); } catch (e) {}
    activeVideoEl = null;
    activeVideoPath = null;
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    if (body) body.innerHTML = '';
    if (modal) modal.classList.add('hidden');
    comicPages = [];
    comicIndex = 0;
}

function openImageViewer(path, title) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) return;

    const token = getCookie('auth_token');
    let streamUrl = `${API_BASE}/media/stream?path=${encodeURIComponent(path)}`;
    if (token) streamUrl += '&token=' + token;

    heading.textContent = title ? String(title) : 'Image';
    body.innerHTML = `<div class="image-viewer"><img src="${streamUrl}" style="max-width:100%; max-height:80vh; border-radius:8px;"></div>`;
    modal.classList.remove('hidden');
}

async function openMovieDetails(file) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading || !file?.path) {
        openVideoViewer(file?.path, cleanTitle(file?.name || 'Movie'), file?.progress?.current_time || 0);
        return;
    }

    const baseTitle = file.omdb?.title || file.omdb?.meta?.Title || cleanTitle(file.name || 'Movie');
    const startSeconds = Number(file.progress?.current_time || 0);

    body.innerHTML = `
        <div style="padding: 18px;">
            <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
                <div style="width: 180px; flex: 0 0 180px;">
                    <div style="width:100%; aspect-ratio:2/3; border-radius: 14px; overflow:hidden; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08);">
                        ${file.poster ? `<img src="${file.poster}" alt="${escapeHtml(baseTitle)}" style="width:100%; height:100%; object-fit:cover;">` : `<div style="width:100%; height:100%; display:flex; align-items:center; justify-content:center; color: var(--text-muted); font-weight:700;">MOVIE</div>`}
                    </div>
                </div>
                <div style="flex: 1 1 260px; min-width: 240px;">
                    <div style="font-weight: 900; font-size: 1.25rem; margin-bottom: 8px;">${escapeHtml(baseTitle)}</div>
                    <div id="movie-meta-line" style="color: var(--text-muted); margin-bottom: 10px;"></div>
                    <div id="movie-plot" style="color: #d7dde8; line-height: 1.5; margin-bottom: 14px;"></div>
                    ${startSeconds > 10 ? `<div style="color: var(--text-muted); margin-bottom: 12px;">Resume at ${escapeHtml(formatClock(startSeconds))}</div>` : ``}
                    <div style="display:flex; gap:10px; flex-wrap:wrap;">
                        <button class="primary" id="movie-play-btn">${startSeconds > 10 ? 'Resume' : 'Play'}</button>
                        <button class="secondary" id="movie-play-from-start-btn">Play From Start</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    const token = getCookie('auth_token');
    let streamUrl = `${API_BASE}/media/stream?path=${encodeURIComponent(file.path)}`;
    if (token) streamUrl += '&token=' + token;
    const fullUrl = window.location.origin + streamUrl;
    const vlcUrl = `vlc://${fullUrl.replace(/^https?:\/\//, '')}`;

    heading.innerHTML = `
        <div style="display:flex; align-items:center; gap:12px; width:100%;">
            <span style="flex-grow:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(baseTitle)}</span>
            <div class="external-player-btns" style="display:flex; gap:8px;">
                <a href="${streamUrl}&download=true" class="player-action-btn" title="Download for offline playback">
                    <span>💾</span><span class="btn-text">Download</span>
                </a>
                <a href="${vlcUrl}" class="player-action-btn vlc-btn" title="Open in VLC (Fixes playback issues)">
                    <span>🧡</span><span class="btn-text">VLC</span>
                </a>
            </div>
        </div>
    `;

    modal.classList.remove('hidden');

    const applyMeta = (data) => {
        const year = data?.year || data?.meta?.Year;
        const rated = data?.rated || data?.meta?.Rated;
        const runtime = data?.runtime || data?.meta?.Runtime;
        const genre = data?.genre || data?.meta?.Genre;
        const parts = [year, rated, runtime, genre].filter(v => v && v !== 'N/A');
        const line = document.getElementById('movie-meta-line');
        if (line) line.textContent = parts.join(' • ');

        const plot = data?.plot || data?.meta?.Plot;
        const plotEl = document.getElementById('movie-plot');
        if (plotEl) plotEl.textContent = plot && plot !== 'N/A' ? plot : '';

        const poster = data?.poster || data?.meta?.Poster;
        if (!file.poster && poster && poster !== 'N/A') file.poster = poster;
    };

    if (file.omdb) {
        applyMeta(file.omdb);
    } else {
        document.getElementById('movie-meta-line')?.replaceChildren();
        document.getElementById('movie-plot')?.replaceChildren();
        const meta = await fetchMovieMeta(file);
        if (meta) applyMeta(meta);
    }

    document.getElementById('movie-play-btn')?.addEventListener('click', () => {
        openVideoViewer(file.path, baseTitle, startSeconds);
    });
    document.getElementById('movie-play-from-start-btn')?.addEventListener('click', () => {
        openVideoViewer(file.path, baseTitle, 0);
    });
}

function openVideoViewer(path, title, startSeconds = 0) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    const token = getCookie('auth_token');
    let streamUrl = `${API_BASE}/media/stream?path=${encodeURIComponent(path)}`;
    if (token) streamUrl += '&token=' + token;

    // Build the full URL for external players
    const fullUrl = window.location.origin + streamUrl;
    const vlcUrl = `vlc://${fullUrl.replace(/^https?:\/\//, '')}`;

    // Sanitize title and filename
    const safeTitle = title ? escapeHtml(String(title)) : 'Video';
    const extMatch = path.match(/\.([a-z0-9]+)$/i);
    const safeExt = extMatch ? extMatch[0] : '.mp4';
    const downloadName = (title ? String(title).replace(/[^a-z0-9]/gi, '_') : 'video') + safeExt;

    heading.innerHTML = `
        <div style="display:flex; align-items:center; gap:12px; width:100%;">
            <span style="flex-grow:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${safeTitle}</span>
            <div class="external-player-btns" style="display:flex; gap:8px;">
                <a href="${streamUrl}&download=true" class="player-action-btn" title="Download for offline playback">
                    <span>💾</span><span class="btn-text">Download</span>
                </a>
                <a href="${vlcUrl}" class="player-action-btn vlc-btn" title="Open in VLC (Fixes playback issues)">
                    <span>🧡</span><span class="btn-text">VLC</span>
                </a>
            </div>
        </div>
    `;
    body.innerHTML = '';

    console.log('Opening video:', path, 'at', streamUrl);

    const videoWrap = document.createElement('div');
    videoWrap.style.position = 'relative';
    videoWrap.style.width = '100%';
    videoWrap.style.height = '100%';

    const video = document.createElement('video');
    video.className = 'video-frame';
    video.controls = true;
    video.preload = 'auto';  // Changed from 'metadata' to 'auto' to ensure audio tracks load
    video.crossOrigin = 'anonymous';  // Enable CORS for better compatibility
    video.src = streamUrl;
    video.addEventListener('timeupdate', () => updateProgress(video, path));
    video.addEventListener('pause', () => { try { updateProgress(video, path, true); } catch (e) {} });
    video.addEventListener('seeked', () => { try { updateProgress(video, path, true); } catch (e) {} });
    video.addEventListener('play', () => {
        if (activeVideoProgressInterval) clearInterval(activeVideoProgressInterval);
        activeVideoProgressInterval = setInterval(() => {
            try { updateProgress(video, path); } catch (e) {}
        }, 5000);
    });
    video.addEventListener('ended', () => {
        if (activeVideoProgressInterval) clearInterval(activeVideoProgressInterval);
        activeVideoProgressInterval = null;
    });
    video.addEventListener('loadedmetadata', () => checkResume(video, path, Number(startSeconds || 0)), { once: true });

    // Auto-detect and load subtitles
    loadSubtitlesForVideo(video, path);

    prefetchAndQueueNextEpisode(path);

    // Auto-play next episode when current one ends
    video.addEventListener('ended', async () => {
        try { await updateProgress(video, path, true); } catch (e) {}
        await handleVideoEnded(path, title);
    });

    activeVideoEl = video;
    activeVideoPath = path;
    if (!playbackHeartbeatInstalled) {
        playbackHeartbeatInstalled = true;
        window.addEventListener('pagehide', () => {
            try { updateProgress(activeVideoEl, activeVideoPath, true, { keepalive: true }); } catch (e) {}
        });
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState !== 'hidden') return;
            try { updateProgress(activeVideoEl, activeVideoPath, true, { keepalive: true }); } catch (e) {}
        });
    }

    videoWrap.appendChild(video);
    body.appendChild(videoWrap);
    modal.classList.remove('hidden');
}

async function openComicViewer(path, title) {
    // Use new eBook reader if available
    if (window.ebookReader) {
        window.ebookReader.open(path, title || 'Comic');
        return;
    }

    // Fallback to old comic viewer
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    heading.textContent = title ? String(title) : 'Comic';
    body.innerHTML = `<div class="loading" style="padding:40px;">
        <div class="logo animate-fade" style="font-size:1.5rem; margin-bottom:10px;">Loading Comic...</div>
        <div class="progress-container" style="max-width:200px; margin:0 auto;"><div class="progress-fill" style="width:100%; animation: pulse 1.5s infinite;"></div></div>
    </div>`;
    modal.classList.remove('hidden');
    comicZoom = 1;

    try {
        const res = await fetch(`${API_BASE}/media/books/comic/pages?path=${encodeURIComponent(path)}`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data || {});
            body.innerHTML = `<div style="padding:40px; text-align:center;">
                <div style="font-size:3rem; margin-bottom:20px;">⚠️</div>
                <div style="color:#ddd; font-size:1.1rem;">${escapeHtml(msg || 'Failed to load comic.')}</div>
            </div>`;
            return;
        }
        comicPages = Array.isArray(data.pages) ? data.pages : [];
        comicIndex = 0;

        if (comicPages.length === 0) {
            body.innerHTML = `<div style="padding:40px; text-align:center; color:#ddd;">No pages found in this comic.</div>`;
            return;
        }

        renderComicPage();
    } catch (e) {
        body.innerHTML = `<div style="padding:40px; text-align:center; color:#ddd;">Failed to connect to server.</div>`;
    }
}

function renderComicPage() {
    const body = document.getElementById('viewer-body');
    if (!body) return;
    if (!comicPages || comicPages.length === 0) return;
    comicIndex = Math.max(0, Math.min(comicIndex, comicPages.length - 1));

    const page = comicPages[comicIndex];
    let url = page?.path || page?.url || '';
    const token = getCookie('auth_token');
    if (token && url.startsWith('/data/')) {
        url += (url.includes('?') ? '&' : '?') + 'token=' + token;
    }
    const total = comicPages.length;
    const idx = comicIndex + 1;

    body.innerHTML = `
        <div class="comic-viewer">
            <div class="comic-controls">
                <button class="comic-btn" onclick="comicPrev()" ${comicIndex === 0 ? 'disabled' : ''}>
                    <span>←</span> Previous
                </button>
                <div class="comic-indicator">${idx} / ${total}</div>
                <button class="comic-btn primary" onclick="comicNext()" ${comicIndex >= total - 1 ? 'disabled' : ''}>
                    Next <span>→</span>
                </button>
            </div>
            <div class="comic-stage" id="comic-stage">
                <div class="comic-page-wrapper" id="comic-wrapper" style="transform: scale(${comicZoom})">
                    <img class="comic-page" src="${escapeHtml(url)}" alt="Page ${idx}" 
                         style="max-width: ${comicFit === 'width' ? '100%' : 'none'}; 
                                max-height: ${comicFit === 'height' ? '80vh' : 'none'};">
                </div>
                <div class="zoom-controls">
                    <button class="zoom-btn" onclick="changeComicZoom(0.1)" title="Zoom In">+</button>
                    <button class="zoom-btn" onclick="changeComicZoom(-0.1)" title="Zoom Out">-</button>
                    <button class="zoom-btn" onclick="toggleComicFit()" title="Toggle Fit">
                        ${comicFit === 'width' ? '↕️' : '↔️'}
                    </button>
                </div>
            </div>
        </div>
    `;

    // Preload next page
    if (comicIndex < total - 1) {
        const nextImg = new Image();
        let nextUrl = comicPages[comicIndex + 1].path || comicPages[comicIndex + 1].url;
        if (token && nextUrl.startsWith('/data/')) {
            nextUrl += (nextUrl.includes('?') ? '&' : '?') + 'token=' + token;
        }
        nextImg.src = nextUrl;
    }
}

function changeComicZoom(delta) {
    comicZoom = Math.max(0.5, Math.min(3, comicZoom + delta));
    const wrapper = document.getElementById('comic-wrapper');
    if (wrapper) wrapper.style.transform = `scale(${comicZoom})`;
}

function toggleComicFit() {
    comicFit = comicFit === 'width' ? 'height' : 'width';
    renderComicPage();
}

function comicPrev() {
    if (comicIndex > 0) {
        comicIndex -= 1;
        comicZoom = 1;
        renderComicPage();
        document.getElementById('comic-stage')?.scrollTo(0, 0);
    }
}

function comicNext() {
    if (comicPages && comicIndex < comicPages.length - 1) {
        comicIndex += 1;
        comicZoom = 1;
        renderComicPage();
        document.getElementById('comic-stage')?.scrollTo(0, 0);
    }
}

document.addEventListener('keydown', (e) => {
    const modal = document.getElementById('viewer-modal');
    if (!modal || modal.classList.contains('hidden')) return;
    if (e.key === 'Escape') closeViewer();
    if (e.key === 'ArrowLeft') comicPrev();
    if (e.key === 'ArrowRight') comicNext();
});

async function loadShowsLibrary() {
    const container = document.getElementById('shows-list');
    if (!container) return;

    container.innerHTML = '<div class="loading">Loading...</div>';
    try {
        if (!showsLibraryCache) {
            console.log('[Shows] Fetching shows library from API...');
            const res = await fetch(`${API_BASE}/media/shows/library`, {
                headers: getAuthHeaders()
            });
            console.log('[Shows] API response status:', res.status);

            if (res.status === 401) { logout(); return; }

            if (!res.ok) {
                throw new Error(`API returned status ${res.status}`);
            }

            const data = await res.json();
            console.log('[Shows] API response:', data);
            console.log('[Shows] Number of shows:', data.shows ? data.shows.length : 0);

            showsLibraryCache = data.shows || [];

            if (showsLibraryCache.length === 0) {
                console.warn('[Shows] No shows returned from API. Database may be empty or library needs rebuilding.');
            }

            // Populate filters if they are empty
            updateFilters('shows');
        } else {
            console.log('[Shows] Using cached shows:', showsLibraryCache.length);
        }
        if (!restoreShowsState()) {
            showsState = showsState || { level: 'shows', showName: null, seasonName: null };
        }
        renderShows();
    } catch (e) {
        console.error('[Shows] Error loading shows:', e);
        container.innerHTML = `<div class="error-state"><p>Error loading shows</p><p style="color:var(--text-muted);font-size:0.9em;">${escapeHtml(e.message)}</p><button onclick="showsLibraryCache=null;loadShowsLibrary()" class="secondary" style="margin-top:10px;">Retry</button></div>`;
    }
}

function renderShowsLevel() {
    const filterBar = document.getElementById('shows-filter-bar');
    if (filterBar) filterBar.style.display = 'none';
    
    const breadcrumb = document.getElementById('shows-breadcrumb');
    if (breadcrumb) breadcrumb.style.display = 'block';
    
    const continueSection = document.getElementById('shows-continue');
    if (continueSection) continueSection.style.display = 'block';
    
    renderShows();
}

function setShowsLevel(level, showName = null, seasonName = null) {
    showsState = { level, showName, seasonName };
    saveShowsState();
    
    if (level === 'shows') {
        const filterBar = document.getElementById('shows-filter-bar');
        if (filterBar) filterBar.style.display = 'flex';
        
        const breadcrumb = document.getElementById('shows-breadcrumb');
        if (breadcrumb) breadcrumb.style.display = 'none';
        
        const continueSection = document.getElementById('shows-continue');
        if (continueSection) continueSection.style.display = 'block';
        
        showsLibraryCache = null; // Clear cache for a fresh fetch
        loadShowsLibrary();
    } else {
        renderShowsLevel();
    }
}

function shouldContinue(progress) {
    if (!progress) return false;
    const t = Number(progress.current_time || 0);
    const d = Number(progress.duration || 0);
    if (!Number.isFinite(t)) return false;
    if (!Number.isFinite(d) || d <= 0) return t > 10;
    return t > 10 && (d - t) > 10;
}

function applyLocalProgressUpdate(filePath, currentTime, duration) {
    const t = Number(currentTime || 0);
    const d = Number(duration || 0);
    if (!filePath || !Number.isFinite(t) || t < 0) return;
    const nowIso = new Date().toISOString();

    for (const cat of ['movies', 'shows']) {
        const state = mediaPageState?.[cat];
        const items = state?.items;
        if (!Array.isArray(items) || items.length === 0) continue;
        const item = items.find(x => x?.path === filePath);
        if (!item) continue;
        const prev = item.progress && typeof item.progress === 'object' ? item.progress : {};
        const next = { ...prev, current_time: t, last_played: nowIso };
        if (Number.isFinite(d) && d > 0) next.duration = d;
        item.progress = next;
    }

    if (Array.isArray(showsLibraryCache)) {
        for (const show of showsLibraryCache) {
            const seasons = show?.seasons;
            if (!Array.isArray(seasons)) continue;
            for (const season of seasons) {
                const episodes = season?.episodes;
                if (!Array.isArray(episodes)) continue;
                for (const ep of episodes) {
                    if (!ep || ep.path !== filePath) continue;
                    const prev = ep.progress && typeof ep.progress === 'object' ? ep.progress : {};
                    const next = { ...prev, current_time: t, last_played: nowIso };
                    if (Number.isFinite(d) && d > 0) next.duration = d;
                    ep.progress = next;
                    show.last_played = nowIso;
                    season.last_played = nowIso;
                    return;
                }
            }
        }
    }
}

function collectContinueEpisodes(showName = null) {
    if (!showsLibraryCache) return [];
    const out = [];
    for (const show of showsLibraryCache) {
        if (showName && show.name !== showName) continue;
        for (const season of (show.seasons || [])) {
            for (const ep of (season.episodes || [])) {
                if (shouldContinue(ep.progress)) {
                    out.push({
                        showName: show.name,
                        seasonName: season.name,
                        name: ep.name,
                        path: ep.path,
                        progress: ep.progress,
                        poster: ep.poster
                    });
                }
            }
        }
    }

    out.sort((a, b) => {
        const at = Date.parse(a.progress?.last_played || '') || 0;
        const bt = Date.parse(b.progress?.last_played || '') || 0;
        if (bt !== at) return bt - at;
        return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
    });

    return out;
}

function renderShows() {
    const container = document.getElementById('shows-list');
    const breadcrumb = document.getElementById('shows-breadcrumb');
    const searchInput = document.getElementById('shows-search');
    const continueEl = document.getElementById('shows-continue');
    if (!container) return;

    const q = (searchInput?.value || '').trim().toLowerCase();
    container.innerHTML = '';
    if (continueEl) continueEl.innerHTML = '';

    const getDelBtn = (path) => path ? `<button class="delete-btn" style="position:absolute;top:5px;right:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1.2em;line-height:1;" title="Delete" onclick="event.stopPropagation(); deleteItem('${escapeHtml(path)}')">×</button>` : '';
    const getRenameBtn = (path, name) => path ? `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;" title="Rename" onclick="event.stopPropagation(); promptRenameShowPart('${escapeHtml(path)}', '${escapeHtml(name)}')">✏️</button>` : '';

    if (!showsLibraryCache || showsLibraryCache.length === 0) {
        container.innerHTML = '<p>No shows found.</p>';
        if (breadcrumb) breadcrumb.innerHTML = '';
        return;
    }

    if (breadcrumb) {
        breadcrumb.innerHTML = '';

        const showsLink = document.createElement('a');
        showsLink.href = '#';
        showsLink.textContent = 'Shows';
        showsLink.onclick = (e) => { e.preventDefault(); setShowsLevel('shows'); };
        breadcrumb.appendChild(showsLink);

        if (showsState.showName) {
            breadcrumb.append(' / ');
            const showLink = document.createElement('a');
            showLink.href = '#';
            showLink.textContent = showsState.showName;
            showLink.onclick = (e) => { e.preventDefault(); setShowsLevel('seasons', showsState.showName, null); };
            breadcrumb.appendChild(showLink);
        }

        if (showsState.seasonName) {
            breadcrumb.append(' / ');
            const seasonLabel = document.createElement('span');
            seasonLabel.textContent = showsState.seasonName;
            breadcrumb.appendChild(seasonLabel);
        }
    }

    if (showsState.level === 'shows') {
        const genre = document.getElementById('shows-genre')?.value || '';
        const year = document.getElementById('shows-year')?.value || '';
        const sort = document.getElementById('shows-sort')?.value || 'name';

        let list = [...showsLibraryCache];

        // Filter by search
        if (q) {
            list = list.filter(s => s.name.toLowerCase().includes(q));
        }

        // Filter by genre
        if (genre) {
            list = list.filter(s => (s.genres || []).includes(genre));
        }

        // Filter by year
        if (year) {
            list = list.filter(s => (s.years || []).includes(year));
        }

        // Sort
        list.sort((a, b) => {
            if (sort === 'newest') return (b.mtime || 0) - (a.mtime || 0);
            if (sort === 'recently_played') {
                const at = Date.parse(a.last_played || '') || 0;
                const bt = Date.parse(b.last_played || '') || 0;
                return bt - at;
            }
            if (sort === 'top_watched') return (b.play_count || 0) - (a.play_count || 0);
            return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
        });

        if (continueEl && !q && !genre && !year) {
            const cont = collectContinueEpisodes().slice(0, 6);
            if (cont.length > 0) {
                const title = document.createElement('h3');
                title.textContent = 'Continue Watching';
                continueEl.appendChild(title);

                const grid = document.createElement('div');
                grid.className = 'media-grid';

                cont.forEach(item => {
                    const div = document.createElement('div');
                    div.className = 'media-item media-card';
                    div.style.cursor = 'pointer';
                    
                    const start = Number(item.progress?.current_time || 0);
                    const posterHtml = item.poster 
                        ? `<img class="poster-img" src="${item.poster}" loading="lazy" alt="${escapeHtml(item.name)}">`
                        : `<div class="poster-placeholder"></div>`;

                    let progressHtml = '';
                    if (item.progress?.duration) {
                        const pct = (Number(item.progress.current_time || 0) / Number(item.progress.duration || 1)) * 100;
                        progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
                    }

                    const subtitle = `${escapeHtml(item.showName)} • ${escapeHtml(item.seasonName)}`;

                    div.innerHTML = `
                        <div class="poster-shell">
                            ${posterHtml}
                            <div class="media-info">
                                <h3>${escapeHtml(item.name)}</h3>
                                <div class="media-details">${subtitle}</div>
                            </div>
                            <button class="poster-play">Resume</button>
                        </div>
                        <div class="card-meta">
                            <div style="color:#aaa;font-size:0.85em;margin-bottom:4px;">${subtitle}</div>
                            <div class="card-title">${escapeHtml(item.name)}</div>
                        </div>
                        ${progressHtml}
                    `;

                    div.addEventListener('click', (e) => {
                        if (e.target.closest('button')) return;
                        openVideoViewer(item.path, item.name, start);
                    });

                    const playBtn = div.querySelector('.poster-play');
                    if (playBtn) {
                        playBtn.addEventListener('click', (e) => {
                            e.stopPropagation();
                            openVideoViewer(item.path, item.name, start);
                        });
                    }

                    grid.appendChild(div);
                });

                continueEl.appendChild(grid);
            }
        }

        list.forEach(show => {
            const div = document.createElement('div');
            div.className = 'media-item show-card';
            const contEp = collectContinueEpisodes(show.name)[0] || null;
            const poster = show.poster
                ? `<img class="show-poster" src="${show.poster}" loading="lazy" alt="${escapeHtml(show.name)}">`
                : `<div class="show-poster" style="background: radial-gradient(circle at 30% 20%, rgba(229, 9, 20, 0.35), rgba(20, 20, 20, 0.95) 60%);"></div>`;
            
            const subtitle = contEp ? `Continue • ${escapeHtml(contEp.seasonName || '')}` : `${(show.seasons || []).length} season(s)`;
            const resumeBtn = contEp ? `<button class="poster-play">Resume</button>` : '';

            let progressHtml = '';
            const duration = Number(contEp?.progress?.duration || 0);
            if (contEp?.progress && Number(contEp.progress.current_time || 0) > 0 && Number.isFinite(duration) && duration > 0) {
                const pct = (Number(contEp.progress.current_time || 0) / duration) * 100;
                progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
            }
            
            div.innerHTML = `
                ${getDelBtn(show.path)}
                ${getRenameBtn(show.path, show.name)}
                <div class="poster-shell">
                    ${poster}
                    <div class="media-info">
                        <h3>${escapeHtml(show.name)}</h3>
                        <div class="media-details">${subtitle}</div>
                    </div>
                    ${resumeBtn}
                </div>
                <div class="show-meta">
                    <h3 class="show-title">${escapeHtml(show.name)}</h3>
                    <div class="show-subtitle">${subtitle}</div>
                    ${contEp ? `<button class="secondary show-resume-inline" style="width:100%; margin-top:10px;">Resume</button>` : ''}
                </div>
                ${progressHtml}
            `;
            div.style.cursor = 'pointer';
            div.onclick = () => setShowsLevel('seasons', show.name, null);
            const resume = div.querySelector('.poster-play');
            if (resume && contEp) {
                const start = Number(contEp.progress?.current_time || 0);
                resume.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openVideoViewer(contEp.path, contEp.name, start);
                });
            }
            const resumeInline = div.querySelector('.show-resume-inline');
            if (resumeInline && contEp) {
                const start = Number(contEp.progress?.current_time || 0);
                resumeInline.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openVideoViewer(contEp.path, contEp.name, start);
                });
            }
            container.appendChild(div);
        });
        return;
    }

    const show = showsLibraryCache.find(s => s.name === showsState.showName);
    if (!show) {
        setShowsLevel('shows');
        return;
    }

    if (showsState.level === 'seasons') {
        const seasons = q ? show.seasons.filter(s => s.name.toLowerCase().includes(q)) : show.seasons;
        seasons.forEach(season => {
            const div = document.createElement('div');
            div.className = 'media-item media-card';
            div.style.cursor = 'pointer';
            
            const posterHtml = season.poster 
                ? `<img class="poster-img" src="${season.poster}" loading="lazy" alt="${escapeHtml(season.name)}">`
                : `<div class="poster-placeholder"></div>`;

            const contEp = Array.isArray(season.episodes) ? season.episodes.find(ep => shouldContinue(ep?.progress)) : null;
            const subtitle = contEp ? `Continue • ${escapeHtml(contEp.name)}` : `${season.episodes.length} episode(s)`;

            let progressHtml = '';
            const duration = Number(contEp?.progress?.duration || 0);
            if (contEp?.progress && Number(contEp.progress.current_time || 0) > 0 && Number.isFinite(duration) && duration > 0) {
                const pct = (Number(contEp.progress.current_time || 0) / duration) * 100;
                progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
            }
            const resumeBtn = contEp ? `<button class="poster-play">Resume</button>` : '';

            div.innerHTML = `
                ${getDelBtn(season.path)}
                ${getRenameBtn(season.path, season.name)}
                <div class="poster-shell">
                    ${posterHtml}
                    <div class="media-info">
                        <h3>${escapeHtml(season.name)}</h3>
                        <div class="media-details">${subtitle}</div>
                    </div>
                    ${resumeBtn}
                </div>
                <div class="card-meta">
                    <div class="card-title">${escapeHtml(season.name)}</div>
                    <div class="card-subtitle">${subtitle}</div>
                    ${contEp ? `<button class="secondary season-resume-inline" style="width:100%; margin-top:10px;">Resume</button>` : ''}
                </div>
                ${progressHtml}
            `;
            div.onclick = () => setShowsLevel('episodes', show.name, season.name);
            const resume = div.querySelector('.poster-play');
            if (resume && contEp) {
                const start = Number(contEp.progress?.current_time || 0);
                resume.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openVideoViewer(contEp.path, contEp.name, start);
                });
            }
            const resumeInline = div.querySelector('.season-resume-inline');
            if (resumeInline && contEp) {
                const start = Number(contEp.progress?.current_time || 0);
                resumeInline.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openVideoViewer(contEp.path, contEp.name, start);
                });
            }
            container.appendChild(div);
        });
        return;
    }

    const season = show.seasons.find(s => s.name === showsState.seasonName);
    if (!season) {
        setShowsLevel('seasons', show.name, null);
        return;
    }

    const episodes = q ? season.episodes.filter(e => e.name.toLowerCase().includes(q)) : season.episodes;
    if (episodes.length === 0) {
        container.innerHTML = '<p>No episodes found.</p>';
        return;
    }

        episodes.forEach(ep => {
            const div = document.createElement('div');
            div.className = 'media-item media-card';
            div.style.cursor = 'pointer';
        
        const posterHtml = ep.poster 
            ? `<img class="poster-img" src="${ep.poster}" loading="lazy" alt="${escapeHtml(ep.name)}">`
            : `<div class="poster-placeholder"></div>`;

        let progressHtml = '';
        const duration = Number(ep?.progress?.duration || 0);
        if (ep.progress && ep.progress.current_time > 0 && Number.isFinite(duration) && duration > 0) {
            const pct = (Number(ep.progress.current_time || 0) / duration) * 100;
            progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
        }

        const subtitle = `${escapeHtml(show.name)} • ${escapeHtml(season.name)}`;
        const playLabel = shouldContinue(ep.progress) ? 'Resume' : 'Play';

        div.innerHTML = `
            ${getDelBtn(ep.path)}
            ${getRenameBtn(ep.path, ep.name)}
            <div class="poster-shell">
                ${posterHtml}
                <div class="media-info">
                    <h3>${escapeHtml(ep.name)}</h3>
                    <div class="media-details">${subtitle}</div>
                </div>
                <button class="poster-play">${playLabel}</button>
            </div>
            <div class="card-meta">
                <div class="card-title">${escapeHtml(ep.name)}</div>
                <div class="card-subtitle">${subtitle}</div>
            </div>
            ${progressHtml}
        `;

        div.addEventListener('click', (e) => {
            if (e.target.closest('button')) return;
            openVideoViewer(ep.path, ep.name, ep.progress?.current_time || 0);
        });

        const btn = div.querySelector('.poster-play');
        if (btn) {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                openVideoViewer(ep.path, ep.name, ep.progress?.current_time || 0);
            });
        }

        container.appendChild(div);
    });
}

function escapeHtml(str) {
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

async function updateProgress(mediaElement, filePath, force = false, opts = null) {
    if (!mediaElement || !filePath) return;
    
    // Only update every 5 seconds or if we're at the very end
    const isNearEnd = mediaElement.duration > 0 && (mediaElement.duration - mediaElement.currentTime) < 5;
    if (!force && Math.abs(mediaElement.currentTime - (mediaElement.lastTime || 0)) < 5 && !isNearEnd) return;
    
    mediaElement.lastTime = mediaElement.currentTime;

    try {
        const duration = Number.isFinite(mediaElement.duration) && mediaElement.duration > 0 ? mediaElement.duration : null;
        const payload = {
            file_path: filePath,
            current_time: mediaElement.currentTime
        };
        if (duration !== null) payload.duration = duration;
        const res = await fetch(`${API_BASE}/media/progress`, {
            method: 'POST',
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json'
            },
            keepalive: Boolean(opts && opts.keepalive),
            body: JSON.stringify(payload)
        });
        if (res.status === 401) { logout(); }
        else if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            console.warn('Progress update failed:', res.status, data);
        } else if (!progressDebugSent.has(filePath)) {
            applyLocalProgressUpdate(filePath, payload.current_time, payload.duration);
            progressDebugSent.add(filePath);
            console.log('[Progress] Saved:', filePath);
        } else {
            applyLocalProgressUpdate(filePath, payload.current_time, payload.duration);
        }
        if (force) {
            const isVisible = (id) => {
                const el = document.getElementById(id);
                return el && !el.classList.contains('hidden') && el.style.display !== 'none';
            };
            if (isVisible('movies')) {
                const st = getPageState('movies');
                renderMediaListPaged('movies', st.items, st.hasMore);
            }
            if (isVisible('shows')) {
                renderShows();
            }
        }
    } catch (e) {
        console.error('Failed to update progress:', e);
    }
}

function showResumePrompt(mediaElement, filePath, savedTime) {
    const container = mediaElement?.parentElement || document.getElementById('viewer-body') || document.body;
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position:absolute;
        inset:0;
        display:flex;
        align-items:center;
        justify-content:center;
        background: rgba(0,0,0,0.55);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        z-index: 50;
        padding: 16px;
    `;

    const box = document.createElement('div');
    box.style.cssText = `
        width: 100%;
        max-width: 420px;
        background: rgba(20, 20, 28, 0.92);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 18px;
        box-shadow: 0 18px 50px rgba(0,0,0,0.55);
        padding: 18px 18px 16px 18px;
        text-align: center;
    `;

    const resumeFrom = formatClock(savedTime);
    box.innerHTML = `
        <div style="font-weight:800; font-size:1.1rem; margin-bottom:6px;">Resume playback?</div>
        <div style="color: var(--text-muted); margin-bottom:14px;">Saved position: ${escapeHtml(resumeFrom)}</div>
        <div style="display:flex; gap:10px; justify-content:center; flex-wrap:wrap;">
            <button class="secondary" id="resume-startover-btn" style="min-width:140px;">Start Over</button>
            <button class="primary" id="resume-continue-btn" style="min-width:140px;">Resume</button>
        </div>
    `;

    overlay.appendChild(box);
    container.appendChild(overlay);

    const cleanup = () => {
        try { overlay.remove(); } catch {}
    };

    const setProgressNow = async (time, duration) => {
        try {
            const payload = {
                file_path: filePath,
                current_time: time
            };
            const d = Number.isFinite(duration) && duration > 0 ? duration : null;
            if (d !== null) payload.duration = d;
            await fetch(`${API_BASE}/media/progress`, {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
        } catch {}
    };

    overlay.querySelector('#resume-continue-btn')?.addEventListener('click', async () => {
        cleanup();
        try {
            mediaElement.currentTime = savedTime;
        } catch {}
        mediaElement.lastTime = null;
        const p = mediaElement.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
    });

    overlay.querySelector('#resume-startover-btn')?.addEventListener('click', async () => {
        cleanup();
        try {
            mediaElement.currentTime = 0;
        } catch {}
        mediaElement.lastTime = null;
        await setProgressNow(0, mediaElement.duration);
        const p = mediaElement.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
    });
}

function checkResume(mediaElement, filePath, savedTime) {
    if (savedTime > 10 && (mediaElement.duration - savedTime) > 10) {
        try { mediaElement.pause(); } catch {}
        showResumePrompt(mediaElement, filePath, savedTime);
    }
}

async function loadResume() {
    const container = document.getElementById('resume-list');
    const section = document.getElementById('resume-section');
    if (!container) return;
    
    try {
        const res = await fetch(`${API_BASE}/media/resume?limit=12`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        const watching = Array.isArray(data.items) ? data.items : [];
        
        if (watching.length > 0) {
            section.classList.remove('hidden');
            container.innerHTML = '';
            watching.forEach(file => {
                 const div = document.createElement('div');
                 div.className = 'media-item media-card';
                 div.style.cursor = 'pointer';
                 const label = file.type ? escapeHtml(file.type) : 'Video';
                 
                 const posterHtml = file.poster 
                    ? `<img class="poster-img" src="${file.poster}" loading="lazy" alt="${escapeHtml(file.name)}">`
                    : `<div class="poster-placeholder"></div>`;

                 const renameBtnHtml = `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;" title="Rename">✏️</button>`;

                 let progressHtml = '';
                 if (file.progress && file.progress.duration) {
                    const pct = (file.progress.current_time / file.progress.duration) * 100;
                    progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
                 }

                 div.innerHTML = `
                    ${renameBtnHtml}
                    <div class="poster-shell">
                        ${posterHtml}
                        <div class="media-info">
                            <h3>${escapeHtml(cleanTitle(file.name))}</h3>
                            <div class="media-details">${label}</div>
                        </div>
                        <button class="poster-play">Play</button>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(cleanTitle(file.name))}</div>
                        <div class="card-subtitle">${label}</div>
                    </div>
                    ${progressHtml}
                 `;
                 
                 div.addEventListener('click', (e) => {
                    if (e.target.closest('button')) return;
                    openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0);
                 });

                 const btn = div.querySelector('.poster-play');
                 if (btn) {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openVideoViewer(file.path, cleanTitle(file.name), file.progress?.current_time || 0);
                    });
                 }

                 const renameBtn = div.querySelector('.rename-btn-card');
                 if (renameBtn) {
                    renameBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        await promptRename(file.path, file.name, loadResume);
                    });
                 }

                 container.appendChild(div);
            });
        } else {
            section.classList.add('hidden');
        }

    } catch(e) {
        console.error(e);
    }
}

async function loadRecent() {
    const container = document.getElementById('recent-list');
    const section = document.getElementById('recent-section');
    if (!container) return;

    try {
        const [mRes, sRes] = await Promise.all([
            fetch(`${API_BASE}/media/library/movies?sort=newest&limit=6`, { headers: getAuthHeaders() }),
            fetch(`${API_BASE}/media/library/shows?sort=newest&limit=6`, { headers: getAuthHeaders() })
        ]);

        const mData = await mRes.json();
        const sData = await sRes.json();

        const movies = (mData.items || []).map(m => ({...m, category: 'movies'}));
        const shows = (sData.items || []).map(s => ({...s, category: 'shows'}));

        const all = [...movies, ...shows].sort((a, b) => {
            return new Date(b.mtime) - new Date(a.mtime);
        }).slice(0, 12);

        if (all.length > 0) {
            section.classList.remove('hidden');
            container.innerHTML = '';
            
            all.forEach(item => {
                const div = document.createElement('div');
                div.className = 'media-item media-card';
                div.style.cursor = 'pointer';
                
                const title = item.category === 'movies' ? (item.omdb?.title || cleanTitle(item.name)) : item.name;
                const subtitle = item.category === 'movies' ? 'Movie' : 'TV Show';
                const poster = item.poster 
                    ? `<img class="poster-img" src="${item.poster}" loading="lazy" alt="${escapeHtml(title)}">`
                    : `<div class="poster-placeholder"></div>`;

                div.innerHTML = `
                    <div class="poster-shell">
                        ${poster}
                        <div class="media-info">
                            <h3>${escapeHtml(title)}</h3>
                            <div class="media-details">${subtitle}</div>
                        </div>
                    </div>
                    <div class="card-meta">
                        <div class="card-title">${escapeHtml(title)}</div>
                        <div class="card-subtitle">${subtitle}</div>
                    </div>
                `;

                div.addEventListener('click', () => {
                    if (item.category === 'movies') {
                        openVideoViewer(item.path, cleanTitle(item.name), item.progress?.current_time || 0);
                    } else {
                        showSection('shows');
                        setShowsLevel('seasons', item.name);
                    }
                });
                container.appendChild(div);
            });
        } else {
            section.classList.add('hidden');
        }
    } catch (e) {
        console.error("Failed to load recent", e);
    }
}

const uploadQueue = [];
let activeUploads = [];
let wifiEnabled = true;

async function loadWifiStatus() {
    try {
        const res = await fetch(`${API_BASE}/system/wifi/status`, { headers: getAuthHeaders() });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        
        const btn = document.getElementById('wifi-toggle-btn');
        const text = document.getElementById('wifi-status-text');
        const details = document.getElementById('wifi-connection-details');
        const icon = document.getElementById('wifi-status-icon');
        
        if (btn && text) {
            if (data.status === 'unsupported') {
                btn.disabled = true;
                btn.textContent = 'Unsupported';
                text.textContent = 'Status: Unsupported';
                if (details) details.textContent = 'Only works on Linux/RPi';
                return;
            }
            
            wifiEnabled = data.enabled;
            btn.textContent = wifiEnabled ? 'Disable Wi-Fi' : 'Enable Wi-Fi';
            btn.className = wifiEnabled ? 'danger' : 'primary';
            text.textContent = `Status: ${wifiEnabled ? 'Enabled' : 'Disabled'}`;
            if (icon) icon.textContent = wifiEnabled ? '📡' : '🚫';

            // If enabled, also get detailed info
            if (wifiEnabled) {
                const infoRes = await fetch(`${API_BASE}/system/wifi/info`, { headers: getAuthHeaders() });
                if (infoRes.ok) {
                    const info = await infoRes.json();
                    if (details) {
                        if (info.mode === 'wifi' && info.ssid) {
                            let detailStr = `Connected to: <strong>${info.ssid}</strong>`;
                            if (info.ip) detailStr += ` • IP: ${info.ip}`;
                            if (info.bitrate) detailStr += ` • ${info.bitrate}`;
                            if (info.frequency) detailStr += ` • ${info.frequency}`;
                            details.innerHTML = detailStr;
                            if (icon) icon.textContent = '📶';
                        } else if (info.mode === 'hotspot') {
                            details.textContent = 'Hotspot Active: NomadPi (10.42.0.1)';
                            if (icon) icon.textContent = '🔥';
                        } else {
                            details.textContent = 'Not connected to any network';
                        }
                    }
                }
            } else {
                if (details) details.textContent = 'Wi-Fi is turned off';
            }
        }
    } catch (e) {
        console.error('Failed to load Wi-Fi status:', e);
    }
}

async function scanWifi() {
    const container = document.getElementById('wifi-scan-container');
    const list = document.getElementById('wifi-networks-list');
    if (!container || !list) return;

    container.classList.remove('hidden');
    list.innerHTML = `
        <div style="padding:40px; text-align:center;">
            <div class="spinner" style="margin: 0 auto 15px auto; width: 30px; height: 30px; border: 3px solid rgba(255,255,255,0.1); border-top-color: var(--accent-color); border-radius: 50%; animation: spin 1s linear infinite;"></div>
            <div style="color:var(--text-muted);">Scanning airwaves... this might take a moment.</div>
        </div>
    `;

    try {
        const res = await fetch(`${API_BASE}/system/wifi/scan`, { headers: getAuthHeaders() });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();

        if (data.networks && data.networks.length > 0) {
            list.innerHTML = '';
            data.networks.forEach(net => {
                const div = document.createElement('div');
                div.className = 'glass-hover';
                div.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:15px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05); border-radius:12px; transition:all 0.2s ease; cursor:pointer; margin-bottom:4px;';
                div.onclick = () => openWifiModal(net.ssid);
                
                // Signal strength icon logic
                let signalIcon = net.bars || '📶';
                let signalColor = 'var(--success-color)';
                if (net.signal < 30) signalColor = 'var(--danger-color)';
                else if (net.signal < 60) signalColor = 'var(--warning-color)';
                
                const isEncrypted = net.security && net.security !== 'None';
                
                const info = document.createElement('div');
                info.innerHTML = `
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-weight:600; font-size:1.05em;">${net.ssid}</span>
                        ${isEncrypted ? '<span style="font-size:0.8em; opacity:0.6;" title="' + net.security + '">🔒</span>' : ''}
                    </div>
                    <div style="font-size:0.85em; color:var(--text-muted); margin-top:4px;">
                        <span style="color:${signalColor}; font-weight:bold;">${net.signal}%</span> ${signalIcon} 
                        ${net.freq ? ' • ' + net.freq : ''}
                    </div>
                `;
                
                const connectBtn = document.createElement('div');
                connectBtn.innerHTML = `
                    <div style="background:var(--accent-color); color:black; padding:6px 16px; border-radius:8px; font-weight:600; font-size:0.9em;">
                        Connect
                    </div>
                `;
                
                div.appendChild(info);
                div.appendChild(connectBtn);
                list.appendChild(div);
            });
        } else {
            list.innerHTML = `
                <div style="padding:40px; text-align:center; color:var(--text-muted);">
                    <div style="font-size:2em; margin-bottom:10px;">🔍</div>
                    No networks found. Try moving closer to the router or refreshing.
                </div>
            `;
        }
    } catch (e) {
        list.innerHTML = `
            <div style="padding:30px; text-align:center; color:var(--danger-color);">
                <div style="font-size:2em; margin-bottom:10px;">⚠️</div>
                Error: ${e.message}
            </div>
        `;
    }
}

function openWifiModal(ssid) {
    const modal = document.getElementById('wifi-modal');
    const ssidLabel = document.getElementById('modal-ssid');
    const passwordInput = document.getElementById('wifi-password-input');
    const connectBtn = document.getElementById('modal-connect-btn');
    
    if (!modal || !ssidLabel || !passwordInput || !connectBtn) return;
    
    ssidLabel.textContent = `Network: ${ssid}`;
    passwordInput.value = '';
    modal.classList.remove('hidden');
    passwordInput.focus();
    
    connectBtn.onclick = () => {
        const password = passwordInput.value;
        if (!password) {
            showToast('Please enter a password', 'warning');
            return;
        }
        connectToWifi(ssid, password);
    };

    // Close on escape - assigned to a stable property to avoid memory leaks
    if (!window._wifiModalEscHandler) {
        window._wifiModalEscHandler = (e) => {
            if (e.key === 'Escape') {
                closeWifiModal();
            }
        };
        window.addEventListener('keydown', window._wifiModalEscHandler);
    }
}

function closeWifiModal() {
    const modal = document.getElementById('wifi-modal');
    if (modal) modal.classList.add('hidden');
    
    // Clean up the escape key listener to prevent memory leaks
    if (window._wifiModalEscHandler) {
        window.removeEventListener('keydown', window._wifiModalEscHandler);
        window._wifiModalEscHandler = null;
    }
}

async function connectToWifi(ssid, password) {
    const modal = document.getElementById('wifi-modal');
    const connectBtn = document.getElementById('modal-connect-btn');
    const originalText = connectBtn.textContent;
    
    connectBtn.disabled = true;
    connectBtn.textContent = 'Connecting...';

    try {
        const res = await fetch(`${API_BASE}/system/wifi/connect`, {
            method: 'POST',
            headers: { 
                ...getAuthHeaders(),
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ ssid, password })
        });
        
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        
        if (res.ok) {
            closeWifiModal();
            // Show success toast or alert
            const toast = document.createElement('div');
            toast.style.cssText = 'position:fixed; bottom:100px; left:50%; transform:translateX(-50%); background:var(--success-color); color:white; padding:12px 24px; border-radius:12px; z-index:2000; box-shadow:var(--shadow-lg); animation:fadeIn 0.3s ease;';
            toast.textContent = `Successfully connected to ${ssid}`;
            document.body.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.5s ease';
                setTimeout(() => toast.remove(), 500);
            }, 3000);
            
            document.getElementById('wifi-scan-container').classList.add('hidden');
            loadWifiStatus();
        } else {
            showToast(`Failed to connect: ${data.detail || 'Unknown error'}`, 'error');
        }
    } catch (e) {
        showToast(`Connection error: ${e.message}`, 'error');
    } finally {
        connectBtn.disabled = false;
        connectBtn.textContent = originalText;
    }
}

async function toggleWifiUI() {
    const btn = document.getElementById('wifi-toggle-btn');
    if (!btn) return;
    
    const newState = !wifiEnabled;
    btn.disabled = true;
    btn.textContent = newState ? 'Enabling...' : 'Disabling...';
    
    try {
        const res = await fetch(`${API_BASE}/system/wifi/toggle?enable=${newState}`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        
        if (res.ok) {
            await loadWifiStatus();
        } else {
            const data = await res.json();
            alert(`Error: ${data.detail || 'Failed to toggle Wi-Fi'}`);
            await loadWifiStatus();
        }
    } catch (e) {
        alert(`Error: ${e.message}`);
        await loadWifiStatus();
    } finally {
        btn.disabled = false;
    }
}

function cancelUpload() {
    if (activeUploads.length === 0) return;
    
    if (confirm('Are you sure you want to cancel all active uploads?')) {
        console.log(`Cancelling ${activeUploads.length} uploads...`);
        activeUploads.forEach(xhr => {
            try {
                xhr.abort();
            } catch (e) {
                console.error('Error aborting XHR:', e);
            }
        });
        activeUploads = [];
        
        const statusDiv = document.getElementById('upload-status');
        if (statusDiv) {
            statusDiv.innerHTML = '<span style="color:var(--warning-color)">Upload cancelled by user.</span>';
        }
        
        const cancelBtn = document.getElementById('cancel-upload-btn');
        if (cancelBtn) cancelBtn.classList.add('hidden');
        
        const startBtn = document.getElementById('start-upload-btn');
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.textContent = 'Start Upload';
        }
    }
}

// Debounce function moved to utilities section (line ~503)

document.addEventListener('DOMContentLoaded', () => {
    initTheme(); // Initialize theme before anything else

    // Ensure all sections except home are hidden on page load
    document.querySelectorAll('main > section').forEach(section => {
        if (section.id !== 'home') {
            section.classList.add('hidden');
            section.style.display = 'none';
        }
    });

    checkAuth(); // Check auth on load

    // Initialize eBook reader
    if (typeof EBookReader !== 'undefined') {
        window.ebookReader = new EBookReader();
        console.log('eBook reader initialized');
    }

    // Initialize music player
    if (typeof MusicPlayer !== 'undefined') {
        window.musicPlayer = new MusicPlayer();
        console.log('Music player initialized');
    }

    const setupHintEl = document.getElementById('setup-hint');
    const passwordInput = document.getElementById('password-input');
    if (setupHintEl && passwordInput) {
        fetch(`${API_BASE}/system/setup/status`)
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
                if (!data) return;
                if (data.admin_must_change_password && data.password_hint) {
                    setupHintEl.textContent = `First-time setup: default password is "${data.password_hint}". Please change it after login.`;
                    setupHintEl.style.display = 'block';
                    passwordInput.placeholder = `Password (default: ${data.password_hint})`;
                } else {
                    setupHintEl.style.display = 'none';
                    setupHintEl.textContent = '';
                    passwordInput.placeholder = 'Password';
                }
            })
            .catch(() => {});
    }

    // Inline form validation for login
    const usernameInput = document.getElementById('username-input');
    if (usernameInput) {
        usernameInput.addEventListener('blur', () => {
            const value = usernameInput.value.trim();
            if (value && !FormValidator.minLength(value, 3)) {
                FormValidator.showError(usernameInput, 'Username must be at least 3 characters');
            } else {
                FormValidator.clearError(usernameInput);
            }
        });
        usernameInput.addEventListener('input', () => {
            if (usernameInput.value.trim().length >= 3) {
                FormValidator.clearError(usernameInput);
            }
        });
    }

    if (passwordInput) {
        passwordInput.addEventListener('input', () => {
            if (passwordInput.value.length > 0) {
                FormValidator.clearError(passwordInput);
            }
        });
    }

    // Password change form validation
    const changePwNew = document.getElementById('change-pw-new');
    const changePwConfirm = document.getElementById('change-pw-confirm');

    if (changePwNew) {
        changePwNew.addEventListener('input', debounce(() => {
            const value = changePwNew.value;
            if (value) {
                const strength = FormValidator.passwordStrength(value);
                if (strength.score < 3) {
                    FormValidator.showError(changePwNew, strength.feedback.join(', '));
                } else {
                    FormValidator.clearError(changePwNew);
                }
            } else {
                FormValidator.clearError(changePwNew);
            }
        }, 500));
    }

    if (changePwConfirm && changePwNew) {
        changePwConfirm.addEventListener('input', () => {
            const newPw = changePwNew.value;
            const confirmPw = changePwConfirm.value;
            if (confirmPw && newPw !== confirmPw) {
                FormValidator.showError(changePwConfirm, 'Passwords do not match');
            } else {
                FormValidator.clearError(changePwConfirm);
            }
        });
    }

    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const folderInput = document.getElementById('folder-input');
    const uploadCategory = document.getElementById('upload-category');
    const showsUploadOptions = document.getElementById('shows-upload-options');
    const moviesSearch = document.getElementById('movies-search');
    const showsSearch = document.getElementById('shows-search');
    const musicSearch = document.getElementById('music-search');
    const filesSearch = document.getElementById('files-search');
    const audio = document.getElementById('global-audio');
    const bar = document.getElementById('player-bar');
    const titleEl = document.getElementById('player-title');
    const btnPlay = document.getElementById('player-play');
    const btnPrev = document.getElementById('player-prev');
    const btnNext = document.getElementById('player-next');
    const btnShuffle = document.getElementById('player-shuffle');
    const seek = document.getElementById('player-seek');
    const timeEl = document.getElementById('player-time');
    const vol = document.getElementById('player-volume');

    if (audio && bar) {
        audio.addEventListener('timeupdate', () => {
            if (musicQueue[musicIndex]) updateProgress(audio, musicQueue[musicIndex].path);
            if (seek && Number.isFinite(audio.duration) && audio.duration > 0) {
                seek.value = String(Math.floor((audio.currentTime / audio.duration) * 100));
            }
            if (timeEl) {
                const cur = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
                const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
                timeEl.textContent = `${formatClock(cur)} / ${formatClock(dur)}`;
            }
        });
        audio.addEventListener('ended', () => musicNext());
        audio.addEventListener('play', () => { if (btnPlay) btnPlay.textContent = '⏸'; });
        audio.addEventListener('pause', () => { if (btnPlay) btnPlay.textContent = '▶'; });
        audio.addEventListener('error', (e) => {
            console.error('Global audio error:', audio.error);
            const titleEl = document.getElementById('player-title');
            if (titleEl) titleEl.textContent = 'Error playing track';
            const btnPlay = document.getElementById('player-play');
            if (btnPlay) btnPlay.textContent = '▶';
            
            // Show more details if possible
            let msg = 'Unknown playback error';
            if (audio.error) {
                switch (audio.error.code) {
                    case 1: msg = 'Playback aborted'; break;
                    case 2: msg = 'Network error'; break;
                    case 3: msg = 'Decoding error'; break;
                    case 4: msg = 'Source not supported'; break;
                }
            }
            console.error('Audio Error Detail:', msg);
        });
    }

    if (btnPlay && audio) {
        btnPlay.addEventListener('click', () => {
            if (!audio.src) return;
            if (audio.paused) audio.play().catch(() => {});
            else audio.pause();
        });
    }
    if (btnPrev) btnPrev.addEventListener('click', () => musicPrev());
    if (btnNext) btnNext.addEventListener('click', () => musicNext());
    if (btnShuffle) {
        btnShuffle.addEventListener('click', () => {
            musicShuffle = !musicShuffle;
            btnShuffle.classList.toggle('active', musicShuffle);
            if (musicShuffle && musicQueue.length) {
                musicShuffleOrder = shuffleOrder(musicQueue.length, musicIndex);
                musicShufflePos = 0;
            }
        });
    }
    const btnClosePlayer = document.getElementById('player-close');
    if (btnClosePlayer && audio && bar) {
        btnClosePlayer.addEventListener('click', () => {
            audio.pause();
            audio.currentTime = 0;
            bar.classList.add('hidden');
            musicQueue = [];
            currentMedia = null;
        });
    }
    if (seek && audio) {
        seek.addEventListener('input', () => {
            const pct = Number(seek.value || 0) / 100;
            if (Number.isFinite(audio.duration) && audio.duration > 0) {
                audio.currentTime = audio.duration * pct;
            }
        });
    }
    if (vol && audio) {
        vol.addEventListener('input', () => {
            const v = Number(vol.value);
            audio.volume = Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 1;
        });
    }
    if (titleEl && !titleEl.textContent) titleEl.textContent = 'Not playing';

    if (uploadCategory && showsUploadOptions) {
        const syncShowsOptions = () => {
            const isShows = uploadCategory.value === 'shows';
            showsUploadOptions.classList.toggle('hidden', !isShows);
        };
        uploadCategory.addEventListener('change', syncShowsOptions);
        syncShowsOptions();
    }

    if (dropZone) {
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');

            const items = e.dataTransfer.items;
            if (items) {
                const entries = [];
                for (let i = 0; i < items.length; i++) {
                    const item = items[i].webkitGetAsEntry();
                    if (item) {
                        await traverseFileTree(item, entries);
                    }
                }
                handleFiles(entries);
            } else {
                handleFiles(e.dataTransfer.files);
            }
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => handleFiles(e.target.files));
    }
    
    if (folderInput) {
        folderInput.addEventListener('change', (e) => handleFiles(e.target.files));
    }

    if (moviesSearch) {
        moviesSearch.addEventListener('input', debounce(() => {
            loadMediaPage('movies', true);
        }, 300));
    }
    if (musicSearch) {
        musicSearch.addEventListener('input', debounce(() => {
            loadMediaPage('music', true);
        }, 300));
    }
    if (showsSearch) {
        showsSearch.addEventListener('input', debounce(() => {
            if (showsLibraryCache) renderShows();
        }, 300));
    }
    if (filesSearch) {
        filesSearch.addEventListener('input', debounce(() => {
            loadMediaPage('files', true);
        }, 300));
    }
});

function formatClock(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, '0')}`;
}

function traverseFileTree(item, entryList, path = '') {
    return new Promise((resolve) => {
        if (item.isFile) {
            item.file((file) => {
                entryList.push({ file, relativePath: `${path}${file.name}` });
                resolve();
            });
        } else if (item.isDirectory) {
            const dirReader = item.createReader();
            dirReader.readEntries(async (entries) => {
                for (const entry of entries) {
                    await traverseFileTree(entry, entryList, `${path}${item.name}/`);
                }
                resolve();
            });
        } else {
            resolve();
        }
    });
}

function handleFiles(files) {
    const queueDiv = document.getElementById('upload-queue');
    const list = Array.isArray(files) ? files : Array.from(files);
    for (const entry of list) {
        const isWrapped = entry && entry.file instanceof File;
        const file = isWrapped ? entry.file : entry;
        const relativePath = isWrapped ? entry.relativePath : (file.webkitRelativePath || file.name);

        uploadQueue.push({ file, relativePath });
        const item = document.createElement('div');
        item.textContent = `${relativePath} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
        item.style.fontSize = '0.9em';
        item.style.borderBottom = '1px solid #444';
        queueDiv.appendChild(item);
    }
}

async function uploadFiles() {
    const category = document.getElementById('upload-category').value;
    const statusDiv = document.getElementById('upload-status');
    const rawShowName = (document.getElementById('upload-show-name')?.value || '').trim();

    if (uploadQueue.length === 0) {
        showToast("Please select files to upload", 'warning');
        return;
    }

    statusDiv.innerHTML = '<div class="progress-container"><div id="upload-progress-bar" class="progress-fill" style="width:0%">0%</div></div>';
    const progressBar = document.getElementById('upload-progress-bar');

    const items = uploadQueue.filter(e => e.file && e.file.size > 0);
    const totalFiles = items.length;
    const totalBytes = items.reduce((sum, e) => sum + (e.file?.size || 0), 0);
    let completedBytes = 0;
    let completed = 0;
    let processed = 0;
    let errors = 0;
    const errorList = [];

    if (totalFiles === 0) {
        showToast("Please select valid files to upload", 'warning');
        return;
    }
    
    // Show cancel button
    let cancelBtn = document.getElementById('cancel-upload-btn');
    if (cancelBtn) cancelBtn.classList.remove('hidden');
    let startBtn = document.getElementById('start-upload-btn');
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.textContent = 'Uploading...';
    }
    
    const concurrency = 3; // Reduced concurrency for better stability on low-power devices like Pi Zero 2W
    const loadedByIndex = new Array(totalFiles).fill(0);

    function computeDisplayName(entry) {
        const file = entry.file;
        let displayName = entry.relativePath || file.name;
        displayName = String(displayName || '').replaceAll('\\', '/');
        if (category === 'shows') {
            let showName = rawShowName.replaceAll('/', '').replaceAll('\\', '').trim();
            if (!showName) {
                showName = inferShowNameFromFilename(displayName);
            }

            const parts = displayName.split('/').filter(Boolean);
            const first = (parts[0] || '').toLowerCase();
            const seasonLike = first.startsWith('season') || first.startsWith('series') || /^s\d{1,3}/.test(first);
            if (showName) {
                if (parts[0] !== showName) {
                    displayName = `${showName}/${displayName}`;
                }
            } else if (parts.length < 2 || seasonLike) {
                displayName = `Unsorted/${displayName}`;
            }
        }
        return displayName;
    }

    function updateAggregateProgress() {
        const inFlightBytes = loadedByIndex.reduce((sum, v) => sum + v, 0);
        const uploaded = completedBytes + inFlightBytes;
        const pct = totalBytes > 0 ? (uploaded / totalBytes) * 100 : 0;
        progressBar.style.width = `${pct}%`;
        progressBar.textContent = `${formatBytes(uploaded)}/${formatBytes(totalBytes)} (${pct.toFixed(0)}%)`;
    }

    async function uploadOne(entry, index) {
        const file = entry.file;
        const displayName = computeDisplayName(entry);
        try {
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', `${API_BASE}/media/upload_stream/${category}?path=${encodeURIComponent(displayName)}`, true);
                const authHeaders = getAuthHeaders();
                if (authHeaders.Authorization) {
                    xhr.setRequestHeader('Authorization', authHeaders.Authorization);
                }
                xhr.setRequestHeader('Content-Type', 'application/octet-stream');
                xhr.setRequestHeader('X-File-Path', displayName);
                xhr.upload.onprogress = function(e) {
                    if (!e.lengthComputable) return;
                    loadedByIndex[index] = e.loaded;
                    updateAggregateProgress();
                };
                
                xhr.onload = function() {
                    if (xhr.status === 200) {
                        resolve();
                    } else if (xhr.status === 401) {
                        logout();
                        reject('Unauthorized (Session Expired)');
                    } else if (xhr.status === 413) {
                        reject('File Too Large');
                    } else {
                        let detail = '';
                        try {
                            const parsed = JSON.parse(xhr.responseText || '{}');
                            if (typeof parsed.detail === 'string') detail = parsed.detail;
                            else if (parsed.detail) detail = JSON.stringify(parsed.detail);
                        } catch {
                            detail = (xhr.responseText || '').trim();
                        }
                        if (detail) {
                            reject(`Server Error ${xhr.status}: ${detail}`);
                        } else {
                            reject(`Server Error ${xhr.status}: ${xhr.statusText}`);
                        }
                    }
                };
                
                xhr.onerror = function() {
                    reject('Network Error (Check Connection/Permissions)');
                };
                
                activeUploads.push(xhr);
                xhr.send(file);
            });
            completed++;
            completedBytes += file.size || 0;
            loadedByIndex[index] = 0;
        } catch (e) {
            console.error(`Failed to upload ${displayName}:`, e);
            errors++;
            errorList.push(`${displayName}: ${e}`);
            loadedByIndex[index] = 0;
        } finally {
            // Remove this XHR from activeUploads
            activeUploads = activeUploads.filter(x => x.readyState !== 4 && x.readyState !== 0);
        }

        processed++;
        const pctFiles = Math.round((processed / totalFiles) * 100);
        if (totalBytes > 0) {
            const pctBytes = (completedBytes / totalBytes) * 100;
            progressBar.style.width = `${pctBytes}%`;
            progressBar.textContent = `${formatBytes(completedBytes)}/${formatBytes(totalBytes)} (${pctFiles}%)`;
        } else {
            progressBar.style.width = `${pctFiles}%`;
            progressBar.textContent = `${processed}/${totalFiles} (${pctFiles}%)`;
        }
    }

    const queue = items.map((entry, idx) => ({ entry, idx }));
    const workers = new Array(Math.min(concurrency, queue.length)).fill(0).map(async () => {
        while (queue.length) {
            const next = queue.shift();
            if (!next) return;
            await uploadOne(next.entry, next.idx);
            updateAggregateProgress();
        }
    });
    await Promise.all(workers);

    // Hide cancel button
    cancelBtn = document.getElementById('cancel-upload-btn');
    if (cancelBtn) cancelBtn.classList.add('hidden');
    startBtn = document.getElementById('start-upload-btn');
    if (startBtn) {
        startBtn.disabled = false;
        startBtn.textContent = 'Start Upload';
    }

    if (errors === 0) {
        statusDiv.innerHTML = `<span style="color:#4caf50">Success! Uploaded ${completed} files.</span>`;
        uploadQueue.length = 0; // Clear queue
        document.getElementById('upload-queue').innerHTML = '';
    } else {
        let errorHtml = `<span style="color:var(--danger-color)">Finished with ${errors} errors. Uploaded ${completed}/${totalFiles}.</span>`;
        errorHtml += '<div style="max-height:100px;overflow-y:auto;background:#333;padding:5px;margin-top:5px;font-size:0.8em;">';
        errorList.forEach(err => {
            errorHtml += `<div>${err}</div>`;
        });
        errorHtml += '</div>';
        statusDiv.innerHTML = errorHtml;
    }

    if (completed > 0) {
        delete mediaCache[category];
        if (category === 'shows') showsLibraryCache = null;

        const active = document.querySelector('main > section.active')?.id;
        if (active === category) {
            if (category === 'shows') {
                loadShowsLibrary();
            } else {
                loadMedia(category);
            }
        }
    }
}

async function deleteItem(path) {
    if (!confirm('Are you sure you want to delete this item? This cannot be undone.')) return;
    try {
        const res = await fetch(`${API_BASE}/media/delete?path=${encodeURIComponent(path)}`, { 
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || 'Delete failed');
        }
        
        // Clear caches
        delete mediaCache['movies'];
        delete mediaCache['music'];
        delete mediaCache['books'];
        delete mediaCache['gallery'];
        delete mediaCache['files'];
        showsLibraryCache = null;

        const active = document.querySelector('main > section.active')?.id;
        if (active === 'shows') loadShowsLibrary();
        else if (active) loadMedia(active);
    } catch (e) {
        alert(e.message);
    }
}

function getAuthHeaders() {
    const token = localStorage.getItem('nomad_auth_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

async function rescanLibrary() {
    if (!confirm('Rescan all libraries? This may take a while.')) return;
    try {
        const res = await fetch(`${API_BASE}/media/scan`, { 
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                ...getAuthHeaders()
            }
        });
        
        if (res.status === 401) {
            showToast('Session expired. Please log in again.', 'warning');
            logout();
            return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Scan failed');
        showToast(data.message, 'success');
    } catch (e) {
        console.error('Scan error:', e);
        showToast(e.message, 'error');
    }
}

async function prepareDrive(path) {
    if (!confirm(`Create standard folders (movies, shows, etc.) on ${path}?`)) return;
    try {
        const res = await fetch(`${API_BASE}/media/system/prepare_drive?path=${encodeURIComponent(path)}`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        showToast(data.message, 'success');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function inferShowNameFromFilename(pathOrName) {
    const baseName = String(pathOrName || '').split('/').pop() || '';
    const name = baseName.replace(/\.[^.]+$/, '');
    const m = name.match(/^(.*?)(?:\bS\d{1,3}\s*E\d{1,3}\b|\b\d{1,3}x\d{1,3}\b|\bEpisode\s*\d{1,3}\b)/i);
    if (!m || !m[1]) return '';
    const cleaned = m[1].replace(/[\.\-_]+/g, ' ').replace(/\s+/g, ' ').trim();
    if (cleaned.length < 2) return '';
    return cleaned;
}

async function loadStorageStats() {
    if (window.location.protocol === 'file:') return;
    const now = Date.now();
    if (now < statsNextAllowedAt) return;

    try {
        const res = await fetch(`${API_BASE}/system/stats`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) return;
        const data = await res.json();
        statsFailureCount = 0;
        statsNextAllowedAt = 0;
        
        // Disk Stats
        const diskPercent = Number(data.disk_percent || 0);
        const diskUsedGB = Number(data.disk_used || 0) / (1024 ** 3);
        const diskTotalGB = Number(data.disk_total || 0) / (1024 ** 3);
        const diskFreeGB = Number(data.disk_free || 0) / (1024 ** 3);

        // CPU Stats
        const cpuPercent = Number(data.cpu || 0);
        const cpuFreq = Number(data.cpu_freq || 0);
        const throttled = data.throttled || false;

        // RAM Stats
        const ramPercent = Number(data.memory_percent || 0);
        const ramUsedGB = Number(data.memory_used || 0) / (1024 ** 3);
        const ramTotalGB = Number(data.memory_total || 0) / (1024 ** 3);

        // Network Stats
        const now = Date.now();
        const sent = Number(data.network_up);
        const recv = Number(data.network_down);
        let downRate = null;
        let upRate = null;
        if (lastNetSample && Number.isFinite(sent) && Number.isFinite(recv)) {
            const dt = (now - lastNetSample.t) / 1000;
            if (dt > 0) {
                downRate = (recv - lastNetSample.r) / dt;
                upRate = (sent - lastNetSample.s) / dt;
            }
        }
        if (Number.isFinite(sent) && Number.isFinite(recv)) {
            lastNetSample = { t: now, s: sent, r: recv };
        }

        // Update UI
        const updateText = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.innerText = text;
        };
        const updateProgress = (id, percent) => {
            const el = document.getElementById(id);
            if (el) el.style.width = `${percent}%`;
        };

        // Storage Card
        updateText('storage-stats', `${diskPercent.toFixed(0)}%`);
        updateProgress('disk-progress', diskPercent);
        updateText('disk-details', `${diskUsedGB.toFixed(1)}/${diskTotalGB.toFixed(1)} GB used • ${diskFreeGB.toFixed(1)} GB free`);
        
        // Update welcome message with hostname
        const welcomeEl = document.querySelector('#home h1');
        if (welcomeEl && data.hostname) {
            welcomeEl.innerText = `Welcome to ${data.hostname}`;
        }

        // CPU Card
        let cpuValStr = `${cpuPercent.toFixed(0)}%`;
        if (cpuFreq > 0) cpuValStr += ` @ ${cpuFreq < 1000 ? cpuFreq.toFixed(0) + 'MHz' : (cpuFreq/1000).toFixed(2) + 'GHz'}`;
        updateText('cpu-stats', cpuValStr);
        updateProgress('cpu-progress', cpuPercent);
        
        let cpuDetails = `${data.cores || '--'} Cores`;
        
        // Add Overclock info if present
        if (data.cpu_overclock && Object.keys(data.cpu_overclock).length > 0) {
            const oc = data.cpu_overclock;
            if (oc.arm_freq) {
                cpuDetails += ` • OC: ${oc.arm_freq}MHz`;
            }
            if (oc.over_voltage) {
                cpuDetails += ` (+${oc.over_voltage})`;
            }
        }

        if (throttled) cpuDetails += ' • <span style="color:var(--danger-color); font-weight:bold;">THROTTLED</span>';
        const cpuDetailsEl = document.getElementById('cpu-details');
        if (cpuDetailsEl) cpuDetailsEl.innerHTML = cpuDetails;

        // RAM Card
        updateText('ram-stats', `${ramPercent.toFixed(0)}%`);
        updateProgress('mem-progress', ramPercent);
        updateText('mem-details', `${ramUsedGB.toFixed(1)}/${ramTotalGB.toFixed(1)} GB used`);

        // Temp Card
        const tempEl = document.getElementById('cpu-temp');
        if (tempEl) {
            const temp = Number(data.temp);
            tempEl.innerText = Number.isFinite(temp) ? `${temp.toFixed(1)}°C` : '--°C';
            if (temp > 75) tempEl.style.color = 'var(--danger-color)';
            else if (temp > 60) tempEl.style.color = 'var(--warning-color)';
            else tempEl.style.color = 'var(--success-color)';
        }
        const tempDetailsEl = document.getElementById('temp-details');
        if (tempDetailsEl && data.uptime) {
            const uptimeHours = data.uptime / 3600;
            if (uptimeHours < 24) {
                tempDetailsEl.innerText = `Up: ${uptimeHours.toFixed(1)}h • Core Temp`;
            } else {
                tempDetailsEl.innerText = `Up: ${(uptimeHours/24).toFixed(1)}d • Core Temp`;
            }
        }

        // Header Stats
        const headerEl = document.getElementById('header-stats');
        if (headerEl) {
            let headerText = `${data.hostname ? data.hostname + ' • ' : ''}CPU ${cpuPercent.toFixed(0)}% • RAM ${ramPercent.toFixed(0)}%`;
            if (downRate !== null) headerText += ` • ↓ ${formatRate(downRate)}`;
            headerEl.innerText = headerText;
        }

    } catch (e) {
        statsFailureCount = Math.min(statsFailureCount + 1, 10);
        const delay = Math.min(60000, 2000 * Math.pow(2, Math.max(0, statsFailureCount - 1)));
        statsNextAllowedAt = Date.now() + delay;

        const logNow = Date.now();
        if (logNow - statsLastErrorLogAt > 30000) {
            statsLastErrorLogAt = logNow;
            console.error('Failed to load system stats:', e);
        }
    }
}

function formatBytes(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = n;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatRate(bytesPerSec) {
    return `${formatBytes(bytesPerSec)}/s`;
}

let lastDriveData = '';
let musicQueue = [];
let musicIndex = -1;
let musicShuffle = false;
let musicShuffleOrder = [];
let musicShufflePos = 0;
async function changePassword() {
    const currentPw = document.getElementById('change-pw-current').value;
    const newPw = document.getElementById('change-pw-new').value;
    const confirmPw = document.getElementById('change-pw-confirm').value;
    const statusEl = document.getElementById('change-pw-status');

    if (!currentPw || !newPw || !confirmPw) {
        statusEl.textContent = 'Please fill in all fields.';
        statusEl.style.color = 'var(--danger-color)';
        return;
    }

    if (newPw !== confirmPw) {
        statusEl.textContent = 'New passwords do not match.';
        statusEl.style.color = 'var(--danger-color)';
        return;
    }

    statusEl.textContent = 'Updating...';
    statusEl.style.color = 'var(--text-color)';

    try {
        const res = await fetch(`${API_BASE}/auth/change-password`, {
            method: 'POST',
            headers: { 
                ...getAuthHeaders(),
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ current_password: currentPw, new_password: newPw })
        });

        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            statusEl.textContent = 'Password updated successfully!';
            statusEl.style.color = 'var(--success-color)';
            document.getElementById('change-pw-current').value = '';
            document.getElementById('change-pw-new').value = '';
            document.getElementById('change-pw-confirm').value = '';
        } else {
            statusEl.textContent = data.detail || 'Failed to update password.';
            statusEl.style.color = 'var(--danger-color)';
        }
    } catch (e) {
        console.error(e);
        statusEl.textContent = 'Error: ' + e.message;
        statusEl.style.color = 'var(--danger-color)';
    }
}

async function rebuildLibrary() {
    try {
        const res = await fetch(`${API_BASE}/media/rebuild`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        showToast(data.status || 'Library scan started in background', 'success');
        // Refresh stats after a short delay
        setTimeout(loadStorageStats, 2000);
    } catch (err) {
        showToast('Failed to start scan: ' + err, 'error');
    }
}

async function systemControl(action) {
    if (action === 'wifi_restart') {
        if (!confirm('Are you sure you want to restart Wi-Fi? This will temporarily disconnect all wireless connections.')) return;
        try {
            const res = await fetch(`${API_BASE}/system/wifi/restart`, { 
                method: 'POST',
                headers: getAuthHeaders()
            });
            if (res.status === 401) { logout(); return; }
            if (res.ok) {
                alert('Wi-Fi restart initiated.');
                loadWifiStatus();
            } else {
                const data = await res.json();
                alert(`Error: ${data.detail || 'Failed to restart Wi-Fi'}`);
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
        }
        return;
    }

    if (action === 'update') {
        const container = document.getElementById('update-log-container');
        const logView = document.getElementById('update-log-view');
        const badge = document.getElementById('update-status-badge');
        
        if (!confirm('Are you sure you want to update from GitHub? This will pull latest files and restart the service.')) return;
        
        // Save current version before update
        try {
            const statusRes = await fetch(`${API_BASE}/system/status`, { headers: getAuthHeaders() });
            const statusData = await statusRes.json();
            if (statusData.version) {
                localStorage.setItem('nomadpi_pre_update_version', statusData.version);
            }
        } catch (e) { console.warn('Could not save pre-update version', e); }

        container.classList.remove('hidden');
        logView.textContent = 'Starting update...\n';
        badge.textContent = 'Running...';
        badge.className = 'badge warning';

        // Reset progress bar
        const progressFill = document.getElementById('update-progress-fill');
        const progressText = document.getElementById('update-progress-text');
        if (progressFill) progressFill.style.width = '0%';
        if (progressText) progressText.textContent = 'Initializing update...';

        try {
        const res = await fetch(`${API_BASE}/system/control/update`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
            if (res.status === 401) { logout(); return; }
            
            // Start polling for logs and status
            let updateComplete = false;
            let serverRestarting = false;
            let pollCount = 0;
            
            const pollInterval = setInterval(async () => {
                pollCount++;
                try {
                    // 1. Poll Progress Status (JSON)
                    const statusRes = await fetch(`${API_BASE}/system/update/status`, { headers: getAuthHeaders() });
                    if (statusRes.ok) {
                        const statusData = await statusRes.json();
                        if (statusData.progress !== undefined) {
                            if (progressFill) progressFill.style.width = `${statusData.progress}%`;
                            if (progressText) progressText.textContent = statusData.message || 'Updating...';
                        }
                    }

                    // 2. Poll Logs (Text)
                    const logRes = await fetch(`${API_BASE}/system/update/log`, { headers: getAuthHeaders() });
                    if (logRes.ok) {
                        const data = await logRes.json();
                        if (data.log) {
                            const logText = Array.isArray(data.log) ? data.log.join('') : String(data.log);
                            logView.textContent = logText;
                            logView.scrollTop = logView.scrollHeight;
                            
                            // Check if update completed
                            const isSuccess = logText.toLowerCase().includes('update complete!');
                            const isFailure = logText.toLowerCase().includes('update failed!');
                            
                            if ((isSuccess || isFailure) && !updateComplete) {
                                updateComplete = true;
                                if (isSuccess) {
                                    if (progressFill) progressFill.style.width = '100%';
                                    if (progressText) progressText.textContent = 'Update complete! Restarting...';
                                    badge.textContent = 'Restarting...';
                                    badge.className = 'badge warning';
                                    logView.textContent += '\n\n✅ Update script finished!\nServer is restarting...\nPlease wait, we will reconnect automatically.';
                                } else {
                                    badge.textContent = 'Update Failed';
                                    badge.className = 'badge danger';
                                    logView.textContent += '\n\n❌ Update script failed!\nPlease check the logs above for errors.';
                                }
                                
                                if (!serverRestarting) {
                                    serverRestarting = true;
                                    checkServerRestart();
                                }
                            }
                        }
                    } else {
                        // Connection might be lost due to restart
                        if (updateComplete || pollCount > 5) {
                            if (!serverRestarting) {
                                serverRestarting = true;
                                logView.textContent += '\n\n📡 Server connection lost (restarting...)\nChecking for server availability...';
                                checkServerRestart();
                            }
                        }
                    }
                } catch (e) {
                    // Network error usually means server is down
                    if (!serverRestarting && (updateComplete || pollCount > 5)) {
                        serverRestarting = true;
                        logView.textContent += '\n\n📡 Server connection lost (restarting...)\nChecking for server availability...';
                        checkServerRestart();
                    }
                }
                
                if (pollCount > 600) { // Stop polling after 10 minutes (at 1s interval)
                    clearInterval(pollInterval);
                    if (!serverRestarting) {
                        badge.textContent = 'Timed Out';
                        badge.className = 'badge danger';
                        logView.textContent += '\n\nUpdate timed out. Please check the server manually.';
                    }
                }
            }, 1000); // Poll faster (1s) for better responsiveness
            
            // Function to check if server is back online
            async function checkServerRestart() {
                clearInterval(pollInterval);
                let attempts = 0;
                const maxAttempts = 60; // 60 seconds
                
                const checkInterval = setInterval(async () => {
                    attempts++;
                    try {
                        const pingRes = await fetch(`${API_BASE}/system/status`, { 
                            method: 'GET',
                            headers: getAuthHeaders(),
                            cache: 'no-cache'
                        });
                        if (pingRes.ok) {
                            clearInterval(checkInterval);
                            badge.textContent = 'Complete!';
                            badge.className = 'badge success';
                            if (progressText) progressText.textContent = 'System Online!';
                            logView.textContent += '\n\n✅ Server is back online!\n\nRefreshing page...';
                            
                            setTimeout(() => {
                                window.location.reload();
                            }, 1500);
                        }
                    } catch (e) {
                        // Server still down, keep checking
                        if (attempts % 5 === 0) {
                            logView.textContent += '.';
                            logView.scrollTop = logView.scrollHeight;
                        }
                    }
                    
                    if (attempts >= maxAttempts) {
                        clearInterval(checkInterval);
                        badge.textContent = 'Manual Refresh';
                        badge.className = 'badge warning';
                        logView.textContent += '\n\n⚠️ Server restart taking longer than expected.\nPlease refresh the page manually.';
                    }
                }, 1000);
            }

        } catch (e) {
            console.error(e);
            logView.textContent += `\nError: ${e.message}`;
            badge.textContent = 'Error';
            badge.className = 'badge danger';
        }
        return;
    }

    const msg = `Are you sure you want to ${action} the device?`;
    if (!confirm(msg)) return;

    try {
        const res = await fetch(`${API_BASE}/system/control/${action}`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            alert(data.error || data.detail || `Failed to ${action}.`);
            return;
        }
        alert(data.status || data.message || `System ${action} initiated.`);
    } catch (e) {
        console.error(e);
        alert(`Error controlling system: ${e}`);
    }
}

async function loadDrives(silent = false) {
    const container = document.getElementById('drive-list');
    if (!silent) container.innerHTML = '<div class="loading">Scanning...</div>';
    
    try {
        const res = await fetch(`${API_BASE}/system/drives`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        
        // Check if data changed to avoid flickering
        const currentDataStr = JSON.stringify(data);
        if (silent && currentDataStr === lastDriveData) {
            return;
        }
        lastDriveData = currentDataStr;

        container.innerHTML = '';
        const devices = data.blockdevices || data; 
        
        if (!devices || devices.length === 0) {
            container.innerHTML = 'No external drives found.';
            return;
        }

        function renderDevice(dev) {
            const label = dev.label || dev.name || 'Unknown';
            const size = dev.size || 'Unknown';
            const fstype = dev.fstype || dev.type || '';
            const uuid = dev.uuid || '';
            
            let html = `<div class="drive-item" style="border: 1px solid var(--border-color); padding: 10px; margin-bottom: 10px; border-radius: 8px; background: rgba(255,255,255,0.05);">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                    <div>
                        <strong>${escapeHtml(label)}</strong> <small>(${escapeHtml(dev.name || dev.device || '')})</small>
                        <br><small>${escapeHtml(size)} • ${escapeHtml(fstype)}</small>
                        ${uuid ? `<br><small style="color:#888; font-family:monospace;">${escapeHtml(uuid)}</small>` : ''}
                    </div>`;
            
            if (dev.mountpoint) {
                // Try to convert absolute mountpoint to web path if possible
                let browsePath = dev.mountpoint;
                const dataIdx = browsePath.indexOf('data' + (browsePath.includes('\\') ? '\\' : '/') + 'external');
                if (dataIdx !== -1) {
                    browsePath = '/data' + browsePath.substring(dataIdx + 4).replaceAll('\\', '/');
                } else if (!browsePath.startsWith('/data')) {
                    // If not under data/external, we might not be able to browse it yet
                    // But let's try to be smart if it's just 'data/external/...'
                    if (browsePath.startsWith('data/external')) {
                        browsePath = '/' + browsePath;
                    }
                }

                html += `<div style="display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end;margin-top:5px;">
                    <span class="badge success" style="margin-right:auto;">Mounted: ${escapeHtml(dev.mountpoint)}</span>
                    <button class="primary small" onclick="prepareDrive('${escapeHtml(dev.mountpoint)}')">Prepare</button>
                    <button class="secondary small" onclick="mediaState.path='${escapeHtml(browsePath).replaceAll('\\', '\\\\')}';showSection('files');">Browse</button>
                    <button class="danger small drive-unmount" data-mountpoint="${escapeHtml(dev.mountpoint)}">Unmount</button>
                </div>`;
            } else if ((dev.type === 'part' || dev.fstype) && !dev.children) {
                 const mountName = dev.label || dev.uuid || dev.name || dev.device;
                 const devPath = dev.device || dev.name;
                 html += `<div>
                    <button class="primary small drive-mount" data-device="${escapeHtml(devPath || '')}" data-name="${escapeHtml(mountName || '')}">Mount</button>
                 </div>`;
            }
            html += `</div></div>`;
            
            if (dev.children) {
                dev.children.forEach(child => {
                    html += `<div style="margin-left:20px; border-left: 2px solid var(--border-color); padding-left: 10px;">${renderDevice(child)}</div>`;
                });
            }
            return html;
        }

        if (Array.isArray(devices)) {
            devices.forEach(dev => {
                const div = document.createElement('div');
                div.innerHTML = renderDevice(dev);
                container.appendChild(div);
            });
        }

        container.querySelectorAll('.drive-mount').forEach(btn => {
            btn.addEventListener('click', () => {
                mountDrive(btn.dataset.device || '', btn.dataset.name || '', btn);
            });
        });
        container.querySelectorAll('.drive-unmount').forEach(btn => {
            btn.addEventListener('click', () => {
                unmountDrive(btn.dataset.mountpoint || '');
            });
        });
    } catch (e) {
        console.error(e);
        container.innerHTML = 'Error scanning drives.';
    }
}

async function mountDrive(device, name, btn) {
    // Clean name for mount point
    name = String(name).replace(/[^a-zA-Z0-9-_]/g, '');
    if (!name) name = 'usb_drive';

    try {
        let devPath = device;
        if (!device.startsWith('/') && !device.startsWith('PhysicalDrive')) {
            devPath = `/dev/${device}`;
        }
        
        if (btn) {
            btn.innerText = 'Mounting...';
            btn.disabled = true;
        }

        const res = await fetch(`${API_BASE}/system/mount?device=${devPath}&mount_point=${name}`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const result = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(result.detail || result.error || 'Mount failed');
        }
        
        if (result.status === 'mounted' || result.status === 'not_implemented_on_windows') {
            loadDrives(); 
        } else {
            alert('Error: ' + (result.message || JSON.stringify(result)));
            if (btn) {
                btn.innerText = 'Mount';
                btn.disabled = false;
            }
        }
    } catch (e) {
        alert('Error: ' + e);
        loadDrives();
    }
}


async function unmountDrive(mountpoint, force = false) {
    if (!force && !confirm(`Unmount ${mountpoint}?`)) return;

    try {
        const res = await fetch(`${API_BASE}/system/unmount`, {
            method: 'POST',
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                target: mountpoint,
                force: force
            })
        });
        if (res.status === 401) { logout(); return; }

        const result = await res.json().catch(() => ({}));

        if (!res.ok) {
            // Check if drive is busy (409 Conflict)
            if (res.status === 409 && result.detail && result.detail.includes('Drive is busy')) {
                const forceUnmount = confirm(
                    `${result.detail}\n\nDo you want to force unmount and kill these processes?`
                );
                if (forceUnmount) {
                    await unmountDrive(mountpoint, true);
                }
                return;
            }
            throw new Error(result.detail || result.error || 'Unmount failed');
        }

        if (result.status === 'unmounted' || result.status === 'not_implemented_on_windows') {
            loadDrives();
        } else {
            alert('Error: ' + (result.message || JSON.stringify(result)));
        }
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function changePassword() {
    const current = document.getElementById('change-pwd-current').value;
    const newPass = document.getElementById('change-pwd-new').value;
    const confirm = document.getElementById('change-pwd-confirm').value;

    if (!current || !newPass || !confirm) {
        alert('Please fill in all password fields.');
        return;
    }

    if (newPass !== confirm) {
        alert('New passwords do not match.');
        return;
    }

    if (newPass.length < 8) {
        alert('New password must be at least 8 characters long.');
        return;
    }

    if (!/[A-Z]/.test(newPass)) {
        alert('New password must contain at least one uppercase letter.');
        return;
    }

    if (!/[a-z]/.test(newPass)) {
        alert('New password must contain at least one lowercase letter.');
        return;
    }

    if (!/[0-9]/.test(newPass)) {
        alert('New password must contain at least one digit.');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/auth/change-password`, {
            method: 'POST',
            headers: { 
                ...getAuthHeaders(),
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({
                current_password: current,
                new_password: newPass
            })
        });

        const data = await res.json();
        if (res.ok) {
            alert('Password updated successfully!');
            // Clear fields
            document.getElementById('change-pwd-current').value = '';
            document.getElementById('change-pwd-new').value = '';
            document.getElementById('change-pwd-confirm').value = '';
        } else {
            alert(data.detail || 'Failed to update password.');
        }
    } catch (e) {
        console.error('Error updating password:', e);
        alert('Error updating password. See console for details.');
    }
}

async function loadProfileUI() {
    const nameEl = document.getElementById('profile-name');
    const avatarEl = document.getElementById('profile-avatar');
    const parentalEl = document.getElementById('profile-parental');
    if (!nameEl && !avatarEl && !parentalEl) return;

    try {
        const res = await fetch(`${API_BASE}/auth/profile`, { headers: getAuthHeaders() });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) return;

        currentProfile = data;
        if (nameEl && typeof data.name === 'string') nameEl.value = data.name;
        if (avatarEl) avatarEl.value = data.avatar || '';
        if (parentalEl) parentalEl.value = String(Number(data.parental_controls || 0));
    } catch {}
}

async function saveProfileUI() {
    const nameEl = document.getElementById('profile-name');
    const avatarEl = document.getElementById('profile-avatar');
    const parentalEl = document.getElementById('profile-parental');
    if (!nameEl) return;

    const name = String(nameEl.value || '').trim();
    if (!name) {
        showToast('Display name is required', 'error');
        return;
    }

    const avatarRaw = avatarEl ? String(avatarEl.value || '').trim() : '';
    const avatar = avatarRaw ? avatarRaw : null;
    const parental_controls = parentalEl ? Number(parentalEl.value || 0) : 0;

    try {
        const res = await fetch(`${API_BASE}/auth/profile`, {
            method: 'POST',
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name,
                avatar,
                preferences: currentProfile?.preferences || {},
                parental_controls: Number.isFinite(parental_controls) ? parental_controls : 0
            })
        });
        if (res.status === 401) { logout(); return; }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showToast(data.detail || 'Failed to update profile', 'error');
            return;
        }

        currentProfile = {
            ...(currentProfile || {}),
            name,
            avatar,
            parental_controls: Number.isFinite(parental_controls) ? parental_controls : 0
        };
        showToast('Profile updated', 'success');
    } catch {
        showToast('Network error updating profile', 'error');
    }
}

window.saveProfileUI = saveProfileUI;
window.loadProfileUI = loadProfileUI;

function saveSettings() {
    const serverName = document.getElementById('setting-server-name').value;
    const sessionDays = document.getElementById('setting-session-days').value;
    localStorage.setItem('nomadpi.serverName', serverName);
    localStorage.setItem('nomadpi.sessionDays', sessionDays);
    if (serverName) {
        document.querySelectorAll('.logo').forEach(el => el.textContent = serverName);
        document.title = serverName;
    }
    alert('Settings saved locally! (Backend settings requires environment variables update)');
}

function setTheme(theme) {
    if (theme === 'dark') {
        document.body.classList.remove('glass-theme');
        document.body.classList.add('dark-theme');
    } else {
        document.body.classList.remove('dark-theme');
        document.body.classList.add('glass-theme');
    }
    localStorage.setItem('nomadpi.theme', theme);
}

// Initialize settings on load
window.addEventListener('DOMContentLoaded', () => {
    const serverName = localStorage.getItem('nomadpi.serverName');
    const sessionDays = localStorage.getItem('nomadpi.sessionDays');
    const theme = localStorage.getItem('nomadpi.theme');

    if (serverName) {
        const nameInput = document.getElementById('setting-server-name');
        if (nameInput) nameInput.value = serverName;
        document.querySelectorAll('.logo').forEach(el => el.textContent = serverName);
        document.title = serverName;
    }
    if (sessionDays) {
        const daysInput = document.getElementById('setting-session-days');
        if (daysInput) daysInput.value = sessionDays;
    }
    if (theme) setTheme(theme);
    
    // Check if we just updated
    checkPostUpdate();
});

async function loadUsers() {
    const container = document.getElementById('user-management-list');
    if (!container) return;

    try {
        const res = await fetch(`${API_BASE}/auth/users`, { headers: getAuthHeaders() });
        if (res.status === 401) { logout(); return; }
        if (res.status === 403) {
            container.innerHTML = '<p class="error">Admin privileges required.</p>';
            return;
        }
        if (!res.ok) {
            throw new Error(`Failed to load users: ${res.statusText}`);
        }
        
        const users = await res.json();
        if (!Array.isArray(users)) {
            container.innerHTML = '<p>No users found.</p>';
            return;
        }

        container.innerHTML = '';
        users.forEach(user => {
            const div = document.createElement('div');
            div.className = 'list-item glass';
            div.style.display = 'flex';
            div.style.justifyContent = 'space-between';
            div.style.alignItems = 'center';
            div.style.padding = '10px 15px';
            div.style.marginBottom = '8px';
            div.style.borderRadius = '8px';

            const info = document.createElement('div');
            info.innerHTML = `
                <div style="font-weight:bold;">${escapeHtml(user.username)}</div>
                <div style="font-size:0.85em; color:var(--text-muted);">${user.is_admin ? '🛡️ Admin' : '👤 User'} • Joined ${new Date(user.created_at).toLocaleDateString()}</div>
            `;

            const actions = document.createElement('div');
            actions.style.display = 'flex';
            actions.style.gap = '8px';

            // Don't allow deleting yourself or the main admin if possible
            // But for now just basic delete
            const delBtn = document.createElement('button');
            delBtn.className = 'danger btn-sm';
            delBtn.innerHTML = '<i class="fas fa-trash"></i>';
            delBtn.onclick = () => deleteUser(user.id, user.username);
            
            const roleBtn = document.createElement('button');
            roleBtn.className = 'secondary btn-sm';
            roleBtn.innerHTML = user.is_admin ? 'Revoke Admin' : 'Make Admin';
            roleBtn.onclick = () => toggleUserAdmin(user.id, !user.is_admin);

            const passBtn = document.createElement('button');
            passBtn.className = 'secondary btn-sm';
            passBtn.innerHTML = '<i class="fas fa-key"></i>';
            passBtn.title = 'Reset Password';
            passBtn.onclick = () => resetUserPassword(user.id, user.username);

            actions.appendChild(roleBtn);
            actions.appendChild(passBtn);
            actions.appendChild(delBtn);

            div.appendChild(info);
            div.appendChild(actions);
            container.appendChild(div);
        });
    } catch (e) {
        console.error('Error loading users:', e);
        container.innerHTML = '<p>Error loading users.</p>';
    }
}

async function addUser() {
    const usernameInput = document.getElementById('new-user-username');
    const passwordInput = document.getElementById('new-user-password');
    const isAdminInput = document.getElementById('new-user-is-admin');

    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    const is_admin = isAdminInput.checked;

    if (!username || !password) {
        showToast('Username and password are required', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/auth/users`, {
            method: 'POST',
            headers: { 
                ...getAuthHeaders(),
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ username, password, is_admin })
        });

        if (res.status === 401) { logout(); return; }

        if (res.ok) {
            showToast(`User ${username} created`, 'success');
            usernameInput.value = '';
            passwordInput.value = '';
            isAdminInput.checked = false;
            loadUsers();
        } else {
            const data = await res.json();
            showToast(data.detail || 'Failed to create user', 'error');
        }
    } catch (e) {
        console.error('Error adding user:', e);
        showToast('Network error', 'error');
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`Are you sure you want to delete user "${username}"?`)) return;

    try {
        const res = await fetch(`${API_BASE}/auth/users/${userId}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (res.status === 401) { logout(); return; }

        if (res.ok) {
            showToast('User deleted', 'success');
            loadUsers();
        } else {
            const data = await res.json();
            showToast(data.detail || 'Failed to delete user', 'error');
        }
    } catch (e) {
        console.error('Error deleting user:', e);
        showToast('Network error', 'error');
    }
}

async function toggleUserAdmin(userId, makeAdmin) {
    try {
        const res = await fetch(`${API_BASE}/auth/users/${userId}/role`, {
            method: 'POST',
            headers: { 
                ...getAuthHeaders(),
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ is_admin: makeAdmin })
        });

        if (res.status === 401) { logout(); return; }

        if (res.ok) {
            showToast('User role updated', 'success');
            loadUsers();
        } else {
            const data = await res.json();
            showToast(data.detail || 'Failed to update role', 'error');
        }
    } catch (e) {
        console.error('Error updating role:', e);
        showToast('Network error', 'error');
    }
}

async function resetUserPassword(userId, username) {
    const newPassword = prompt(`Enter new password for user "${username}":`);
    if (!newPassword) return;

    try {
        const res = await fetch(`${API_BASE}/auth/users/${userId}/password`, {
            method: 'POST',
            headers: { 
                ...getAuthHeaders(),
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ new_password: newPassword })
        });

        if (res.status === 401) { logout(); return; }

        if (res.ok) {
            showToast('Password reset successfully', 'success');
        } else {
            const data = await res.json();
            showToast(data.detail || 'Failed to reset password', 'error');
        }
    } catch (e) {
        console.error('Error resetting password:', e);
        showToast('Network error', 'error');
    }
}

// Auto-detect and load subtitle files (.srt, .vtt)
async function loadSubtitlesForVideo(videoElement, videoPath) {
    if (!videoElement || !videoPath) return;

    try {
        videoElement.querySelectorAll('track').forEach(t => t.remove());
    } catch {}

    try {
        const res = await fetch(`${API_BASE}/media/meta?path=${encodeURIComponent(videoPath)}`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => ({}));
        const subs = Array.isArray(data?.subtitles) ? data.subtitles : [];
        if (subs.length === 0) return;

        const token = getCookie('auth_token');
        const makeSrc = (p) => {
            let subUrl = `${API_BASE}/media/stream?path=${encodeURIComponent(p)}`;
            if (token) subUrl += '&token=' + token;
            return subUrl;
        };

        let anyTrack = false;
        for (const s of subs) {
            if (!s || !s.path) continue;
            const track = document.createElement('track');
            track.kind = 'subtitles';
            track.label = s.label || 'Subtitles';
            const guessed = String(s.label || '').trim();
            const lang = guessed.length === 2 || guessed.length === 3 ? guessed.toLowerCase() : 'en';
            track.srclang = lang;
            track.src = makeSrc(s.path);
            track.default = !anyTrack;
            videoElement.appendChild(track);
            anyTrack = true;
        }

        if (anyTrack) {
            setTimeout(() => {
                try {
                    if (videoElement.textTracks && videoElement.textTracks.length > 0) {
                        videoElement.textTracks[0].mode = 'showing';
                    }
                } catch {}
            }, 150);
        }
    } catch {}
}

function readUpNextQueue() {
    try {
        const raw = localStorage.getItem(UP_NEXT_QUEUE_KEY);
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function writeUpNextQueue(items) {
    try {
        localStorage.setItem(UP_NEXT_QUEUE_KEY, JSON.stringify(items.slice(0, UP_NEXT_QUEUE_LIMIT)));
    } catch {}
}

function upNextQueueAdd(item) {
    if (!item || !item.path) return;
    const queue = readUpNextQueue();
    const next = [item, ...queue.filter(q => q && q.path && q.path !== item.path)];
    writeUpNextQueue(next);
    renderUpNext(next);
}

function renderUpNext(items) {
    const section = document.getElementById('up-next-section');
    const container = document.getElementById('up-next-list');
    if (!container || !section) return;

    const list = Array.isArray(items) ? items : [];
    if (list.length === 0) {
        section.classList.add('hidden');
        container.innerHTML = '';
        return;
    }

    section.classList.remove('hidden');
    container.innerHTML = '';
    list.slice(0, UP_NEXT_QUEUE_LIMIT).forEach(item => {
        const div = document.createElement('div');
        div.className = 'media-item media-card';
        div.style.cursor = 'pointer';

        const posterHtml = item.poster
            ? `<img class="poster-img" src="${item.poster}" loading="lazy" alt="${escapeHtml(item.name)}">`
            : `<div class="poster-placeholder"></div>`;

        const subtitleParts = [item.show, item.season].filter(Boolean).map(v => escapeHtml(v));
        const subtitle = subtitleParts.length ? subtitleParts.join(' • ') : 'Up Next';

        div.innerHTML = `
            <div class="poster-shell">
                ${posterHtml}
                <div class="media-info">
                    <h3>${escapeHtml(item.name)}</h3>
                    <div class="media-details">${subtitle}</div>
                </div>
                <button class="poster-play">Play</button>
            </div>
            <div class="card-meta">
                <div class="card-title">${escapeHtml(item.name)}</div>
                <div class="card-subtitle">${subtitle}</div>
            </div>
        `;

        div.addEventListener('click', (e) => {
            if (e.target.closest('button')) return;
            openVideoViewer(item.path, item.name, 0);
        });

        div.querySelector('.poster-play')?.addEventListener('click', (e) => {
            e.stopPropagation();
            openVideoViewer(item.path, item.name, 0);
        });

        container.appendChild(div);
    });
}

function loadUpNext() {
    renderUpNext(readUpNextQueue());
}

async function prefetchAndQueueNextEpisode(currentPath) {
    const next = await findNextEpisode(currentPath);
    if (!next) return;
    upNextQueueAdd({
        path: next.path,
        name: next.name || 'Next Episode',
        poster: next.poster || null,
        show: next.show || null,
        season: next.season || null
    });
}

// Handle video ended - auto-play next episode
async function handleVideoEnded(currentPath, currentTitle) {
    console.log('[Auto-Play] Video ended:', currentPath);

    // Check if this is a TV show episode
    const nextEpisode = await findNextEpisode(currentPath);

    if (nextEpisode) {
        upNextQueueAdd({
            path: nextEpisode.path,
            name: nextEpisode.name || 'Next Episode',
            poster: nextEpisode.poster || null,
            show: nextEpisode.show || null,
            season: nextEpisode.season || null
        });
        // Show countdown modal
        showNextEpisodeCountdown(nextEpisode, () => {
            closeViewer();
            setTimeout(() => {
                openVideoViewer(nextEpisode.path, nextEpisode.name, 0);
            }, 100);
        });
    } else {
        console.log('[Auto-Play] No next episode found');
    }
}

// Find the next episode in the series
async function findNextEpisode(currentPath) {
    try {
        const res = await fetch(`${API_BASE}/media/shows/next?path=${encodeURIComponent(currentPath)}`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return null; }
        if (!res.ok) return null;
        const data = await res.json().catch(() => ({}));
        const next = data?.next;
        if (next && next.path) {
            console.log('[Auto-Play] Found next episode:', next.name);
            return next;
        }
    } catch (e) {
        console.error('[Auto-Play] Error finding next episode:', e);
    }

    return null;
}

// Parse episode number from filename
function parseEpisodeNumber(filename) {
    // Try SxxExx format
    let match = filename.match(/S\d+E(\d+)/i);
    if (match) return parseInt(match[1]);

    // Try 1x01 format
    match = filename.match(/\d+x(\d+)/i);
    if (match) return parseInt(match[1]);

    // Try Episode XX format
    match = filename.match(/Episode\s*(\d+)/i);
    if (match) return parseInt(match[1]);

    // Try just numbers
    match = filename.match(/E(\d+)/i);
    if (match) return parseInt(match[1]);

    return null;
}

// Show countdown modal for next episode
function showNextEpisodeCountdown(nextEpisode, onPlay) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.9);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;

    const box = document.createElement('div');
    box.style.cssText = `
        background: var(--card-bg);
        padding: 30px;
        border-radius: 12px;
        text-align: center;
        max-width: 400px;
    `;

    box.innerHTML = `
        <h3 style="margin: 0 0 15px 0;">Next Episode</h3>
        <p style="margin: 10px 0; color: var(--text-muted);">${escapeHtml(nextEpisode.name)}</p>
        <p style="font-size: 2rem; margin: 20px 0; font-weight: bold;" id="countdown-timer">10</p>
        <div style="display: flex; gap: 10px; justify-content: center;">
            <button class="secondary" id="cancel-autoplay">Cancel</button>
            <button class="primary" id="play-now">Play Now</button>
        </div>
    `;

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    let countdown = 10;
    const timer = document.getElementById('countdown-timer');

    const interval = setInterval(() => {
        countdown--;
        if (timer) timer.textContent = countdown;
        if (countdown <= 0) {
            clearInterval(interval);
            document.body.removeChild(overlay);
            onPlay();
        }
    }, 1000);

    document.getElementById('cancel-autoplay').onclick = () => {
        clearInterval(interval);
        document.body.removeChild(overlay);
    };

    document.getElementById('play-now').onclick = () => {
        clearInterval(interval);
        document.body.removeChild(overlay);
        onPlay();
    };
}
// Duplicate Detection Functions
async function findDuplicates() {
    const statusDiv = document.getElementById('duplicates-status');
    if (!statusDiv) return;

    statusDiv.innerHTML = '<div style="padding:20px; text-align:center;"><div class="spinner" style="margin:0 auto 10px;"></div><p>Scanning for duplicates...</p></div>';

    try {
        const res = await fetch(`${API_BASE}/media/duplicates`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();

        const fileCount = data.file_duplicates?.length || 0;
        const contentCount = data.content_duplicates?.length || 0;
        const total = fileCount + contentCount;

        if (total === 0) {
            statusDiv.innerHTML = '<div style="padding:20px; text-align:center; color:var(--success-color);"><i class="fas fa-check-circle" style="font-size:2rem; margin-bottom:10px;"></i><p>No duplicates found!</p></div>';
            return;
        }

        let html = `<div style="padding:20px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.1); border-radius:12px; margin-top:15px;">
            <h3 style="margin-bottom:15px;"><i class="fas fa-exclamation-triangle" style="color:var(--warning-color);"></i> Found ${total} Duplicate${total > 1 ? 's' : ''}</h3>`;

        if (fileCount > 0) {
            html += `<h4 style="margin-top:20px; margin-bottom:10px; color:var(--accent-color);">File Duplicates (${fileCount})</h4>`;
            data.file_duplicates.forEach(dup => {
                html += `<div style="margin-bottom:15px; padding:12px; background:rgba(0,0,0,0.2); border-radius:8px;">
                    <div style="font-weight:600; margin-bottom:5px;">${dup.name}</div>
                    <div style="font-size:0.85em; color:var(--text-muted);">Size: ${(dup.size / 1024 / 1024).toFixed(2)} MB • ${dup.count} copies</div>
                    <div style="margin-top:8px; font-size:0.85em;">`;
                dup.paths.forEach((path, i) => {
                    html += `<div style="padding:4px 0; opacity:${i === 0 ? '1' : '0.6'};">${i === 0 ? '✓' : '✕'} ${path}</div>`;
                });
                html += `</div></div>`;
            });
        }

        if (contentCount > 0) {
            html += `<h4 style="margin-top:20px; margin-bottom:10px; color:var(--accent-color);">Content Duplicates (${contentCount})</h4>`;
            data.content_duplicates.forEach(dup => {
                html += `<div style="margin-bottom:15px; padding:12px; background:rgba(0,0,0,0.2); border-radius:8px;">
                    <div style="font-weight:600; margin-bottom:5px;">${dup.title || 'Unknown'}</div>
                    <div style="font-size:0.85em; color:var(--text-muted);">IMDb: ${dup.imdb_id} • ${dup.count} copies</div>
                    <div style="margin-top:8px; font-size:0.85em;">`;
                dup.paths.forEach((path, i) => {
                    html += `<div style="padding:4px 0; opacity:${i === 0 ? '1' : '0.6'};">${i === 0 ? '✓' : '✕'} ${path}</div>`;
                });
                html += `</div></div>`;
            });
        }

        html += `<div style="margin-top:20px; padding:12px; background:rgba(59,130,246,0.1); border:1px solid rgba(59,130,246,0.3); border-radius:8px;">
            <p style="margin:0; font-size:0.9em;"><i class="fas fa-info-circle"></i> Files marked with ✓ will be kept. Others will be deleted if you run Mass Fix.</p>
        </div></div>`;

        statusDiv.innerHTML = html;

    } catch (e) {
        statusDiv.innerHTML = `<div style="padding:20px; text-align:center; color:var(--danger-color);"><i class="fas fa-times-circle" style="font-size:2rem; margin-bottom:10px;"></i><p>Error: ${e.message}</p></div>`;
        console.error('Failed to find duplicates:', e);
    }
}

async function fixDuplicates() {
    if (!confirm('This will permanently delete duplicate files, keeping only one copy of each. The shortest path (likely already organized) will be kept. Continue?')) {
        return;
    }

    showToast('Starting mass duplicate fix...', 'info');

    try {
        const res = await fetch(`${API_BASE}/media/fix_duplicates`, { 
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();

        showToast(data.message || 'Duplicate fix started. Check logs for progress.', 'success');

        // Clear any existing duplicate results
        const statusDiv = document.getElementById('duplicates-status');
        if (statusDiv) {
            statusDiv.innerHTML = '<div style="padding:20px; text-align:center; color:var(--success-color);"><i class="fas fa-check-circle" style="font-size:2rem; margin-bottom:10px;"></i><p>Mass duplicate fix running in background...</p></div>';
        }

        // Refresh stats after a delay
        setTimeout(() => {
            loadStorageStats();
        }, 3000);

    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
        console.error('Failed to fix duplicates:', e);
    }
}
