# Changelog

## [1.1.7] - 2026-02-01

### Added
- **Captive Portal**: Auto-detection for Android/iOS/Windows devices when connecting to hotspot
  - Redirects to setup page automatically when devices check for internet connectivity
  - Routes: `/generate_204`, `/gen_204` (Android), `/hotspot-detect.html` (iOS), `/connecttest.txt` (Windows)
- **Setup Welcome Page** (`/setup.html`): Beautiful onboarding experience
  - One-click IP address copy for easy bookmarking
  - Platform-specific "Use Without Internet" instructions for hotspot mode
  - Add to Home Screen instructions for iOS/Android
  - Gradient glassmorphism design
- **Dark Mode Toggle**: 3-state theme switcher in header
  - Default Dark → Light → Extra Dark themes
  - Persistent preference in localStorage
  - Smooth animated transitions between themes
  - Dynamic icon changes (moon/sun/adjust)
- **Public System Info API**: New `/api/system/info` endpoint for IP detection

### Changed
- **UI Overhaul - Admin Panel**: Complete modernization
  - Modern card-based layout with hover effects and shadows
  - Section headers with accent-colored icons and underlines
  - Responsive button grid system (`.button-grid`)
  - Enhanced spacing and visual hierarchy
- **UI Overhaul - Button System**: Professional redesign
  - Gradient backgrounds for all button types
  - Elevation hover animations with shadow enhancement
  - New `.success` button variant (green gradient)
  - Icon integration in all buttons
  - Size variants: `.small`, `.large`
- **UI Overhaul - Form System**: Modern input styling
  - Form groups with icon labels
  - Help text system with contextual information
  - Validation states (error/success) with visual feedback
  - Custom select dropdowns with styled arrows
  - Focus glow effects on all inputs
  - Textarea support with consistent styling
- **UI Overhaul - Sections**: Modernized layouts
  - System Control: Grid layout with color-coded actions
  - File Upload: Redesigned drop zone with large icons
  - User Management: Streamlined inline form grid
  - Library Tools: Organized button groups
  - WiFi Controls: Better status indicators
  - Settings: Clean form layouts with icons

### Fixed
- **CRITICAL**: DNS configuration issue (empty `/etc/resolv.conf` preventing package installation)
- **CRITICAL**: CBR/RAR extraction tools missing (installed 7zip, unrar, unar, libarchive-tools)
- **CBR Comics**: Replaced deprecated `p7zip-full` with `7zip` for Ubuntu 24.04+ compatibility

### Technical
- Light theme CSS variables for accessibility
- Form validation CSS classes
- Help text component styling
- Enhanced admin panel card system
- Responsive grid utilities

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
