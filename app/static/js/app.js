console.log("App v1.3 loaded - Continue Watching, Watchlist, Global Search, PiP, Subtitles & More");
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
        if (!res.ok) return;
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
            if (!logRes.ok) return;
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

function closePWAiOSModal() {
    const modal = document.getElementById('pwa-ios-modal');
    if (modal) modal.classList.add('hidden');
}

function installPWA() {
    if (window.deferredInstallPrompt) {
        window.deferredInstallPrompt.prompt();
        window.deferredInstallPrompt.userChoice.then((choice) => {
            if (choice.outcome === 'accepted') {
                const btn = document.getElementById('install-pwa-btn');
                if (btn) btn.classList.add('hidden');
            }
            window.deferredInstallPrompt = null;
        });
        return;
    }
    if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {
        const modal = document.getElementById('pwa-ios-modal');
        if (modal) modal.classList.remove('hidden');
        return;
    }
    showToast('Install is not available in this browser or the app is already installed.', 'info');
}

function initPWAInstallPrompt() {
    const installBtn = document.getElementById('install-pwa-btn');
    if (!installBtn) return;
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        window.deferredInstallPrompt = e;
        installBtn.classList.remove('hidden');
    });
    window.addEventListener('appinstalled', () => {
        window.deferredInstallPrompt = null;
        installBtn.classList.add('hidden');
    });
    if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {
        installBtn.classList.remove('hidden');
        installBtn.innerHTML = '<i class="fas fa-plus-square"></i> Add to Home Screen';
    }
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

    // Apply glass preference (applyTheme already does this; ensure it runs if theme was not applied)
    const noGlass = localStorage.getItem('nomadpi.noGlass') === 'true';
    document.body.classList.toggle('no-glass', noGlass);

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

    // Re-apply glass effect preference so it persists across theme changes
    const noGlass = localStorage.getItem('nomadpi.noGlass') === 'true';
    document.body.classList.toggle('no-glass', noGlass);
}

function toggleGlassEffect() {
    const noGlass = localStorage.getItem('nomadpi.noGlass') !== 'true';
    localStorage.setItem('nomadpi.noGlass', noGlass ? 'true' : 'false');
    document.body.classList.toggle('no-glass', noGlass);
    showToast(noGlass ? 'Glass effects disabled' : 'Glass effects enabled', 'info');
}

let currentMedia = null;
let currentProfile = null;
let driveScanInterval = null;
let statsInterval = null;
let comicPages = [];
let comicIndex = 0;
let comicZoom = 100;          // percent (100 = fit-width)
let comicFit = 'width';       // 'width' | 'height' | 'original'
let comicDouble = false;
let comicThumbsOpen = false;
let comicPath = null;
let _comicTouchStartX = null;
let _comicTouchStartY = null;
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
let activeVideoTitle = null;
let activeVideoPoster = null;
let activeDashboardSessionId = null;
let lastDashboardSessionUpdate = 0;
const DASHBOARD_SESSION_UPDATE_INTERVAL_MS = 5000;
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

// Current user (set on login and checkAuth); used to hide admin-only UI for non-admins
let currentUser = { is_admin: false };

function canEditLibrary() {
    return !!(currentUser && currentUser.is_admin);
}

