from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, validator
import psutil
import os
import subprocess
import platform
import json
import logging
import shutil
import re
from datetime import datetime
from app import database
from app.routers.auth import get_current_user_id

logger = logging.getLogger(__name__)

VERSION = "1.5.1"

router = APIRouter()
public_router = APIRouter()

class OmdbKeyRequest(BaseModel):
    key: str

class ControlRequest(BaseModel):
    action: str

@public_router.get("/settings/omdb")
def get_omdb_key():
    key = database.get_setting("omdb_api_key")
    return {"key": key or ""}

@public_router.post("/settings/omdb")
def save_omdb_key(request: OmdbKeyRequest):
    database.set_setting("omdb_api_key", request.key)
    # Also update environment for current process if possible
    os.environ["OMDB_API_KEY"] = request.key
    return {"status": "ok"}

@public_router.get("/status")
def get_system_status():
    """Lightweight endpoint for connectivity checks"""
    return {"status": "online", "version": VERSION}

@public_router.get("/samba/config")
def get_samba_config():
    """Get Samba configuration for NomadTransferTool auto-setup"""
    user = "beastboost" # Default fallback
    if platform.system() == "Linux":
        try:
            import getpass
            user = getpass.getuser()
        except:
            # Fallback to env or whoami
            user = os.environ.get("USER") or subprocess.check_output(["whoami"], text=True).strip()
    
    # Construct UNC path
    hostname = platform.node()
    # In setup.sh, we configure a [data] share. 
    # Returning this directly makes the tool "just work" for most users.
    path = f"\\\\{hostname}.local\\data"
    
    # Try to get actual IP if hostname.local might fail in some environments
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        path = f"\\\\{ip}\\data"
    except:
        pass
        
    return {
        "user": user,
        "path": path,
        "hostname": hostname,
        "is_default_password": database.get_setting("admin_password") in [None, "nomad"]
    }

@public_router.get("/health")
def get_health():
    """Detailed health check results from startup"""
    from app.main import ENV_CHECK_RESULTS
    return ENV_CHECK_RESULTS

def get_aggregate_disk_usage():
    """Calculate aggregate storage stats for all mounted media-relevant drives."""
    total = 0
    used = 0
    free = 0
    
    seen_mounts = set()
    
    # Get all mounted filesystems
    if platform.system() == "Linux":
        # On Linux, try to be smart about what we count
        # We want to count the root filesystem and any mounted USB/external drives
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint in seen_mounts:
                continue
            
            # Skip system/pseudo filesystems
            if part.fstype in ('tmpfs', 'devtmpfs', 'squashfs', 'iso9660'):
                continue
            
            # Skip read-only mounts that aren't likely media (like loop devices)
            if 'ro' in part.opts and not part.mountpoint.startswith(('/media', '/mnt')):
                continue
                
            try:
                usage = psutil.disk_usage(part.mountpoint)
                total += usage.total
                used += usage.used
                free += usage.free
                seen_mounts.add(part.mountpoint)
            except:
                pass
    else:
        # Windows/Other
        for part in psutil.disk_partitions():
            if 'fixed' not in part.opts and 'removable' not in part.opts:
                continue
            if part.mountpoint in seen_mounts:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                total += usage.total
                used += usage.used
                free += usage.free
                seen_mounts.add(part.mountpoint)
            except:
                pass
                
    if total == 0:
        # Fallback to current dir
        try:
            usage = psutil.disk_usage(os.getcwd())
            return usage.total, usage.used, usage.free, usage.percent
        except:
            return 0, 0, 0, 0
            
    percent = (used / total) * 100 if total > 0 else 0
    return total, used, free, percent

