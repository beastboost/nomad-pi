"""Refuse destructive upgrades when tracked user edits exist.

Nomad stamps two tracked frontend files with build IDs at installation time.
Treat those precise stamp-only modifications as generated, but preserve every
other tracked change instead of silently losing it to git reset --hard.
"""

from pathlib import Path
import re
import subprocess
import sys

GENERATED = {
    "app/static/index.html": (r"\?v=[A-Za-z0-9._-]+", "?v=<build-id>"),
    "app/static/sw.js": (r"const CACHE_NAME = '[^']*'", "const CACHE_NAME = '<build-id>'"),
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def unsafe_changes(root: Path) -> list[str]:
    changed = git(root, "diff", "HEAD", "--name-only", "-z").decode().split("\0")
    unsafe = []
    for name in filter(None, changed):
        spec = GENERATED.get(name)
        file_path = root / name
        if not spec or not file_path.is_file():
            unsafe.append(name)
            continue
        try:
            original = git(root, "show", f"HEAD:{name}").decode("utf-8")
            current = file_path.read_text(encoding="utf-8")
        except (UnicodeError, OSError, subprocess.CalledProcessError):
            unsafe.append(name)
            continue
        pattern, replacement = spec
        if re.sub(pattern, replacement, original) != re.sub(pattern, replacement, current):
            unsafe.append(name)
    return unsafe


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        bad = unsafe_changes(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Update preflight failed: {exc}", file=sys.stderr)
        return 2
    if bad:
        print("Update blocked: local tracked modifications would be overwritten:", file=sys.stderr)
        for name in bad:
            print(f"  {name}", file=sys.stderr)
        print("Commit/stash those changes, or restore the files, then retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