function updateAdminVisibility() {
    const isAdmin = currentUser && currentUser.is_admin;
    const navAdmin = document.querySelector('#main-nav button[onclick*="showSection(\'admin\')"]');
    const homeAdminCard = document.querySelector('.menu-grid .card[onclick="showSection(\'admin\')"]');
    const mobNav = document.getElementById('btn-more-mob');
    if (navAdmin) navAdmin.style.display = isAdmin ? '' : 'none';
    if (homeAdminCard) homeAdminCard.style.display = isAdmin ? '' : 'none';
    if (mobNav) mobNav.style.display = ''; // "More" stays; admin is inside the menu
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
            if (data.user) {
                currentUser = { is_admin: !!data.user.is_admin, id: data.user.id, username: data.user.username };
                updateAdminVisibility();
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
            if (data.user) {
                currentUser = { is_admin: !!data.user.is_admin, id: data.user.id, username: data.user.username };
                updateAdminVisibility();
            }
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('app').classList.remove('hidden');
            loadStorageStats();
            loadResume();
            loadUpNext();
            loadProfileUI();
            startStatsAutoRefresh();
            loadHomeRows();
            checkDiskSpace();
            checkAutoScan();
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
    if (id === 'admin' && !(currentUser && currentUser.is_admin)) {
        showToast('Admin access required', 'warning');
        id = 'home';
    }
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
    if (id === 'debrid') {
        initDebrid();
    }
    if (id === 'settings') {
        refreshTailscaleStatus();
        loadOmdbKey();
    }
    if (id === 'watchlist') {
        loadWatchlist();
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

        if (!res.ok) {
            const errMsg = status.message || status.detail || status.error || `Request failed (${res.status})`;
            statusDiv.innerHTML = `
                <div class="ts-status-row">
                    <div class="badge badge-danger"><i class="fas fa-exclamation-circle"></i> Error</div>
                    <button onclick="refreshTailscaleStatus()" class="secondary btn-sm" title="Retry"><i class="fas fa-sync-alt"></i></button>
                </div>
                <p class="ts-auth-hint">${escapeHtml(errMsg)}</p>`;
            if (controlsDiv) controlsDiv.innerHTML = '';
            if (authDiv) authDiv.classList.add('hidden');
            return;
        }

        const errorMsg = status.message || status.error;
        let html = '';
        let controlsHtml = '';
        let showAuth = !status.connected;

        const stateClass = status.connected ? 'success' : (status.backend_state === 'NeedsLogin' ? 'warning' : 'muted');
        const stateIcon = status.connected ? 'check-circle' : (status.backend_state === 'NeedsLogin' ? 'key' : 'circle');

        html += `<div class="ts-status-row">
            <div class="badge badge-${stateClass}"><i class="fas fa-${stateIcon}"></i> ${escapeHtml(status.backend_state || 'Unknown')}</div>
            <button onclick="refreshTailscaleStatus()" class="secondary btn-sm" title="Refresh"><i class="fas fa-sync-alt"></i></button>
        </div>`;

        if (!status.installed) {
            html += `<p class="ts-auth-hint" style="color:var(--danger-color);"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(errorMsg || 'Tailscale is not installed on this system.')}</p>`;
        } else if (!status.service_running) {
            if (errorMsg) html += `<p class="ts-auth-hint">${escapeHtml(errorMsg)}</p>`;
            else html += `<p class="ts-auth-hint">The Tailscale system service is stopped.</p>`;
            controlsHtml = `<button onclick="controlTailscaleService('start')" class="success"><i class="fas fa-play"></i> Start Service</button>`;
        } else {
            if (status.ipv4) {
                html += `<div class="ts-ip-box">
                    <div class="ts-ip-box-header">
                        <span class="ts-ip-label">Tailscale IP</span>
                        <button onclick="copyToClipboard('${escapeHtml(status.ipv4)}')" class="secondary btn-sm" title="Copy IP"><i class="fas fa-copy"></i></button>
                    </div>
                    <div class="ts-ip-value">${escapeHtml(status.ipv4)}</div>
                    ${status.magic_dns ? `<div class="ts-ip-label" style="margin-top:4px;">${escapeHtml(status.magic_dns)}</div>` : ''}
                </div>`;
            }
            if (status.peer_count > 0) {
                html += `<p class="ts-auth-hint" style="margin-top:8px;"><i class="fas fa-network-wired"></i> ${status.peer_count} peer${status.peer_count === 1 ? '' : 's'} connected</p>`;
            }

            if (status.connected) {
                controlsHtml = `<button onclick="disconnectTailscale()" class="warning"><i class="fas fa-unlink"></i> Disconnect</button>
                    <button onclick="controlTailscaleService('stop')" class="danger btn-sm" title="Stop Service"><i class="fas fa-power-off"></i></button>`;
            } else {
                controlsHtml = `<button onclick="connectTailscale()" class="primary"><i class="fas fa-plug"></i> Connect</button>
                    <button onclick="controlTailscaleService('stop')" class="danger btn-sm" title="Stop Service"><i class="fas fa-power-off"></i></button>`;
            }
        }

        statusDiv.innerHTML = html;
        if (controlsDiv) controlsDiv.innerHTML = controlsHtml;
        if (authDiv) {
            if (showAuth) authDiv.classList.remove('hidden');
            else authDiv.classList.add('hidden');
        }

    } catch (e) {
        console.error('Tailscale status error:', e);
        statusDiv.innerHTML = `
            <div class="ts-status-row">
                <div class="badge badge-danger"><i class="fas fa-exclamation-circle"></i> Error</div>
                <button onclick="refreshTailscaleStatus()" class="secondary btn-sm" title="Retry"><i class="fas fa-sync-alt"></i></button>
            </div>
            <p class="ts-auth-hint">${escapeHtml(e.message || 'Network error')}</p>`;
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
        if (!res.ok) {
            showToast(data.detail || data.message || 'Connection failed', 'error');
            refreshTailscaleStatus();
            return;
        }

        if (data.status === 'success') {
            showToast('Connected to Tailscale!', 'success');
            // Poll a couple of times to let the daemon update
            setTimeout(refreshTailscaleStatus, 1500);
            setTimeout(refreshTailscaleStatus, 4000);
        } else if (data.status === 'needs_auth') {
            const urlMatch = data.output && data.output.match(/https:\/\/[^\s]+/);
            if (urlMatch) {
                if (confirm(`Authentication required. Open Tailscale login page?\n\n${urlMatch[0]}`)) {
                    window.open(urlMatch[0], '_blank');
                }
            } else {
                showToast('Authentication required. Check Tailscale logs.', 'warning');
            }
            refreshTailscaleStatus();
        } else {
            showToast('Connection failed: ' + (data.detail || 'Unknown error'), 'error');
            refreshTailscaleStatus();
        }
    } catch (e) {
        showToast('Connection failed', 'error');
        refreshTailscaleStatus();
    }
}

async function disconnectTailscale() {
    if (!confirm('Disconnect from Tailscale VPN?')) return;
    try {
        const res = await fetch(`${API_BASE}/system/tailscale/down`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            showToast('Disconnected from Tailscale', 'info');
        } else {
            const data = await res.json().catch(() => ({}));
            showToast(data.detail || 'Disconnect failed', 'error');
        }
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
            showToast(`Service ${action === 'start' ? 'started' : 'stopped'}`, 'success');
            // Give the daemon a moment to fully start/stop
            setTimeout(refreshTailscaleStatus, 2000);
        } else {
            const data = await res.json().catch(() => ({}));
            showToast(`Failed: ${data.detail || 'Unknown error'}`, 'error');
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
                    <div class="media-card glass" onclick="loadFileBrowser(${JSON.stringify(d.mountpoint)})">
                        <div class="media-info">
                            <h3>💽 Drive ${escapeHtml(d.name)} (${formatBytes(d.free)} free)</h3>
                            <p>${escapeHtml(d.fstype)} - ${escapeHtml(d.mountpoint)}</p>
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
                <div class="media-card glass" onclick="loadFileBrowser(${JSON.stringify(parentPath || '/data')})">
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
                const itemPath = item.path;

                if (item.is_dir) {
                    div.innerHTML = `
                        <div class="media-card glass">
                            <div class="media-info">
                                <h3>📁 ${escapeHtml(item.name)}</h3>
                            </div>
                        </div>
                    `;
                    // Use addEventListener instead of inline onclick for better reliability
                    div.querySelector('.media-card').addEventListener('click', () => loadFileBrowser(itemPath));
                } else {
                    const ext = item.name.split('.').pop().toLowerCase();
                    let icon = '📄';
                    if (['mp4', 'mkv', 'avi', 'mov', 'webm'].includes(ext)) icon = '🎬';
                    if (['mp3', 'flac', 'wav', 'm4a'].includes(ext)) icon = '🎵';
                    if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) icon = '🖼️';
                    if (['pdf', 'epub', 'cbz', 'cbr'].includes(ext)) icon = '📚';

                    div.innerHTML = `
                        <div class="media-card glass">
                            <div class="media-info">
                                <h3>${icon} ${escapeHtml(item.name)}</h3>
                                <p>${formatBytes(item.size)}</p>
                            </div>
                        </div>
                    `;
                    // Use addEventListener instead of inline onclick for better reliability
                    div.querySelector('.media-card').addEventListener('click', () => openFile(itemPath));
                }
                container.appendChild(div);
            });
        }
        
        mediaState.path = path;
    } catch (e) {
        console.error('Error in loadFileBrowser:', e);
        container.innerHTML = `<p>Error loading directory: ${escapeHtml(e.message || String(e))}</p>`;
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
        const icons = { movies:'🎬', shows:'📺', music:'🎵', books:'📖', gallery:'🖼️', files:'📁' };
        const labels = { movies:'No movies found', shows:'No shows found', music:'No music found', books:'No books found', gallery:'No gallery items', files:'No files found' };
        container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">${icons[category] || '📂'}</div><div class="empty-state-title">${labels[category] || 'Nothing here yet'}</div><div class="empty-state-subtitle">Upload files in the Admin section to get started.</div></div>`;
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
        const isListCategory = (category === 'music' || category === 'files' || category === 'books');
        div.className = isListCategory ? 'list-item' : 'media-item';
        div.style.position = 'relative';

        let folderHtml = '';
        if (file.folder && file.folder !== '.') {
            if (isListCategory) {
                folderHtml = `<div class="track-artist">${escapeHtml(file.folder)}</div>`;
            } else {
                folderHtml = `<div class="folder-tag">${escapeHtml(file.folder)}</div>`;
            }
        }

        const canEdit = canEditLibrary();
        const cardDeleteBtn = canEdit ? `<button class="card-action-btn card-delete-btn" title="Delete" data-delete-path="${escapeHtml(file.path)}">×</button>` : '';
        const cardRenameBtn = canEdit ? `<button class="card-action-btn card-rename-btn rename-btn-card" title="Rename">✏</button>` : '';

        if (category === 'music') {
            const title = escapeHtml(cleanTitle(file.name));
            const artist = file.folder && file.folder !== '.' ? escapeHtml(file.folder) : '';
            div.innerHTML = `
                <div class="track-art">🎵</div>
                <div class="track-info">
                    <div class="track-title">${title}</div>
                    ${artist ? `<div class="track-artist">${artist}</div>` : ''}
                </div>
                <div class="track-actions">
                    ${canEdit ? '<button class="icon-btn rename-btn" title="Rename">✏</button>' : ''}
                    <button class="btn-play-track music-play" title="Play">▶</button>
                    ${canEdit ? `<button class="icon-btn" title="Delete" onclick="deleteItem(${JSON.stringify(file.path)})">🗑</button>` : ''}
                </div>
            `;
            const playBtn = div.querySelector('.music-play');
            if (playBtn) {
                playBtn.addEventListener('click', () => startMusicQueue(files, files.indexOf(file)));
            }
            const renameBtn = div.querySelector('.rename-btn');
            if (renameBtn) {
                renameBtn.addEventListener('click', () => promptRename(file.path, file.name, () => loadMediaPage('music', true)));
            }
        } else if (category === 'files') {
            const ext = (file.name.split('.').pop() || '').toLowerCase();
            const fileIcon = { pdf:'📄', mp4:'🎬', mkv:'🎬', avi:'🎬', mov:'🎬', mp3:'🎵', flac:'🎵', ogg:'🎵', jpg:'🖼️', jpeg:'🖼️', png:'🖼️', gif:'🖼️', zip:'📦', rar:'📦', txt:'📝', doc:'📝', docx:'📝' }[ext] || '📁';
            div.innerHTML = `
                <div class="file-icon">${fileIcon}</div>
                <div class="file-info">
                    <div class="file-name">${escapeHtml(file.name)}</div>
                    ${file.folder && file.folder !== '.' ? `<div class="file-folder">${escapeHtml(file.folder)}</div>` : ''}
                </div>
                <div class="file-actions">
                    ${canEdit ? '<button class="icon-btn rename-btn" title="Rename">✏</button>' : ''}
                    <a href="${escapeHtml(file.path)}" target="_blank" class="btn-open-file">Open</a>
                    ${canEdit ? `<button class="icon-btn" title="Delete" onclick="deleteItem(${JSON.stringify(file.path)})">🗑</button>` : ''}
                </div>
            `;
            const renameBtn = div.querySelector('.rename-btn');
            if (renameBtn) {
                renameBtn.addEventListener('click', () => promptRename(file.path, file.name, () => loadMediaPage('files', true)));
            }
        } else if (category === 'gallery') {
            if (file.name.match(/\.(jpg|jpeg|png|gif|webp)$/i)) {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${cardRenameBtn}
                    <img src="${escapeHtml(file.path)}" loading="lazy" alt="${escapeHtml(file.name)}">
                    <div class="caption">${escapeHtml(file.name)}</div>
                `;
                div.querySelector('img')?.addEventListener('click', () => openImageViewer(file.path, file.name));
            } else {
                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${cardRenameBtn}
                    <video controls preload="metadata" src="${escapeHtml(file.path)}"></video>
                    <div class="caption">${escapeHtml(file.name)}</div>
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
            const isCbz = /\.cbz$/i.test(file.name || '');
            const isCbr = /\.cbr$/i.test(file.name || '');
            const isEpub = /\.epub$/i.test(file.name || '');
            const title = escapeHtml(cleanTitle(file.name));
            const bookIcon = isPdf ? '📄' : (isCbz || isCbr) ? '📚' : isEpub ? '📖' : '📖';
            const canView = isPdf || isCbz || isCbr;
            div.innerHTML = `
                <div class="book-cover">${bookIcon}</div>
                <div class="book-info">
                    <div class="book-title">${title}</div>
                    ${file.folder && file.folder !== '.' ? `<div class="book-folder">${escapeHtml(file.folder)}</div>` : ''}
                </div>
                <div class="book-actions">
                    ${canEdit ? '<button class="icon-btn rename-btn-card" title="Rename">✏</button>' : ''}
                    ${canView ? '<button class="icon-btn view-btn" title="View">👁</button>' : ''}
                    <a href="${escapeHtml(file.path)}" target="_blank" class="btn-open-file">Open</a>
                    ${canEdit ? `<button class="icon-btn" title="Delete" onclick="deleteItem(${JSON.stringify(file.path)})">🗑</button>` : ''}
                </div>
            `;

            const btn = div.querySelector('.view-btn');
            if (btn) {
                btn.addEventListener('click', () => {
                    if (isPdf) openPdfViewer(file.path, file.name || 'PDF');
                    else openComicViewer(file.path, file.name || 'Comic');
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
                
                const playLabel = Number(file?.progress?.current_time || 0) > 10 ? 'Resume' : 'Play';

                div.innerHTML = `
                    ${cardDeleteBtn}
                    ${cardRenameBtn}
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

let renameModalState = { oldPath: '', oldName: '', ext: '', refreshCallback: null, isShowPart: false };

function getRenameBaseAndExt(name, path) {
    const slashIdx = name.lastIndexOf('/');
    const dotIdx = name.lastIndexOf('.');
    const isFile = dotIdx !== -1 && (slashIdx === -1 || dotIdx > slashIdx);
    const ext = isFile ? name.substring(dotIdx) : '';
    const base = isFile ? name.substring(0, dotIdx) : name;
    return { base, ext, isFile };
}

function openRenameModal(oldPath, oldName, refreshCallback, isShowPart) {
    const { base, ext, isFile } = getRenameBaseAndExt(oldName, oldPath);
    renameModalState = { oldPath, oldName, ext, refreshCallback: refreshCallback || null, isShowPart: !!isShowPart };
    const modal = document.getElementById('rename-modal');
    const title = document.getElementById('rename-modal-title');
    const hint = document.getElementById('rename-modal-hint');
    const input = document.getElementById('rename-modal-input');
    const errEl = document.getElementById('rename-modal-error');
    if (title) title.textContent = `Rename ${isFile ? 'File' : 'Folder'}`;
    if (hint) hint.textContent = isFile ? 'Extension will be preserved.' : 'Enter the new folder name.';
    if (input) {
        input.value = base;
        input.focus();
        input.select();
    }
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    if (modal) modal.classList.remove('hidden');
}

function closeRenameModal() {
    const modal = document.getElementById('rename-modal');
    if (modal) modal.classList.add('hidden');
    renameModalState = { oldPath: '', oldName: '', ext: '', refreshCallback: null, isShowPart: false };
}

async function confirmRenameModal() {
    const input = document.getElementById('rename-modal-input');
    const errEl = document.getElementById('rename-modal-error');
    if (!input || !renameModalState.oldPath) return;
    const newBase = (input.value || '').trim();
    const { base, ext } = getRenameBaseAndExt(renameModalState.oldName, renameModalState.oldPath);
    if (!newBase) {
        if (errEl) { errEl.textContent = 'Please enter a name.'; errEl.style.display = 'block'; }
        return;
    }
    if (newBase === base) {
        closeRenameModal();
        return;
    }
    const newName = newBase + ext;
    const parts = renameModalState.oldPath.split('/');
    parts.pop();
    const newPath = parts.join('/').replace(/\/+/g, '/') + '/' + newName;
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    const submitBtn = document.getElementById('rename-modal-submit');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Renaming…'; }
    try {
        await renameMediaPath(renameModalState.oldPath, newPath);
        closeRenameModal();
        if (renameModalState.refreshCallback) renameModalState.refreshCallback();
        if (renameModalState.isShowPart) {
            if (showsState.level !== 'shows' && showsState.showName === renameModalState.oldName) {
                showsState.showName = newBase;
            } else if (showsState.level === 'episodes' && showsState.seasonName === renameModalState.oldName) {
                showsState.seasonName = newBase;
            }
            await loadShowsLibrary();
        }
        showToast('Renamed successfully', 'success');
    } catch (err) {
        if (errEl) { errEl.textContent = err.message || 'Rename failed'; errEl.style.display = 'block'; }
        showToast(err.message || 'Rename failed', 'error');
    } finally {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Rename'; }
    }
}

function initRenameModal() {
    const input = document.getElementById('rename-modal-input');
    const submitBtn = document.getElementById('rename-modal-submit');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') confirmRenameModal();
            if (e.key === 'Escape') closeRenameModal();
        });
    }
    if (submitBtn) submitBtn.addEventListener('click', confirmRenameModal);
}

async function promptRename(oldPath, oldName, refreshCallback) {
    openRenameModal(oldPath, oldName, refreshCallback, false);
}

async function promptRenameShowPart(oldPath, oldName) {
    openRenameModal(oldPath, oldName, () => loadShowsLibrary(), true);
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
    const artistEl = document.getElementById('player-artist');
    if (artistEl) artistEl.textContent = (track.folder && track.folder !== '.') ? track.folder : '';
    const artEl = document.getElementById('player-art');
    if (artEl) artEl.textContent = '🎵';
    
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
    if (!musicQueue.length) return;
    if (musicShuffle) {
        musicShufflePos = Math.max(musicShufflePos - 1, 0);
        playMusicAt(musicShuffleOrder[musicShufflePos] ?? musicIndex);
        return;
    }
    playMusicAt((musicIndex - 1 + musicQueue.length) % musicQueue.length);
}

