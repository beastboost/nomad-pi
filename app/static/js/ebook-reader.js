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
                </div>
            `;
            document.body.appendChild(modal);

            // Add keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                if (!modal.classList.contains('hidden')) {
                    switch(e.key) {
                        case 'ArrowLeft':
                            this.previousPage();
                            break;
                        case 'ArrowRight':
                            this.nextPage();
                            break;
                        case 'Escape':
                            this.close();
                            break;
                        case 'f':
                        case 'F':
                            if (e.ctrlKey || e.metaKey) {
                                e.preventDefault();
                                // TODO: Add search functionality
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
            alert('Failed to load book: ' + error.message);
            this.close();
        }
    }

    async loadPDF(path) {
        const token = getCookie('auth_token');
        const url = `${API_BASE}/media/stream?path=${encodeURIComponent(path)}${token ? '&token=' + token : ''}`;

        // Load PDF.js if not already loaded
        if (typeof pdfjsLib === 'undefined') {
            await this.loadScript('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js');
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        }

        const loadingTask = pdfjsLib.getDocument(url);
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
        const token = getCookie('auth_token');
        const url = `${API_BASE}/media/stream?path=${encodeURIComponent(path)}${token ? '&token=' + token : ''}`;

        // Load EPUB.js if not already loaded
        if (typeof ePub === 'undefined') {
            await this.loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');
            await this.loadScript('https://cdnjs.cloudflare.com/ajax/libs/epub.js/0.3.93/epub.min.js');
        }

        const epubViewer = document.getElementById('epub-viewer');
        epubViewer.classList.remove('hidden');

        this.epubBook = ePub(url);
        const rendition = this.epubBook.renderTo(epubViewer, {
            width: '100%',
            height: '100%',
            spread: 'none'
        });

        await rendition.display();

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
        const navigation = await this.epubBook.loaded.navigation;
        this.loadTOC(navigation.toc);
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
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
}

// Initialize global eBook reader instance
let ebookReader;
document.addEventListener('DOMContentLoaded', () => {
    ebookReader = new EBookReader();
});
