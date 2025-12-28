from fastapi import APIRouter, HTTPException
import psutil
import os
import subprocess
import platform
import json

router = APIRouter()

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

@router.post("/control/{action}")
def system_control(action: str):
    if action not in ["shutdown", "reboot"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    if platform.system() == "Linux":
        cmd = ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"] if action == "shutdown" else ["sudo", "-n", "/usr/sbin/reboot"]
        try:
            subprocess.Popen(cmd)
            return {"status": f"System {action} initiated"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        return {"status": f"Simulated {action} (Windows)"}