function openPdfViewer(path, title) {
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
    if (activeDashboardSessionId && activeVideoPath) {
        updateDashboardSession(activeDashboardSessionId, activeVideoPath, activeVideoTitle || 'Video', 'stopped', activeVideoEl?.currentTime ?? 0, activeVideoEl?.duration ?? 0, activeVideoPoster);
        activeDashboardSessionId = null;
        activeVideoTitle = null;
        activeVideoPoster = null;
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

function openVideoViewer(path, title, startSeconds = 0, posterUrl = null) {
    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');
    if (!modal || !body || !heading) {
        window.open(path, '_blank');
        return;
    }

    activeDashboardSessionId = 'web_' + Date.now() + '_' + Math.random().toString(36).slice(2, 9);
    activeVideoTitle = title || 'Video';
    activeVideoPoster = posterUrl || null;

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
        <div class="viewer-title-row">
            <span class="viewer-title-text">${safeTitle}</span>
            <div class="external-player-btns">
                <button class="player-action-btn" id="pip-btn" title="Picture-in-Picture" onclick="togglePiP()">
                    <span>⧉</span><span class="btn-text">PiP</span>
                </button>
                <select class="player-action-btn speed-select" id="speed-select" title="Playback speed" onchange="setPlaybackSpeed(this.value)">
                    <option value="0.5">0.5×</option>
                    <option value="0.75">0.75×</option>
                    <option value="1" selected>1×</option>
                    <option value="1.25">1.25×</option>
                    <option value="1.5">1.5×</option>
                    <option value="2">2×</option>
                </select>
                <button class="player-action-btn" title="Subtitles" onclick="openSubtitleSearch('${escapeHtml(path)}', '${safeTitle}')">
                    <span>💬</span><span class="btn-text">Subs</span>
                </button>
                <button class="player-action-btn" title="Mark as watched" onclick="markAsWatched('${escapeHtml(path)}', 1)">
                    <span>✓</span><span class="btn-text">Watched</span>
                </button>
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
    video.addEventListener('timeupdate', () => {
        updateProgress(video, path);
        if (activeDashboardSessionId && !video.paused) {
            updateDashboardSession(activeDashboardSessionId, path, activeVideoTitle, 'playing', video.currentTime, video.duration, activeVideoPoster);
        }
    });
    video.addEventListener('pause', () => {
        try { updateProgress(video, path, true); } catch (e) {}
        if (activeDashboardSessionId) {
            updateDashboardSession(activeDashboardSessionId, path, activeVideoTitle, 'paused', video.currentTime, video.duration, activeVideoPoster);
        }
    });
    video.addEventListener('seeked', () => { try { updateProgress(video, path, true); } catch (e) {} });
    video.addEventListener('play', () => {
        if (activeDashboardSessionId) {
            updateDashboardSession(activeDashboardSessionId, path, activeVideoTitle, 'playing', video.currentTime, video.duration, activeVideoPoster);
        }
        if (activeVideoProgressInterval) clearInterval(activeVideoProgressInterval);
        activeVideoProgressInterval = setInterval(() => {
            try { updateProgress(video, path); } catch (e) {}
            if (activeDashboardSessionId && !video.paused) {
                updateDashboardSession(activeDashboardSessionId, path, activeVideoTitle, 'playing', video.currentTime, video.duration, activeVideoPoster);
            }
        }, 5000);
    });
    video.addEventListener('ended', () => {
        if (activeVideoProgressInterval) clearInterval(activeVideoProgressInterval);
        activeVideoProgressInterval = null;
        if (activeDashboardSessionId) {
            updateDashboardSession(activeDashboardSessionId, path, activeVideoTitle, 'stopped', video.currentTime, video.duration, activeVideoPoster);
        }
    });
    video.addEventListener('loadedmetadata', () => checkResume(video, path, Number(startSeconds || 0)), { once: true });

    // Auto-detect and load subtitles
    loadSubtitlesForVideo(video, path);

    prefetchAndQueueNextEpisode(path);

    // Auto-play next episode when current one ends
    video.addEventListener('ended', async () => {
        try { await updateProgress(video, path, true); } catch (e) {}
        await handleVideoEnded(path, activeVideoTitle);
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

// ═══════════════════════════════════════════════════════════
//  COMIC READER — full revamp v1.3.0
// ═══════════════════════════════════════════════════════════

async function openComicViewer(path, title) {
    comicPath = path;
    comicPages = [];
    comicIndex = 0;
    comicZoom = 100;
    comicFit = 'width';
    comicDouble = false;

    const overlay = document.getElementById('comic-overlay');
    if (!overlay) return;

    // Show overlay, set title, show loading
    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    _comicSetTitle(title || 'Comic');
    _comicShowLoading(true);
    _comicUpdateFitBtn();
    _comicUpdateZoomUI();

    // Attach touch events once
    const stage = document.getElementById('cr-stage');
    if (stage && !stage._comicTouchBound) {
        stage.addEventListener('touchstart', _comicTouchStart, { passive: true });
        stage.addEventListener('touchend', _comicTouchEnd, { passive: true });
        stage._comicTouchBound = true;
    }

    try {
        const res = await fetch(`${API_BASE}/media/books/comic/pages?path=${encodeURIComponent(path)}`, {
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = typeof data.detail === 'string' ? data.detail : 'Failed to load comic.';
            _comicShowError(msg);
            return;
        }
        comicPages = Array.isArray(data.pages) ? data.pages : [];
        if (comicPages.length === 0) { _comicShowError('No pages found in this comic.'); return; }

        // Use server-returned title if we have better data than the filename
        if (data.title) _comicSetTitle(data.title);

        _comicShowLoading(false);
        _comicBuildThumbs();
        _comicRender();
    } catch (e) {
        _comicShowError('Connection error. Please try again.');
    }
}

function closeComicOverlay() {
    const overlay = document.getElementById('comic-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
    // Exit fullscreen if active
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    comicPages = [];
    comicIndex = 0;
}

function _comicSetTitle(t) {
    const el = document.getElementById('cr-title');
    if (el) el.textContent = String(t);
}

function _comicShowLoading(show) {
    document.getElementById('cr-loading')?.classList.toggle('hidden', !show);
    document.getElementById('cr-pages')?.classList.toggle('hidden', show);
    document.getElementById('cr-zoom-bar')?.classList.toggle('hidden', show);
}

function _comicShowError(msg) {
    _comicShowLoading(false);
    const pagesEl = document.getElementById('cr-pages');
    if (pagesEl) pagesEl.innerHTML = `<div class="cr-error"><i class="fas fa-exclamation-triangle"></i><p>${escapeHtml(msg)}</p></div>`;
    pagesEl?.classList.remove('hidden');
}

function _comicTokenUrl(url) {
    if (!url) return '';
    const token = getCookie('auth_token');
    if (token && (url.startsWith('/data/') || url.startsWith('/api/'))) {
        return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);
    }
    return url;
}

function _comicRender() {
    const pagesEl = document.getElementById('cr-pages');
    if (!pagesEl || !comicPages.length) return;
    comicIndex = Math.max(0, Math.min(comicIndex, comicPages.length - 1));

    pagesEl.innerHTML = '';
    pagesEl.className = 'cr-pages' + (comicDouble ? ' cr-pages--double' : '');

    const showPages = comicDouble
        ? [comicIndex, comicIndex + 1].filter(i => i < comicPages.length)
        : [comicIndex];

    showPages.forEach(i => {
        const page = comicPages[i];
        const url = _comicTokenUrl(page?.path || page?.url || '');
        const img = document.createElement('img');
        img.className = 'cr-page-img';
        img.alt = `Page ${i + 1}`;
        img.loading = 'eager';
        img.src = url;
        img.style.cssText = _comicImgStyle();
        pagesEl.appendChild(img);
    });

    // Update controls
    _comicUpdateNav();
    _comicScrollToTop();
    _comicPreload();
    _comicUpdateThumbHighlight();
}

function _comicImgStyle() {
    if (comicFit === 'width') return 'width:100%; height:auto; display:block;';
    if (comicFit === 'height') return `width:auto; height:calc(100vh - 120px); display:block;`;
    // 'zoom' mode — use comicZoom %
    return `width:${comicZoom}%; height:auto; display:block;`;
}

function _comicUpdateNav() {
    const total = comicPages.length;
    const idx = comicIndex + 1;
    const indEl = document.getElementById('cr-page-indicator');
    if (indEl) indEl.textContent = `${idx} / ${total}`;
    const prevBtn = document.getElementById('cr-prev-btn');
    const nextBtn = document.getElementById('cr-next-btn');
    if (prevBtn) prevBtn.disabled = comicIndex === 0;
    if (nextBtn) nextBtn.disabled = comicIndex >= total - (comicDouble ? 2 : 1);
}

function _comicScrollToTop() {
    const stage = document.getElementById('cr-stage');
    if (stage) stage.scrollTo({ top: 0, behavior: 'instant' });
}

function _comicPreload() {
    const token = getCookie('auth_token');
    [-1, 1, 2].forEach(offset => {
        const i = comicIndex + offset;
        if (i < 0 || i >= comicPages.length) return;
        const url = _comicTokenUrl(comicPages[i]?.path || comicPages[i]?.url || '');
        if (url) { const img = new Image(); img.src = url; }
    });
}

// ── Navigation ───────────────────────────────────────────
function comicPrev() {
    if (comicIndex <= 0) return;
    comicIndex = Math.max(0, comicIndex - (comicDouble ? 2 : 1));
    _comicRender();
}

function comicNext() {
    if (!comicPages.length) return;
    const max = comicPages.length - (comicDouble ? 2 : 1);
    if (comicIndex >= max) return;
    comicIndex = Math.min(comicPages.length - 1, comicIndex + (comicDouble ? 2 : 1));
    _comicRender();
}

function comicGoTo(index) {
    comicIndex = Math.max(0, Math.min(index, comicPages.length - 1));
    _comicRender();
    // Close thumbs on mobile
    if (window.innerWidth < 600) comicThumbsOpen = false, _comicApplyThumbs();
}

// ── Fit / Zoom ───────────────────────────────────────────
function comicCycleFit() {
    const modes = ['width', 'height', 'zoom'];
    comicFit = modes[(modes.indexOf(comicFit) + 1) % modes.length];
    if (comicFit === 'zoom') comicZoom = 100;
    _comicUpdateFitBtn();
    _comicApplyImgStyles();
}

function _comicUpdateFitBtn() {
    const icons = { width: 'fa-arrows-alt-h', height: 'fa-arrows-alt-v', zoom: 'fa-search' };
    const titles = { width: 'Fit width', height: 'Fit height', zoom: 'Manual zoom' };
    const iconEl = document.getElementById('cr-fit-icon');
    const btn = document.getElementById('cr-fit-btn');
    if (iconEl) iconEl.className = `fas ${icons[comicFit] || 'fa-expand-arrows-alt'}`;
    if (btn) btn.title = titles[comicFit] || 'Fit';
    const zoomBar = document.getElementById('cr-zoom-bar');
    if (zoomBar) zoomBar.classList.toggle('cr-zoom-bar--active', comicFit === 'zoom');
}

function comicZoomIn() { comicSetZoom(Math.min(300, comicZoom + 10)); }
function comicZoomOut() { comicSetZoom(Math.max(50, comicZoom - 10)); }
function comicResetZoom() { comicSetZoom(100); }

function comicSetZoom(val) {
    comicZoom = Math.max(50, Math.min(300, parseInt(val)));
    comicFit = 'zoom';
    _comicUpdateFitBtn();
    _comicUpdateZoomUI();
    _comicApplyImgStyles();
}

function _comicUpdateZoomUI() {
    const slider = document.getElementById('cr-zoom-slider');
    const pct = document.getElementById('cr-zoom-pct');
    if (slider) slider.value = comicZoom;
    if (pct) pct.textContent = `${comicZoom}%`;
}

function _comicApplyImgStyles() {
    document.querySelectorAll('#cr-pages .cr-page-img').forEach(img => {
        img.style.cssText = _comicImgStyle();
    });
}

// ── Double page mode ─────────────────────────────────────
function comicToggleDouble() {
    comicDouble = !comicDouble;
    const btn = document.getElementById('cr-double-btn');
    if (btn) btn.classList.toggle('cr-btn--active', comicDouble);
    _comicRender();
}

// ── Thumbnails ───────────────────────────────────────────
function _comicBuildThumbs() {
    const scroll = document.getElementById('cr-thumbs-scroll');
    if (!scroll) return;
    scroll.innerHTML = comicPages.map((page, i) => {
        const url = _comicTokenUrl(page?.path || page?.url || '');
        return `<div class="cr-thumb ${i === comicIndex ? 'cr-thumb--active' : ''}"
                     data-idx="${i}" onclick="comicGoTo(${i})" title="Page ${i+1}">
            <img src="${escapeHtml(url)}" loading="lazy" alt="Page ${i+1}">
            <span>${i+1}</span>
        </div>`;
    }).join('');
}

function comicToggleThumbs() {
    comicThumbsOpen = !comicThumbsOpen;
    _comicApplyThumbs();
}

function _comicApplyThumbs() {
    const panel = document.getElementById('cr-thumbs-panel');
    const btn = document.getElementById('cr-thumbs-btn');
    if (panel) panel.classList.toggle('hidden', !comicThumbsOpen);
    if (btn) btn.classList.toggle('cr-btn--active', comicThumbsOpen);
}

function _comicUpdateThumbHighlight() {
    document.querySelectorAll('#cr-thumbs-scroll .cr-thumb').forEach(el => {
        const active = parseInt(el.dataset.idx) === comicIndex;
        el.classList.toggle('cr-thumb--active', active);
        if (active) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
}

// ── Fullscreen ───────────────────────────────────────────
function comicToggleFullscreen() {
    const overlay = document.getElementById('comic-overlay');
    if (!overlay) return;
    if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
    } else {
        overlay.requestFullscreen?.().catch(() => {
            // Fallback: toggle CSS fullscreen class
            overlay.classList.toggle('cr-css-fullscreen');
        });
    }
}

document.addEventListener('fullscreenchange', () => {
    const icon = document.getElementById('cr-fs-icon');
    if (!icon) return;
    if (document.fullscreenElement) {
        icon.className = 'fas fa-compress';
    } else {
        icon.className = 'fas fa-expand';
    }
});

// ── Touch / Swipe ────────────────────────────────────────
function _comicTouchStart(e) {
    if (e.touches.length === 1) {
        _comicTouchStartX = e.touches[0].clientX;
        _comicTouchStartY = e.touches[0].clientY;
    }
}

function _comicTouchEnd(e) {
    if (_comicTouchStartX === null) return;
    const dx = e.changedTouches[0].clientX - _comicTouchStartX;
    const dy = e.changedTouches[0].clientY - _comicTouchStartY;
    _comicTouchStartX = null;
    _comicTouchStartY = null;
    // Only horizontal swipes >50px that aren't primarily vertical
    if (Math.abs(dx) < 50 || Math.abs(dy) > Math.abs(dx) * 0.8) return;
    if (dx < 0) comicNext(); else comicPrev();
}

document.addEventListener('keydown', (e) => {
    // Comic overlay keyboard shortcuts (checked first)
    const comicOverlay = document.getElementById('comic-overlay');
    if (comicOverlay && !comicOverlay.classList.contains('hidden')) {
        if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA')) return;
        if (e.key === 'Escape') { closeComicOverlay(); return; }
        if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); comicPrev(); return; }
        if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); comicNext(); return; }
        if (e.key === '+' || e.key === '=') { e.preventDefault(); comicZoomIn(); return; }
        if (e.key === '-') { e.preventDefault(); comicZoomOut(); return; }
        if (e.key === '0') { e.preventDefault(); comicResetZoom(); return; }
        if (e.key === 'f' || e.key === 'F') { e.preventDefault(); comicToggleFullscreen(); return; }
        if (e.key === 'd' || e.key === 'D') { e.preventDefault(); comicToggleDouble(); return; }
        return; // Don't propagate to video shortcuts when comic is open
    }
    // Video modal keyboard shortcuts
    const modal = document.getElementById('viewer-modal');
    if (!modal || modal.classList.contains('hidden')) return;
    if (e.key === 'Escape') closeViewer();
    // Video keyboard shortcuts
    const video = activeVideoEl;
    if (!video) return;
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT')) return;
    if (e.key === ' ' || e.code === 'Space') { e.preventDefault(); video.paused ? video.play() : video.pause(); }
    if (e.key === 'ArrowLeft' && !e.altKey) { e.preventDefault(); video.currentTime = Math.max(0, video.currentTime - 10); }
    if (e.key === 'ArrowRight' && !e.altKey) { e.preventDefault(); video.currentTime = Math.min(video.duration || 0, video.currentTime + 10); }
    if (e.key === 'ArrowUp') { e.preventDefault(); video.volume = Math.min(1, video.volume + 0.1); }
    if (e.key === 'ArrowDown') { e.preventDefault(); video.volume = Math.max(0, video.volume - 0.1); }
    if (e.key === 'f' || e.key === 'F') { if (document.fullscreenElement) document.exitFullscreen(); else video.requestFullscreen?.(); }
    if (e.key === 'm' || e.key === 'M') { video.muted = !video.muted; }
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

    const getDelBtn = (path) => (canEditLibrary() && path) ? `<button class="delete-btn" style="position:absolute;top:5px;right:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1.2em;line-height:1;opacity:0.7;" title="Delete" data-delete-path="${escapeHtml(path)}">×</button>` : '';
    const getRenameBtn = (path, name) => (canEditLibrary() && path) ? `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;opacity:0.7;" title="Rename" data-rename-path="${escapeHtml(path)}" data-rename-name="${escapeHtml(name)}">✏️</button>` : '';

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

async function updateDashboardSession(sessionId, path, title, state, currentTime, duration, posterUrl) {
    if (!sessionId || !path) return;
    const headers = getAuthHeaders();
    if (!headers.Authorization && !headers['X-Auth-Token']) return;
    const now = Date.now();
    if (state === 'playing' && now - lastDashboardSessionUpdate < DASHBOARD_SESSION_UPDATE_INTERVAL_MS) return;
    lastDashboardSessionUpdate = now;
    const mediaType = (path.indexOf('/shows/') !== -1) ? 'episode' : (path.indexOf('/movies/') !== -1) ? 'movie' : 'video';
    const payload = {
        session_id: sessionId,
        path: path,
        title: title || 'Unknown',
        media_type: mediaType,
        current_time: Number(currentTime) || 0,
        duration: Number(duration) || 0,
        state: state || 'playing',
        username: (currentUser && currentUser.username) ? currentUser.username : 'Unknown'
    };
    if (posterUrl) payload.poster_url = posterUrl;
    try {
        const res = await fetch(`${API_BASE}/dashboard/session/update`, {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.status === 401) logout();
    } catch (e) {
        console.warn('[Dashboard] Session update failed:', e);
    }
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

                 const resumeRenameBtn = canEditLibrary() ? `<button class="rename-btn-card" style="position:absolute;top:5px;left:5px;z-index:20;background:rgba(0,0,0,0.6);border:none;color:#fff;cursor:pointer;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:1em;" title="Rename">✏️</button>` : '';

                 let progressHtml = '';
                 if (file.progress && file.progress.duration) {
                    const pct = (file.progress.current_time / file.progress.duration) * 100;
                    progressHtml = `<div class="card-progress"><div class="fill" style="width:${pct}%"></div></div>`;
                 }

                 div.innerHTML = `
                    ${resumeRenameBtn}
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
            const data = await res.json().catch(() => ({}));
            showToast(data.detail || 'Failed to toggle Wi-Fi', 'error');
            await loadWifiStatus();
        }
    } catch (e) {
        showToast(e.message || 'Wi-Fi toggle failed', 'error');
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
    initPWAInstallPrompt();
    initRenameModal();
    
    // Network status monitoring - show banner when offline
    function updateNetworkStatus() {
        const isOnline = navigator.onLine;
        let banner = document.getElementById('offline-banner');
        if (!isOnline) {
            if (!banner) {
                banner = document.createElement('div');
                banner.id = 'offline-banner';
                banner.innerHTML = '<i class="fas fa-wifi"></i> You are offline. Some features may be limited.';
                banner.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#ef4444;color:#fff;padding:8px;text-align:center;z-index:99999;font-size:14px;';
                document.body.appendChild(banner);
            }
            banner.style.display = 'block';
        } else {
            if (banner) banner.style.display = 'none';
        }
    }
    
    // Listen for network status changes
    window.addEventListener('online', updateNetworkStatus);
    window.addEventListener('offline', updateNetworkStatus);
    updateNetworkStatus(); // Check initial state

    // Ensure all sections except home are hidden on page load
    document.querySelectorAll('main > section').forEach(section => {
        if (section.id !== 'home') {
            section.classList.add('hidden');
            section.style.display = 'none';
        }
    });

    checkAuth(); // Check auth on load

    const setupHintEl = document.getElementById('setup-hint');
    const passwordInput = document.getElementById('password-input');
    if (setupHintEl && passwordInput) {
        fetch(`${API_BASE}/system/setup/status`)
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
                if (!data) return;
                if (data.admin_must_change_password && data.has_default_password) {
                    setupHintEl.textContent = 'First-time setup: check your terminal for the default password. Please change it after login.';
                    setupHintEl.style.display = 'block';
                    passwordInput.placeholder = 'Password (see terminal)';
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
    if (!canEditLibrary()) { showToast('Admin access required', 'warning'); return; }
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

let scanProgressInterval = null;

async function pollScanProgress() {
    const progEl = document.getElementById('scan-progress');
    const msgEl = document.getElementById('scan-progress-message');
    const barEl = document.getElementById('scan-progress-bar');
    try {
        const res = await fetch(`${API_BASE}/media/scan/status`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        if (msgEl) msgEl.textContent = data.message || `Scanning ${data.category || 'library'}… ${data.count || 0} files`;
        if (barEl) barEl.style.width = data.in_progress ? '100%' : '0%';
        if (!data.in_progress) {
            if (scanProgressInterval) {
                clearInterval(scanProgressInterval);
                scanProgressInterval = null;
            }
            if (progEl) progEl.classList.add('hidden');
            showToast('Library scan complete', 'success');
            const active = document.querySelector('main > section.active')?.id;
            if (active === 'shows') loadShowsLibrary();
            else if (active && ['movies', 'music', 'books', 'gallery'].includes(active)) loadMedia(active);
        }
    } catch (_) {}
}

async function rescanLibrary() {
    if (!confirm('Rescan all libraries? This may take a while.')) return;
    const progEl = document.getElementById('scan-progress');
    const msgEl = document.getElementById('scan-progress-message');
    const barEl = document.getElementById('scan-progress-bar');
    try {
        const res = await fetch(`${API_BASE}/media/rebuild`, {
            method: 'POST',
            headers: { 'Accept': 'application/json', ...getAuthHeaders() }
        });
        if (res.status === 401) {
            showToast('Session expired. Please log in again.', 'warning');
            logout();
            return;
        }
        if (res.status === 403) {
            showToast('Admin access required', 'warning');
            return;
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Scan failed');
        if (progEl) progEl.classList.remove('hidden');
        if (msgEl) msgEl.textContent = 'Starting scan…';
        if (barEl) barEl.style.width = '100%';
        if (scanProgressInterval) clearInterval(scanProgressInterval);
        scanProgressInterval = setInterval(pollScanProgress, 1500);
        pollScanProgress();
    } catch (e) {
        console.error('Scan error:', e);
        showToast(e.message || 'Scan failed', 'error');
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
        if (!res.ok) throw new Error('Stats unavailable');
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


async function unmountDrive(mountpoint) {
    if (!confirm(`Unmount ${mountpoint}?`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/system/unmount?target=${encodeURIComponent(mountpoint)}`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.status === 401) { logout(); return; }
        const result = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(result.detail || result.error || 'Unmount failed');
        }
        
        if (result.status === 'unmounted' || result.status === 'not_implemented_on_windows') {
            loadDrives();
        } else {
            alert('Error: ' + (result.message || JSON.stringify(result)));
        }
    } catch (e) {
        alert('Error: ' + e);
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
                openVideoViewer(nextEpisode.path, nextEpisode.name, 0, nextEpisode.poster || null);
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

// =====================================================
// NEW FEATURES v1.3.0
// =====================================================

// --- PiP & Playback Speed ---
function togglePiP() {
    const video = activeVideoEl;
    if (!video) return;
    if (document.pictureInPictureElement) {
        document.exitPictureInPicture().catch(() => {});
    } else if (document.pictureInPictureEnabled) {
        video.requestPictureInPicture().catch(e => showToast('PiP not supported in this browser', 'info'));
    } else {
        showToast('Picture-in-Picture is not supported in this browser', 'info');
    }
}

function setPlaybackSpeed(speed) {
    const video = activeVideoEl;
    if (video) video.playbackRate = parseFloat(speed);
}

// --- Home Rows: Continue Watching & Recently Added ---
async function loadHomeRows() {
    await Promise.all([loadContinueWatching(), loadRecentlyAdded()]);
}

async function loadContinueWatching() {
    const section = document.getElementById('continue-watching-section');
    const list = document.getElementById('continue-watching-list');
    if (!section || !list) return;
    try {
        const res = await fetch(`${API_BASE}/media/resume?limit=12`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const items = data.items || data || [];
        if (!items.length) { section.classList.add('hidden'); return; }
        section.classList.remove('hidden');
        list.innerHTML = items.map(item => renderHomeCard(item, 'continue')).join('');
    } catch (e) { console.warn('loadContinueWatching failed:', e); }
}

async function loadRecentlyAdded() {
    const section = document.getElementById('recently-added-section');
    const list = document.getElementById('recently-added-list');
    if (!section || !list) return;
    try {
        const res = await fetch(`${API_BASE}/media/recently_added?limit=20`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const items = data.items || [];
        if (!items.length) { section.classList.add('hidden'); return; }
        section.classList.remove('hidden');
        list.innerHTML = items.map(item => renderHomeCard(item, 'recent')).join('');
    } catch (e) { console.warn('loadRecentlyAdded failed:', e); }
}

function renderHomeCard(item, type) {
    const poster = item.poster || item.poster_url || '';
    const title = escapeHtml(item.title || item.name || 'Unknown');
    const path = escapeHtml(item.path || '');
    const pct = item.progress ? Math.round((item.progress.current_time / item.progress.duration) * 100) : 0;
    const progressBar = (type === 'continue' && pct > 0 && pct < 100) ?
        `<div class="home-card-progress"><div class="home-card-progress-fill" style="width:${pct}%"></div></div>` : '';
    const watched = item.watched ? '<div class="watched-badge"><i class="fas fa-check"></i></div>' : '';
    const yearLabel = item.year ? `<span class="home-card-year">${item.year}</span>` : '';
    return `<div class="home-card" onclick="openVideoViewer('${path}', '${title.replace(/'/g,"\\'")}', ${item.progress?.current_time || 0})">
        <div class="home-card-poster">
            ${poster ? `<img src="${escapeHtml(poster)}" loading="lazy" onerror="this.style.display='none'">` : '<div class="home-card-no-poster"><i class="fas fa-film"></i></div>'}
            <div class="home-card-play-icon"><i class="fas fa-play"></i></div>
            ${watched}${progressBar}
        </div>
        <div class="home-card-info">
            <div class="home-card-title">${title}</div>
            ${yearLabel}
        </div>
    </div>`;
}

// --- Disk Space Warning ---
async function checkDiskSpace() {
    try {
        const res = await fetch(`${API_BASE}/system/storage/info`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const disks = data.disks || [];
        for (const disk of disks) {
            const total = disk.total || 0;
            const used = disk.used || 0;
            const pct = total > 0 ? Math.round((used / total) * 100) : 0;
            if (pct >= 90) {
                showToast(`⚠️ Disk "${disk.mountpoint || '/'}" is ${pct}% full — consider freeing up space.`, 'warning', 8000);
            }
        }
    } catch (e) { console.warn('checkDiskSpace failed:', e); }
}

// --- Auto-scan on Startup ---
async function checkAutoScan() {
    try {
        const lastScan = parseInt(localStorage.getItem('nomadpi_last_scan_ts') || '0');
        const now = Date.now();
        const hoursElapsed = (now - lastScan) / 3600000;
        if (hoursElapsed < 24) return;
        console.log('[AutoScan] Library stale (>24h), triggering background scan...');
        await fetch(`${API_BASE}/media/scan`, { method: 'POST', headers: getAuthHeaders() });
        localStorage.setItem('nomadpi_last_scan_ts', String(now));
        showToast('Library scan started automatically (>24h since last scan)', 'info', 4000);
    } catch (e) { console.warn('checkAutoScan failed:', e); }
}

// --- Watchlist ---
async function loadWatchlist() {
    const list = document.getElementById('watchlist-list');
    if (!list) return;
    list.innerHTML = '<div class="loading">Loading watchlist...</div>';
    try {
        const res = await fetch(`${API_BASE}/media/watchlist`, { headers: getAuthHeaders() });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        const items = data.items || [];
        if (!items.length) {
            list.innerHTML = '<div class="empty-state"><i class="fas fa-heart" style="font-size:3rem; opacity:0.2; margin-bottom:1rem;"></i><p>Your watchlist is empty.<br>Press the ♥ on any movie or show to add it.</p></div>';
            return;
        }
        list.innerHTML = `<div class="media-grid">${items.map(item => renderWatchlistCard(item)).join('')}</div>`;
    } catch (e) {
        list.innerHTML = `<div class="empty-state"><p>Error loading watchlist: ${e.message}</p></div>`;
    }
}

function renderWatchlistCard(item) {
    const title = escapeHtml(item.title || 'Unknown');
    const poster = item.poster ? escapeHtml(item.poster) : '';
    const path = escapeHtml(item.path || '');
    return `<div class="media-item" onclick="openVideoViewer('${path}', '${title.replace(/'/g,"\\'")}', 0)">
        <div class="poster-shell">
            ${poster ? `<img class="poster-img" src="${poster}" loading="lazy" onerror="this.style.display='none'">` : ''}
            <div class="poster-play"><i class="fas fa-play"></i></div>
            <button class="watchlist-btn active" title="Remove from watchlist" onclick="event.stopPropagation(); toggleWatchlist('${path}', '${escapeHtml(item.category || '')}', '${title.replace(/'/g,"\\'")}', '${poster}')">
                <i class="fas fa-heart"></i>
            </button>
        </div>
        <div class="card-title">${title}</div>
        <div class="card-subtitle">${escapeHtml(item.category || '')}</div>
    </div>`;
}

async function toggleWatchlist(path, category, title, poster) {
    try {
        const checkRes = await fetch(`${API_BASE}/media/watchlist`, { headers: getAuthHeaders() });
        const checkData = await checkRes.json();
        const existing = (checkData.items || []).find(i => i.path === path);
        if (existing) {
            await fetch(`${API_BASE}/media/watchlist`, {
                method: 'DELETE',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ path })
            });
            showToast('Removed from watchlist', 'info');
            updateWatchlistBtn(path, false);
        } else {
            await fetch(`${API_BASE}/media/watchlist`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, category, title, poster })
            });
            showToast('Added to watchlist ♥', 'success');
            updateWatchlistBtn(path, true);
        }
        if (document.getElementById('watchlist')?.classList.contains('active-section')) loadWatchlist();
    } catch (e) { showToast('Failed to update watchlist', 'error'); }
}

function updateWatchlistBtn(path, active) {
    document.querySelectorAll(`[data-watchlist-path="${CSS.escape(path)}"]`).forEach(btn => {
        btn.classList.toggle('active', active);
    });
}

// --- Mark as Watched ---
async function markAsWatched(path, watched) {
    try {
        const res = await fetch(`${API_BASE}/media/mark_watched`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, watched: watched ? 1 : 0 })
        });
        if (!res.ok) throw new Error('Failed');
        showToast(watched ? 'Marked as watched ✓' : 'Marked as unwatched', 'success');
        // Update any visible cards
        document.querySelectorAll(`[data-watched-path]`).forEach(el => {
            if (el.dataset.watchedPath === path) el.classList.toggle('is-watched', !!watched);
        });
    } catch (e) { showToast('Failed to update watched status', 'error'); }
}