@router.get("/stats")
def get_stats(user_id: int = Depends(get_current_user_id)):
    # Use aggregate disk usage for consistency across panels
    disk_total, disk_used, disk_free, disk_percent = get_aggregate_disk_usage()
    
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    net = psutil.net_io_counters()
    
    # Check for memory pressure warnings (especially on Pi Zero)
    mem_warning = None
    if mem.total < 1024 * 1024 * 600: # Less than 600MB RAM (Pi Zero)
        if swap.total < 1024 * 1024 * 500: # Less than 500MB swap
            mem_warning = "Low memory detected. Recommend increasing swap space to 1GB for stability."
        elif swap.percent > 80:
            mem_warning = "Swap space almost full. Performance may be degraded."

    # Get temperature if on Linux/RPi
    temp = 0
    cpu_freq = 0
    cpu_freq_max = 0
    cpu_freq_min = 0
    throttled = False
    cpu_overclock = {}
    
    if platform.system() == "Linux":
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = int(f.read()) / 1000
        except:
            pass
        
        # Get CPU frequency (Raspberry Pi specific)
        try:
            result = subprocess.run(
                ["vcgencmd", "measure_clock", "arm"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                # Output format: frequency(48)=1500000000
                freq_str = result.stdout.strip().split('=')[1]
                cpu_freq = int(freq_str) / 1000000  # Convert to MHz
        except:
            # Fallback to psutil
            try:
                freq = psutil.cpu_freq()
                if freq:
                    cpu_freq = freq.current
                    cpu_freq_max = freq.max
                    cpu_freq_min = freq.min
            except:
                pass
        
        # Check for throttling (Raspberry Pi specific)
        try:
            result = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                # Output format: throttled=0x0
                throttled_hex = result.stdout.strip().split('=')[1]
                throttled_value = int(throttled_hex, 16)
                # Bit 0: under-voltage, Bit 1: arm frequency capped, Bit 2: currently throttled
                throttled = (throttled_value & 0x7) != 0
        except:
            pass

        # Get Overclocking config (Raspberry Pi specific)
        try:
            # Check arm_freq and over_voltage
            for param in ["arm_freq", "over_voltage", "core_freq", "gpu_freq"]:
                res = subprocess.run(["vcgencmd", "get_config", param], capture_output=True, text=True, timeout=1)
                if res.returncode == 0 and "=" in res.stdout:
                    val = res.stdout.strip().split("=")[1]
                    cpu_overclock[param] = val
        except:
            pass

    return {
        "hostname": platform.node(),
        "cpu": psutil.cpu_percent(interval=0.1),
        "cores": psutil.cpu_count(),
        "cpu_freq": cpu_freq,
        "cpu_freq_max": cpu_freq_max,
        "cpu_freq_min": cpu_freq_min,
        "cpu_overclock": cpu_overclock,
        "throttled": throttled,
        "memory_total": mem.total,
        "memory_used": mem.used,
        "memory_percent": mem.percent,
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_percent": swap.percent,
        "mem_warning": mem_warning,
        "network_up": net.bytes_sent,
        "network_down": net.bytes_recv,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_free": disk_free,
        "disk_percent": disk_percent,
        "temp": temp,
        "uptime": datetime.now().timestamp() - psutil.boot_time()
    }

@router.get("/storage/info")
def get_storage_info(user_id: int = Depends(get_current_user_id)):
    disk_total, disk_used, disk_free, disk_percent = get_aggregate_disk_usage()
    
    drives = []
    if platform.system() == "Linux":
        try:
            # Use -b for bytes
            output = subprocess.check_output(["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,LABEL,FSTYPE"]).decode()
            data = json.loads(output)
            # Flatten lsblk output for easier consumption
            for dev in data.get("blockdevices", []):
                if dev.get("type") == "part" or not dev.get("children"):
                    size_bytes = 0
                    try:
                        size_bytes = int(dev.get("size", 0))
                    except:
                        pass

                    d = {
                        "device": f"/dev/{dev['name']}",
                        "total": size_bytes,
                        "mounted": bool(dev.get("mountpoint")),
                        "mountpoint": dev.get("mountpoint"),
                        "label": dev.get("label"),
                        "fstype": dev.get("fstype"),
                        "free": 0,
                        "used": 0
                    }
                    if d["mounted"]:
                        try:
                            usage = psutil.disk_usage(d["mountpoint"])
                            d["free"] = usage.free
                            d["used"] = usage.used
                            d["total"] = usage.total # More accurate than lsblk size
                        except:
                            pass
                    drives.append(d)
                
                for child in dev.get("children", []):
                    size_bytes = 0
                    try:
                        size_bytes = int(child.get("size", 0))
                    except:
                        pass

                    c = {
                        "device": f"/dev/{child['name']}",
                        "total": size_bytes,
                        "mounted": bool(child.get("mountpoint")),
                        "mountpoint": child.get("mountpoint"),
                        "label": child.get("label"),
                        "fstype": child.get("fstype"),
                        "free": 0,
                        "used": 0
                    }
                    if c["mounted"]:
                        try:
                            usage = psutil.disk_usage(c["mountpoint"])
                            c["free"] = usage.free
                            c["used"] = usage.used
                            c["total"] = usage.total
                        except:
                            pass
                    drives.append(c)
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
                    "free": usage.free,
                    "mounted": True,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype
                })
            except:
                pass

    return {
        "total": disk_total,
        "used": disk_used,
        "percentage": disk_percent,
        "disks": drives
    }

