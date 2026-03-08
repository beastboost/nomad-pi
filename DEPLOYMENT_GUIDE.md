# Deployment Guide: Security and Stability Fixes

## Quick Start

This guide will help you deploy the critical security and stability fixes to prevent crashes on your Raspberry Pi.

## Pre-Deployment Checklist

- [ ] Backup your current database: `cp data/nomad.db data/nomad.db.backup`
- [ ] Note your current configuration
- [ ] Read the SECURITY_FIXES_SUMMARY.md document
- [ ] Schedule a maintenance window (5-10 minutes)

## Deployment Steps

### 1. Update Your Repository

```bash
cd /path/to/nomad-pi
git fetch origin
git checkout fix/security-and-stability-improvements
```

### 2. Configure Environment Variables

Create or edit `.env` file:

```bash
cat > .env << EOF
# Security: Restrict CORS origins
# Add your local network and any remote access you need
ALLOWED_ORIGINS=http://localhost:8000,http://nomadpi.local:8000

# Security: Enable secure cookies (HTTPS only)
# Set to 'false' for HTTP, 'true' for HTTPS
NOMAD_SECURE_COOKIES=false

# Session configuration
SESSION_MAX_AGE_DAYS=30
EOF
```

**For Home Network:**
```bash
ALLOWED_ORIGINS=http://localhost:8000,http://192.168.1.*,http://nomadpi.local:8000
```

**For Remote Access:**
```bash
ALLOWED_ORIGINS=https://yourdomain.com
NOMAD_SECURE_COOKIES=true
```

### 3. Install/Update Dependencies

```bash
pip install -r requirements.txt --upgrade
```

### 4. Restart the Service

**Option A: Using systemd (recommended)**
```bash
sudo systemctl restart nomad-pi
sudo systemctl status nomad-pi
```

**Option B: Manual restart**
```bash
# Find the running process
ps aux | grep uvicorn

# Stop it
sudo pkill -f "python.*uvicorn"

# Start it
./run.sh  # or your start script
```

### 5. Verify the Deployment

```bash
# Check if service is running
curl http://localhost:8000/api/system/status

# Check health endpoint
curl http://localhost:8000/api/system/health

# Check logs for errors
tail -50 data/app.log
```

## Post-Deployment Verification

### 1. Test Security Fixes

**Test SQL Injection Protection:**
```bash
# This should not cause SQL errors
curl "http://localhost:8000/api/media/movies?q=test' OR '1'='1"
```

**Test CORS Restrictions:**
```bash
# From a different origin, should get CORS error
curl -H "Origin: http://malicious.com" -I http://localhost:8000
```

**Test Password Validation:**
```bash
# Try to create user with weak password
curl -X POST http://localhost:8000/api/auth/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"username":"test","password":"weak"}'
# Should return error: "Password must be at least 8 characters..."
```

### 2. Test Stability Improvements

**Test Memory Management:**
```bash
# Monitor memory during operations
watch -n 5 'free -h && echo "---" && ps aux | grep uvicorn | head -5'
```

**Test Upload Progress:**
```bash
# Upload a file and check if progress tracking works
# The progress should be accurate and not crash
curl -X POST http://localhost:8000/api/uploads/single \
  -F "file=@testfile.txt" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3. Monitor for 24-48 Hours

```bash
# Watch for errors
tail -f data/app.log | grep -i "error"

# Monitor system resources
htop  # or top
```

## Troubleshooting

### Issue: Service won't start

**Check logs:**
```bash
tail -100 data/app.log
```

**Common solutions:**
- Verify Python dependencies are installed
- Check database file permissions: `ls -la data/nomad.db`
- Ensure port 8000 is not in use: `netstat -tlnp | grep 8000`

### Issue: CORS errors in browser

**Solution:**
1. Add your origin to `ALLOWED_ORIGINS` in `.env`
2. Restart the service
3. Clear browser cache and reload

### Issue: Can't login after update

**Solution:**
1. Check if password meets new requirements:
   - Minimum 8 characters
   - At least one uppercase letter
   - At least one lowercase letter
   - At least one digit
2. If using default admin password, you may need to reset it

### Issue: Memory still causing crashes

**Solution:**
1. Increase swap space on Pi Zero:
```bash
# Create 1GB swap file
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Change CONF_SWAPSIZE=100 to CONF_SWAPSIZE=1024
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

2. Reduce concurrent operations
3. Monitor and restart if needed

### Issue: Upload progress not working

**Solution:**
1. Check logs for thread lock errors
2. Verify no zombie processes: `ps aux | grep -E 'defunct|zombie'`
3. Restart the service

## Rollback Procedure

If you need to rollback to the previous version:

```bash
# Stop the service
sudo systemctl stop nomad-pi

# Go back to main branch
git checkout main

# Restore database if needed
cp data/nomad.db.backup data/nomad.db

# Restart the service
sudo systemctl start nomad-pi
```

## Performance Monitoring

### Key Metrics to Monitor

1. **Memory Usage:**
```bash
free -h
# Should stay below 80% of total RAM
```

2. **CPU Usage:**
```bash
top -bn1 | grep uvicorn
# Should not stay at 100% for long periods
```

3. **Disk Space:**
```bash
df -h
# Ensure at least 20% free space
```

4. **Error Rate:**
```bash
tail -1000 data/app.log | grep -c ERROR
# Should be minimal (0-5 errors per day)
```

### Alert Thresholds

Set up alerts if:
- Memory usage > 85% for > 5 minutes
- CPU usage > 90% for > 10 minutes
- Disk space < 10% free
- Error rate > 10 per hour

## Next Steps

After successful deployment:

1. **Test all functionality** - Ensure media playback, uploads, and searches work
2. **Monitor for 48 hours** - Watch for crashes or errors
3. **Update documentation** - Document any changes to your setup
4. **Plan next improvements** - Review remaining issues from CODE_ANALYSIS_REPORT.md

## Support

If you encounter issues:

1. Check logs: `tail -100 data/app.log`
2. Review troubleshooting section above
3. Check SECURITY_FIXES_SUMMARY.md
4. Check CODE_ANALYSIS_REPORT.md for context
5. Search for similar issues in the repository

## Success Criteria

Deployment is successful when:
- ✅ Service starts without errors
- ✅ No crashes in 48-hour monitoring period
- ✅ All security tests pass
- ✅ Memory usage remains stable
- ✅ Upload progress tracking works
- ✅ All existing functionality still works

---

**Deployment Date:** _____________  
**Deployed By:** _____________  
**Rollback Needed?** ☐ Yes ☐ No  
**Notes:** _____________