// --- View Mode Toggle ---
const viewModes = { movies: 'grid', shows: 'grid' };

function setViewMode(category, mode) {
    viewModes[category] = mode;
    const gridBtn = document.getElementById(`${category}-view-grid`);
    const listBtn = document.getElementById(`${category}-view-list`);
    if (gridBtn) gridBtn.classList.toggle('active', mode === 'grid');
    if (listBtn) listBtn.classList.toggle('active', mode === 'list');
    const container = document.getElementById(`${category}-list`);
    if (container) {
        container.classList.toggle('list-view', mode === 'list');
        container.classList.toggle('grid-view', mode === 'grid');
    }
}

// --- Global Search ---
function openGlobalSearch() {
    const overlay = document.getElementById('global-search-overlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    setTimeout(() => {
        const input = document.getElementById('global-search-input');
        if (input) input.focus();
    }, 100);
}

function closeGlobalSearch() {
    const overlay = document.getElementById('global-search-overlay');
    if (overlay) overlay.classList.add('hidden');
}

let globalSearchTimeout = null;
function onGlobalSearchInput(value) {
    clearTimeout(globalSearchTimeout);
    if (!value || value.length < 2) {
        const res = document.getElementById('global-search-results');
        if (res) res.innerHTML = '';
        return;
    }
    globalSearchTimeout = setTimeout(() => performGlobalSearch(value), 350);
}

