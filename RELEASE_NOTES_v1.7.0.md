# Nomad Pi v1.7.0 - Release Notes

## ✅ Completed in this Release

### Bug Fixes
- ✅ **Fixed TV Shows Loading** - Added comprehensive debugging and fixed database migration
- ✅ **Fixed Database Schema** - Automatic migration now runs during updates
- ✅ **Update Modal** - Version bumped to trigger changelog display
- ✅ **Cleaned up repository** - Removed test/debug files

### Improvements
- ✅ **Better Error Messages** - TV shows display helpful errors with retry button
- ✅ **Console Logging** - Detailed `[Shows]` logs for debugging
- ✅ **Automatic Migration** - Database updates run seamlessly during update process

---

## 🚧 TODO - Features Requested

### High Priority
- [ ] **Subtitle Support** - Auto-detect .srt/.vtt files and add to video player
- [ ] **Auto-Play Next Episode** - Countdown timer and auto-advance to next episode
- [ ] **Continue Watching Improvements** - Better resume functionality across all media
- [ ] **Update Modal Fix** - Ensure changelog shows every time after update

### Medium Priority
- [ ] **File Manager UI** - Fix tile sizes to not stretch full screen
- [ ] **PWA Improvements** - Ensure offline functionality and install prompts work
- [ ] **Storage Failover** - Auto-switch to USB when main storage >85% full

### Low Priority
- [ ] **UI Polish** - Modern file browser, better mobile responsiveness
- [ ] **Storage Monitoring** - Dashboard showing usage and alerts

---

## Implementation Notes

### Subtitle Support
**Approach:**
```javascript
// In video player, scan for subtitle files
const videoPath = '/data/shows/MyShow/episode.mp4';
const subtitlePath = videoPath.replace(/\.\w+$/, '.srt');

// Check if subtitle exists and add track
fetch(subtitlePath, {method: 'HEAD'})
  .then(res => {
    if (res.ok) {
      const track = document.createElement('track');
      track.src = subtitlePath;
      track.kind = 'subtitles';
      track.label = 'English';
      track.default = true;
      videoElement.appendChild(track);
    }
  });
```

### Auto-Next Episode
**Approach:**
```javascript
videoElement.addEventListener('ended', () => {
  const nextEpisode = findNextEpisode(currentShow, currentSeason, currentEpisode);
  if (nextEpisode) {
    showCountdown(10, () => {
      playMedia(nextEpisode.path);
    });
  }
});
```

### Storage Failover
**Approach:**
- Monitor `/api/system/stats` for storage percentage
- When >85%, set flag in database: `storage_failover_enabled`
- Update upload/organize endpoints to check flag
- If enabled, use USB path from `/data/external/*` instead of `/data/`

---

## Deployment

**Update Process:**
1. Pull from GitHub: `git pull origin main`
2. Run migration: `python migrate_db.py` (now automatic)
3. Restart service: `sudo systemctl restart nomad-pi`
4. Update modal should show with v1.7.0 changelog

**If Update Modal Doesn't Show:**
- Clear localStorage in browser
- Hard refresh (Ctrl+Shift+R)
- Check console for errors
- Verify version in `/api/system/status` returns "1.7.0"

