#!/bin/bash
echo "Fixing Nomad Pi permissions..."

# Correctly identify the real user even if run with sudo
REAL_USER=${SUDO_USER:-$USER}

# Create shared group
sudo groupadd -f nomadpi
sudo usermod -a -G nomadpi "$REAL_USER"
sudo usermod -a -G nomadpi minidlna

# Fix ownership and permissions
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
sudo chown -R "$REAL_USER:nomadpi" data
find data -type d -exec sudo chmod 2775 {} +  # 2 = setgid bit
find data -type f -exec sudo chmod 664 {} +

# Install ACL if needed
if ! command -v setfacl &> /dev/null; then
    sudo apt-get install -y acl
fi

# Set default ACLs
sudo setfacl -R -d -m u::rwx,g::rwx,o::rx data
sudo setfacl -R -d -m g:nomadpi:rwx data

# Restart services
sudo systemctl restart nomad-pi
sudo systemctl restart smbd
sudo systemctl restart minidlna

echo "Done! Log out and back in for group changes to take effect."