async function performGlobalSearch(q) {
    const resultsEl = document.getElementById('global-search-results');
    if (!resultsEl) return;
    resultsEl.innerHTML = '<div class="search-loading"><i class="fas fa-spinner fa-spin"></i> Searching...</div>';
    try {
        const res = await fetch(`${API_BASE}/media/search?q=${encodeURIComponent(q)}&limit=40`, { headers: getAuthHeaders() });
        if (res.status === 401) { logout(); return; }
        const data = await res.json();
        const items = data.results || data.items || data || [];
        if (!items.length) {
            resultsEl.innerHTML = `<div class="search-empty">No results for "<strong>${escapeHtml(q)}</strong>"</div>`;
            return;
        }
        resultsEl.innerHTML = items.map(item => {
            const title = escapeHtml(item.title || item.name || '');
            const path = escapeHtml(item.path || '');
            const cat = escapeHtml(item.category || item.type || '');
            const poster = item.poster ? escapeHtml(item.poster) : '';
            return `<div class="search-result-item" onclick="closeGlobalSearch(); openVideoViewer('${path}', '${title.replace(/'/g,"\\'")}', 0)">
                ${poster ? `<img class="search-result-poster" src="${poster}" onerror="this.style.display='none'">` : '<div class="search-result-poster search-result-no-poster"><i class="fas fa-film"></i></div>'}
                <div class="search-result-info">
                    <div class="search-result-title">${title}</div>
                    <div class="search-result-cat">${cat}</div>
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        resultsEl.innerHTML = `<div class="search-empty">Error: ${e.message}</div>`;
    }
}

document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); openGlobalSearch(); }
    if (e.key === 'Escape') {
        const overlay = document.getElementById('global-search-overlay');
        if (overlay && !overlay.classList.contains('hidden')) closeGlobalSearch();
    }
});

// --- Backup Download ---
function downloadBackup() {
    showToast('Preparing backup...', 'info');
    const a = document.createElement('a');
    a.href = `${API_BASE}/system/backup?token=${getCookie('auth_token') || ''}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// --- OpenSubtitles Key ---
async function saveOpenSubtitlesKey() {
    const input = document.getElementById('opensubtitles-key');
    if (!input) return;
    const key = input.value.trim();
    try {
        const res = await fetch(`${API_BASE}/system/settings`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'opensubtitles_key', value: key })
        });
        if (!res.ok) throw new Error('Failed');
        showToast('OpenSubtitles API key saved', 'success');
    } catch (e) { showToast('Failed to save API key', 'error'); }
}

// --- OMDb API Key ---
async function loadOmdbKey() {
    try {
        const res = await fetch(`${API_BASE}/system/settings/omdb`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const input = document.getElementById('omdb-api-key');
        if (input && data.key) input.placeholder = data.key.slice(0, 4) + '****';
    } catch (e) { /* ignore */ }
}

async function saveOmdbKey() {
    const input = document.getElementById('omdb-api-key');
    if (!input) return;
    const key = input.value.trim();
    if (!key) { showToast('Please enter an OMDb API key', 'warning'); return; }
    try {
        const res = await fetch(`${API_BASE}/system/settings/omdb`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ key }),
        });
        if (!res.ok) throw new Error('Failed');
        showToast('OMDb API key saved', 'success');
        input.value = '';
        input.placeholder = key.slice(0, 4) + '****';
    } catch (e) { showToast('Failed to save OMDb key', 'error'); }
}

// --- Metadata Editor ---
let _metaEditorPath = null;

function openMetaEditor(path, title, year, poster, plot) {
    _metaEditorPath = path;
    const modal = document.getElementById('meta-editor-modal');
    if (!modal) return;
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
    const pathEl = document.getElementById('meta-editor-path');
    if (pathEl) pathEl.value = path;
    setVal('meta-editor-title', title);
    setVal('meta-editor-year', year);
    setVal('meta-editor-poster', poster);
    setVal('meta-editor-plot', plot);
    modal.classList.remove('hidden');
}

function closeMetaEditor() {
    const modal = document.getElementById('meta-editor-modal');
    if (modal) modal.classList.add('hidden');
    _metaEditorPath = null;
}

