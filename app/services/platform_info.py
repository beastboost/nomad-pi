"""Platform and board detection shared by Nomad runtime services.

Nomad started on Raspberry Pi hardware but now runs on multiple Linux SBCs and
server-class machines.  Keep hardware identification in one place so playback,
health reporting and future platform-specific executors make the same decision.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os
import platform
import re
from typing import Any

import psutil


def _read_text(path: str, *, nul_to_space: bool = True) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    if nul_to_space:
        raw = raw.replace(b"\x00", b" ")
    return raw.decode("utf-8", errors="ignore").strip()


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return values


def _cpu_hardware() -> str:
    text = _read_text("/proc/cpuinfo", nul_to_space=False)
    for pattern in (r"(?im)^Hardware\s*:\s*(.+)$", r"(?im)^Model name\s*:\s*(.+)$"):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _classify(model: str, compatible: str, hardware: str) -> tuple[str, str, str]:
    combined = " ".join((model, compatible, hardware)).lower()

    if "raspberry pi" in combined or "brcm,bcm" in combined:
        return "raspberry-pi", "Raspberry Pi", "broadcom"

    # Radxa Cubie A7Z/A7A vendor kernels often expose only sun60iw2 rather than
    # the marketing board name. sun60iw2 is the kernel platform identifier for
    # the Allwinner A733 family.
    if any(token in combined for token in ("sun60iw2", "allwinner,a733", "a733", "cubie-a7", "cubie a7")):
        vendor = "Radxa" if "radxa" in combined or "cubie" in combined else "Allwinner"
        return "allwinner-a733", vendor, "allwinner-a733"

    if "rockchip" in combined or re.search(r"\brk(?:35|33|32)\d{2}\b", combined):
        return "rockchip", "Rockchip", "rockchip"

    if "amlogic" in combined or re.search(r"\bs9\d{2}\b", combined):
        return "amlogic", "Amlogic", "amlogic"

    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64", "armv7l", "armv8l"}:
        return "generic-arm", "Generic ARM", "arm"
    if machine in {"x86_64", "amd64", "i386", "i686"}:
        return "generic-x86", "Generic x86", "x86"
    return "generic-linux", "Generic Linux", machine or "unknown"


def _friendly_model(model: str, family: str) -> str:
    clean = model.strip()
    if family == "allwinner-a733":
        if clean and clean.lower() not in {"sun60iw2", "allwinner sun60iw2"}:
            return f"{clean} · Allwinner A733"
        return "Allwinner A733 (sun60iw2)"
    return clean or platform.node() or platform.machine() or "Linux device"


@lru_cache(maxsize=1)
def platform_info() -> dict[str, Any]:
    model = _read_text("/proc/device-tree/model") or _read_text("/sys/firmware/devicetree/base/model")
    compatible = _read_text("/proc/device-tree/compatible") or _read_text("/sys/firmware/devicetree/base/compatible")
    hardware = _cpu_hardware()
    family, vendor, soc_family = _classify(model, compatible, hardware)
    release = _os_release()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()

    ram_mb = round(memory.total / (1024 * 1024))
    if ram_mb < 768:
        memory_class = "tiny"
    elif ram_mb < 1536:
        memory_class = "low"
    elif ram_mb < 4096:
        memory_class = "standard"
    else:
        memory_class = "high"

    return {
        "model": _friendly_model(model, family),
        "raw_model": model,
        "compatible": compatible,
        "hardware": hardware,
        "family": family,
        "vendor": vendor,
        "soc_family": soc_family,
        "machine": platform.machine(),
        "architecture": platform.machine(),
        "kernel": platform.release(),
        "platform": platform.platform(),
        "hostname": platform.node(),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_mb": ram_mb,
        "swap_mb": round(swap.total / (1024 * 1024)),
        "memory_class": memory_class,
        "distro_id": release.get("ID", ""),
        "distro_name": release.get("PRETTY_NAME", release.get("NAME", "Linux")),
        "distro_version": release.get("VERSION_ID", ""),
        "is_raspberry_pi": family == "raspberry-pi",
        "is_allwinner_a733": family == "allwinner-a733",
        "is_arm": platform.machine().lower() in {"aarch64", "arm64", "armv7l", "armv8l"},
        "container": bool(os.path.exists("/.dockerenv") or os.environ.get("container")),
    }


def clear_platform_info_cache() -> None:
    platform_info.cache_clear()
