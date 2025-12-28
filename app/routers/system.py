from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import psutil
import os
import subprocess
import platform
import json
from datetime import datetime
from app import database

router = APIRouter()

class OmdbKeyRequest(BaseModel):
    key: str

@router.get("/settings/omdb")
def get_omdb_key():
    key = database.get_setting("omdb_api_key")
    return {"key": key or ""}

@router.post("/settings/omdb")
def save_omdb_key(request: OmdbKeyRequest):
    database.set_setting("omdb_api_key", request.key)
    # Also update environment for current process if possible
    os.environ["OMDB_API_KEY"] = request.key
    return {"status": "ok"}

@router.get("/stats")
def get_stats():
    disk_path = "/" if platform.system() == "Linux" else os.getcwd()
    disk = psutil.disk_usage(disk_path)
    mem = psutil.virtual_memory()
    net = psutil.net_io_counters()
    
    # Get temperature if on Linux/RPi
    temp = 0
    if platform.system() == "Linux":
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = int(f.read()) / 1000
        except:
            pass

    return {
        "cpu": psutil.cpu_percent(interval=0.1),
        "cores": psutil.cpu_count(),
        "memory_total": mem.total,
        "memory_used": mem.used,
        "memory_percent": mem.percent,
        "network_up": net.bytes_sent,
        "network_down": net.bytes_recv,
        "temperature": temp,
        "uptime": int(psutil.boot_time()),
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent
    }

@router.get("/storage/info")
def get_storage_info():
    disk_path = "/" if platform.system() == "Linux" else os.getcwd()
    disk = psutil.disk_usage(disk_path)
    
    drives = []
    if platform.system() == "Linux":
        try:
            output = subprocess.check_output(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,LABEL,FSTYPE"]).decode()
            data = json.loads(output)
            # Flatten lsblk output for easier consumption
            for dev in data.get("blockdevices", []):
                if dev.get("type") == "part" or not dev.get("children"):
                    drives.append({
                        "device": f"/dev/{dev['name']}",
                        "total": dev.get("size"),
                        "mounted": bool(dev.get("mountpoint")),
                        "mountpoint": dev.get("mountpoint"),
                        "label": dev.get("label"),
                        "fstype": dev.get("fstype")
                    })
                for child in dev.get("children", []):
                    drives.append({
                        "device": f"/dev/{child['name']}",
                        "total": child.get("size"),
                        "mounted": bool(child.get("mountpoint")),
                        "mountpoint": child.get("mountpoint"),
                        "label": child.get("label"),
                        "fstype": child.get("fstype")
                    })
        except:
            pass
    else:
        for p in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(p.mountpoint)
                drives.append({
                    "device": p.device,
                    "total": usage.total,
                    "used": usage.used,
                    "mounted": True,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype
                })
            except:
                pass

    return {
        "total": disk.total,
        "used": disk.used,
        "percentage": disk.percent,
        "disks": drives
    }

@router.post("/storage/scan")
def scan_storage():
    # In a real app, this might trigger a rescan of block devices
    return {"status": "success", "message": "Storage scan complete"}

@router.get("/services")
def get_services():
    services = []
    if platform.system() == "Linux":
        # Check some common services we might care about
        check_services = ["nomad-pi.service", "nginx", "docker"]
        for s in check_services:
            try:
                status = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True).stdout.strip()
                services.append({"name": s, "status": "running" if status == "active" else "stopped"})
            except:
                pass
    else:
        services = [
            {"name": "Nomad Pi Server", "status": "running"},
            {"name": "Database", "status": "running"}
        ]
    return {"services": services}

@router.get("/storage")
def get_storage():
    disk_path = "/" if platform.system() == "Linux" else os.getcwd()
    disk = psutil.disk_usage(disk_path)
    mem = psutil.virtual_memory()
    net = psutil.net_io_counters()
    return {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": mem.percent,
        "ram_total": mem.total,
        "ram_used": mem.used,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv
    }