async function saveMetaEditor() {
    if (!_metaEditorPath) return;
    const getVal = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    const payload = {
        path: _metaEditorPath,
        title: getVal('meta-editor-title'),
        year: getVal('meta-editor-year'),
        poster: getVal('meta-editor-poster'),
        plot: getVal('meta-editor-plot')
    };
    try {
        const res = await fetch(`${API_BASE}/media/meta/override`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('Save failed');
        showToast('Metadata saved', 'success');
        closeMetaEditor();
        // Invalidate caches
        moviesLibraryCache = null;
        showsLibraryCache = null;
    } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

// --- Subtitle Search & Download ---
let _subtitleVideoPath = null;

function openSubtitleSearch(path, title) {
    _subtitleVideoPath = path;
    const modal = document.getElementById('subtitle-modal');
    if (!modal) {
        // Build modal on-the-fly if not in HTML
        _buildSubtitleModal();
    }
    const titleEl = document.getElementById('subtitle-search-title');
    if (titleEl) titleEl.value = title || '';
    const resultsEl = document.getElementById('subtitle-results');
    if (resultsEl) resultsEl.innerHTML = '';
    document.getElementById('subtitle-modal')?.classList.remove('hidden');
}

function _buildSubtitleModal() {
    const modal = document.createElement('div');
    modal.id = 'subtitle-modal';
    modal.className = 'modal-overlay hidden';
    modal.innerHTML = `
        <div class="modal-box" style="max-width:560px">
            <div class="modal-header">
                <h3><i class="fas fa-closed-captioning"></i> Subtitle Search</h3>
                <button class="modal-close-btn" onclick="closeSubtitleModal()"><i class="fas fa-times"></i></button>
            </div>
            <div class="modal-body">
                <div style="display:flex; gap:8px; margin-bottom:12px;">
                    <input id="subtitle-search-title" class="settings-input" placeholder="Movie/show title..." style="flex:1">
                    <button class="btn btn-primary" onclick="searchSubtitles()"><i class="fas fa-search"></i></button>
                </div>
                <div id="subtitle-results" style="max-height:320px; overflow-y:auto;"></div>
            </div>
        </div>`;
    document.body.appendChild(modal);
}

function closeSubtitleModal() {
    document.getElementById('subtitle-modal')?.classList.add('hidden');
}

async function searchSubtitles() {
    const titleInput = document.getElementById('subtitle-search-title');
    const query = titleInput?.value?.trim();
    if (!query) return;
    const resultsEl = document.getElementById('subtitle-results');
    if (resultsEl) resultsEl.innerHTML = '<div class="loading"><i class="fas fa-spinner fa-spin"></i> Searching OpenSubtitles...</div>';
    try {
        const res = await fetch(`${API_BASE}/media/subtitles/search?query=${encodeURIComponent(query)}`, { headers: getAuthHeaders() });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Search failed');
        }
        const data = await res.json();
        const subs = data.subtitles || data.data || [];
        if (!subs.length) {
            if (resultsEl) resultsEl.innerHTML = '<div class="search-empty">No subtitles found</div>';
            return;
        }
        if (resultsEl) {
            resultsEl.innerHTML = subs.slice(0, 30).map(s => {
                const attr = s.attributes || s;
                const lang = attr.language || '?';
                const title = escapeHtml(attr.feature_details?.movie_name || attr.release || 'Unknown');
                const fileId = attr.files?.[0]?.file_id || s.file_id || '';
                const dlCount = attr.download_count || 0;
                return `<div class="subtitle-result-item" onclick="downloadSubtitle(${fileId}, '${lang}')">
                    <div>
                        <span class="sub-lang-badge">${lang.toUpperCase()}</span>
                        <span>${title}</span>
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-muted)">${dlCount} downloads</div>
                </div>`;
            }).join('');
        }
    } catch (e) {
        if (resultsEl) resultsEl.innerHTML = `<div class="search-empty">Error: ${escapeHtml(e.message)}</div>`;
    }
}

async function downloadSubtitle(fileId, lang) {
    if (!fileId || !_subtitleVideoPath) { showToast('Missing subtitle info', 'error'); return; }
    showToast('Downloading subtitle...', 'info');
    try {
        const res = await fetch(`${API_BASE}/media/subtitles/download`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id: fileId, video_path: _subtitleVideoPath, language: lang })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Download failed');
        }
        const data = await res.json();
        showToast(`Subtitle saved: ${data.path || 'success'}`, 'success');
        closeSubtitleModal();
        // Reload subtitles for active video
        if (activeVideoEl) loadSubtitlesForVideo(activeVideoEl, _subtitleVideoPath);
    } catch (e) { showToast(`Subtitle error: ${e.message}`, 'error'); }
}

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

document.addEventListener('keydown', (e) => {
    // Skip if user is typing in an input/textarea
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;

    const playerOverlay = document.getElementById('player-overlay');
    const videoEl = document.getElementById('main-video');
    const isPlayerOpen = playerOverlay && playerOverlay.style.display !== 'none';

    // Player shortcuts (when video player is open)
    if (isPlayerOpen && videoEl) {
        switch (e.key) {
            case ' ':
            case 'k':
                e.preventDefault();
                videoEl.paused ? videoEl.play() : videoEl.pause();
                return;
            case 'f':
                e.preventDefault();
                if (document.fullscreenElement) document.exitFullscreen();
                else playerOverlay.requestFullscreen?.();
                return;
            case 'Escape':
                e.preventDefault();
                const closeBtn = playerOverlay.querySelector('.close-player, [onclick*="closePlayer"]');
                if (closeBtn) closeBtn.click();
                return;
            case 'm':
                e.preventDefault();
                videoEl.muted = !videoEl.muted;
                return;
            case 'ArrowLeft':
                e.preventDefault();
                videoEl.currentTime = Math.max(0, videoEl.currentTime - (e.shiftKey ? 30 : 10));
                return;
            case 'ArrowRight':
                e.preventDefault();
                videoEl.currentTime = Math.min(videoEl.duration || Infinity, videoEl.currentTime + (e.shiftKey ? 30 : 10));
                return;
            case 'ArrowUp':
                e.preventDefault();
                videoEl.volume = Math.min(1, videoEl.volume + 0.1);
                return;
            case 'ArrowDown':
                e.preventDefault();
                videoEl.volume = Math.max(0, videoEl.volume - 0.1);
                return;
            case ',':
                if (videoEl.paused) { videoEl.currentTime -= 1/30; }
                return;
            case '.':
                if (videoEl.paused) { videoEl.currentTime += 1/30; }
                return;
        }
        return;
    }

    // Global navigation shortcuts
    if (e.key === '/' || (e.key === 'k' && (e.ctrlKey || e.metaKey))) {
        e.preventDefault();
        openGlobalSearch();
        return;
    }

    // Navigation: 1-9 for sections
    const sectionMap = { '1': 'home', '2': 'movies', '3': 'shows', '4': 'music', '5': 'books', '6': 'gallery', '7': 'files', '8': 'debrid', '9': 'admin' };
    if (sectionMap[e.key] && !e.ctrlKey && !e.metaKey && !e.altKey) {
        showSection(sectionMap[e.key]);
        return;
    }

    // ? to show shortcuts help
    if (e.key === '?' && !e.ctrlKey) {
        showKeyboardShortcutsHelp();
    }
});

function showKeyboardShortcutsHelp() {
    const existing = document.getElementById('shortcuts-modal');
    if (existing) { existing.remove(); return; }

    const modal = document.createElement('div');
    modal.id = 'shortcuts-modal';
    modal.style.cssText = 'display:flex;position:fixed;inset:0;z-index:9999;align-items:center;justify-content:center;background:rgba(0,0,0,.7)';
    modal.innerHTML = `
        <div class="glass-card" style="padding:2rem;max-width:500px;width:90%;max-height:80vh;overflow-y:auto">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
                <h3><i class="fas fa-keyboard"></i> Keyboard Shortcuts</h3>
                <button onclick="this.closest('#shortcuts-modal').remove()" class="secondary small"><i class="fas fa-times"></i></button>
            </div>
            <div style="font-size:.9rem">
                <h4 style="color:var(--accent);margin:.75rem 0 .5rem">Navigation</h4>
                <div style="display:grid;grid-template-columns:80px 1fr;gap:.25rem .75rem">
                    <kbd>/</kbd><span>Search</span>
                    <kbd>1-9</kbd><span>Switch sections</span>
                    <kbd>?</kbd><span>Show this help</span>
                </div>
                <h4 style="color:var(--accent);margin:.75rem 0 .5rem">Video Player</h4>
                <div style="display:grid;grid-template-columns:80px 1fr;gap:.25rem .75rem">
                    <kbd>Space/K</kbd><span>Play / Pause</span>
                    <kbd>F</kbd><span>Fullscreen</span>
                    <kbd>M</kbd><span>Mute</span>
                    <kbd>Esc</kbd><span>Close player</span>
                    <kbd>&larr; / &rarr;</kbd><span>Seek &plusmn;10s (Shift: &plusmn;30s)</span>
                    <kbd>&uarr; / &darr;</kbd><span>Volume up / down</span>
                    <kbd>, / .</kbd><span>Frame step (paused)</span>
                </div>
            </div>
        </div>
    `;
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
}

// ============================================================================
// Real-Debrid Integration
// ============================================================================

let _debridDownloadInterval = null;
let _debridSelectedImdb = null;
let _debridSelectedTitle = null;
let _debridSelectedYear = null;

function debridShowType() {
    const t = document.getElementById('debrid-type');
    const se = document.getElementById('debrid-season-ep');
    if (t && se) se.style.display = t.value === 'series' ? 'flex' : 'none';
}

let _debridProvider = 'rd';

async function initDebrid() {
    const typeSelect = document.getElementById('debrid-type');
    if (typeSelect) typeSelect.addEventListener('change', debridShowType);

    // Load saved provider preference
    try {
        const provRes = await fetch(`${API_BASE}/debrid/settings/provider`, { headers: getAuthHeaders() });
        if (provRes.ok) {
            const provData = await provRes.json();
            _debridProvider = provData.provider || 'rd';
        }
    } catch (e) { /* default rd */ }

    _updateProviderTabs();
    await _checkDebridKey();
    refreshDebridDownloads();
}

function _updateProviderTabs() {
    const rdTab = document.getElementById('debrid-tab-rd');
    const adTab = document.getElementById('debrid-tab-ad');
    if (rdTab) { rdTab.className = _debridProvider === 'rd' ? 'small primary' : 'small secondary'; }
    if (adTab) { adTab.className = _debridProvider === 'ad' ? 'small primary' : 'small secondary'; }
}

async function debridSwitchProvider(provider) {
    _debridProvider = provider;
    _updateProviderTabs();
    try {
        await fetch(`${API_BASE}/debrid/settings/provider?provider=${provider}`, {
            method: 'POST', headers: getAuthHeaders(),
        });
    } catch (e) { /* ignore */ }
    await _checkDebridKey();
}

async function _checkDebridKey() {
    const setupRd = document.getElementById('debrid-setup');
    const setupAd = document.getElementById('debrid-setup-ad');
    const main = document.getElementById('debrid-main');
    const accountInfo = document.getElementById('rd-account-info');

    // Hide both setups first
    if (setupRd) setupRd.style.display = 'none';
    if (setupAd) setupAd.style.display = 'none';

    const endpoint = _debridProvider === 'ad' ? 'settings/ad-key' : 'settings/key';
    try {
        const res = await fetch(`${API_BASE}/debrid/${endpoint}`, { headers: getAuthHeaders() });
        if (!res.ok) { _showDebridSetup(); return; }
        const data = await res.json();

        if (data.configured && (data.user || data.valid !== false)) {
            if (main) main.style.display = 'block';
            if (accountInfo) {
                accountInfo.style.display = 'block';
                const usernameEl = document.getElementById('rd-username');
                if (usernameEl) usernameEl.textContent = (data.user?.username || 'Connected');
                const badge = document.getElementById('rd-premium-badge');
                if (badge) badge.style.display = (data.user?.premium) ? '' : 'none';
            }
        } else {
            _showDebridSetup();
        }
    } catch (e) {
        _showDebridSetup();
    }
}

function _showDebridSetup() {
    const setupRd = document.getElementById('debrid-setup');
    const setupAd = document.getElementById('debrid-setup-ad');
    const main = document.getElementById('debrid-main');
    if (setupRd) setupRd.style.display = _debridProvider === 'rd' ? 'block' : 'none';
    if (setupAd) setupAd.style.display = _debridProvider === 'ad' ? 'block' : 'none';
    if (main) main.style.display = 'none';
}

async function saveRDKey() {
    const input = document.getElementById('rd-api-key-input');
    const key = input ? input.value.trim() : '';
    if (!key) { showToast('Please enter an API key', 'warning'); return; }

    try {
        const res = await fetch(`${API_BASE}/debrid/settings/key`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to save key');
        }
        showToast('Real-Debrid connected!', 'success');
        _debridProvider = 'rd';
        await debridSwitchProvider('rd');
    } catch (e) { showToast(e.message, 'error'); }
}

async function saveADKey() {
    const input = document.getElementById('ad-api-key-input');
    const key = input ? input.value.trim() : '';
    if (!key) { showToast('Please enter an AllDebrid API key', 'warning'); return; }

    try {
        const res = await fetch(`${API_BASE}/debrid/settings/ad-key`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to save key');
        }
        showToast('AllDebrid connected!', 'success');
        _debridProvider = 'ad';
        await debridSwitchProvider('ad');
    } catch (e) { showToast(e.message, 'error'); }
}

async function removeDebridKey() {
    const label = _debridProvider === 'ad' ? 'AllDebrid' : 'Real-Debrid';
    if (!confirm(`Remove ${label} API key?`)) return;
    const endpoint = _debridProvider === 'ad' ? 'settings/ad-key' : 'settings/key';
    try {
        await fetch(`${API_BASE}/debrid/${endpoint}`, { method: 'DELETE', headers: getAuthHeaders() });
        showToast(`${label} key removed`, 'info');
        await _checkDebridKey();
    } catch (e) { showToast(e.message, 'error'); }
}

