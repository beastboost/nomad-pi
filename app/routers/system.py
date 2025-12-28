from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import psutil
import os
import subprocess
import platform
import json
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
    status_file = "/tmp/nomad-pi-update.json"
    if os.path.exists(status_file):
        try:
            # Secure validation of the status file
            st = os.stat(status_file)
            # Check ownership (should be same as running user)
            if st.st_uid != os.getuid():
                return {"progress": 0, "message": "Security error: invalid file ownership"}
            # Check permissions (should not be world-writable)
            if st.st_mode & 0o002:
                return {"progress": 0, "message": "Security error: invalid file permissions"}
                
            with open(status_file, "r") as f:
                return json.load(f)
        except Exception:
            return {"progress": 0, "message": "Error reading status"}
    return {"progress": 0, "message": "No update in progress"}

@router.post("/control/{action}")
def system_control(action: str):
    if action not in ["shutdown", "reboot", "update"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    if action == "update":
        if platform.system() == "Linux":
            # Run the update script in the background
            try:
                # We use Popen so the API can return a response before the service restarts
                subprocess.Popen(["/bin/bash", "./update.sh"], cwd=os.getcwd())
                return {"status": "Update initiated. System will restart shortly."}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        else:
            return {"status": "update_simulated", "message": "Update script would run on Linux (git pull + restart)"}

    if platform.system() == "Linux":
        cmd = ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"] if action == "shutdown" else ["sudo", "-n", "/usr/sbin/reboot"]
        try:
            subprocess.Popen(cmd)
            return {"status": f"System {action} initiated"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        return {"status": f"Simulated {action} (Windows)"}
