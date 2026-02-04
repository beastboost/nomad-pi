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
from typing import List
from datetime import datetime
from app import database
from app.routers.auth import get_current_user_id

logger = logging.getLogger(__name__)

# Read version from VERSION file
def get_version():
    version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION")
    try:
        with open(version_file, 'r') as f:
            return f.read().strip()
    except Exception:
        return "1.0.0"  # Fallback version

VERSION = get_version()

router = APIRouter()
public_router = APIRouter()

class OmdbKeyRequest(BaseModel):
    key: str

class ControlRequest(BaseModel):
    action: str

class FormatDriveRequest(BaseModel):
    device: str
    label: str
    fstype: str = "ext4"

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
    commit = None
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), text=True).strip()
    except Exception:
        commit = None
    return {"status": "online", "version": VERSION, "commit": commit}

@public_router.get("/info")
def get_public_system_info():
    """Get basic system info including IP address for setup page"""
    import socket

    ip_address = None
    try:
        # Try to get the local IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
    except Exception:
        # Fallback methods
        try:
            ip_address = socket.gethostbyname(socket.gethostname())
        except (socket.gaierror, OSError):
            pass

    return {
        "ip_address": ip_address,
        "hostname": platform.node(),
        "version": VERSION
    }

@public_router.get("/setup/status")
def get_setup_status():
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    allow_insecure_default = os.environ.get("ALLOW_INSECURE_DEFAULT", "true").lower() == "true"

    users = []
    try:
        users = database.get_all_users() or []
    except Exception:
        users = []

    admin_user = None
    try:
        admin_user = database.get_user_by_username("admin")
    except Exception:
        admin_user = None

    admin_must_change_password = bool(admin_user.get("must_change_password", 0)) if admin_user else False

    password_hint = None
    if admin_must_change_password and allow_insecure_default and not admin_password and not admin_password_hash:
        password_hint = "nomad"

    return {
        "users_exist": bool(users),
        "default_username": "admin",
        "password_hint": password_hint,
        "admin_must_change_password": admin_must_change_password,
        "omdb_configured": bool(database.get_setting("omdb_api_key") or os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")),
    }

@public_router.get("/samba/config")
def get_samba_config():
    """Get Samba configuration for NomadTransferTool auto-setup"""
    user = "beastboost" # Default fallback
    if platform.system() == "Linux":
        try:
            import getpass
            user = getpass.getuser()
        except (ImportError, OSError):
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
    except (socket.gaierror, OSError):
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
            except (PermissionError, OSError):
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
            except (PermissionError, OSError):
                pass
                
    if total == 0:
        # Fallback to current dir
        try:
            usage = psutil.disk_usage(os.getcwd())
            return usage.total, usage.used, usage.free, usage.percent
        except (PermissionError, OSError):
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
        except (FileNotFoundError, PermissionError, OSError, ValueError):
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
        except (subprocess.SubprocessError, FileNotFoundError, OSError, IndexError, ValueError):
            # Fallback to psutil
            try:
                freq = psutil.cpu_freq()
                if freq:
                    cpu_freq = freq.current
                    cpu_freq_max = freq.max
                    cpu_freq_min = freq.min
            except (AttributeError, OSError):
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
        except (subprocess.SubprocessError, FileNotFoundError, OSError, IndexError, ValueError):
            pass

        # Get Overclocking config (Raspberry Pi specific)
        try:
            # Check arm_freq and over_voltage
            for param in ["arm_freq", "over_voltage", "core_freq", "gpu_freq"]:
                res = subprocess.run(["vcgencmd", "get_config", param], capture_output=True, text=True, timeout=1)
                if res.returncode == 0 and "=" in res.stdout:
                    val = res.stdout.strip().split("=")[1]
                    cpu_overclock[param] = val
        except (subprocess.SubprocessError, FileNotFoundError, OSError, IndexError):
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
                    except (ValueError, TypeError):
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
                        except (PermissionError, OSError):
                            pass
                    drives.append(d)
                
                for child in dev.get("children", []):
                    size_bytes = 0
                    try:
                        size_bytes = int(child.get("size", 0))
                    except (ValueError, TypeError):
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
                        except (PermissionError, OSError):
                            pass
                    drives.append(c)
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError):
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
            except (PermissionError, OSError):
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
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
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
                    except (ValueError, TypeError): d["size"] = 0

                    # Add free space if mounted
                    if d.get("mountpoint"):
                        try:
                            usage = psutil.disk_usage(d["mountpoint"])
                            d["free"] = usage.free
                            d["size"] = usage.total
                        except (PermissionError, OSError):
                            d["free"] = 0
                    else:
                        d["free"] = 0
                    flattened.append(d)
                
                # Check children (partitions)
                for child in dev.get("children", []):
                    c = child.copy()
                    # Ensure size is a number
                    try: c["size"] = int(c.get("size", 0))
                    except (ValueError, TypeError): c["size"] = 0

                    if c.get("mountpoint"):
                        try:
                            usage = psutil.disk_usage(c["mountpoint"])
                            c["free"] = usage.free
                            c["size"] = usage.total
                        except (PermissionError, OSError):
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
            except (PermissionError, OSError):
                pass
    return {"blockdevices": drives}

PERSISTENT_MOUNTS_FILE = "data/mounts.json"

def save_mount(device, mount_point):
    mounts = {}
    if os.path.exists(PERSISTENT_MOUNTS_FILE):
        try:
            with open(PERSISTENT_MOUNTS_FILE, 'r') as f:
                mounts = json.load(f)
        except (FileNotFoundError, PermissionError, json.JSONDecodeError): pass
    mounts[device] = mount_point
    with open(PERSISTENT_MOUNTS_FILE, 'w') as f:
        json.dump(mounts, f)

