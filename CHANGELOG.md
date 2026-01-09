# Changelog

All notable changes to Nomad Pi will be documented in this file.

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
