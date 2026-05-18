#!/bin/bash -e

cd /opt/nomad-pi

# Setup Python virtual environment
python3 -m venv venv

# Install requirements
/opt/nomad-pi/venv/bin/pip install -r requirements.txt

# Ensure permissions
chown -R ${FIRST_USER_NAME}:${FIRST_USER_NAME} /opt/nomad-pi
