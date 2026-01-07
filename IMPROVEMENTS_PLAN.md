# Nomad Pi - Improvement Plan

## Priority 1: Quick Fixes (Do Now)
- [x] Clean up test files from GitHub ✅
- [ ] Fix file manager tile sizes (currently too wide)
- [ ] Fix update success/changelog modal to show automatically
- [ ] Fix PWA manifest and service worker

## Priority 2: Enhanced Playback Features
- [ ] Add subtitle support (.srt, .vtt files)
- [ ] Improve continue watching (save/resume for all media)
- [ ] Auto-play next episode functionality
- [ ] Better progress tracking UI

## Priority 3: Storage Management
- [ ] Storage failover to USB when main storage near limit
- [ ] Storage usage monitoring and alerts
- [ ] Automatic cleanup suggestions

## Priority 4: UI Polish
- [ ] Modernize file browser UI
- [ ] Better loading states
- [ ] Improved mobile responsiveness
- [ ] Dark mode refinements

---

## Implementation Details

### Fix File Manager Tiles
**Problem:** Tiles stretch to full screen width
**Solution:** Use max-width on grid items
```css
.file-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 200px));
    /* Limits max tile width to 200px */
}
```

### Fix Update Modal
**Problem:** Modal doesn't show after update
**Solution:**
- Ensure localStorage version tracking works
- Add fallback to always show modal on first load after update
- Check if checkPostUpdate() is called on page load

### Subtitles Support
**Approach:**
- Scan for .srt/.vtt files next to video files
- Add track element to video player
- UI toggle for subtitle selection

### Auto-Play Next Episode
**Approach:**
- Detect when video ends (ended event)
- Find next episode in same season
- Show countdown timer (10 seconds)
- Auto-start or allow cancel

### Storage Failover
**Approach:**
- Monitor storage usage via /api/system/stats
- When main storage >85%, set flag in database
- Update upload/organize endpoints to use USB path
- Add admin UI to configure threshold and failover drive