@router.get("/drives")
def list_drives():
    drives = []
    if platform.system() == "Linux":
        try:
            output = subprocess.check_output(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,LABEL,UUID,FSTYPE,MODEL"]).decode()
            data = json.loads(output)
            return data
        except Exception as e:
            return {"error": str(e)}
    else:
        partitions = psutil.disk_partitions()
        for p in partitions:
            try:
                usage = psutil.disk_usage(p.mountpoint)
                drives.append({
                    "name": p.device,
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total": usage.total,
                    "free": usage.free,
                    "label": p.mountpoint  # Windows doesn't easily give labels via psutil
                })
            except:
                pass
    return {"blockdevices": drives}

@router.post("/mount")
def mount_drive(device: str, mount_point: str):
    if platform.system() == "Linux":
        # Create a clean mount point name from the label or device name
        clean_name = "".join(c for c in mount_point if c.isalnum() or c in ('-', '_')).strip()
        if not clean_name:
            clean_name = "usb_drive"
            
        target = os.path.join("data", "external", clean_name)
        os.makedirs(target, exist_ok=True)
        
        try:
            # Check if already mounted
            subprocess.run(["sudo", "-n", "/usr/bin/mount", device, target], check=True)
            return {"status": "mounted", "device": device, "target": target}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"status": "not_implemented_on_windows", "message": "Simulated mount success"}

@router.post("/unmount")
def unmount_drive(target: str):
    if platform.system() == "Linux":
        try:
            subprocess.run(["sudo", "-n", "/usr/bin/umount", target], check=True)
            # Try to remove the directory if it's empty to keep things clean
            try:
                os.rmdir(target)
            except:
                pass 
            return {"status": "unmounted", "target": target}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"status": "not_implemented_on_windows", "message": "Simulated unmount success"}

@router.get("/update/check")
def check_update():
    if platform.system() == "Linux":
        try:
            subprocess.run(["git", "fetch"], check=True)
            output = subprocess.check_output(["git", "status", "-uno"]).decode()
            if "Your branch is behind" in output:
                return {"available": True, "message": "New version available on GitHub"}
            return {"available": False, "message": "System is up to date"}
        except Exception as e:
            return {"available": False, "error": str(e)}
    return {"available": True, "message": "Update check simulated (Windows)"}

@router.get("/update/status")
def get_update_status():
    if platform.system() == "Windows":
        status_file = "update_status.json"
    else:
        status_file = "/tmp/nomad-pi-update.json"

    if os.path.exists(status_file):
        try:
            # On Linux, perform security checks
            if platform.system() == "Linux":
                st = os.stat(status_file)
                if st.st_uid != os.getuid():
                    return {"progress": 0, "message": "Security error: invalid file ownership"}
                if st.st_mode & 0o002:
                    return {"progress": 0, "message": "Security error: invalid file permissions"}
                
            with open(status_file, "r") as f:
                return json.load(f)
        except Exception:
            return {"progress": 0, "message": "Error reading status"}
    return {"progress": 0, "message": "No update in progress"}