def get_device_fstype(device: str) -> str:
    for cmd in (
        ["lsblk", "-no", "FSTYPE", device],
        ["blkid", "-o", "value", "-s", "TYPE", device],
    ):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                fstype = (res.stdout or "").strip().splitlines()[0].strip()
                if fstype:
                    return fstype
        except Exception:
            continue
    return ""

def mount_with_permissions(device: str, target: str) -> None:
    uid = os.getuid()
    gid = os.getgid()
    fstype = get_device_fstype(device).lower()

    mount_bin = shutil.which("mount") or "/usr/bin/mount"
    chown_bin = shutil.which("chown") or "/usr/bin/chown"
    chmod_bin = shutil.which("chmod") or "/usr/bin/chmod"

    attempts = []
    if fstype in {"ntfs", "ntfs3"}:
        attempts.append(["sudo", "-n", mount_bin, "-t", "ntfs3", "-o", f"uid={uid},gid={gid},umask=0002", device, target])
        attempts.append(["sudo", "-n", mount_bin, "-t", "ntfs-3g", "-o", f"uid={uid},gid={gid},umask=0002,big_writes", device, target])
        attempts.append(["sudo", "-n", mount_bin, "-t", "ntfs", "-o", f"uid={uid},gid={gid},umask=0002", device, target])
    elif fstype == "exfat":
        attempts.append(["sudo", "-n", mount_bin, "-t", "exfat", "-o", f"uid={uid},gid={gid},umask=0002", device, target])
    elif fstype in {"vfat", "fat", "msdos"}:
        attempts.append(["sudo", "-n", mount_bin, "-t", "vfat", "-o", f"uid={uid},gid={gid},umask=0002", device, target])

    attempts.append(["sudo", "-n", mount_bin, device, target])

    last_err = None
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            last_err = None
            break
        except subprocess.CalledProcessError as e:
            last_err = (e.stderr or e.stdout or str(e)).strip()

    if last_err:
        raise RuntimeError(last_err)

    try:
        subprocess.run(["sudo", "-n", chown_bin, f"{uid}:{gid}", target], check=False, capture_output=True, text=True)
        subprocess.run(["sudo", "-n", chmod_bin, "0775", target], check=False, capture_output=True, text=True)
    except Exception:
        pass

def remove_mount(target):
    if os.path.exists(PERSISTENT_MOUNTS_FILE):
        try:
            with open(PERSISTENT_MOUNTS_FILE, 'r') as f:
                mounts = json.load(f)
            mounts = {k: v for k, v in mounts.items() if v != target}
            with open(PERSISTENT_MOUNTS_FILE, 'w') as f:
                json.dump(mounts, f)
        except (FileNotFoundError, PermissionError, json.JSONDecodeError): pass

def ensure_media_folders(root: str) -> List[str]:
    created = []
    if not isinstance(root, str) or not root:
        return created
    for folder in ["movies", "shows", "music", "books", "gallery", "files"]:
        try:
            p = os.path.join(root, folder)
            if not os.path.exists(p):
                os.makedirs(p, exist_ok=True)
                created.append(folder)
        except Exception:
            continue
    return created

def ensure_external_category_symlinks(external_root: str, label: str) -> None:
    if platform.system() != "Linux":
        return
    if not isinstance(external_root, str) or not external_root:
        return
    if not isinstance(label, str) or not label:
        return

    data_root = os.path.abspath("data")
    for cat in ["movies", "shows", "music", "books", "gallery", "files"]:
        src = os.path.join(external_root, cat)
        if not os.path.isdir(src):
            continue
        dst_parent = os.path.join(data_root, cat)
        try:
            os.makedirs(dst_parent, exist_ok=True)
        except Exception:
            continue
        dst = os.path.join(dst_parent, f"External_{label}")
        try:
            if os.path.islink(dst):
                if os.path.exists(dst):
                    continue
                os.unlink(dst)
            if os.path.exists(dst):
                continue
            os.symlink(src, dst)
        except Exception:
            continue

def restart_minidlna_best_effort() -> None:
    if platform.system() != "Linux":
        return
    try:
        subprocess.run(["sudo", "-n", "systemctl", "restart", "minidlna"], check=False, capture_output=True, text=True, timeout=10)
    except Exception:
        pass

@router.post("/mount")
def mount_drive(device: str, mount_point: str, user_id: int = Depends(get_current_user_id)):
    if platform.system() == "Linux":
        # Validate device path
        if not device.startswith("/dev/"):
            raise HTTPException(status_code=400, detail="Invalid device path")

        # Additional security checks for device path
        if '..' in device or any(char in device for char in [';', '&', '|', '`', '$', '\x00']):
            raise HTTPException(status_code=400, detail="Invalid characters in device path")

        # Validate mount_point - prevent directory traversal and command injection
        if any(char in mount_point for char in [';', '&', '|', '`', '$', '\x00', '\n', '\r']):
            raise HTTPException(status_code=400, detail="Invalid characters in mount point")

        if '..' in mount_point or mount_point.startswith('/'):
            raise HTTPException(status_code=400, detail="Invalid mount point path")

        # Create a clean mount point name from the label or device name
        clean_name = "".join(c for c in mount_point if c.isalnum() or c in ('-', '_')).strip()
        if not clean_name:
            clean_name = "usb_drive"
            
        target = os.path.join("data", "external", clean_name)
        os.makedirs(target, exist_ok=True)
        
        try:
            mount_with_permissions(device, target)
            save_mount(device, target)
            created = ensure_media_folders(target)
            ensure_external_category_symlinks(target, clean_name)
            restart_minidlna_best_effort()
            return {"status": "mounted", "device": device, "target": target, "created_folders": created}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"status": "not_implemented_on_windows", "message": "Simulated mount success"}

