$PiUser = "beastboost"
$PiHost = Read-Host "Enter your Pi's IP address (e.g., 192.168.1.100) or hostname (e.g., nomadpi.local)"
$TargetDir = "/home/beastboost/nomad-pi"

Write-Host "Transferring files to $PiUser@$PiHost:$TargetDir ..." -ForegroundColor Cyan

# Create directory first to be safe
ssh $PiUser@$PiHost "mkdir -p $TargetDir"

# Copy files
scp -r .\app .\requirements.txt .\setup.sh .\update.sh .\check_db.py .\rebuild_index.py "$PiUser@$PiHost`:$TargetDir"

Write-Host "Transfer complete!" -ForegroundColor Green
Write-Host "You can now run the setup script on the Pi:" -ForegroundColor Yellow
Write-Host "ssh $PiUser@$PiHost 'cd $TargetDir && chmod +x setup.sh && ./setup.sh'" -ForegroundColor Gray