@router.get("/update/log")
def get_update_log():
    log_path = os.path.abspath("update.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                return {"log": lines}
        except Exception as e:
            return {"log": [f"Error reading log: {str(e)}"]}
    return {"log": ["No update log found."]}

@router.post("/control/{action}")
def system_control(action: str):
    if action not in ["shutdown", "reboot", "update"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    if action == "update":
        log_file = os.path.abspath("update.log")
        # Ensure log file is clean before starting
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except:
                pass
        
        with open(log_file, "w") as f:
            f.write(f"Update triggered at {datetime.now()}\n")

        if platform.system() == "Linux":
            # Run the update script in the background
            try:
                # Use a shell wrapper to ensure output is flushed and we have a clear completion marker
                cmd = "bash ./update.sh >> update.log 2>&1 && echo '\nUpdate complete!' >> update.log || echo '\nUpdate failed!' >> update.log"
                subprocess.Popen(cmd, shell=True, cwd=os.getcwd())
                return {"status": "Update initiated. System will restart shortly."}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        elif platform.system() == "Windows":
            # Support for testing update on Windows
            try:
                # Use powershell to append to log and add completion marker
                # We use -ExecutionPolicy Bypass to ensure the script can run
                pwsh_cmd = "powershell.exe -ExecutionPolicy Bypass -Command \"& { ./update.ps1 | Out-File -FilePath update.log -Append -Encoding utf8; if ($?) { Add-Content update.log '`nUpdate complete!' } else { Add-Content update.log '`nUpdate failed!' } }\""
                subprocess.Popen(pwsh_cmd, shell=True, cwd=os.getcwd())
                return {"status": "Update initiated (Windows)."}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        else:
            return {"status": "update_simulated", "message": "Update script would run on Linux or Windows"}

    if platform.system() == "Linux":
        cmd = ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"] if action == "shutdown" else ["sudo", "-n", "/usr/sbin/reboot"]
        try:
            subprocess.Popen(cmd)
            return {"status": f"System {action} initiated"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        return {"status": f"Simulated {action} (Windows)"}

# WiFi and Hotspot Management
@router.get("/wifi/status")
def get_wifi_status():
    """Get current WiFi connection status"""
    if platform.system() != "Linux":
        return {"mode": "unknown", "message": "WiFi management only available on Linux"}
    
    try:
        # Check if connected to WiFi
        nmcli_output = subprocess.check_output(
            ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "connection", "show", "--active"],
            text=True
        )
        
        mode = "disconnected"
        ssid = None
        signal = None
        
        for line in nmcli_output.strip().split('\n'):
            if not line:
                continue
            parts = line.split(':')
            if len(parts) >= 3:
                conn_type, state, conn_name = parts[0], parts[1], parts[2]
                if conn_type == "802-11-wireless" and state == "activated":
                    mode = "wifi"
                    ssid = conn_name
                    break
        
        # Check if hotspot is active
        if mode == "disconnected":
            try:
                hotspot_check = subprocess.check_output(
                    ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "connection", "show", "--active"],
                    text=True
                )
                if "NomadPi" in hotspot_check or "hotspot" in hotspot_check.lower():
                    mode = "hotspot"
                    ssid = "NomadPi"
            except:
                pass
        
        # Get signal strength if on WiFi
        if mode == "wifi":
            try:
                iwconfig_output = subprocess.check_output(["iwconfig", "wlan0"], text=True, stderr=subprocess.DEVNULL)
                import re
                signal_match = re.search(r'Signal level=(-?\d+)', iwconfig_output)
                if signal_match:
                    signal = int(signal_match.group(1))
            except:
                pass
        
        return {
            "mode": mode,
            "ssid": ssid,
            "signal": signal,
            "interface": "wlan0"
        }
    except Exception as e:
        return {"mode": "error", "message": str(e)}

@router.post("/wifi/toggle-hotspot")
def toggle_hotspot(enable: bool = True):
    """Toggle hotspot mode on/off"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="WiFi management only available on Linux")
    
    try:
        if enable:
            # Enable hotspot
            subprocess.run(
                ["sudo", "nmcli", "connection", "up", "NomadPi"],
                check=True,
                capture_output=True,
                text=True
            )
            return {
                "status": "ok",
                "mode": "hotspot",
                "message": "Hotspot enabled. Connect to 'NomadPi' network.",
                "ssid": "NomadPi",
                "url": "http://10.42.0.1:8000"
            }
        else:
            # Disable hotspot and try to connect to saved WiFi
            subprocess.run(
                ["sudo", "nmcli", "connection", "down", "NomadPi"],
                check=False,
                capture_output=True
            )
            
            # Try to connect to home WiFi
            try:
                subprocess.run(
                    ["sudo", "nmcli", "connection", "up", "id", os.environ.get("HOME_SSID", "")],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                return {
                    "status": "ok",
                    "mode": "wifi",
                    "message": "Connected to WiFi"
                }
            except:
                return {
                    "status": "ok",
                    "mode": "disconnected",
                    "message": "Hotspot disabled. No WiFi connection available."
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dlna/info")
def get_dlna_info():
    """Get DLNA server information"""
    if platform.system() != "Linux":
        return {"enabled": False, "message": "DLNA only available on Linux"}
    
    try:
        # Check if minidlna is running
        status = subprocess.run(
            ["systemctl", "is-active", "minidlna"],
            capture_output=True,
            text=True
        )
        
        is_running = status.stdout.strip() == "active"
        
        # Get server info
        info = {
            "enabled": is_running,
            "service": "MiniDLNA",
            "friendly_name": "Nomad Pi",
            "port": 8200,
            "url": "http://nomadpi.local:8200",
            "instructions": {
                "vlc": "Open VLC → View → Playlist → Local Network → Universal Plug'n'Play → Nomad Pi",
                "tv": "Open your TV's media player → Look for 'Nomad Pi' in DLNA/Media Servers",
                "windows": "Open File Explorer → Network → Nomad Pi",
                "android": "Use a DLNA app like BubbleUPnP or VLC"
            }
        }
        
        if is_running:
            info["message"] = "DLNA server is running. Your media is available on the network."
        else:
            info["message"] = "DLNA server is not running. Run setup.sh to enable it."
        
        return info
    except Exception as e:
        return {"enabled": False, "message": str(e)}

@router.post("/dlna/restart")
def restart_dlna():
    """Restart DLNA server"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="DLNA only available on Linux")
    
    try:
        subprocess.run(["sudo", "systemctl", "restart", "minidlna"], check=True)
        # Force rescan
        subprocess.run(["sudo", "minidlnad", "-R"], check=False)
        return {"status": "ok", "message": "DLNA server restarted and rescanning media"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
