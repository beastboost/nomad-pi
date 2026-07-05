/**
 * eBook Reader Component
 * Supports PDF, EPUB, and Comic Books (CBZ/CBR)
 * Uses PDF.js and EPUB.js libraries
 */

class EBookReader {
    constructor() {
        this.currentBook = null;
        this.currentPage = 1;
        this.totalPages = 1;
        this.bookPath = null;
        this.bookType = null; // 'pdf', 'epub', 'comic'
        this.fontSize = 16;
        this.theme = localStorage.getItem('ebook-theme') || 'light';
        this.pdfDoc = null;
        this.epubBook = null;
        this.comicPages = [];
        this.comicIndex = 0;
        this.bookmarks = JSON.parse(localStorage.getItem('ebook-bookmarks') || '{}');

        this.initializeUI();
    }

    initializeUI() {
        // Create reader modal if it doesn't exist
        if (!document.getElementById('ebook-reader-modal')) {
            const modal = document.createElement('div');
            modal.id = 'ebook-reader-modal';
            modal.className = 'ebook-reader-modal hidden';
            modal.innerHTML = `
                <div class="ebook-reader-container">
                    <!-- Header -->
                    <div class="ebook-reader-header">
                        <button class="ebook-btn" onclick="ebookReader.close()" title="Close">
                            <i class="fas fa-arrow-left"></i>
                        </button>
                        <div class="ebook-title" id="ebook-title">Book Title</div>
                        <div class="ebook-header-actions">
                            <button class="ebook-btn" onclick="ebookReader.toggleSearch()" title="Search (Ctrl+F)">
                                <i class="fas fa-search"></i>
                            </button>
                            <button class="ebook-btn" onclick="ebookReader.toggleBookmarks()" title="Bookmarks">
                                <i class="fas fa-bookmark"></i>
                            </button>
                            <button class="ebook-btn" onclick="ebookReader.toggleTOC()" title="Table of Contents">
                                <i class="fas fa-list"></i>
                            </button>
                            <button class="ebook-btn" onclick="ebookReader.toggleSettings()" title="Settings">
                                <i class="fas fa-cog"></i>
                            </button>
                        </div>
                    </div>

                    <!-- Main Content Area -->
                    <div class="ebook-reader-content">
                        <!-- PDF Renderer -->
                        <canvas id="pdf-canvas" class="pdf-canvas hidden"></canvas>

                        <!-- EPUB Renderer -->
                        <div id="epub-viewer" class="epub-viewer hidden"></div>

                        <!-- Comic Viewer -->
                        <div id="comic-viewer" class="comic-viewer hidden">
                            <img id="comic-image" src="" alt="Comic Page">
                        </div>

                        <!-- Loading Indicator -->
                        <div id="ebook-loading" class="ebook-loading hidden">
                            <div class="spinner"></div>
                            <p>Loading book...</p>
                        </div>
                    </div>

                    <!-- Controls -->
                    <div class="ebook-reader-controls">
                        <div class="ebook-controls-left">
                            <button class="ebook-btn" onclick="ebookReader.previousPage()" title="Previous Page">
                                <i class="fas fa-chevron-left"></i>
                            </button>
                            <span class="ebook-page-info" id="ebook-page-info">1 / 1</span>
                            <button class="ebook-btn" onclick="ebookReader.nextPage()" title="Next Page">
                                <i class="fas fa-chevron-right"></i>
                            </button>
                        </div>

                        <div class="ebook-controls-center">
                            <input type="range" id="ebook-progress-slider"
                                   min="1" max="100" value="1"
                                   onchange="ebookReader.goToPage(parseInt(this.value))">
                        </div>

                        <div class="ebook-controls-right">
                            <button class="ebook-btn" onclick="ebookReader.decreaseFontSize()" title="Decrease Font Size">
                                <i class="fas fa-minus"></i> A
                            </button>
                            <button class="ebook-btn" onclick="ebookReader.increaseFontSize()" title="Increase Font Size">
                                <i class="fas fa-plus"></i> A
                            </button>
                            <button class="ebook-btn" onclick="ebookReader.toggleTheme()" title="Toggle Theme">
                                <i class="fas fa-adjust"></i>
                            </button>
                            <button class="ebook-btn" onclick="ebookReader.toggleFullscreen()" title="Fullscreen">
                                <i class="fas fa-expand"></i>
                            </button>
                        </div>
                    </div>

                    <!-- Settings Panel -->
                    <div id="ebook-settings-panel" class="ebook-side-panel hidden">
                        <h3>Settings</h3>
                        <div class="ebook-setting">
                            <label>Font Size</label>
                            <input type="range" min="12" max="32" value="16"
                                   oninput="ebookReader.setFontSize(parseInt(this.value))">
                            <span id="font-size-display">16px</span>
                        </div>
                        <div class="ebook-setting">
                            <label>Theme</label>
                            <select onchange="ebookReader.setTheme(this.value)">
                                <option value="light">Light</option>
                                <option value="sepia">Sepia</option>
                                <option value="dark">Dark</option>
                            </select>
                        </div>
                    </div>

                    <!-- Table of Contents Panel -->
                    <div id="ebook-toc-panel" class="ebook-side-panel hidden">
                        <h3>Table of Contents</h3>
                        <div id="ebook-toc-content"></div>
                    </div>

                    <!-- Bookmarks Panel -->
                    <div id="ebook-bookmarks-panel" class="ebook-side-panel hidden">
                        <h3>Bookmarks</h3>
                        <button class="ebook-btn-primary" onclick="ebookReader.addBookmark()">
                            <i class="fas fa-bookmark"></i> Add Bookmark
                        </button>
                        <div id="ebook-bookmarks-list"></div>
                    </div>

                    <!-- Search Panel -->
                    <div id="ebook-search-panel" class="ebook-side-panel hidden">
                        <h3>Search</h3>
                        <div class="ebook-search-form">
                            <input type="search" id="ebook-search-input" placeholder="Search in book…"
                                   onkeydown="if (event.key === 'Enter') ebookReader.performSearch()">
                            <button class="ebook-btn-primary" onclick="ebookReader.performSearch()">
                                <i class="fas fa-search"></i> Search
                            </button>
                        </div>
                        <div id="ebook-search-results"></div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            // Add keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                if (!modal.classList.contains('hidden')) {
                    // Don't hijack keys while typing in the search box
                    const typing = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA');
                    switch(e.key) {
                        case 'ArrowLeft':
                            if (!typing) this.previousPage();
                            break;
                        case 'ArrowRight':
                            if (!typing) this.nextPage();
                            break;
                        case 'Escape':
                            this.close();
                            break;
                        case 'f':
                        case 'F':
                            if (e.ctrlKey || e.metaKey) {
                                e.preventDefault();
                                this.toggleSearch();
                            }
                            break;
                    }
                }
            });

            // Touch swipe support
            let touchStartX = 0;
            let touchEndX = 0;

            modal.addEventListener('touchstart', (e) => {
                touchStartX = e.changedTouches[0].screenX;
            });

            modal.addEventListener('touchend', (e) => {
                touchEndX = e.changedTouches[0].screenX;
                this.handleSwipe();
            });

            this.handleSwipe = () => {
                const swipeThreshold = 50;
                if (touchEndX < touchStartX - swipeThreshold) {
                    this.nextPage();
                }
                if (touchEndX > touchStartX + swipeThreshold) {
                    this.previousPage();
                }
            };
        }
    }

    async open(bookPath, bookTitle) {
        this.bookPath = bookPath;
        this.currentPage = 1;

        // Determine book type from extension
        const ext = bookPath.toLowerCase().split('.').pop();
        if (ext === 'pdf') {
            this.bookType = 'pdf';
        } else if (ext === 'epub') {
            this.bookType = 'epub';
        } else if (ext === 'cbz' || ext === 'cbr') {
            this.bookType = 'comic';
        } else {
            alert('Unsupported book format: ' + ext);
            return;
        }

        // Show modal and loading
        const modal = document.getElementById('ebook-reader-modal');
        modal.classList.remove('hidden');
        document.getElementById('ebook-title').textContent = bookTitle;
        this.showLoading(true);

        // Hide all viewers
        document.getElementById('pdf-canvas').classList.add('hidden');
        document.getElementById('epub-viewer').classList.add('hidden');
        document.getElementById('comic-viewer').classList.add('hidden');

        // Load the book
        try {
            if (this.bookType === 'pdf') {
                await this.loadPDF(bookPath);
            } else if (this.bookType === 'epub') {
                await this.loadEPUB(bookPath);
            } else if (this.bookType === 'comic') {
                await this.loadComic(bookPath);
            }

            // Restore progress
            await this.restoreProgress();

            this.showLoading(false);
        } catch (error) {
            console.error('Error loading book:', error);
            const errorMsg = error?.message || error?.toString() || 'Unknown error occurred';
            alert('Failed to load book: ' + errorMsg);
            this.close();
        }
    }

    async loadPDF(path) {
        const token = getCookie('auth_token');
        const url = `${API_BASE}/media/stream?path=${encodeURIComponent(path)}${token ? '&token=' + token : ''}`;

        // Load PDF.js if not already loaded
        if (typeof window.pdfjsLib === 'undefined') {
            await this.loadScript('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js');
            window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        }

        const loadingTask = window.pdfjsLib.getDocument(url);
        this.pdfDoc = await loadingTask.promise;
        this.totalPages = this.pdfDoc.numPages;

        document.getElementById('pdf-canvas').classList.remove('hidden');
        this.updatePageInfo();
        await this.renderPDFPage(this.currentPage);
    }

    async renderPDFPage(pageNum) {
        if (!this.pdfDoc) return;

        const page = await this.pdfDoc.getPage(pageNum);
        const canvas = document.getElementById('pdf-canvas');
        const ctx = canvas.getContext('2d');

        // Calculate scale based on container width
        const container = document.querySelector('.ebook-reader-content');
        const viewport = page.getViewport({ scale: 1.0 });
        const scale = (container.clientWidth * 0.9) / viewport.width;
        const scaledViewport = page.getViewport({ scale });

        canvas.height = scaledViewport.height;
        canvas.width = scaledViewport.width;

        const renderContext = {
            canvasContext: ctx,
            viewport: scaledViewport
        };

        await page.render(renderContext).promise;
        this.saveProgress();
    }

    async loadEPUB(path) {
        try {
            const token = getCookie('auth_token');
            const url = `${API_BASE}/media/stream?path=${encodeURIComponent(path)}${token ? '&token=' + token : ''}`;

            console.log('Starting EPUB load for:', path);

            // Load EPUB.js if not already loaded
            if (typeof window.ePub === 'undefined') {
                console.log('Loading JSZip library...');
                try {
                    await this.loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');
                } catch (err) {
                    throw new Error('Failed to load JSZip library. Check internet connection.');
                }

                console.log('Loading EPUB.js library...');
                try {
                    await this.loadScript('https://cdn.jsdelivr.net/npm/epubjs@0.3.93/dist/epub.min.js');
                } catch (err) {
                    throw new Error('Failed to load EPUB.js library. Check internet connection.');
                }

                // Wait a bit for library to initialize
                await new Promise(resolve => setTimeout(resolve, 100));

                // Check if library loaded successfully
                if (typeof window.ePub === 'undefined') {
                    throw new Error('EPUB.js library failed to load. Please check your internet connection.');
                }
                console.log('EPUB.js loaded successfully');
            }

            const epubViewer = document.getElementById('epub-viewer');
            if (!epubViewer) {
                throw new Error('EPUB viewer element not found in page');
            }
            epubViewer.classList.remove('hidden');
            epubViewer.innerHTML = ''; // Clear any previous content

            console.log('Creating EPUB book instance from:', url);
            this.epubBook = window.ePub(url);

            if (!this.epubBook) {
                throw new Error('Failed to create EPUB book instance');
            }

            console.log('Rendering to viewer...');
            const rendition = this.epubBook.renderTo(epubViewer, {
                width: '100%',
                height: '100%',
                spread: 'none',
                flow: 'paginated'
            });

            if (!rendition) {
                throw new Error('Failed to create EPUB rendition');
            }

            console.log('Displaying EPUB...');
            try {
                await rendition.display();
            } catch (err) {
                throw new Error('Failed to display EPUB: ' + (err.message || err));
            }

            // Apply theme
            this.applyEPUBTheme(rendition);

            // Navigation
            rendition.on('relocated', (location) => {
                this.currentPage = location.start.displayed.page;
                this.totalPages = location.start.displayed.total;
                this.updatePageInfo();
                this.saveProgress();
            });

            // Store rendition for navigation
            this.epubRendition = rendition;

            // Load TOC
            try {
                const navigation = await this.epubBook.loaded.navigation;
                this.loadTOC(navigation.toc);
            } catch (err) {
                console.warn('Failed to load TOC:', err);
                // Non-fatal, continue anyway
            }

            console.log('EPUB loaded successfully');
        } catch (error) {
            console.error('Error in loadEPUB:', error);
            throw new Error(error.message || error.toString() || 'Failed to load EPUB file');
        }
    }

    async loadComic(path) {
        try {
            const token = getCookie('auth_token');
            const response = await fetch(`${API_BASE}/media/books/comic/pages?path=${encodeURIComponent(path)}`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            if (!response.ok) throw new Error('Failed to load comic pages');

            const data = await response.json();
            this.comicPages = data.pages || [];
            this.totalPages = this.comicPages.length;
            this.comicIndex = 0;

            if (this.comicPages.length === 0) {
                throw new Error('No pages found in comic');
            }

            document.getElementById('comic-viewer').classList.remove('hidden');
            this.updatePageInfo();
            await this.renderComicPage(this.comicIndex);
        } catch (error) {
            console.error('Error loading comic:', error);
            throw error;
        }
    }

    async renderComicPage(index) {
        if (!this.comicPages[index]) return;

        const token = getCookie('auth_token');
        const page = this.comicPages[index];
        const url = `${API_BASE}/media/stream?path=${encodeURIComponent(page.path)}${token ? '&token=' + token : ''}`;

        const img = document.getElementById('comic-image');
        img.src = url;
        this.currentPage = index + 1;
        this.updatePageInfo();
        this.saveProgress();
    }

    nextPage() {
        if (this.bookType === 'pdf' && this.currentPage < this.totalPages) {
            this.currentPage++;
            this.renderPDFPage(this.currentPage);
        } else if (this.bookType === 'epub' && this.epubRendition) {
            this.epubRendition.next();
        } else if (this.bookType === 'comic' && this.comicIndex < this.comicPages.length - 1) {
            this.comicIndex++;
            this.renderComicPage(this.comicIndex);
        }
    }

    previousPage() {
        if (this.bookType === 'pdf' && this.currentPage > 1) {
            this.currentPage--;
            this.renderPDFPage(this.currentPage);
        } else if (this.bookType === 'epub' && this.epubRendition) {
            this.epubRendition.prev();
        } else if (this.bookType === 'comic' && this.comicIndex > 0) {
            this.comicIndex--;
            this.renderComicPage(this.comicIndex);
        }
    }

    goToPage(pageNum) {
        pageNum = Math.max(1, Math.min(pageNum, this.totalPages));

        if (this.bookType === 'pdf') {
            this.currentPage = pageNum;
            this.renderPDFPage(pageNum);
        } else if (this.bookType === 'comic') {
            this.comicIndex = pageNum - 1;
            this.renderComicPage(this.comicIndex);
        }
        // EPUB navigation by page number is complex, skip for now
    }

    updatePageInfo() {
        document.getElementById('ebook-page-info').textContent = `${this.currentPage} / ${this.totalPages}`;

        const slider = document.getElementById('ebook-progress-slider');
        slider.max = this.totalPages;
        slider.value = this.currentPage;
    }

    increaseFontSize() {
        this.fontSize = Math.min(32, this.fontSize + 2);
        this.applyFontSize();
    }

    decreaseFontSize() {
        this.fontSize = Math.max(12, this.fontSize - 2);
        this.applyFontSize();
    }

    setFontSize(size) {
        this.fontSize = size;
        this.applyFontSize();
        document.getElementById('font-size-display').textContent = size + 'px';
    }

    applyFontSize() {
        if (this.bookType === 'epub' && this.epubRendition) {
            this.epubRendition.themes.fontSize(this.fontSize + 'px');
        }
    }

    toggleTheme() {
        const themes = ['light', 'sepia', 'dark'];
        const currentIndex = themes.indexOf(this.theme);
        this.theme = themes[(currentIndex + 1) % themes.length];
        this.setTheme(this.theme);
    }

    setTheme(theme) {
        this.theme = theme;
        localStorage.setItem('ebook-theme', theme);

        const modal = document.getElementById('ebook-reader-modal');
        modal.className = 'ebook-reader-modal ebook-theme-' + theme;

        if (this.bookType === 'epub' && this.epubRendition) {
            this.applyEPUBTheme(this.epubRendition);
        }
    }

    applyEPUBTheme(rendition) {
        const themes = {
            light: { body: { background: '#ffffff', color: '#000000' } },
            sepia: { body: { background: '#f4ecd8', color: '#5b4636' } },
            dark: { body: { background: '#1a1a1a', color: '#e0e0e0' } }
        };

        rendition.themes.register(themes);
        rendition.themes.select(this.theme);
        rendition.themes.fontSize(this.fontSize + 'px');
    }

    toggleSettings() {
        this.togglePanel('ebook-settings-panel');
    }

    toggleTOC() {
        this.togglePanel('ebook-toc-panel');
    }

    toggleBookmarks() {
        this.loadBookmarksList();
        this.togglePanel('ebook-bookmarks-panel');
    }

    togglePanel(panelId) {
        const panel = document.getElementById(panelId);
        const allPanels = document.querySelectorAll('.ebook-side-panel');

        allPanels.forEach(p => {
            if (p.id !== panelId) {
                p.classList.add('hidden');
            }
        });

        panel.classList.toggle('hidden');
    }

    toggleSearch() {
        this.togglePanel('ebook-search-panel');
        const panel = document.getElementById('ebook-search-panel');
        if (panel && !panel.classList.contains('hidden')) {
            document.getElementById('ebook-search-input')?.focus();
        }
    }

    async performSearch() {
        const input = document.getElementById('ebook-search-input');
        const resultsEl = document.getElementById('ebook-search-results');
        const query = (input?.value || '').trim();
        if (!query || !resultsEl) return;

        if (this.bookType === 'comic') {
            resultsEl.innerHTML = '<p class="ebook-search-empty">Comics have no text to search.</p>';
            return;
        }

        resultsEl.innerHTML = '<p class="ebook-search-empty">Searching…</p>';
        try {
            const results = this.bookType === 'pdf'
                ? await this.searchPDF(query)
                : await this.searchEPUB(query);
            this.renderSearchResults(results, query);
        } catch (err) {
            console.error('Search failed:', err);
            resultsEl.innerHTML = '<p class="ebook-search-empty">Search failed. Try again.</p>';
        }
    }

    async searchPDF(query) {
        const needle = query.toLowerCase();
        const results = [];
        const MAX_RESULTS = 100;
        for (let pageNum = 1; pageNum <= this.totalPages && results.length < MAX_RESULTS; pageNum++) {
            const page = await this.pdfDoc.getPage(pageNum);
            const content = await page.getTextContent();
            const text = content.items.map(it => it.str).join(' ');
            const haystack = text.toLowerCase();
            let idx = haystack.indexOf(needle);
            while (idx !== -1 && results.length < MAX_RESULTS) {
                const start = Math.max(0, idx - 40);
                const end = Math.min(text.length, idx + query.length + 40);
                results.push({ page: pageNum, excerpt: (start > 0 ? '…' : '') + text.slice(start, end) + (end < text.length ? '…' : '') });
                idx = haystack.indexOf(needle, idx + needle.length);
            }
        }
        return results;
    }

    async searchEPUB(query) {
        if (!this.epubBook) return [];
        const MAX_RESULTS = 100;
        const spineItems = this.epubBook.spine?.spineItems || [];
        const perItem = await Promise.all(spineItems.map(item =>
            item.load(this.epubBook.load.bind(this.epubBook))
                .then(() => {
                    const found = item.find(query) || [];
                    item.unload();
                    return found;
                })
                .catch(() => [])
        ));
        return perItem.flat().slice(0, MAX_RESULTS)
            .map(r => ({ cfi: r.cfi, excerpt: r.excerpt || '' }));
    }

    renderSearchResults(results, query) {
        const resultsEl = document.getElementById('ebook-search-results');
        if (!resultsEl) return;
        if (!results.length) {
            resultsEl.innerHTML = `<p class="ebook-search-empty">No matches for “${this.escapeText(query)}”.</p>`;
            return;
        }
        this._searchResults = results;
        resultsEl.innerHTML = `<p class="ebook-search-count">${results.length}${results.length >= 100 ? '+' : ''} match(es)</p>` +
            results.map((r, i) => `
                <button class="ebook-search-result" onclick="ebookReader.goToSearchResult(${i})">
                    ${r.page ? `<span class="ebook-search-page">p. ${r.page}</span>` : ''}
                    <span>${this.escapeText(r.excerpt)}</span>
                </button>`).join('');
    }

    goToSearchResult(index) {
        const r = this._searchResults?.[index];
        if (!r) return;
        if (this.bookType === 'pdf' && r.page) {
            this.goToPage(r.page);
        } else if (this.bookType === 'epub' && r.cfi && this.epubRendition) {
            this.epubRendition.display(r.cfi);
        }
    }

    escapeText(str) {
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    loadTOC(toc) {
        const tocContent = document.getElementById('ebook-toc-content');
        tocContent.innerHTML = '';

        const buildTOCList = (items, level = 0) => {
            const ul = document.createElement('ul');
            ul.style.paddingLeft = (level * 20) + 'px';

            items.forEach(item => {
                const li = document.createElement('li');
                li.innerHTML = `<a href="#" onclick="ebookReader.navigateToTOC('${item.href}'); return false;">${item.label}</a>`;
                ul.appendChild(li);

                if (item.subitems && item.subitems.length > 0) {
                    ul.appendChild(buildTOCList(item.subitems, level + 1));
                }
            });

            return ul;
        };

        tocContent.appendChild(buildTOCList(toc));
    }

    navigateToTOC(href) {
        if (this.epubRendition) {
            this.epubRendition.display(href);
            this.togglePanel('ebook-toc-panel');
        }
    }

    addBookmark() {
        if (!this.bookPath) return;

        const bookmarkKey = this.bookPath;
        if (!this.bookmarks[bookmarkKey]) {
            this.bookmarks[bookmarkKey] = [];
        }

        const bookmark = {
            page: this.currentPage,
            date: new Date().toISOString(),
            label: `Page ${this.currentPage}`
        };

        this.bookmarks[bookmarkKey].push(bookmark);
        localStorage.setItem('ebook-bookmarks', JSON.stringify(this.bookmarks));

        this.loadBookmarksList();
        alert('Bookmark added!');
    }

    loadBookmarksList() {
        const list = document.getElementById('ebook-bookmarks-list');
        list.innerHTML = '';

        const bookmarkKey = this.bookPath;
        const bookmarks = this.bookmarks[bookmarkKey] || [];

        if (bookmarks.length === 0) {
            list.innerHTML = '<p style="color: #888; padding: 10px;">No bookmarks yet</p>';
            return;
        }

        bookmarks.forEach((bookmark, index) => {
            const item = document.createElement('div');
            item.className = 'bookmark-item';
            item.innerHTML = `
                <div onclick="ebookReader.goToPage(${bookmark.page})">
                    <strong>${bookmark.label}</strong>
                    <small>${new Date(bookmark.date).toLocaleDateString()}</small>
                </div>
                <button onclick="ebookReader.removeBookmark(${index})"><i class="fas fa-trash"></i></button>
            `;
            list.appendChild(item);
        });
    }

    removeBookmark(index) {
        const bookmarkKey = this.bookPath;
        if (this.bookmarks[bookmarkKey]) {
            this.bookmarks[bookmarkKey].splice(index, 1);
            localStorage.setItem('ebook-bookmarks', JSON.stringify(this.bookmarks));
            this.loadBookmarksList();
        }
    }

    toggleFullscreen() {
        const modal = document.getElementById('ebook-reader-modal');

        if (!document.fullscreenElement) {
            modal.requestFullscreen().catch(err => {
                console.error('Error entering fullscreen:', err);
            });
        } else {
            document.exitFullscreen();
        }
    }

    async saveProgress() {
        if (!this.bookPath) return;

        try {
            const token = getCookie('auth_token');
            await fetch(`${API_BASE}/media/progress`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { 'Authorization': `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    path: this.bookPath,
                    current_time: this.currentPage,
                    duration: this.totalPages
                })
            });
        } catch (error) {
            console.error('Error saving progress:', error);
        }
    }

    async restoreProgress() {
        if (!this.bookPath) return;

        try {
            const token = getCookie('auth_token');
            const response = await fetch(`${API_BASE}/media/progress/${encodeURIComponent(this.bookPath)}`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            if (response.ok) {
                const data = await response.json();
                if (data.current_time && data.current_time > 1) {
                    const page = Math.floor(data.current_time);
                    if (confirm(`Resume from page ${page}?`)) {
                        this.goToPage(page);
                    }
                }
            }
        } catch (error) {
            console.error('Error restoring progress:', error);
        }
    }

    showLoading(show) {
        const loading = document.getElementById('ebook-loading');
        if (show) {
            loading.classList.remove('hidden');
        } else {
            loading.classList.add('hidden');
        }
    }

    close() {
        const modal = document.getElementById('ebook-reader-modal');
        modal.classList.add('hidden');

        // Cleanup
        if (this.pdfDoc) {
            this.pdfDoc.destroy();
            this.pdfDoc = null;
        }
        if (this.epubBook) {
            this.epubBook.destroy();
            this.epubBook = null;
            this.epubRendition = null;
        }

        this.comicPages = [];
        this.comicIndex = 0;
        this.currentBook = null;
        this.bookPath = null;
    }

    loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.onload = () => {
                console.log('Script loaded:', src);
                resolve();
            };
            script.onerror = () => {
                const error = new Error(`Failed to load script: ${src}`);
                console.error(error);
                reject(error);
            };
            document.head.appendChild(script);
        });
    }
}

// Initialize global eBook reader instance
let ebookReader;
document.addEventListener('DOMContentLoaded', () => {
    ebookReader = new EBookReader();
});