@router.post("/storage/scan")
def scan_storage(user_id: int = Depends(get_current_user_id)):
    # In a real app, this might trigger a rescan of block devices
    return {"status": "success", "message": "Storage scan complete"}

@router.get("/services")
def get_services(user_id: int = Depends(get_current_user_id)):
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
def get_storage(user_id: int = Depends(get_current_user_id)):
    if platform.system() == "Linux":
        app_path = os.getcwd()
        disk_path = app_path
        while not os.path.ismount(disk_path) and disk_path != "/":
            disk_path = os.path.dirname(disk_path)
    else:
        disk_path = os.getcwd()
        
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
def list_drives(user_id: int = Depends(get_current_user_id)):
    drives = []
    if platform.system() == "Linux":
        try:
            # Use -b for bytes
            output = subprocess.check_output(["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,LABEL,UUID,FSTYPE,MODEL"]).decode()
            data = json.loads(output)
            
            # Flatten lsblk output for easier consumption in the UI
            flattened = []
            for dev in data.get("blockdevices", []):
                # If it's a partition or has no children, it's a candidate
                if dev.get("type") == "part" or not dev.get("children"):
                    d = dev.copy()
                    # Ensure size is a number
                    try: d["size"] = int(d.get("size", 0))
                    except: d["size"] = 0

                    # Add free space if mounted
                    if d.get("mountpoint"):
                        try:
                            usage = psutil.disk_usage(d["mountpoint"])
                            d["free"] = usage.free
                            d["size"] = usage.total
                        except:
                            d["free"] = 0
                    else:
                        d["free"] = 0
                    flattened.append(d)
                
                # Check children (partitions)
                for child in dev.get("children", []):
                    c = child.copy()
                    # Ensure size is a number
                    try: c["size"] = int(c.get("size", 0))
                    except: c["size"] = 0

                    if c.get("mountpoint"):
                        try:
                            usage = psutil.disk_usage(c["mountpoint"])
                            c["free"] = usage.free
                            c["size"] = usage.total
                        except:
                            c["free"] = 0
                    else:
                        c["free"] = 0
                    flattened.append(c)
            
            return {"blockdevices": flattened}
        except Exception as e:
            return {"error": str(e), "blockdevices": []}
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
                    "size": usage.total,
                    "label": p.mountpoint
                })
            except:
                pass
    return {"blockdevices": drives}

@router.post("/mount")
def mount_drive(device: str, mount_point: str, user_id: int = Depends(get_current_user_id)):
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
def unmount_drive(target: str, user_id: int = Depends(get_current_user_id)):
    if platform.system() == "Linux":
        try:
            subprocess.run(["sudo", "-n", "/usr/bin/umount", "-l", target], check=True)
            return {"status": "unmounted", "target": target}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"status": "not_implemented_on_windows", "message": "Simulated unmount success"}

@router.get("/wifi/status")
def get_wifi_status(user_id: int = Depends(get_current_user_id)):
    if platform.system() != "Linux":
        return {"status": "unsupported", "enabled": True}
    
    try:
        result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True)
        if result.returncode == 0:
            status = result.stdout.strip()
            return {"status": "ok", "enabled": status == "enabled"}
        
        # Fallback to rfkill
        result = subprocess.run(["rfkill", "list", "wifi"], capture_output=True, text=True)
        if "Soft blocked: yes" in result.stdout:
            return {"status": "ok", "enabled": False}
        return {"status": "ok", "enabled": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/wifi/toggle")
def toggle_wifi(enable: bool, user_id: int = Depends(get_current_user_id)):
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="Wi-Fi control only supported on Linux/Raspberry Pi")
    
    try:
        action = "on" if enable else "off"
        # Try nmcli first
        result = subprocess.run(["nmcli", "radio", "wifi", action], capture_output=True, text=True)
        if result.returncode == 0:
            return {"status": "success", "enabled": enable}
        
        # Fallback to rfkill
        action = "unblock" if enable else "block"
        subprocess.run(["sudo", "rfkill", action, "wifi"], check=True)
        return {"status": "success", "enabled": enable}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs")