async function debridSearch() {
    const query = document.getElementById('debrid-search').value.trim();
    const mediaType = document.getElementById('debrid-type').value;
    if (!query) { showToast('Enter a search term', 'warning'); return; }

    const season = document.getElementById('debrid-season')?.value || '';
    const episode = document.getElementById('debrid-episode')?.value || '';

    // If the user entered an IMDB ID directly (e.g. tt0111161), skip title search
    if (/^tt\d{5,}$/i.test(query)) {
        debridSelectTitle(query, query, mediaType);
        return;
    }

    const resultsDiv = document.getElementById('debrid-results');
    const resultsList = document.getElementById('debrid-results-list');
    const torrentsDiv = document.getElementById('debrid-torrents');

    resultsList.innerHTML = '<p style="text-align:center;color:var(--text-secondary)"><i class="fas fa-spinner fa-spin"></i> Searching...</p>';
    resultsDiv.style.display = 'block';
    torrentsDiv.style.display = 'none';

    try {
        let params = `query=${encodeURIComponent(query)}&media_type=${mediaType}`;
        if (season) params += `&season=${season}`;
        if (episode) params += `&episode=${episode}`;

        const res = await fetch(`${API_BASE}/debrid/search?${params}`, { headers: getAuthHeaders() });
        if (!res.ok) throw new Error('Search failed');
        const data = await res.json();

        if (data.type === 'search_results') {
            if (!data.results || data.results.length === 0) {
                const msg = data.message || 'No results found. Try a different search or enter an IMDB ID (e.g. tt0111161).';
                resultsList.innerHTML = `<p style="text-align:center;color:var(--text-secondary)">${msg}</p>`;
                return;
            }
            resultsList.innerHTML = data.results.map(r => `
                <div class="glass-card" style="padding:1rem;margin-bottom:.5rem;cursor:pointer;display:flex;gap:1rem;align-items:center"
                     onclick="debridSelectTitle('${r.imdb_id}','${escapeHtml(r.title).replace(/'/g, "\\'") }','${mediaType}','${r.year || ''}')">
                    ${r.poster ? `<img src="${r.poster}" style="width:50px;height:75px;object-fit:cover;border-radius:4px" alt="">` : '<div style="width:50px;height:75px;background:var(--glass-bg);border-radius:4px;display:flex;align-items:center;justify-content:center"><i class="fas fa-film" style="color:var(--text-secondary)"></i></div>'}
                    <div>
                        <strong>${escapeHtml(r.title)}</strong> <span style="color:var(--text-secondary)">(${r.year || '?'})</span>
                        <div style="font-size:.8rem;color:var(--text-secondary)">${r.imdb_id} &middot; ${r.type || mediaType}</div>
                    </div>
                </div>
            `).join('');
        } else if (data.type === 'torrents') {
            resultsDiv.style.display = 'none';
            renderTorrentResults(data.results, data.imdb_id);
        }
    } catch (e) {
        resultsList.innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
    }
}

async function debridSelectTitle(imdbId, title, mediaType, year) {
    _debridSelectedImdb = imdbId;
    _debridSelectedTitle = title;
    _debridSelectedYear = year || '';

    const season = document.getElementById('debrid-season')?.value || '';
    const episode = document.getElementById('debrid-episode')?.value || '';

    const torrentsDiv = document.getElementById('debrid-torrents');
    const torrentsList = document.getElementById('debrid-torrents-list');

    torrentsList.innerHTML = '<p style="text-align:center;color:var(--text-secondary)"><i class="fas fa-spinner fa-spin"></i> Finding torrents...</p>';
    torrentsDiv.style.display = 'block';

    try {
        let params = `imdb_id=${imdbId}&media_type=${mediaType}`;
        if (season) params += `&season=${season}`;
        if (episode) params += `&episode=${episode}`;

        const res = await fetch(`${API_BASE}/debrid/search?${params}`, { headers: getAuthHeaders() });
        if (!res.ok) throw new Error('Torrent search failed');
        const data = await res.json();

        renderTorrentResults(data.results || [], imdbId);
    } catch (e) {
        torrentsList.innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
    }
}

async function renderTorrentResults(results, imdbId) {
    const torrentsDiv = document.getElementById('debrid-torrents');
    const torrentsList = document.getElementById('debrid-torrents-list');
    torrentsDiv.style.display = 'block';

    if (!results || results.length === 0) {
        torrentsList.innerHTML = '<p style="text-align:center;color:var(--text-secondary)">No torrents found for this title</p>';
        return;
    }

    // Apply quality filter
    const maxQuality = document.getElementById('debrid-quality')?.value;
    if (maxQuality) {
        const maxRes = parseInt(maxQuality);
        const qualityValue = { '480p': 480, '720p': 720, '1080p': 1080, '2160p': 2160, '4K': 2160 };
        results = results.filter(t => {
            const qVal = qualityValue[t.quality] || 0;
            return qVal === 0 || qVal <= maxRes;
        });
    }

    if (results.length === 0) {
        torrentsList.innerHTML = '<p style="text-align:center;color:var(--text-secondary)">No torrents match your quality filter</p>';
        return;
    }

    const qualityColors = { '2160p': '#e6c619', '4K': '#e6c619', '1080p': '#4CAF50', '720p': '#2196F3', '480p': '#9E9E9E' };

    // Check which torrents are instantly available (cached) on the active debrid provider
    let cached = {};
    try {
        const hashes = results.map(t => t.info_hash).filter(Boolean);
        if (hashes.length) {
            const res = await fetch(`${API_BASE}/debrid/instant`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ hashes }),
            });
            if (res.ok) {
                const data = await res.json();
                cached = data.cached || {};
            }
        }
    } catch (e) { console.warn('Instant availability check failed:', e); }

    torrentsList.innerHTML = results.map((t, i) => {
        const qColor = qualityColors[t.quality] || 'var(--text-secondary)';
        const isCached = cached[t.info_hash] || cached[t.info_hash?.toLowerCase()];
        const cachedBadge = isCached
            ? '<span style="background:#4CAF50;color:#fff;font-size:.7rem;padding:2px 6px;border-radius:4px;font-weight:700;margin-left:.5rem">RD CACHED</span>'
            : '';
        const escapedName = escapeHtml(t.name).replace(/'/g, "\\'");
        return `
            <div class="glass-card" style="padding:1rem;margin-bottom:.5rem">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
                    <div style="flex:1;min-width:200px">
                        <div style="font-weight:600;margin-bottom:.25rem">${escapeHtml(t.name)}${cachedBadge}</div>
                        <div style="font-size:.85rem;color:var(--text-secondary)">
                            <span style="color:${qColor};font-weight:600">${t.quality}</span>
                            ${t.size ? ` &middot; ${t.size}` : ''}
                            ${t.source ? ` &middot; ${t.source}` : ''}
                            ${t.seeders != null ? ` &middot; <i class="fas fa-arrow-up" style="font-size:.7rem"></i> ${t.seeders}` : ''}
                        </div>
                    </div>
                    <div style="display:flex;gap:.5rem;flex-shrink:0">
                        <button onclick="debridAddMagnet('${t.info_hash}',${t.file_idx != null ? t.file_idx : 'null'},'${escapedName}')" class="primary small" title="${isCached ? 'Instantly available — stream or download' : 'Send to Real-Debrid'}">
                            <i class="fas ${isCached ? 'fa-play' : 'fa-magnet'}"></i> ${isCached ? 'Watch' : 'Add'}
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function debridAddMagnet(infoHash, fileIdx, name) {
    showToast('Adding to Real-Debrid...', 'info');
    debridShowProcessing(name, 'Adding magnet...');
    try {
        const body = { info_hash: infoHash };

        const res = await fetch(`${API_BASE}/debrid/magnet`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to add magnet');
        }
        const data = await res.json();

        if (data.torrent_status === 'downloaded' && data.links && data.links.length > 0) {
            debridShowProcessing(name, 'Cached! Getting stream link...');
            debridHandleLinks(data.links, data.filename || name);
        } else if (data.torrent_status === 'waiting_files_selection' && data.files && data.files.length > 0) {
            debridHideProcessing();
            showToast('Select files to download', 'info');
            debridShowFiles(data);
        } else if (data.torrent_status === 'error' || data.torrent_status === 'dead' || data.torrent_status === 'virus' || data.torrent_status === 'magnet_error') {
            debridHideProcessing();
            showToast(`Torrent failed: ${data.torrent_status}`, 'error');
        } else {
            // Any other status — start polling with visible progress
            debridShowProcessing(name, `${data.torrent_status || 'Processing'}...`);
            if (data.torrent_id) debridPollTorrent(data.torrent_id, data.filename || name);
        }
    } catch (e) {
        debridHideProcessing();
        showToast(e.message, 'error');
    }
}

function debridShowProcessing(name, statusText) {
    let card = document.getElementById('debrid-processing-card');
    if (!card) {
        card = document.createElement('div');
        card.id = 'debrid-processing-card';
        card.className = 'glass-card';
        card.style.cssText = 'padding:1rem;margin-bottom:1rem;border-left:3px solid var(--accent)';
        const torrentsDiv = document.getElementById('debrid-torrents');
        if (torrentsDiv) torrentsDiv.parentElement.insertBefore(card, torrentsDiv);
        else document.querySelector('#debrid-tab .glass-card')?.after(card);
    }
    card.innerHTML = `
        <div style="display:flex;align-items:center;gap:.75rem">
            <i class="fas fa-spinner fa-spin" style="color:var(--accent);font-size:1.2rem"></i>
            <div style="flex:1">
                <div style="font-weight:600;font-size:.9rem">${escapeHtml(name || 'Processing...')}</div>
                <div id="debrid-processing-status" style="font-size:.85rem;color:var(--text-secondary)">${statusText || 'Working...'}</div>
                <div style="background:var(--glass-bg);border-radius:4px;height:6px;overflow:hidden;margin-top:.5rem">
                    <div id="debrid-processing-bar" style="background:var(--accent);height:100%;width:0%;transition:width .5s"></div>
                </div>
            </div>
        </div>
    `;
    card.style.display = 'block';
}

function debridUpdateProcessing(statusText, progress) {
    const statusEl = document.getElementById('debrid-processing-status');
    const barEl = document.getElementById('debrid-processing-bar');
    if (statusEl) statusEl.textContent = statusText;
    if (barEl) barEl.style.width = `${progress || 0}%`;
}

function debridHideProcessing() {
    const card = document.getElementById('debrid-processing-card');
    if (card) card.style.display = 'none';
}

async function debridHandleLinks(links, filename) {
    if (!links || links.length === 0) {
        debridHideProcessing();
        showToast('No download links available', 'warning');
        return;
    }

    // Build metadata query params for clean filename generation
    const mediaType = document.getElementById('debrid-type')?.value || 'movie';
    const season = document.getElementById('debrid-season')?.value || '';
    const episode = document.getElementById('debrid-episode')?.value || '';
    let metaParams = '';
    if (_debridSelectedTitle) metaParams += `&title=${encodeURIComponent(_debridSelectedTitle)}`;
    if (_debridSelectedYear) metaParams += `&year=${encodeURIComponent(_debridSelectedYear)}`;
    metaParams += `&media_type=${mediaType}`;
    if (season) metaParams += `&season=${season}`;
    if (episode) metaParams += `&episode=${episode}`;

    let handled = false;
    for (const link of links) {
        try {
            debridUpdateProcessing('Unrestricting link...', 50);
            const res = await fetch(`${API_BASE}/debrid/unrestrict?link=${encodeURIComponent(link)}${metaParams}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                console.warn('Unrestrict failed:', err.detail || res.status);
                continue;
            }
            const data = await res.json();

            if (data.download && data.filename) {
                debridHideProcessing();
                const action = await debridActionDialog(data.filename, data.download, data.filesize);
                if (action === 'stream') {
                    debridStreamFile(data.download, data.filename);
                } else if (action === 'download') {
                    debridDownloadToPi(data.download, data.filename);
                }
                handled = true;
            }
        } catch (e) {
            console.error('Unrestrict failed:', e);
        }
    }

    if (!handled) {
        debridHideProcessing();
        showToast('Could not get download links — try again or choose a different torrent', 'error');
    }
}

function debridActionDialog(filename, downloadUrl, filesize) {
    return new Promise((resolve) => {
        const sizeStr = filesize ? `(${(filesize / 1073741824).toFixed(2)} GB)` : '';
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.style.cssText = 'display:flex;position:fixed;inset:0;z-index:9999;align-items:center;justify-content:center;background:rgba(0,0,0,.7)';
        modal.innerHTML = `
            <div class="glass-card" style="padding:2rem;max-width:500px;width:90%">
                <h3 style="margin-bottom:1rem"><i class="fas fa-check-circle" style="color:var(--accent)"></i> Ready!</h3>
                <p style="word-break:break-word;margin-bottom:.5rem"><strong>${escapeHtml(filename)}</strong></p>
                <p style="color:var(--text-secondary);margin-bottom:1.5rem;font-size:.9rem">${sizeStr}</p>
                <div style="display:flex;gap:.75rem;flex-wrap:wrap">
                    <button class="primary" onclick="this.closest('.modal-overlay')._resolve('stream')">
                        <i class="fas fa-play"></i> Stream Now
                    </button>
                    <button class="secondary" onclick="this.closest('.modal-overlay')._resolve('download')">
                        <i class="fas fa-download"></i> Download to Pi
                    </button>
                    <button class="danger" onclick="this.closest('.modal-overlay')._resolve('cancel')">
                        Cancel
                    </button>
                </div>
            </div>
        `;
        modal._resolve = (val) => { modal.remove(); resolve(val); };
        modal.addEventListener('click', (e) => { if (e.target === modal) { modal.remove(); resolve('cancel'); } });
        document.body.appendChild(modal);
    });
}

