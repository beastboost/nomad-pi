#!/usr/bin/env python3
"""Build the native Nomad Android APK with minimal manual setup.

Usage:
    python android/build_apk.py

The script prefers an existing Android SDK and Gradle installation. If either is
missing it bootstraps a private toolchain under ``.android-toolchain`` by using
the official Google Android repository and the official Gradle distribution.
It then runs the JVM tests and assembles the debug APK, copying the result to
``dist/Nomad-Android-debug.apk``.

A working internet connection is required on the first run because Android
Gradle Plugin, AndroidX/Compose/Media3 and the Android SDK are external build
dependencies. Subsequent runs can reuse Gradle/SDK caches.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

GRADLE_VERSION = "8.13"
COMPILE_SDK = "36"
BUILD_TOOLS = "36.0.0"

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
TOOLS = ROOT / ".android-toolchain"
SDK = TOOLS / "sdk"
GRADLE_HOME = TOOLS / f"gradle-{GRADLE_VERSION}"
DIST = ROOT / "dist"


def log(message: str) -> None:
    print(f"[nomad-android] {message}", flush=True)


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, input_text: str | None = None) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        env=env,
        input=input_text,
        text=True,
        check=True,
    )


def download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        log(f"Using cached {target.name}")
        return target
    log(f"Downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "NomadPi-Android-Builder/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    return target


def extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(destination)


def host_os() -> str:
    value = platform.system().lower()
    if value == "linux":
        return "linux"
    if value == "darwin":
        return "macosx"
    if value == "windows":
        return "windows"
    raise RuntimeError(f"Unsupported host OS: {platform.system()}")


def xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(node: ET.Element, name: str) -> str | None:
    for child in node.iter():
        if xml_local(child.tag) == name and child.text:
            return child.text.strip()
    return None


def revision_tuple(remote: ET.Element) -> tuple[int, int, int]:
    revision = next((n for n in remote if xml_local(n.tag) == "revision"), None)
    if revision is None:
        return (0, 0, 0)
    values = {}
    for child in revision:
        try:
            values[xml_local(child.tag)] = int((child.text or "0").strip())
        except ValueError:
            values[xml_local(child.tag)] = 0
    return values.get("major", 0), values.get("minor", 0), values.get("micro", 0)


def latest_cmdline_tools_url() -> str:
    # repository2-1.xml is Google's machine-readable Android SDK package index.
    index_url = "https://dl.google.com/android/repository/repository2-1.xml"
    log("Finding the latest Android command-line tools")
    request = urllib.request.Request(index_url, headers={"User-Agent": "NomadPi-Android-Builder/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        root = ET.fromstring(response.read())

    wanted_os = host_os()
    choices: list[tuple[tuple[int, int, int], str]] = []
    for remote in root.iter():
        if xml_local(remote.tag) != "remotePackage":
            continue
        package_path = remote.attrib.get("path", "")
        if not package_path.startswith("cmdline-tools;") or "preview" in package_path.lower():
            continue
        revision = revision_tuple(remote)
        for archive in remote.iter():
            if xml_local(archive.tag) != "archive":
                continue
            archive_os = child_text(archive, "host-os")
            url = child_text(archive, "url")
            if archive_os == wanted_os and url:
                choices.append((revision, "https://dl.google.com/android/repository/" + url))
    if not choices:
        raise RuntimeError(f"Could not locate Android command-line tools for {wanted_os}")
    choices.sort(reverse=True)
    return choices[0][1]


def find_existing_sdk() -> Path | None:
    candidates = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(Path.home() / "Android" / "Sdk"),
        str(Path.home() / "Library" / "Android" / "sdk"),
    ]
    for value in candidates:
        if value:
            path = Path(value).expanduser()
            if path.is_dir():
                return path
    return None


def sdkmanager_path(sdk: Path) -> Path | None:
    names = ["sdkmanager.bat", "sdkmanager"] if os.name == "nt" else ["sdkmanager", "sdkmanager.bat"]
    for name in names:
        candidates = list((sdk / "cmdline-tools").glob(f"*/bin/{name}")) if (sdk / "cmdline-tools").exists() else []
        candidates += [sdk / "tools" / "bin" / name]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def bootstrap_sdk() -> Path:
    existing = find_existing_sdk()
    if existing and sdkmanager_path(existing):
        log(f"Using Android SDK: {existing}")
        return existing

    SDK.mkdir(parents=True, exist_ok=True)
    manager = sdkmanager_path(SDK)
    if manager is None:
        url = latest_cmdline_tools_url()
        archive = download(url, TOOLS / "downloads" / "commandlinetools.zip")
        stage = TOOLS / "cmdline-tools-stage"
        shutil.rmtree(stage, ignore_errors=True)
        extract_zip(archive, stage)
        source = stage / "cmdline-tools"
        if not source.is_dir():
            children = [p for p in stage.iterdir() if p.is_dir()]
            if len(children) != 1:
                raise RuntimeError("Unexpected Android command-line tools archive layout")
            source = children[0]
        latest = SDK / "cmdline-tools" / "latest"
        shutil.rmtree(latest, ignore_errors=True)
        latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(latest))
        shutil.rmtree(stage, ignore_errors=True)
        manager = sdkmanager_path(SDK)
    if manager is None:
        raise RuntimeError("sdkmanager was not installed correctly")

    if os.name != "nt":
        manager.chmod(manager.stat().st_mode | stat.S_IXUSR)
    return SDK


def install_sdk_packages(sdk: Path, env: dict[str, str]) -> None:
    manager = sdkmanager_path(sdk)
    if manager is None:
        raise RuntimeError("sdkmanager not found")
    manager_cmd = [str(manager), f"--sdk_root={sdk}"]
    # License acceptance is idempotent. A large block of 'y' handles all SDK licenses.
    try:
        run(manager_cmd + ["--licenses"], env=env, input_text="y\n" * 80)
    except subprocess.CalledProcessError:
        log("License command returned non-zero; continuing to package installation")
    run(
        manager_cmd
        + [
            f"platforms;android-{COMPILE_SDK}",
            f"build-tools;{BUILD_TOOLS}",
            "platform-tools",
        ],
        env=env,
    )


def find_gradle() -> Path | None:
    wrapper = ANDROID / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if wrapper.exists():
        return wrapper
    system = shutil.which("gradle")
    if system:
        return Path(system)
    binary = GRADLE_HOME / "bin" / ("gradle.bat" if os.name == "nt" else "gradle")
    if binary.exists():
        return binary
    return None


def bootstrap_gradle() -> Path:
    found = find_gradle()
    if found:
        log(f"Using Gradle: {found}")
        return found
    archive = download(
        f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip",
        TOOLS / "downloads" / f"gradle-{GRADLE_VERSION}-bin.zip",
    )
    extract_zip(archive, TOOLS)
    found = find_gradle()
    if found is None:
        raise RuntimeError("Gradle bootstrap failed")
    if os.name != "nt":
        found.chmod(found.stat().st_mode | stat.S_IXUSR)
    return found


def java_major() -> int:
    java = shutil.which("java")
    if not java:
        raise RuntimeError("Java is not installed. JDK 17 or newer is required.")
    proc = subprocess.run([java, "-version"], capture_output=True, text=True)
    line = (proc.stderr or proc.stdout).splitlines()[0]
    quoted = line.split('"')[1]
    major = int(quoted.split(".")[0])
    return major


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Nomad's native Android debug APK")
    parser.add_argument("--skip-tests", action="store_true", help="Assemble without running JVM unit tests")
    parser.add_argument("--no-bootstrap", action="store_true", help="Require Android SDK and Gradle to already exist")
    args = parser.parse_args()

    if java_major() < 17:
        raise RuntimeError("JDK 17 or newer is required")

    sdk = find_existing_sdk() if args.no_bootstrap else bootstrap_sdk()
    if sdk is None:
        raise RuntimeError("Android SDK not found; remove --no-bootstrap to install a private SDK")

    env = os.environ.copy()
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["ANDROID_HOME"] = str(sdk)
    env.setdefault("GRADLE_USER_HOME", str(TOOLS / "gradle-cache"))

    if not args.no_bootstrap:
        install_sdk_packages(sdk, env)

    gradle = find_gradle() if args.no_bootstrap else bootstrap_gradle()
    if gradle is None:
        raise RuntimeError("Gradle not found; remove --no-bootstrap to bootstrap Gradle")

    # Keep the native-only contract enforced outside CI too.
    forbidden = ("android.webkit.WebView", "TrustedWebActivity", "androidx.browser.trusted")
    offenders = []
    source_root = ANDROID / "app" / "src"
    for path in source_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".kt", ".java", ".xml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(term in text for term in forbidden):
            offenders.append(path.relative_to(ROOT))
    if offenders:
        raise RuntimeError("Native-only guard failed: " + ", ".join(map(str, offenders)))

    tasks = [":app:assembleDebug"] if args.skip_tests else [":app:testDebugUnitTest", ":app:assembleDebug"]
    run([str(gradle), "-p", str(ANDROID), *tasks, "--stacktrace"], env=env)

    apk = ANDROID / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise RuntimeError(f"Gradle completed but APK was not found at {apk}")
    DIST.mkdir(parents=True, exist_ok=True)
    output = DIST / "Nomad-Android-debug.apk"
    shutil.copy2(apk, output)
    log(f"APK ready: {output}")
    log(f"SHA-256: {sha256(output)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"[nomad-android] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