def get_logs(lines: int = 100, user_id: int = Depends(get_current_user_id)):
    """Retrieve the last N lines of the application log"""
    # Try the configured log file first
    log_file = os.environ.get("NOMAD_LOG_FILE", "data/app.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.readlines()
                return {"logs": [line.strip() for line in content[-lines:]]}
        except Exception:
            pass

    # On Linux, try journalctl as a backup
    if platform.system() == "Linux":
        try:
            result = subprocess.run(
                ["journalctl", "-u", "nomad-pi", "-n", str(lines), "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return {"logs": result.stdout.splitlines()}
        except Exception:
            pass
            
    return {"logs": ["No logs available. Check if data/app.log exists or if journalctl is accessible."]}

@router.post("/control")
def system_control_body(request: ControlRequest, user_id: int = Depends(get_current_user_id)):
    return system_control(request.action, user_id=user_id)

@router.post("/control/{action}")
def system_control(action: str, user_id: int = Depends(get_current_user_id)):
    if action not in ["shutdown", "reboot", "update", "restart"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    def _get_bin_path(name: str, default: str) -> str:
        return shutil.which(name) or default

    if action == "restart":
        if platform.system() == "Linux":
            try:
                systemctl = _get_bin_path("systemctl", "/usr/bin/systemctl")
                subprocess.Popen(["sudo", "-n", systemctl, "restart", "nomad-pi.service"])
                return {"status": "ok", "message": "Service restart initiated..."}
            except Exception as e:
                return {"status": "error", "message": f"Failed to restart service: {e}"}
        return {"status": "error", "message": "Service restart not supported on this OS"}

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
                pwsh_cmd = "powershell.exe -ExecutionPolicy Bypass -Command \"& { ./update.ps1 | Out-File -FilePath update.log -Append -Encoding utf8; if ($?) { Add-Content update.log '`nUpdate complete!' } else { Add-Content update.log '`nUpdate failed!' } }\""
                subprocess.Popen(pwsh_cmd, shell=True, cwd=os.getcwd())
                return {"status": "Update initiated (Windows)."}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        else:
            return {"status": "update_simulated", "message": "Update script would run on Linux or Windows"}

    if platform.system() == "Linux":
        shutdown_bin = _get_bin_path("shutdown", "/usr/sbin/shutdown")
        reboot_bin = _get_bin_path("reboot", "/usr/sbin/reboot")
        
        cmd = ["sudo", "-n", shutdown_bin, "-h", "now"] if action == "shutdown" else ["sudo", "-n", reboot_bin]
        try:
            subprocess.Popen(cmd)
            return {"status": "ok", "message": f"{action.capitalize()} initiated..."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to {action}: {e}"}
    
    return {"status": "error", "message": f"{action.capitalize()} not supported on this OS"}

@router.get("/update/check")
def check_update(user_id: int = Depends(get_current_user_id)):
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
def get_update_status(user_id: int = Depends(get_current_user_id)):
    if platform.system() == "Windows":
        status_file = "update_status.json"
    else:
        status_file = "/tmp/nomad-pi-update.json"

    if os.path.exists(status_file):
        try:
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

@public_router.get("/changelog")
def get_changelog():
    """Fetch recent git commits as a changelog"""
    if platform.system() == "Linux":
        try:
            # Get last 10 commits with summary and relative date
            output = subprocess.check_output(
                ["git", "log", "-n", "10", "--pretty=format:%s (%cr)"],
                text=True
            ).splitlines()
            return {"changelog": output}
        except Exception as e:
            return {"changelog": [f"Error fetching changelog: {e}"]}
    
    # Fallback for Windows/Testing
    return {
        "changelog": [
            "Fixed mobile UI header alignment (1.5.1)",
            "Improved PWA notch support (1.5.1)",
            "Redesigned mobile menu transition (1.5.1)",
            "Added mass duplicate file deletion (1.5.1)",
            "Enhanced update feedback with changelog (1.5.1)",
            "Optimized database queries for faster loading (1.5.0)",
            "Initial release of Nomad Pi (1.0.0)"
        ]
    }

@router.get("/update/log")
def get_update_log(user_id: int = Depends(get_current_user_id)):
    log_path = os.path.abspath("update.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                return {"log": lines}
        except Exception as e:
            return {"log": [f"Error reading log: {str(e)}"]}
    return {"log": ["No update log found."]}

# WiFi and Hotspot Management
@router.get("/wifi/info")
def get_wifi_info(user_id: int = Depends(get_current_user_id)):
    """Get detailed WiFi connection information"""
    if platform.system() != "Linux":
        return {
            "mode": "wifi", 
            "ssid": "Mock_WiFi", 
            "signal": 85, 
            "interface": "wlan0",
            "ip": "192.168.1.100",
            "bitrate": "150 Mb/s",
            "frequency": "2.412 GHz"
        }
    
    try:
        # Detect Wi-Fi interface
        wifi_iface = "wlan0"
        try:
            dev_output = subprocess.check_output(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"], text=True).strip().split('\n')
            for line in dev_output:
                if ':wifi' in line:
                    wifi_iface = line.split(':')[0]
                    break
        except:
            pass

        # Get active wifi info directly from 'dev wifi' which is more accurate for current SSID
        mode = "disconnected"
        ssid = None
        signal = None
        ip_addr = None
        bitrate = None
        freq = None

        try:
            # Check for active WiFi SSID and signal
            dev_wifi = subprocess.check_output(
                ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,FREQ,BARS", "dev", "wifi"],
                text=True
            ).strip().split('\n')
            
            for line in dev_wifi:
                if line.startswith('yes:'):
                    parts = line.split(':')
                    if len(parts) >= 5:
                        mode = "wifi"
                        # yes:SSID:SIGNAL:FREQ:BARS
                        # SSID can have colons
                        bars = parts[-1]
                        freq = parts[-2]
                        signal_str = parts[-3]
                        ssid = ":".join(parts[1:-3])
                        signal = int(signal_str) if signal_str.isdigit() else 0
                        break
        except:
            pass

        # If not found via dev wifi, check if hotspot is active
        if mode == "disconnected":
            try:
                active_conns = subprocess.check_output(
                    ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "connection", "show", "--active"],
                    text=True
                )
                if "NomadPi" in active_conns or "hotspot" in active_conns.lower():
                    mode = "hotspot"
                    ssid = "NomadPi"
                    ip_addr = "10.42.0.1"
                elif "wifi" in active_conns.lower():
                    # If nmcli says wifi is active but we didn't find the SSID yet
                    mode = "wifi"
            except:
                pass
        
        # Get IP address if connected
        if mode != "disconnected" and not ip_addr:
            try:
                ip_output = subprocess.check_output(["hostname", "-I"], text=True).split()
                if ip_output:
                    ip_addr = ip_output[0]
                    if mode == "disconnected":
                        mode = "wifi" # Fallback if we have an IP but nmcli was unsure
            except:
                pass

        # If we have mode=wifi but no SSID, try to get it from iwgetid
        if mode == "wifi" and not ssid:
            try:
                ssid = subprocess.check_output(["iwgetid", "-r"], text=True).strip()
            except:
                pass

        # Get bitrate from iwconfig if on wifi
        if mode == "wifi":
            try:
                iw_output = subprocess.check_output(["iwconfig", wifi_iface], text=True, stderr=subprocess.DEVNULL)
                import re
                br_match = re.search(r'Bit Rate[:=](\d+\.?\d*\s*\w+/s)', iw_output)
                if br_match:
                    bitrate = br_match.group(1)
                
                # If freq not found yet
                if not freq:
                    fr_match = re.search(r'Frequency[:=](\d+\.?\d*\s*\w+Hz)', iw_output)
                    if fr_match:
                        freq = fr_match.group(1)
            except:
                pass
        
        return {
            "mode": mode,
            "ssid": ssid,
            "signal": signal,
            "interface": wifi_iface,
            "ip": ip_addr,
            "bitrate": bitrate,
            "frequency": freq
        }
    except Exception as e:
        return {"mode": "error", "message": str(e)}

@router.post("/wifi/toggle-hotspot")
def toggle_hotspot(enable: bool = True, user_id: int = Depends(get_current_user_id)):
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
                "password": "nomadpassword",
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

@router.get("/wifi/scan")
def scan_wifi(user_id: int = Depends(get_current_user_id)):
    """Scan for available WiFi networks with better discovery"""
    if platform.system() != "Linux":
        # Mock data for Windows
        return {
            "networks": [
                {"ssid": "Mock_Network_1", "signal": 85, "security": "WPA2", "freq": "2.4 GHz", "bars": "▂▄▆█"},
                {"ssid": "Mock_Network_2", "signal": 40, "security": "WPA2", "freq": "5 GHz", "bars": "▂▄"},
                {"ssid": "Open_WiFi", "signal": 60, "security": "None", "freq": "2.4 GHz", "bars": "▂▄▆"}
            ]
        }
    
    try:
        # Some Linux systems require 'sudo' for a full Wi-Fi scan or to see other networks
        # We'll try with sudo first, then fallback to normal user
        
        def get_networks(use_sudo=True, force_rescan=True):
            cmd = []
            if use_sudo:
                cmd = ["sudo", "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ,BARS", "dev", "wifi", "list"]
            else:
                cmd = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ,BARS", "dev", "wifi", "list"]
            
            if force_rescan:
                cmd.append("--rescan")
                cmd.append("yes")
                
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if result.returncode != 0 and use_sudo:
                    # If sudo failed (e.g. no nopasswd), try without sudo
                    return get_networks(use_sudo=False, force_rescan=force_rescan)
                
                nets = []
                seen = set()
                for line in result.stdout.strip().split('\n'):
                    if not line: continue
                    parts = line.split(':')
                    if len(parts) >= 6:
                        bars = parts[-1]
                        freq = parts[-2]
                        security = parts[-3]
                        signal_str = parts[-4]
                        in_use = parts[0] == '*'
                        ssid = ":".join(parts[1:-4])
                        if not ssid or ssid in seen: continue
                        nets.append({
                            "ssid": ssid,
                            "signal": int(signal_str) if signal_str.isdigit() else 0,
                            "security": security if security else "None",
                            "freq": freq,
                            "bars": bars,
                            "active": in_use
                        })
                        seen.add(ssid)
                return nets
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as e:
                # Targeted exception handling as requested
                logging.error(f"WiFi scan error (sudo={use_sudo}): {str(e)}")
                if use_sudo:
                    return get_networks(use_sudo=False, force_rescan=force_rescan)
                return []
            # KeyboardInterrupt and SystemExit will propagate naturally as they are not caught here

        # Try with sudo and rescan first for maximum visibility
        networks = get_networks(use_sudo=True, force_rescan=True)
        
        # If still nothing, try one more time without rescan (sometimes rescan fails but list works)
        if len(networks) <= 1:
            networks = get_networks(use_sudo=False, force_rescan=False)
            
        # Sort: active first, then by signal strength
        networks.sort(key=lambda x: (x.get('active', False), x['signal']), reverse=True)
        return {"networks": networks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class WifiConnectRequest(BaseModel):
    ssid: str
    password: str
    
    @validator('ssid')
    def validate_ssid(cls, v):
        # Allow only alphanumeric, spaces, hyphens, underscores, and dots
        if not re.match(r'^[a-zA-Z0-9 _\-\.]+$', v):
            raise ValueError("SSID contains invalid characters")
        if len(v) > 32:
            raise ValueError("SSID too long (max 32 characters)")
        return v

@router.post("/wifi/connect")
def connect_wifi(request: WifiConnectRequest, user_id: int = Depends(get_current_user_id)):
    """Connect to a new WiFi network"""
    if platform.system() != "Linux":
        return {"status": "success", "message": f"Simulated connection to {request.ssid}"}
    
    try:
        # First, try to delete any existing connection profile for this SSID to avoid conflicts
        subprocess.run(["sudo", "nmcli", "connection", "delete", "id", request.ssid], capture_output=True, check=False)
        
        # Connect to WiFi using nmcli
        # We use 'nmcli device wifi connect' which creates a new profile if needed
        # Adding 'name' helps ensure the connection is identifiable
        result = subprocess.run(
            ["sudo", "nmcli", "dev", "wifi", "connect", request.ssid, "password", request.password, "name", request.ssid],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return {"status": "success", "message": f"Successfully connected to {request.ssid}"}
        else:
            # If the direct connect fails, try the long way: add then up
            # This is sometimes needed for specific security configurations
            err_msg = result.stderr or result.stdout or "Failed to connect"
            logging.error(f"WiFi connection failed: {err_msg}")
            
            # Fallback: manually create the connection if it's a security property issue
            if "802-11-wireless-security.key-mgmt" in err_msg:
                logging.info("Attempting fallback manual connection creation...")
                # 1. Add the connection manually
                add_cmd = [
                    "sudo", "nmcli", "con", "add", "type", "wifi", "ifname", "*", 
                    "con-name", request.ssid, "ssid", request.ssid
                ]
                subprocess.run(add_cmd, capture_output=True, check=False)
                
                # 2. Set the password and security
                modify_cmd = [
                    "sudo", "nmcli", "con", "modify", request.ssid,
                    "wifi-sec.key-mgmt", "wpa-psk",
                    "wifi-sec.psk", request.password
                ]
                subprocess.run(modify_cmd, capture_output=True, check=False)
                
                # 3. Try to bring it up
                up_result = subprocess.run(
                    ["sudo", "nmcli", "con", "up", "id", request.ssid],
                    capture_output=True, text=True, timeout=20
                )
                
                if up_result.returncode == 0:
                    return {"status": "success", "message": f"Successfully connected to {request.ssid} (via fallback)"}
                else:
                    err_msg = up_result.stderr or up_result.stdout or "Manual connection failed"
            
            raise HTTPException(status_code=400, detail=err_msg)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Connection attempt timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/wifi/reconnect")
def reconnect_wifi(ssid: str = None, user_id: int = Depends(get_current_user_id)):
    """Reconnect to WiFi network"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="WiFi management only available on Linux")
    
    try:
        # First, disable hotspot if active
        subprocess.run(
            ["sudo", "nmcli", "connection", "down", "NomadPi"],
            check=False,
            capture_output=True
        )
        
        # If SSID provided, try to connect to it
        if ssid:
            result = subprocess.run(
                ["sudo", "nmcli", "connection", "up", "id", ssid],
                check=True,
                capture_output=True,
                text=True,
                timeout=15
            )
            return {
                "status": "ok",
                "mode": "wifi",
                "ssid": ssid,
                "message": f"Connected to {ssid}"
            }
        else:
            # Try HOME_SSID from environment
            home_ssid = os.environ.get("HOME_SSID", "")
            if home_ssid:
                result = subprocess.run(
                    ["sudo", "nmcli", "connection", "up", "id", home_ssid],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                return {
                    "status": "ok",
                    "mode": "wifi",
                    "ssid": home_ssid,
                    "message": f"Connected to {home_ssid}"
                }
            else:
                # List available connections
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                    capture_output=True,
                    text=True
                )
                connections = []
                for line in result.stdout.strip().split('\n'):
                    if '802-11-wireless' in line and 'NomadPi' not in line:
                        conn_name = line.split(':')[0]
                        connections.append(conn_name)
                
                if connections:
                    # Try first available WiFi connection
                    first_conn = connections[0]
                    subprocess.run(
                        ["sudo", "nmcli", "connection", "up", "id", first_conn],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=15
                    )
                    return {
                        "status": "ok",
                        "mode": "wifi",
                        "ssid": first_conn,
                        "message": f"Connected to {first_conn}"
                    }
                else:
                    raise HTTPException(status_code=404, detail="No saved WiFi connections found")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Connection timeout")
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e.stderr if e.stderr else str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/wifi/saved")
def get_saved_wifi(user_id: int = Depends(get_current_user_id)):
    """Get list of saved WiFi connections"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="WiFi management only available on Linux")
    
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True,
            text=True
        )
        
        connections = []
        for line in result.stdout.strip().split('\n'):
            if '802-11-wireless' in line and 'NomadPi' not in line:
                conn_name = line.split(':')[0]
                connections.append(conn_name)
        
        return {
            "connections": connections,
            "count": len(connections)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dlna/info")
def get_dlna_info(user_id: int = Depends(get_current_user_id)):
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
def restart_dlna(user_id: int = Depends(get_current_user_id)):
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

@router.get("/info")
def get_system_info(user_id: int = Depends(get_current_user_id)):
    """Get detailed system information"""
    info = {
        "hostname": platform.node(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }
    
    if platform.system() == "Linux":
        # Get Raspberry Pi model
        try:
            with open("/proc/device-tree/model", "r") as f:
                info["model"] = f.read().strip().replace('\x00', '')
        except:
            info["model"] = "Unknown"
        
        # Get OS info
        try:
            with open("/etc/os-release", "r") as f:
                os_info = {}
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        os_info[key] = value.strip('"')
                info["os_name"] = os_info.get("PRETTY_NAME", "Linux")
                info["os_version"] = os_info.get("VERSION", "Unknown")
        except:
            info["os_name"] = "Linux"
            info["os_version"] = "Unknown"
        
        # Get kernel version
        try:
            info["kernel"] = subprocess.check_output(["uname", "-r"], text=True).strip()
        except:
            info["kernel"] = platform.release()
        
        # Get uptime
        try:
            with open("/proc/uptime", "r") as f:
                uptime_seconds = float(f.read().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                info["uptime_formatted"] = f"{days}d {hours}h {minutes}m"
        except:
            info["uptime_formatted"] = "Unknown"
        
        # Get memory info
        try:
            mem = psutil.virtual_memory()
            info["memory_total_gb"] = round(mem.total / (1024**3), 2)
            info["memory_available_gb"] = round(mem.available / (1024**3), 2)
        except:
            pass
        
        # Get CPU info
        try:
            info["cpu_count"] = psutil.cpu_count(logical=False)
            info["cpu_count_logical"] = psutil.cpu_count(logical=True)
        except:
            pass
        
        # Get voltage (Raspberry Pi specific)
        try:
            result = subprocess.run(
                ["vcgencmd", "measure_volts", "core"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                # Output format: volt=1.2000V
                voltage_str = result.stdout.strip().split('=')[1].rstrip('V')
                info["voltage"] = float(voltage_str)
        except:
            pass
    
    return info

@router.get("/processes")
def get_processes(user_id: int = Depends(get_current_user_id)):
    """Get list of running processes"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                pinfo = proc.info
                # Only include processes using significant resources or important ones
                if pinfo['cpu_percent'] > 1 or pinfo['memory_percent'] > 1 or pinfo['name'] in ['python', 'uvicorn', 'minidlna', 'smbd', 'nmbd']:
                    processes.append({
                        'pid': pinfo['pid'],
                        'name': pinfo['name'],
                        'cpu': round(pinfo['cpu_percent'], 1),
                        'memory': round(pinfo['memory_percent'], 1),
                        'status': pinfo['status']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Sort by CPU usage
        processes.sort(key=lambda x: x['cpu'], reverse=True)
        return {"processes": processes[:20]}  # Top 20
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs/all")
def get_system_logs(lines: int = 50, user_id: int = Depends(get_current_user_id)):
    """Get recent system logs"""
    if platform.system() != "Linux":
        return {"logs": ["System logs only available on Linux"]}
    
    try:
        # Try journalctl first
        result = subprocess.run(
            ["journalctl", "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return {"logs": result.stdout.split('\n')}
        
        # Fallback to syslog
        result = subprocess.run(
            ["tail", "-n", str(lines), "/var/log/syslog"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return {"logs": result.stdout.split('\n')}
        
        return {"logs": ["No logs available"]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {str(e)}"]}

@router.get("/network/interfaces")
def get_network_interfaces(user_id: int = Depends(get_current_user_id)):
    """Get network interface information"""
    try:
        interfaces = []
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        
        for interface_name, addresses in net_if_addrs.items():
            if interface_name == 'lo':
                continue
            
            interface_info = {
                "name": interface_name,
                "addresses": [],
                "is_up": net_if_stats[interface_name].isup if interface_name in net_if_stats else False,
                "speed": net_if_stats[interface_name].speed if interface_name in net_if_stats else 0
            }
            
            for addr in addresses:
                if addr.family == 2:  # AF_INET (IPv4)
                    interface_info["addresses"].append({
                        "type": "IPv4",
                        "address": addr.address,
                        "netmask": addr.netmask
                    })
                elif addr.family == 10:  # AF_INET6 (IPv6)
                    interface_info["addresses"].append({
                        "type": "IPv6",
                        "address": addr.address
                    })
                elif addr.family == 17:  # AF_PACKET (MAC)
                    interface_info["mac"] = addr.address
            
            interfaces.append(interface_info)
        
        return {"interfaces": interfaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
