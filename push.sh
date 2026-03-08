#!/bin/bash
# Automation script to stage, commit and push changes to GitHub
# Usage: ./push.sh "Your commit message"

COMMIT_MSG=$1
if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Update: $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo -e "\e[36m🚀 Starting push to GitHub...\e[0m"

echo "📦 Staging changes..."
git add .
if [ $? -ne 0 ]; then
    echo -e "\e[31m❌ 'git add' failed. Aborting push.\e[0m"
    exit 1
fi

echo "💾 Committing changes with message: '$COMMIT_MSG'..."
git commit -m "$COMMIT_MSG"
if [ $? -ne 0 ]; then
    echo -e "\e[31m❌ 'git commit' failed. Aborting push.\e[0m"
    exit 1
fi

echo "📤 Pushing to GitHub..."
git push origin main

if [ $? -eq 0 ]; then
    echo -e "\e[32m✅ Successfully pushed to GitHub!\e[0m"
else
    echo -e "\e[31m❌ Push failed. Please check for errors above.\e[0m"
    exit 1
fi
