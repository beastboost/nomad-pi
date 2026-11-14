"""Restrict legacy media routes to files intended for playback or display.

This is a file exposure boundary, not an authentication mechanism. Both the
/data static mount and /api/media/{stream,subtitle} must use this guard.
"""

from pathlib import Path

from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles

MEDIA_DIRS = frozenset({
    "movies", "shows", "music", "books", "files", "external", "uploads", "ingest",
})
CACHE_DIRS = frozenset({
    ("cache", "posters"), ("cache", "music-art"),
    (".cache", "comics"), (".nomad_cache", "ios"),
    ("media", "movies"), ("media", "shows"), ("media", "music"),
    ("media", "books"), ("media", "files"),
})
MEDIA_EXTENSIONS = frozenset({
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".wmv",
    ".flv", ".ts", ".mts", ".m2ts", ".3gp", ".3g2", ".mpg",
    ".mpeg", ".mpe", ".ogv", ".m4s", ".m3u8", ".mpd",
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".alac", ".aiff", ".aif", ".ape", ".wv", ".mid",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
    ".avif", ".heic", ".heif", ".tif", ".tiff",
    ".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx", ".lrc",
    ".pdf", ".epub", ".mobi", ".azw", ".azw3", ".cbz", ".cbr",
    ".djvu", ".djv", ".txt", ".rtf", ".fb2",
})


def _valid_segments(parts: tuple[str, ...]) -> bool:
    return bool(parts) and all(
        part not in {"", ".", ".."} and not part.startswith(".") for part in parts
    )


def is_public_media_file(path: str | Path, *, data_root: str | Path = "data") -> bool:
    """Return whether a canonical file path is in a publishable media area.

    Paths are resolved before checking to prevent traversal and symlink escapes.
    A media ticket must never open the database, token secret, or a private
    gallery file regardless of its extension.
    """
    try:
        source = Path(path).resolve()
        if source.suffix.lower() not in MEDIA_EXTENSIONS:
            return False
        root = Path(data_root).resolve()
        try:
            rel = source.relative_to(root)
        except ValueError:
            # Legacy external drives can use an absolute /media or /mnt URL.
            for external_root in (Path("/media"), Path("/mnt")):
                try:
                    rel = source.relative_to(external_root.resolve())
                except ValueError:
                    continue
                return len(rel.parts) >= 2 and _valid_segments(rel.parts)
            return False
        parts = rel.parts
        if len(parts) >= 2 and parts[0] in MEDIA_DIRS:
            return _valid_segments(parts)
        if len(parts) >= 3 and tuple(parts[:2]) in CACHE_DIRS:
            return _valid_segments(parts[2:])
        return False
    except (OSError, RuntimeError, ValueError):
        return False


class PublicMediaStaticFiles(StaticFiles):
    """Expose only media, never the complete mutable data directory."""

    async def get_response(self, path: str, scope):
        if not is_public_media_file(
            Path(self.directory) / path, data_root=self.directory
        ):
            raise HTTPException(status_code=404, detail="Media not found")
        return await super().get_response(path, scope)
