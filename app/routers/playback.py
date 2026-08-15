"""Compatibility facade for the Nomad 2.x playback routers."""

import sys

from app.routers import playback_core as _core
from app.routers.playback_tracks import router as _tracks_router
from app.routers.playback_quality import router as _quality_router

_core.router.include_router(_tracks_router)
_core.router.include_router(_quality_router)

# Preserve imports such as ``from app.routers import playback`` while keeping
# the main playback implementation and optional controls modular.
sys.modules[__name__] = _core
