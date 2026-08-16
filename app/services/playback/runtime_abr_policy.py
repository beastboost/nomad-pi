"""Runtime policy overlay for adaptive multi-rendition HLS.

ABR is substantially heavier than a single remux/transcode: every selected
rendition is encoded concurrently and cached.  A compiled-in encoder wrapper is
not enough reason to enable that automatically on a sub-2GiB appliance.
"""

from __future__ import annotations

import os
import threading

import psutil

from app.services.platform_info import platform_info
from app.services.playback import abr as abr_module


_INSTALLED = False
_LOCK = threading.Lock()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def install_runtime_abr_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    with _LOCK:
        if _INSTALLED:
            return

        original = abr_module.abr_available

        def guarded_abr_available(*, available_encoders=None, policy=None):
            allowed, reason, candidates = original(
                available_encoders=available_encoders,
                policy=policy,
            )
            selected_policy = str(policy or abr_module.abr_policy()).strip().lower()
            if selected_policy in {"off", "force"} or not allowed:
                return allowed, reason, candidates

            try:
                memory = int(psutil.virtual_memory().total)
            except Exception:
                memory = 0
            system = platform_info()

            # Multi-rendition encode + HLS cache + Python web server is too
            # aggressive as an automatic default on 1GiB-class SBCs.  Users
            # can explicitly opt in for testing without weakening single-stream
            # remux/transcode behaviour.
            if memory and memory < 2 * 1024 * 1024 * 1024 and not _truthy("NOMAD_ABR_LOW_MEMORY"):
                return (
                    False,
                    "Auto adaptive bitrate is disabled below 2 GiB RAM; use a single quality profile or set NOMAD_ABR_LOW_MEMORY=1 to test it",
                    candidates,
                )

            # The A733 vendor OMX backend currently accelerates one H.264 HLS
            # rendition.  ABR remains FFmpeg-only, so do not imply that the
            # validated GStreamer OMX path can drive a three-rendition ladder.
            if system.get("is_allwinner_a733") and not _truthy("NOMAD_ABR_A733"):
                return (
                    False,
                    "A733 automatic ABR is disabled while Nomad uses the vendor OMX backend for single-rendition hardware transcode; set NOMAD_ABR_A733=1 to test FFmpeg ABR",
                    candidates,
                )

            return allowed, reason, candidates

        abr_module.abr_available = guarded_abr_available
        _INSTALLED = True
