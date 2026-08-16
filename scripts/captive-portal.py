#!/usr/bin/env python3
"""Tiny HTTP captive-portal responder for the Nomad hotspot.

The real Nomad UI stays on port 8000. This process only owns port 80 so:
  * OS captive-network probes are redirected to the stable hotspot address.
  * http://nomad.local (without :8000) lands on the real UI.
  * there is no nginx/apache process or extra application worker on tiny SBCs.

DNS interception is deliberately limited to known captive-check hostnames by
NetworkManager's shared dnsmasq configuration. Normal internet DNS therefore
continues to work if the hotspot happens to have an upstream connection.
"""

from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import os
import re
import sys


BIND_HOST = os.environ.get("NOMAD_CAPTIVE_BIND", "0.0.0.0")
BIND_PORT = int(os.environ.get("NOMAD_CAPTIVE_PORT", "80"))
HOTSPOT_IP = os.environ.get("NOMAD_HOTSPOT_IP", "10.42.0.1")
NOMAD_PORT = int(os.environ.get("NOMAD_WEB_PORT", "8000"))

CAPTIVE_HOSTS = {
    "captive.apple.com",
    "connectivitycheck.gstatic.com",
    "connectivitycheck.android.com",
    "clients3.google.com",
    "www.msftconnecttest.com",
    "www.msftncsi.com",
    "detectportal.firefox.com",
}

CAPTIVE_PATHS = {
    "/hotspot-detect.html",
    "/generate_204",
    "/gen_204",
    "/connecttest.txt",
    "/ncsi.txt",
    "/canonical.html",
    "/success.txt",
}

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")


def _clean_host(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    # IPv6 Host headers use [addr]:port. Preserve the address but never copy
    # arbitrary Host text into a Location header.
    if raw.startswith("["):
        end = raw.find("]")
        if end > 0:
            candidate = raw[1:end]
            try:
                ipaddress.IPv6Address(candidate)
                return f"[{candidate}]"
            except ValueError:
                return ""
    candidate = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
    if _HOST_RE.fullmatch(candidate):
        return candidate.lower()
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        return ""


def _is_captive_probe(host: str, path: str) -> bool:
    plain = host.strip("[]").lower()
    return plain in CAPTIVE_HOSTS or path.split("?", 1)[0] in CAPTIVE_PATHS


def _ui_url(host: str) -> str:
    plain = host.strip("[]").lower()
    # Captive assistants should never depend on mDNS. Use the hotspot gateway
    # directly, while normal LAN visits retain the hostname/IP the user typed.
    if not host or plain in CAPTIVE_HOSTS or plain == HOTSPOT_IP:
        return f"http://{HOTSPOT_IP}:{NOMAD_PORT}/"
    return f"http://{host}:{NOMAD_PORT}/"


def _portal_page(target: str) -> bytes:
    safe = escape(target, quote=True)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="refresh" content="1;url={safe}">
<title>Nomad</title>
<style>
html,body{{height:100%;margin:0}}body{{display:grid;place-items:center;background:#161826;color:#e9e9ed;font:15px system-ui,-apple-system,sans-serif}}
main{{width:min(88vw,360px);padding:28px;border:1px solid rgba(233,233,237,.14);border-radius:18px;background:#232532;text-align:center;box-shadow:0 18px 50px rgba(0,0,0,.32)}}
h1{{margin:0 0 8px;font-size:27px;font-weight:650}}p{{margin:0 0 20px;color:rgba(233,233,237,.65);line-height:1.5}}a{{display:block;padding:13px 16px;border-radius:12px;background:#9184d9;color:#101120;text-decoration:none;font-weight:700}}
small{{display:block;margin-top:14px;color:rgba(233,233,237,.42)}}
</style></head><body><main>
<h1>Nomad</h1><p>Connected to the Nomad hotspot. Opening your media server…</p>
<a href="{safe}">Open Nomad</a><small>Hotspot gateway {escape(HOTSPOT_IP)}</small>
</main><script>setTimeout(()=>location.replace({target!r}),350)</script></body></html>""".encode("utf-8")


class NomadPortalHandler(BaseHTTPRequestHandler):
    server_version = "NomadPortal/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        # Keep journal noise low; captive checks can happen repeatedly while a
        # phone screen is on. Only errors are useful on an appliance.
        if args and str(args[1]).startswith("5"):
            super().log_message(fmt, *args)

    def _host(self) -> str:
        return _clean_host(self.headers.get("Host"))

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _portal(self, target: str, *, body: bool = True) -> None:
        payload = _portal_page(target)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if body:
            self.wfile.write(payload)

    def _handle(self, *, body: bool) -> None:
        host = self._host()
        path = self.path or "/"
        target = _ui_url(host)

        if _is_captive_probe(host, path):
            # Redirect probes to our HTTP-only landing page. Returning the
            # vendor's expected 204/success text would tell the OS there is no
            # captive portal and suppress the automatic mini-browser.
            self._redirect(f"http://{HOTSPOT_IP}/portal")
            return

        if path.split("?", 1)[0] == "/portal" or host.strip("[]") == HOTSPOT_IP:
            self._portal(target, body=body)
            return

        # Convenience path for normal LAN users: http://nomad.local becomes the
        # actual app at http://nomad.local:8000 without a second web stack.
        self._redirect(target)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle(body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle(body=False)


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def main() -> int:
    try:
        server = ReusableHTTPServer((BIND_HOST, BIND_PORT), NomadPortalHandler)
    except OSError as exc:
        print(f"nomad-captive-portal: cannot bind {BIND_HOST}:{BIND_PORT}: {exc}", file=sys.stderr)
        return 1
    print(f"nomad-captive-portal: listening on {BIND_HOST}:{BIND_PORT} -> Nomad :{NOMAD_PORT}")
    try:
        server.serve_forever(poll_interval=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
