# Add Auto-Restart on Failure to Service

If you want the service to ALWAYS auto-restart when it stops (for any reason),
add this to your service file:

## Edit the service file:

```bash
sudo nano /etc/systemd/system/nomad-pi.service
```

## Add these lines in the [Service] section:

```ini
[Service]
Restart=always
RestartSec=10
```

## Full service file should look like:

```ini
[Unit]
Description=Nomad Pi Media Server
After=network.target

[Service]
Type=simple
User=beastboost
WorkingDirectory=/home/beastboost/nomad-pi
Environment="PATH=/home/beastboost/nomad-pi/venv/bin"
ExecStart=/home/beastboost/nomad-pi/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Apply changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nomad-pi
```

Now the service will ALWAYS restart automatically within 10 seconds if it stops for any reason.
