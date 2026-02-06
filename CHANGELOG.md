# Changelog

## [2.0.0] - 2026-02-06

### 🎉 Major Release - Comprehensive Media Experience

This release represents a complete overhaul of the Books and Music sections with professional-grade readers and players.

### Added - eBook Reader
- **📚 PDF Support**: Full PDF rendering using PDF.js with canvas-based display
  - Navigate pages with arrow keys or touch swipes
  - Zoom and pan controls
  - Table of contents extraction
  - Progress tracking with auto-save
- **📖 EPUB Support**: Reflowable text using EPUB.js
  - Adjustable font sizes
  - Theme switching (light, sepia, dark)
  - Chapter navigation
  - Text reflow for optimal reading
- **🎨 Comic Book Support**: CBZ/CBR viewing with full-page display
  - High-quality image rendering
  - Keyboard and touch navigation
  - Fit-to-screen modes
- **🔖 Bookmarks System**: Save and restore reading positions
  - LocalStorage-based persistence
  - Quick jump to bookmarked pages
  - Bookmark management UI
- **⚡ Enhanced UI**: Modern full-screen reader modal
  - Keyboard shortcuts (arrows, ESC, fullscreen)
  - Touch gestures for mobile
  - Progress slider with visual feedback
  - Responsive design for all screen sizes

### Added - Music Player
- **🎵 Professional Player**: Complete rewrite of music playback system
  - Album art display (ready for metadata extraction)
  - Artist and title information
  - Visual waveform-style progress bar
- **📋 Queue Management**: Full control over playback queue
  - Add, remove, and reorder tracks
  - Side panel with queue visualization
  - Clear queue functionality
  - Queue persistence across sessions
- **🔀 Advanced Controls**: Professional playback features
  - Shuffle mode with proper randomization
  - Repeat modes (none, all, one track)
  - Previous/next track navigation
  - Volume control with localStorage persistence
- **🎨 Enhanced UI**: Modern glassmorphic player bar
  - Album art thumbnail
  - Dual time display (current/total)
  - Responsive controls for mobile
  - Queue panel with drag handles
- **📱 Media Session API**: Native OS integration
  - Lockscreen controls on mobile
  - Notification media controls
  - System playback integration

### Changed
- Books section now supports PDF, EPUB, and comic books with unified reader
- Music player completely redesigned with queue management
- Improved mobile responsiveness for player controls
- Better progress tracking integration for all media types

### Technical
- Dynamic CDN loading for PDF.js and EPUB.js libraries
- Backward compatibility maintained (old viewers as fallback)
- Optimized for Raspberry Pi performance
- No additional dependencies required in setup

## [1.1.6] - 2026-01-14

### Added
- **Mobile**: Close button to media player to stop playback and hide the bar
- **Admin**: Format drive functionality (ext4) in Storage Management
- **System**: Persistent drive mounting (mounts survive reboots via `mounts.json`)

### Fixed
- **Admin**: Drive size display now correctly formats GB/MB (robust handling of string/number types)
- **System**: Auto-mount logic ensures drives are accessible after formatting

## [1.1.5] - 2026-01-11

### Fixed
- NomadTransferTool: server scan now authenticates (no more “scan unauthorized” after transfer)
- NomadTransferTool: remote logs and restart now work after login

## [1.1.4] - 2026-01-09

### Fixed
- **CRITICAL**: PWA service worker serving stale CSS (music player buttons still squished after update)
  - Updated cache name from v3.1 to v1.1.4 to force cache invalidation
  - This ensures all PWA clients get the new CSS with proper button spacing
- **CRITICAL**: Changelog popup not appearing after manual updates (git pull/merge)
  - Now tracks both pre-update version and last-seen version in localStorage
  - Works with any update method, not just the "Update from GitHub" button

## [1.1.3] - 2026-01-09

### Fixed
- **CRITICAL**: Music player controls overlapping/clipping on mobile
  - Increased gap between buttons (24-28px depending on orientation)
  - Fixed button sizing conflicts with proper padding and flex properties
  - Added horizontal padding to title and progress bar
  - Improved overall spacing and breathing room

## [1.1.2] - 2026-01-09

### Fixed
- **CRITICAL**: Changelog popup not appearing after updates (VERSION was hardcoded instead of reading from file)

## [1.1.1] - 2026-01-09

### Fixed
- Music player orientation-specific spacing (portrait vs landscape optimizations)

## [1.1.0] - 2026-01-09

### Added
- Welcome screen with feature tutorial for first-time users
- System diagnostics endpoint (`/system/diagnostics`) for health checks
- Better error messages for comic book viewer with installation instructions
- Hotspot credentials and network info in README

### Fixed
- **CRITICAL**: Mobile menu navigation now works properly
  - Backdrop no longer interferes with menu button clicks
  - Menu items navigate correctly and close menu after selection
- **CRITICAL**: Bottom navigation bar no longer clips into page content
  - Proper safe-area padding for notched devices
  - Content padding adjusted to prevent overlap
- **CRITICAL**: Music player bar now only appears when music is playing
  - Fixed permanent bar visibility issue on mobile
  - Player properly positioned above bottom nav (90px in portrait, 70px in landscape)
  - Orientation-specific spacing for optimal experience
  - Content padding adjusts automatically when player is visible
- Comic book viewer (CBR) extraction with detailed troubleshooting
- MiniDLNA sudo permissions now persist after system updates
- Duplicate scan no longer deletes TV show episodes (excluded series from detection)
- Movie download button now works with proper Content-Disposition headers
- Mobile menu backdrop now only covers left side, leaving menu fully interactive

### Changed
- **UI Overhaul**: Complete modernization of the interface
  - Modern input fields with focus glow effects
  - Gradient primary buttons with shine animation
  - Color-coded button variants (success, warning, danger)
  - Enhanced media cards with better shadows and hover effects
  - Improved mobile responsiveness across all components
  - Glassmorphic bottom navigation with modern design
  - Active state indicators on navigation items
  - Better touch targets (minimum 48px) throughout
- Media grid is now more responsive (120px-160px based on screen size)
- Improved animations with smooth cubic-bezier easing
- Better contrast and visual hierarchy throughout the UI

### Security
- Added sudoers syntax validation before installation (prevents breaking sudo)
- Fixed Content-Disposition header encoding vulnerability

## [1.0.0] - 2026-01-09

### Added
- Initial release
- Modern glassmorphism UI
- Support for Movies, TV Shows, Music, Books, and Gallery
- Automatic metadata fetching and caching
- Wi-Fi hotspot fallback mode
- MiniDLNA integration for smart TV streaming
- Samba file sharing
- Web-based file uploads
- Resume playback support
- Subtitle support
- Comic book reader (CBZ/CBR)
- System management and monitoring
- One-click GitHub updates