function debridStreamFile(url, filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const videoExts = ['mp4', 'mkv', 'avi', 'mov', 'webm', 'm4v', 'ts'];

    if (!videoExts.includes(ext)) {
        window.open(url, '_blank');
        return;
    }

    const modal = document.getElementById('viewer-modal');
    const body = document.getElementById('viewer-body');
    const heading = document.getElementById('viewer-title');

    if (!modal || !body) {
        window.open(url, '_blank');
        return;
    }

    const safeTitle = escapeHtml(filename);

    if (heading) {
        heading.innerHTML = `
            <div class="viewer-title-row">
                <span class="viewer-title-text">${safeTitle}</span>
                <div class="external-player-btns">
                    <button class="player-action-btn" id="pip-btn" title="Picture-in-Picture" onclick="togglePiP()">
                        <span>⧉</span><span class="btn-text">PiP</span>
                    </button>
                    <select class="player-action-btn speed-select" id="speed-select" title="Playback speed" onchange="setPlaybackSpeed(this.value)">
                        <option value="0.5">0.5×</option>
                        <option value="0.75">0.75×</option>
                        <option value="1" selected>1×</option>
                        <option value="1.25">1.25×</option>
                        <option value="1.5">1.5×</option>
                        <option value="2">2×</option>
                    </select>
                    <a href="${url}" download="${escapeHtml(filename)}" class="player-action-btn" title="Download file">
                        <span>💾</span><span class="btn-text">Save</span>
                    </a>
                    <button class="player-action-btn" title="Copy link" onclick="navigator.clipboard.writeText('${url}');showToast('Link copied!','success')">
                        <span>📋</span><span class="btn-text">Copy URL</span>
                    </button>
                </div>
            </div>
        `;
    }

    body.innerHTML = '';

    const video = document.createElement('video');
    video.className = 'video-frame';
    video.controls = true;
    video.preload = 'auto';
    video.src = url;
    video.style.width = '100%';
    video.style.maxHeight = '80vh';

    video.addEventListener('error', () => {
        body.innerHTML = `
            <div style="text-align:center;padding:2rem">
                <p style="margin-bottom:1rem;color:var(--text-secondary)">
                    <i class="fas fa-exclamation-triangle" style="color:var(--warning,#ff9800)"></i>
                    Browser can't play this format directly (${ext.toUpperCase()})
                </p>
                <div style="display:flex;gap:.75rem;justify-content:center;flex-wrap:wrap">
                    <a href="${url}" target="_blank" class="primary" style="display:inline-flex;align-items:center;gap:.5rem;padding:.5rem 1rem;border-radius:8px;text-decoration:none">
                        <i class="fas fa-external-link-alt"></i> Open in Browser
                    </a>
                    <button class="secondary" onclick="navigator.clipboard.writeText('${url}');showToast('Link copied — paste in VLC or another player','success')" style="display:inline-flex;align-items:center;gap:.5rem;padding:.5rem 1rem;border-radius:8px">
                        <i class="fas fa-copy"></i> Copy Link for VLC
                    </button>
                </div>
            </div>
        `;
    });

    body.appendChild(video);
    modal.classList.remove('hidden');
    video.play().catch(() => {});
    showToast('Streaming from Real-Debrid', 'success');
}

async function debridDownloadToPi(url, filename) {
    const isShow = document.getElementById('debrid-type')?.value === 'series';
    try {
        const res = await fetch(`${API_BASE}/debrid/download`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ download_url: url, filename, category: 'auto', is_show: isShow }),
        });
        if (!res.ok) throw new Error('Download request failed');
        showToast(`Downloading ${filename} to Pi...`, 'success');
        refreshDebridDownloads();

        // Start polling
        if (!_debridDownloadInterval) {
            _debridDownloadInterval = setInterval(refreshDebridDownloads, 3000);
        }
    } catch (e) { showToast(e.message, 'error'); }
}

async function refreshDebridDownloads() {
    try {
        const res = await fetch(`${API_BASE}/debrid/downloads`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const list = document.getElementById('debrid-downloads-list');
        if (!list) return;

        const downloads = data.downloads || [];
        if (downloads.length === 0) {
            list.innerHTML = '<p style="color:var(--text-secondary);text-align:center">No active downloads</p>';
            if (_debridDownloadInterval) { clearInterval(_debridDownloadInterval); _debridDownloadInterval = null; }
            return;
        }

        const hasActive = downloads.some(d => d.status === 'downloading');
        if (!hasActive && _debridDownloadInterval) {
            clearInterval(_debridDownloadInterval);
            _debridDownloadInterval = null;
        }

        list.innerHTML = downloads.map(d => {
            const pct = d.progress || 0;
            const speed = d.speed ? `${(d.speed / 1048576).toFixed(1)} MB/s` : '';
            const total = d.size_total ? `${(d.size_total / 1073741824).toFixed(2)} GB` : '';

            let statusIcon = '';
            let statusColor = '';
            if (d.status === 'downloading') { statusIcon = 'fa-spinner fa-spin'; statusColor = 'var(--accent)'; }
            else if (d.status === 'completed') { statusIcon = 'fa-check-circle'; statusColor = 'var(--success, #4CAF50)'; }
            else if (d.status === 'failed') { statusIcon = 'fa-exclamation-circle'; statusColor = 'var(--danger, #f44336)'; }
            else if (d.status === 'cancelled') { statusIcon = 'fa-times-circle'; statusColor = 'var(--text-secondary)'; }

            return `
                <div class="glass-card" style="padding:.75rem;margin-bottom:.5rem">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.25rem">
                        <span style="font-weight:600;font-size:.9rem"><i class="fas ${statusIcon}" style="color:${statusColor}"></i> ${escapeHtml(d.filename)}</span>
                        ${d.status === 'downloading' ? `<button onclick="cancelDebridDownload('${d.id}')" class="danger small" title="Cancel"><i class="fas fa-times"></i></button>` : ''}
                    </div>
                    <div style="background:var(--glass-bg);border-radius:4px;height:6px;overflow:hidden;margin:.5rem 0">
                        <div style="background:var(--accent);height:100%;width:${pct}%;transition:width .3s"></div>
                    </div>
                    <div style="font-size:.8rem;color:var(--text-secondary);display:flex;justify-content:space-between">
                        <span>${pct.toFixed(1)}% ${speed ? '&middot; ' + speed : ''}</span>
                        <span>${total} &middot; ${d.category || ''}</span>
                    </div>
                    ${d.error ? `<div style="font-size:.8rem;color:var(--danger);margin-top:.25rem">${escapeHtml(d.error)}</div>` : ''}
                </div>
            `;
        }).join('');
    } catch (e) { /* silently fail */ }
}

async function cancelDebridDownload(id) {
    try {
        await fetch(`${API_BASE}/debrid/downloads/${id}`, { method: 'DELETE', headers: getAuthHeaders() });
        refreshDebridDownloads();
    } catch (e) { showToast(e.message, 'error'); }
}

async function clearCompletedDownloads() {
    try {
        await fetch(`${API_BASE}/debrid/downloads/clear`, { method: 'POST', headers: getAuthHeaders() });
        refreshDebridDownloads();
    } catch (e) { showToast(e.message, 'error'); }
}

async function debridPollTorrent(torrentId, filename) {
    let attempts = 0;
    const maxAttempts = 120;

    const poll = async () => {
        try {
            const res = await fetch(`${API_BASE}/debrid/torrent/${torrentId}`, { headers: getAuthHeaders() });
            if (!res.ok) {
                attempts++;
                if (attempts < 5) { setTimeout(poll, 3000); return; }
                debridHideProcessing();
                showToast('Failed to check torrent status', 'error');
                return;
            }
            const data = await res.json();

            if (data.status === 'downloaded' && data.links && data.links.length > 0) {
                debridUpdateProcessing('Ready! Getting stream link...', 100);
                debridHandleLinks(data.links, filename);
                return;
            }

            if (data.status === 'error' || data.status === 'dead' || data.status === 'virus' || data.status === 'magnet_error') {
                debridHideProcessing();
                showToast(`Torrent failed: ${data.status}`, 'error');
                return;
            }

            // Auto-select files if stuck waiting
            if (data.status === 'waiting_files_selection') {
                try {
                    await fetch(`${API_BASE}/debrid/select-files`, {
                        method: 'POST',
                        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ torrent_id: torrentId, file_ids: 'all' }),
                    });
                } catch (e) { /* retry on next poll */ }
            }

            attempts++;
            if (attempts < maxAttempts) {
                const pct = data.progress || 0;
                const speed = data.speed ? ` @ ${(data.speed / 1048576).toFixed(1)} MB/s` : '';
                const statusLabel = {
                    'magnet_conversion': 'Converting magnet',
                    'waiting_files_selection': 'Selecting files',
                    'queued': 'Queued on RD',
                    'downloading': 'Downloading on RD',
                    'compressing': 'Compressing',
                    'uploading': 'Uploading to RD',
                }[data.status] || data.status || 'Processing';
                debridUpdateProcessing(`${statusLabel}: ${pct}%${speed}`, pct);
                setTimeout(poll, 3000);
            } else {
                debridHideProcessing();
                showToast('Torrent taking too long — check Real-Debrid dashboard', 'warning');
            }
        } catch (e) {
            debridHideProcessing();
            showToast(e.message, 'error');
        }
    };

    setTimeout(poll, 2000);
}

function debridShowFiles(data) {
    const files = data.files || [];
    if (files.length === 0) return;

    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.style.cssText = 'display:flex;position:fixed;inset:0;z-index:9999;align-items:center;justify-content:center;background:rgba(0,0,0,.7)';
    modal.innerHTML = `
        <div class="glass-card" style="padding:2rem;max-width:600px;width:90%;max-height:80vh;overflow-y:auto">
            <h3 style="margin-bottom:1rem">Select Files</h3>
            <div style="margin-bottom:1rem">
                ${files.map(f => `
                    <label style="display:flex;gap:.5rem;align-items:center;padding:.5rem;cursor:pointer;border-bottom:1px solid var(--glass-border)">
                        <input type="checkbox" value="${f.id}" checked>
                        <span style="flex:1;font-size:.9rem">${escapeHtml(f.path)}</span>
                        <span style="color:var(--text-secondary);font-size:.8rem">${f.bytes ? (f.bytes / 1073741824).toFixed(2) + ' GB' : ''}</span>
                    </label>
                `).join('')}
            </div>
            <div style="display:flex;gap:.5rem">
                <button class="primary" onclick="debridConfirmFiles(this,'${data.torrent_id}','${escapeHtml(data.filename || '')}')">
                    <i class="fas fa-check"></i> Select & Download
                </button>
                <button class="secondary" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

async function debridConfirmFiles(btn, torrentId, filename) {
    const modal = btn.closest('.modal-overlay');
    const checked = Array.from(modal.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
    modal.remove();

    if (checked.length === 0) { showToast('No files selected', 'warning'); return; }

    try {
        await fetch(`${API_BASE}/debrid/select-files`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ torrent_id: torrentId, file_ids: checked.join(',') }),
        });
        debridPollTorrent(torrentId, filename);
    } catch (e) { showToast(e.message, 'error'); }
}

// Global event delegation for delete and rename buttons on media cards
// This ensures click handlers work even when buttons are dynamically created
document.addEventListener('click', function(e) {
    // Handle delete buttons
    const deleteBtn = e.target.closest('[data-delete-path]');
    if (deleteBtn) {
        e.stopPropagation();
        e.preventDefault();
        const path = deleteBtn.dataset.deletePath;
        if (path) {
            deleteItem(path);
        }
        return;
    }
    
    // Handle rename buttons
    const renameBtn = e.target.closest('[data-rename-path]');
    if (renameBtn) {
        e.stopPropagation();
        e.preventDefault();
        const path = renameBtn.dataset.renamePath;
        const name = renameBtn.dataset.renameName;
        if (path && name) {
            promptRenameShowPart(path, name);
        }
        return;
    }
}, false);
