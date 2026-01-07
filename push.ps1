# Automation script to stage, commit and push changes to GitHub
# Usage: .\push.ps1 "Your commit message"

$commitMessage = $args[0]
if (-not $commitMessage) {
    $commitMessage = "Update: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
}

Write-Host "🚀 Starting push to GitHub..." -ForegroundColor Cyan

Write-Host "📦 Staging changes..."
git add .

Write-Host "💾 Committing changes with message: '$commitMessage'..."
git commit -m "$commitMessage"

Write-Host "📤 Pushing to GitHub..."
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Successfully pushed to GitHub!" -ForegroundColor Green
} else {
    Write-Host "❌ Push failed. Please check for errors above." -ForegroundColor Red
}