@router.post("/unmount")
def unmount_drive(target: str, user_id: int = Depends(get_current_user_id)):
    if platform.system() == "Linux":
        # Validate target path - prevent command injection
        if any(char in target for char in [';', '&', '|', '`', '$', '\x00', '\n', '\r']):
            raise HTTPException(status_code=400, detail="Invalid characters in target path")

        # Ensure target is within expected directory structure
        if not target.startswith("data/external/") and not target.startswith("/media/") and not target.startswith("/mnt/"):
            raise HTTPException(status_code=400, detail="Invalid unmount target path")

        try:
            subprocess.run(["sudo", "-n", "/usr/bin/umount", "-l", target], check=True)
            remove_mount(target)
            return {"status": "unmounted", "target": target}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"status": "not_implemented_on_windows", "message": "Simulated unmount success"}

@router.post("/storage/format")
def format_drive(request: FormatDriveRequest, user_id: int = Depends(get_current_user_id)):
    if platform.system() != "Linux":
        return {"status": "success", "message": "Simulated format success"}

    device = request.device
    label = request.label
    fstype = request.fstype

    # Validate device path - prevent path traversal and command injection
    if not device.startswith("/dev/sd") and not device.startswith("/dev/nvme") and not device.startswith("/dev/mmcblk"):
        raise HTTPException(status_code=400, detail="Invalid device path")

    # Additional security checks for device path
    if '..' in device or ';' in device or '&' in device or '|' in device or '`' in device or '$' in device:
        raise HTTPException(status_code=400, detail="Invalid characters in device path")

    # Validate fstype - only allow specific safe filesystem types
    allowed_fstypes = ['ext4', 'ext3', 'exfat', 'vfat', 'ntfs']
    if fstype not in allowed_fstypes:
        raise HTTPException(status_code=400, detail=f"Invalid filesystem type. Allowed: {', '.join(allowed_fstypes)}")

    # Validate and sanitize label - prevent command injection
    if label:
        # Remove any dangerous characters
        if any(char in label for char in [';', '&', '|', '`', '$', '\x00', '\n', '\r']):
            raise HTTPException(status_code=400, detail="Invalid characters in label")
        # Limit label length
        if len(label) > 255:
            raise HTTPException(status_code=400, detail="Label too long (max 255 characters)")
         
    try:
        subprocess.run(["sudo", "umount", device], check=False)
        
        mkfs_cmd = ["sudo", "mkfs", "-t", fstype]
        if label:
            mkfs_cmd.extend(["-L", label])
        if fstype == "ext4":
            mkfs_cmd.append("-F")
        mkfs_cmd.append(device)
            
        subprocess.run(mkfs_cmd, check=True, input="y\n", text=True)
        
        clean_name = "".join(c for c in (label or "drive") if c.isalnum() or c in ('-', '_')).strip()
        if not clean_name: clean_name = "usb_drive"
        target = os.path.join("data", "external", clean_name)
        os.makedirs(target, exist_ok=True)
        
        mount_with_permissions(device, target)
        save_mount(device, target)
        created = ensure_media_folders(target)
        ensure_external_category_symlinks(target, clean_name)
        restart_minidlna_best_effort()
        return {"status": "formatted", "device": device, "target": target, "created_folders": created}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Format failed: {str(e)}")

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
        result = subprocess.run(["nmcli", "radio", "wifi", action], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return {"status": "success", "enabled": enable}
        
        # Fallback to rfkill
        action = "unblock" if enable else "block"
        fallback = subprocess.run(
            ["sudo", "-n", "rfkill", action, "wifi"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if fallback.returncode != 0:
            msg = (fallback.stderr or fallback.stdout or "rfkill failed").strip()
            raise HTTPException(status_code=500, detail=msg)
        return {"status": "success", "enabled": enable}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/wifi/restart")
def restart_wifi(user_id: int = Depends(get_current_user_id)):
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="Wi-Fi restart only supported on Linux/Raspberry Pi")

    try:
        script = "nmcli connection down NomadPi >/dev/null 2>&1 || true; nmcli radio wifi off >/dev/null 2>&1 || true; sleep 2; nmcli radio wifi on >/dev/null 2>&1 || true"
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd = ["bash", "-lc", script]
        else:
            probe = subprocess.run(["sudo", "-n", "true"], capture_output=True, text=True, timeout=2)
            if probe.returncode != 0:
                raise HTTPException(status_code=500, detail=(probe.stderr or probe.stdout or "sudo not permitted").strip())
            cmd = ["sudo", "-n", "bash", "-lc", script]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "ok", "message": "Wi-Fi restart initiated"}
    except HTTPException:
        raise
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
        status_file = "/tmp/nomad-pi-update.json" if platform.system() == "Linux" else os.path.abspath("update_status.json")
        # Ensure log file is clean before starting
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except (PermissionError, OSError):
                pass
        if os.path.exists(status_file):
            try:
                os.remove(status_file)
            except (PermissionError, OSError):
                pass
        
        with open(log_file, "w") as f:
            f.write(f"Update triggered at {datetime.now()}\n")

        if platform.system() == "Linux":
            # Run the update script in the background
            try:
                # Use a shell wrapper to ensure output is flushed and we have a clear completion marker
                if os.geteuid() == 0:
                    cmd = "bash ./update.sh >> update.log 2>&1 && echo '\nUpdate complete!' >> update.log || echo '\nUpdate failed!' >> update.log"
                else:
                    cmd = "sudo -n bash ./update.sh >> update.log 2>&1 && echo '\nUpdate complete!' >> update.log || echo '\nUpdate failed!' >> update.log"
                subprocess.Popen(cmd, shell=True, cwd=os.getcwd())
                return {"status": "Update initiated. System will restart shortly."}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        return {"status": "error", "message": "Update is only supported on Linux"}

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
    return {"available": False, "message": "Update check only supported on Linux"}

@router.get("/update/status")
def get_update_status(user_id: int = Depends(get_current_user_id)):
    if platform.system() == "Windows":
        status_file = "update_status.json"
    else:
        tmp_status = "/tmp/nomad-pi-update.json"
        status_file = tmp_status if os.path.exists(tmp_status) else os.path.abspath("update_status.json")

    if os.path.exists(status_file):
        try:
            if platform.system() == "Linux":
                st = os.stat(status_file)
                if st.st_uid not in {0, os.getuid()}:
                    return {"progress": 0, "message": "Security error: invalid file ownership"}
                if st.st_mode & 0o022:
                    return {"progress": 0, "message": "Security error: invalid file permissions"}
                
            with open(status_file, "r", encoding="utf-8", errors="ignore") as f:
                return json.load(f)
        except Exception:
            return {"progress": 0, "message": "Error reading status"}
    return {"progress": 0, "message": "No update in progress"}

@public_router.get("/changelog")
def get_changelog():
    """Fetch recent git commits as a changelog with fallback to CHANGELOG.md"""
    logger.info("Changelog requested")
    # Try git first
    if platform.system() == "Linux" or os.path.exists(".git"):
        try:
            # Get last 10 commits with summary and relative date
            output = subprocess.check_output(
                ["git", "log", "-n", "10", "--pretty=format:%s (%cr)"],
                text=True,
                stderr=subprocess.DEVNULL
            ).splitlines()
            if output:
                logger.info(f"Returning {len(output)} commits from git log")
                return {"changelog": output}
        except Exception as e:
            logger.debug(f"Git log failed: {e}")
            pass

    # Fallback to CHANGELOG.md
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    changelog_path = os.path.join(project_root, "CHANGELOG.md")
    logger.info(f"Checking for CHANGELOG.md at: {changelog_path}")
    
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                entries = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    # Include version headers and list items
                    if line.startswith("#") or line.startswith("-") or line.startswith("*") or (line and line[0].isdigit()):
                        # Clean up headers for display
                        if line.startswith("###"):
                            line = f"<b>{line.replace('###', '').strip()}</b>"
                        elif line.startswith("##"):
                            line = f"<u>{line.replace('##', '').strip()}</u>"
                        elif line.startswith("#"):
                            line = f"<b>{line.replace('#', '').strip()}</b>"
                        
                        entries.append(line)
                    
                    if len(entries) >= 20:
                        break
                if entries:
                    logger.info(f"Returning {len(entries)} entries from CHANGELOG.md")
                    return {"changelog": entries}
        except Exception as e:
            logger.error(f"Error reading CHANGELOG.md: {e}")
            pass
    
    # Static Fallback
    logger.info("Returning static fallback changelog")
    return {
        "changelog": [
            "Fixed service restart timing for Pi Zero stability (1.7.0)",
            "Added comprehensive TV shows debugging (1.7.0)",
            "Automatic database migrations during updates (1.7.0)",
            "Fixed 203/EXEC service startup error on Raspberry Pi (1.6.1)",
            "Improved TV Show detection for root folders (1.6.0)",
            "Automated MiniDLNA permissions and system tuning in setup.sh (1.6.0)",
            "Secured backend endpoints with user-level authentication (1.6.0)",
            "Fixed cross-user data leaks in database queries (1.6.0)",
            "Fixed mobile UI header alignment (1.5.1)",
            "Improved PWA notch support (1.5.1)",
            "Redesigned mobile menu transition (1.5.1)",
            "Added mass duplicate file deletion (1.5.1)",
            "Enhanced update feedback with changelog (1.5.1)"
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
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
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
        except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
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
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                pass
        
        # Get IP address if connected
        if mode != "disconnected" and not ip_addr:
            try:
                ip_output = subprocess.check_output(["hostname", "-I"], text=True).split()
                if ip_output:
                    ip_addr = ip_output[0]
                    if mode == "disconnected":
                        mode = "wifi" # Fallback if we have an IP but nmcli was unsure
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                pass

        # If we have mode=wifi but no SSID, try to get it from iwgetid
        if mode == "wifi" and not ssid:
            try:
                ssid = subprocess.check_output(["iwgetid", "-r"], text=True).strip()
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
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
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
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
                ["sudo", "-n", "nmcli", "connection", "up", "NomadPi"],
                check=True,
                capture_output=True,
                text=True,
                timeout=20
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
                ["sudo", "-n", "nmcli", "connection", "down", "NomadPi"],
                check=False,
                capture_output=True,
                timeout=20
            )
            
            # Try to connect to home WiFi
            try:
                home_ssid = os.environ.get("HOME_SSID", "").strip()
                if not home_ssid:
                    return {
                        "status": "ok",
                        "mode": "disconnected",
                        "message": "Hotspot disabled. No WiFi configured."
                    }
                subprocess.run(
                    ["sudo", "-n", "nmcli", "connection", "up", "id", home_ssid],
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
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
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
                cmd = ["sudo", "-n", "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ,BARS", "dev", "wifi", "list"]
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
        subprocess.run(
            ["sudo", "-n", "nmcli", "connection", "delete", "id", request.ssid],
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )

        subprocess.run(
            ["sudo", "-n", "nmcli", "connection", "down", "NomadPi"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False
        )
        
        # Connect to WiFi using nmcli
        # We use 'nmcli device wifi connect' which creates a new profile if needed
        # Adding 'name' helps ensure the connection is identifiable
        result = subprocess.run(
            ["sudo", "-n", "nmcli", "dev", "wifi", "connect", request.ssid, "password", request.password, "name", request.ssid],
            capture_output=True,
            text=True,
            timeout=45
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
                    "sudo", "-n", "nmcli", "con", "add", "type", "wifi", "ifname", "*",
                    "con-name", request.ssid, "ssid", request.ssid
                ]
                subprocess.run(add_cmd, capture_output=True, text=True, timeout=20, check=False)
                
                # 2. Set the password and security
                modify_cmd = [
                    "sudo", "-n", "nmcli", "con", "modify", request.ssid,
                    "wifi-sec.key-mgmt", "wpa-psk",
                    "wifi-sec.psk", request.password
                ]
                subprocess.run(modify_cmd, capture_output=True, text=True, timeout=20, check=False)
                
                # 3. Try to bring it up
                up_result = subprocess.run(
                    ["sudo", "-n", "nmcli", "con", "up", "id", request.ssid],
                    capture_output=True, text=True, timeout=20
                )
                
                if up_result.returncode == 0:
                    return {"status": "success", "message": f"Successfully connected to {request.ssid} (via fallback)"}
                else:
                    err_msg = up_result.stderr or up_result.stdout or "Manual connection failed"
            
            raise HTTPException(status_code=400, detail=err_msg)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Connection attempt timed out")
    except HTTPException:
        raise
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
            ["sudo", "-n", "nmcli", "connection", "down", "NomadPi"],
            check=False,
            capture_output=True,
            timeout=15
        )
        
        # If SSID provided, try to connect to it
        if ssid:
            result = subprocess.run(
                ["sudo", "-n", "nmcli", "connection", "up", "id", ssid],
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
                    ["sudo", "-n", "nmcli", "connection", "up", "id", home_ssid],
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
                        ["sudo", "-n", "nmcli", "connection", "up", "id", first_conn],
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
    except HTTPException:
        raise
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

# Tailscale VPN Management
@router.get("/tailscale/status")
def get_tailscale_status(user_id: int = Depends(get_current_user_id)):
    """Get Tailscale connection status"""
    if platform.system() != "Linux":
        return {"installed": False, "connected": False, "message": "Tailscale only available on Linux"}

    try:
        # Check if Tailscale is installed (check multiple paths)
        paths_to_check = ["/usr/bin/tailscale", "/usr/local/bin/tailscale", "/bin/tailscale"]
        tailscale_path = shutil.which("tailscale")
        
        if not tailscale_path:
            # Fallback check
            for path in paths_to_check:
                if os.path.exists(path):
                    tailscale_path = path
                    break
        
        if not tailscale_path:
            return {"installed": False, "connected": False, "message": "Tailscale not found in PATH"}

        # Check if tailscaled service is running
        service_result = subprocess.run(
            ["systemctl", "is-active", "tailscaled"],
            capture_output=True,
            text=True
        )
        service_running = service_result.stdout.strip() == "active"

        if not service_running:
            return {
                "installed": True,
                "connected": False,
                "service_running": False,
                "message": "Tailscale service not running"
            }

        # Get connection status
        status_result = subprocess.run(
            ["sudo", "-n", "tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if status_result.returncode == 0:
            status_data = json.loads(status_result.stdout)
            backend_state = status_data.get("BackendState", "")

            # Get simple status for quick checks
            status_simple = subprocess.run(
                ["sudo", "-n", "tailscale", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Get IP and other details
            self_node = status_data.get("Self", {})
            tailscale_ips = self_node.get("TailscaleIPs", [])
            ipv4 = next((ip for ip in tailscale_ips if "." in ip), None)
            
            return {
                "installed": True,
                "connected": backend_state == "Running",
                "service_running": True,
                "backend_state": backend_state,
                "self": self_node,
                "ipv4": ipv4,
                "magic_dns": status_data.get("MagicDNSSuffix", ""),
                "peer_count": len(status_data.get("Peer", {})),
                "status_output": status_simple.stdout
            }
        else:
            return {
                "installed": True,
                "connected": False,
                "service_running": True,
                "message": "Unable to get status"
            }

    except subprocess.TimeoutExpired:
        return {"installed": True, "connected": False, "error": "Status check timed out"}
    except Exception as e:
        return {"installed": True, "connected": False, "error": str(e)}

@router.post("/tailscale/service/{action}")
def tailscale_service_control(action: str, user_id: int = Depends(get_current_user_id)):
    """Start or stop the Tailscale system service"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="Tailscale service control only available on Linux")
        
    if action not in ["start", "stop", "restart"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    try:
        cmd = ["sudo", "-n", "systemctl", action, "tailscaled"]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
        return {"status": "success", "message": f"Service {action}ed successfully"}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to {action} service: {e.stderr or str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tailscale/ip")
def get_tailscale_ip(user_id: int = Depends(get_current_user_id)):
    """Get Tailscale IP address"""
    if platform.system() != "Linux":
        return {"ip": None, "message": "Tailscale only available on Linux"}

    try:
        result = subprocess.run(
            ["sudo", "-n", "tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            ip = result.stdout.strip()
            return {"ip": ip if ip else None}
        else:
            return {"ip": None, "message": "Not connected to Tailscale"}
    except Exception as e:
        return {"ip": None, "error": str(e)}

class TailscaleKeyRequest(BaseModel):
    auth_key: str

@router.post("/tailscale/set-auth-key")
def set_tailscale_key(request: TailscaleKeyRequest, user_id: int = Depends(get_current_user_id)):
    """Save Tailscale Auth Key to database"""
    database.set_setting("tailscale_auth_key", request.auth_key)
    return {"status": "success", "message": "Auth key saved"}

@router.post("/tailscale/up")
def tailscale_up(user_id: int = Depends(get_current_user_id)):
    """Connect to Tailscale network"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="Tailscale only available on Linux")

    try:
        # Check if already connected
        status_result = subprocess.run(
            ["sudo", "-n", "tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if status_result.returncode == 0:
            status_data = json.loads(status_result.stdout)
            if status_data.get("BackendState") == "Running":
                return {"status": "success", "message": "Already connected to Tailscale"}

        # Get auth key from database if available
        auth_key = database.get_setting("tailscale_auth_key")

        # Build tailscale up command
        cmd = ["sudo", "-n", "tailscale", "up"]

        # Add auth key if available
        if auth_key:
            cmd.extend(["--authkey", auth_key])

        # Add recommended flags for server/always-on use
        cmd.extend([
            "--accept-routes",  # Accept subnet routes from exit nodes
            "--ssh"  # Enable Tailscale SSH
        ])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return {
                "status": "success",
                "message": "Connected to Tailscale",
                "output": result.stdout
            }
        else:
            # Check if it's an auth issue
            if "authenticate" in result.stderr.lower() or "login" in result.stderr.lower():
                return {
                    "status": "needs_auth",
                    "message": "Please authenticate via the provided URL",
                    "output": result.stderr
                }
            else:
                raise HTTPException(status_code=500, detail=result.stderr or "Failed to connect")

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Connection attempt timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tailscale/down")
def tailscale_down(user_id: int = Depends(get_current_user_id)):
    """Disconnect from Tailscale network"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="Tailscale only available on Linux")

    try:
        result = subprocess.run(
            ["sudo", "-n", "tailscale", "down"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return {"status": "success", "message": "Disconnected from Tailscale"}
        else:
            raise HTTPException(status_code=500, detail=result.stderr or "Failed to disconnect")

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Disconnect attempt timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tailscale/peers")
def get_tailscale_peers(user_id: int = Depends(get_current_user_id)):
    """Get list of Tailscale peers"""
    if platform.system() != "Linux":
        return {"peers": [], "message": "Tailscale only available on Linux"}

    try:
        result = subprocess.run(
            ["sudo", "-n", "tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            status_data = json.loads(result.stdout)
            peers_data = status_data.get("Peer", {})

            peers = []
            for peer_id, peer_info in peers_data.items():
                peers.append({
                    "id": peer_id,
                    "hostname": peer_info.get("HostName", "Unknown"),
                    "dns_name": peer_info.get("DNSName", ""),
                    "tailscale_ips": peer_info.get("TailscaleIPs", []),
                    "online": peer_info.get("Online", False),
                    "exit_node": peer_info.get("ExitNode", False),
                    "os": peer_info.get("OS", "")
                })

            return {"peers": peers, "count": len(peers)}
        else:
            return {"peers": [], "message": "Not connected to Tailscale"}

    except Exception as e:
        return {"peers": [], "error": str(e)}

class TailscaleAuthKeyRequest(BaseModel):
    auth_key: str

@router.post("/tailscale/set-auth-key")
def set_tailscale_auth_key(request: TailscaleAuthKeyRequest, user_id: int = Depends(get_current_user_id)):
    """Store Tailscale auth key in database"""
    try:
        # Validate auth key format (starts with tskey-)
        if not request.auth_key.startswith("tskey-"):
            raise HTTPException(status_code=400, detail="Invalid auth key format. Should start with 'tskey-'")

        database.set_setting("tailscale_auth_key", request.auth_key)
        return {"status": "success", "message": "Auth key saved"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tailscale/auth-key")
def get_tailscale_auth_key(user_id: int = Depends(get_current_user_id)):
    """Get stored Tailscale auth key (masked)"""
    try:
        auth_key = database.get_setting("tailscale_auth_key")
        if auth_key:
            # Mask the key, show only first 10 and last 4 characters
            if len(auth_key) > 20:
                masked = auth_key[:10] + "..." + auth_key[-4:]
            else:
                masked = "***"
            return {"has_key": True, "masked_key": masked}
        else:
            return {"has_key": False}
    except Exception as e:
        return {"has_key": False, "error": str(e)}

@router.delete("/tailscale/auth-key")
def delete_tailscale_auth_key(user_id: int = Depends(get_current_user_id)):
    """Delete stored Tailscale auth key"""
    try:
        database.set_setting("tailscale_auth_key", "")
        return {"status": "success", "message": "Auth key deleted"}
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

@router.get("/dlna/status")
def get_dlna_status(user_id: int = Depends(get_current_user_id)):
    """Get DLNA diagnostic information"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="DLNA only available on Linux")

    import glob
    diagnostics = {}

    # Check if service is running
    try:
        result = subprocess.run(["systemctl", "is-active", "minidlna"], capture_output=True, text=True)
        diagnostics["service_running"] = result.stdout.strip() == "active"
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        diagnostics["service_running"] = False

    # Read config to see what paths it's scanning
    db_dir = "/var/cache/minidlna"
    log_dir = "/var/log/minidlna"
    try:
        with open("/etc/minidlna.conf", "r") as f:
            config = f.read()
            lines = config.split("\n")
            media_dirs = [line.split("=", 1)[1].strip() for line in lines if line.startswith("media_dir=")]
            root_container = [line.split("=", 1)[1].strip() for line in lines if line.startswith("root_container=")]
            parsed_db_dirs = [line.split("=", 1)[1].strip() for line in lines if line.startswith("db_dir=")]
            parsed_log_dirs = [line.split("=", 1)[1].strip() for line in lines if line.startswith("log_dir=")]
            if parsed_db_dirs and parsed_db_dirs[0]:
                db_dir = parsed_db_dirs[0]
            if parsed_log_dirs and parsed_log_dirs[0]:
                log_dir = parsed_log_dirs[0]
            diagnostics["configured_paths"] = media_dirs
            diagnostics["root_container"] = root_container[0] if root_container else "NOT SET"
    except (FileNotFoundError, PermissionError, OSError):
        diagnostics["configured_paths"] = ["ERROR: Could not read config"]
        diagnostics["root_container"] = "ERROR"
    diagnostics["db_dir"] = db_dir
    diagnostics["log_dir"] = log_dir

    # Count actual files in data directories
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    movies_dir = os.path.join(base_dir, "data", "movies")
    shows_dir = os.path.join(base_dir, "data", "shows")

    # Check if directories exist
    diagnostics["movies_dir_exists"] = os.path.exists(movies_dir)
    diagnostics["shows_dir_exists"] = os.path.exists(shows_dir)
    diagnostics["movies_dir_path"] = movies_dir
    diagnostics["shows_dir_path"] = shows_dir

    # Check permissions
    try:
        import stat
        if os.path.exists(movies_dir):
            st = os.stat(movies_dir)
            diagnostics["movies_dir_perms"] = oct(st.st_mode)[-3:]
            diagnostics["movies_dir_owner"] = f"{st.st_uid}:{st.st_gid}"
    except (FileNotFoundError, PermissionError, OSError):
        pass

    try:
        movies = glob.glob(os.path.join(movies_dir, "**", "*.mp4"), recursive=True)
        movies += glob.glob(os.path.join(movies_dir, "**", "*.mkv"), recursive=True)
        movies += glob.glob(os.path.join(movies_dir, "**", "*.avi"), recursive=True)
        diagnostics["movie_files_found"] = len(movies)
        diagnostics["movie_samples"] = [os.path.relpath(m, movies_dir) for m in movies[:5]]
    except Exception as e:
        diagnostics["movie_files_found"] = 0
        diagnostics["movie_samples"] = []
        diagnostics["movie_scan_error"] = str(e)

    try:
        shows = glob.glob(os.path.join(shows_dir, "**", "*.mp4"), recursive=True)
        shows += glob.glob(os.path.join(shows_dir, "**", "*.mkv"), recursive=True)
        shows += glob.glob(os.path.join(shows_dir, "**", "*.avi"), recursive=True)
        diagnostics["show_files_found"] = len(shows)
        diagnostics["show_samples"] = [os.path.relpath(s, shows_dir) for s in shows[:5]]
    except Exception as e:
        diagnostics["show_files_found"] = 0
        diagnostics["show_samples"] = []
        diagnostics["show_scan_error"] = str(e)

    # Check cache directory permissions
    try:
        cache_st = os.stat(db_dir)
        diagnostics["cache_dir_perms"] = oct(cache_st.st_mode)[-3:]
        diagnostics["cache_dir_owner"] = f"{cache_st.st_uid}:{cache_st.st_gid}"
        diagnostics["cache_dir_exists"] = True
    except (FileNotFoundError, PermissionError, OSError):
        diagnostics["cache_dir_exists"] = False

    # Read recent log entries - try multiple locations
    logs_found = False
    log_locations = [
        "/var/log/minidlna.log",
        "/var/log/minidlna/minidlna.log",
    ]

    for log_path in log_locations:
        try:
            result = subprocess.run(["sudo", "tail", "-30", log_path],
                                  capture_output=True, text=True, timeout=5)
            if result.stdout and result.stdout.strip():
                diagnostics["recent_logs"] = result.stdout.split("\n")[-15:]
                diagnostics["log_file_location"] = log_path
                logs_found = True
                break
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass

    if not logs_found:
        # Try systemd journal
        try:
            result = subprocess.run(["sudo", "journalctl", "-u", "minidlna", "-n", "20", "--no-pager"],
                                  capture_output=True, text=True, timeout=5)
            if result.stdout and result.stdout.strip():
                diagnostics["recent_logs"] = result.stdout.split("\n")[-15:]
                diagnostics["log_file_location"] = "systemd journal"
            else:
                diagnostics["recent_logs"] = ["No logs found in any location"]
                diagnostics["log_file_location"] = "none"
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            diagnostics["recent_logs"] = ["Could not read logs"]
            diagnostics["log_file_location"] = "error"

    # Check database file
    try:
        db_file = os.path.join(db_dir, "files.db")
        db_exists = os.path.exists(db_file)
        diagnostics["database_exists"] = db_exists
        diagnostics["database_path"] = db_file
        if db_exists:
            db_size = os.path.getsize(db_file)
            diagnostics["database_size_mb"] = round(db_size / 1024 / 1024, 2)
    except (FileNotFoundError, PermissionError, OSError):
        diagnostics["database_exists"] = False
        diagnostics["database_size_mb"] = 0

    return diagnostics

@router.post("/dlna/restart")
def restart_dlna(user_id: int = Depends(get_current_user_id)):
    """Restart DLNA server and rebuild database"""
    if platform.system() != "Linux":
        raise HTTPException(status_code=400, detail="DLNA only available on Linux")

    try:
        db_dir = "/var/cache/minidlna"
        log_dir = "/var/log/minidlna"
        try:
            with open("/etc/minidlna.conf", "r") as f:
                config = f.read()
                lines = config.split("\n")
                parsed_db_dirs = [line.split("=", 1)[1].strip() for line in lines if line.startswith("db_dir=")]
                parsed_log_dirs = [line.split("=", 1)[1].strip() for line in lines if line.startswith("log_dir=")]
                if parsed_db_dirs and parsed_db_dirs[0]:
                    db_dir = parsed_db_dirs[0]
                if parsed_log_dirs and parsed_log_dirs[0]:
                    log_dir = parsed_log_dirs[0]
        except Exception:
            pass

        # Stop service
        subprocess.run(["sudo", "systemctl", "stop", "minidlna"], check=False)

        # Clear database
        subprocess.run(["sudo", "rm", "-f", os.path.join(db_dir, "files.db")], check=False)

        # Recreate cache directory with proper permissions
        subprocess.run(["sudo", "mkdir", "-p", db_dir], check=False)
        subprocess.run(["sudo", "chown", "-R", "minidlna:minidlna", db_dir], check=False)
        subprocess.run(["sudo", "mkdir", "-p", log_dir], check=False)
        subprocess.run(["sudo", "chown", "-R", "minidlna:minidlna", log_dir], check=False)

        # Start service
        subprocess.run(["sudo", "systemctl", "start", "minidlna"], check=True)

        # MiniDLNA will automatically scan on startup when database is missing

        return {"status": "ok", "message": "DLNA database cleared and rebuilding. Wait 2-3 minutes then check your TV."}
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
        except (FileNotFoundError, PermissionError, OSError):
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
        except (FileNotFoundError, PermissionError, OSError):
            info["os_name"] = "Linux"
            info["os_version"] = "Unknown"
        
        # Get kernel version
        try:
            info["kernel"] = subprocess.check_output(["uname", "-r"], text=True).strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            info["kernel"] = platform.release()
        
        # Get uptime
        try:
            with open("/proc/uptime", "r") as f:
                uptime_seconds = float(f.read().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                info["uptime_formatted"] = f"{days}d {hours}h {minutes}m"
        except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
            info["uptime_formatted"] = "Unknown"
        
        # Get memory info
        try:
            mem = psutil.virtual_memory()
            info["memory_total_gb"] = round(mem.total / (1024**3), 2)
            info["memory_available_gb"] = round(mem.available / (1024**3), 2)
        except (AttributeError, OSError):
            pass
        
        # Get CPU info
        try:
            info["cpu_count"] = psutil.cpu_count(logical=False)
            info["cpu_count_logical"] = psutil.cpu_count(logical=True)
        except (AttributeError, OSError):
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
        except (subprocess.SubprocessError, FileNotFoundError, OSError, IndexError, ValueError):
            pass
    
    return info

@router.get("/diagnostics")
def get_system_diagnostics(user_id: int = Depends(get_current_user_id)):
    """Check system for missing dependencies and common issues"""
    diagnostics = {
        "status": "healthy",
        "issues": [],
        "warnings": [],
        "dependencies": {}
    }

    # Check for comic book extraction tools
    comic_tools = {
        "7z": shutil.which("7z") or shutil.which("7zz") or shutil.which("7zr"),
        "unar": shutil.which("unar"),
        "bsdtar": shutil.which("bsdtar")
    }

    comic_tools_available = any(comic_tools.values())
    diagnostics["dependencies"]["comic_extraction"] = {
        "status": "ok" if comic_tools_available else "missing",
        "tools_found": [tool for tool, path in comic_tools.items() if path],
        "description": "Required for CBR/RAR comic book files"
    }

    if not comic_tools_available:
        diagnostics["issues"].append({
            "severity": "error",
            "component": "Comic Book Viewer",
            "message": "CBR/RAR extraction tools not installed",
            "fix": "Run: sudo apt-get update && sudo apt-get install -y p7zip-full unar libarchive-tools",
            "impact": "Cannot read .cbr comic book files (CBZ files still work)"
        })
        diagnostics["status"] = "issues_found"

    # Check for MiniDLNA
    minidlna_installed = shutil.which("minidlnad") is not None
    diagnostics["dependencies"]["minidlna"] = {
        "status": "ok" if minidlna_installed else "missing",
        "description": "DLNA media server for smart TVs"
    }

    if not minidlna_installed:
        diagnostics["warnings"].append({
            "severity": "warning",
            "component": "MiniDLNA",
            "message": "MiniDLNA not installed",
            "fix": "Run: sudo apt-get install -y minidlna",
            "impact": "Cannot stream media to smart TVs via DLNA"
        })

    # Check sudoers file
    sudoers_exists = os.path.exists("/etc/sudoers.d/nomad-pi")
    diagnostics["dependencies"]["sudo_permissions"] = {
        "status": "ok" if sudoers_exists else "missing",
        "description": "Passwordless sudo for system operations"
    }

    if not sudoers_exists:
        diagnostics["warnings"].append({
            "severity": "warning",
            "component": "System Permissions",
            "message": "Sudoers file not found",
            "fix": "Re-run setup.sh or update.sh to restore permissions",
            "impact": "Some admin features may require manual password entry"
        })

    # Check for available disk space
    try:
        disk = psutil.disk_usage("/")
        free_gb = disk.free / (1024**3)
        diagnostics["storage"] = {
            "free_gb": round(free_gb, 2),
            "percent_used": disk.percent
        }

        if free_gb < 1:
            diagnostics["issues"].append({
                "severity": "critical",
                "component": "Disk Space",
                "message": f"Very low disk space: {free_gb:.2f} GB remaining",
                "fix": "Delete unused media files or expand storage",
                "impact": "May cause system instability or prevent new uploads"
            })
            diagnostics["status"] = "critical"
        elif free_gb < 5:
            diagnostics["warnings"].append({
                "severity": "warning",
                "component": "Disk Space",
                "message": f"Low disk space: {free_gb:.2f} GB remaining",
                "fix": "Consider cleaning up media files",
                "impact": "Limited space for new media"
            })
    except (PermissionError, OSError):
        pass

    # Check memory usage
    try:
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            diagnostics["warnings"].append({
                "severity": "warning",
                "component": "Memory",
                "message": f"High memory usage: {mem.percent}%",
                "fix": "Consider restarting the system",
                "impact": "May cause slow performance"
            })
    except (AttributeError, OSError):
        pass

    return diagnostics

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
