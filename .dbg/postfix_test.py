import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
out = {}

out["login"] = client.post("/api/auth/login", json={"username": "admin", "password": "nomad"}).json()
client.post("/api/debrid/provider", json={"provider": "rd"})

resp = client.get("/api/debrid/torrent/28265271")
out["stale_1_status"] = resp.status_code
out["stale_1"] = resp.json()

resp = client.get("/api/debrid/torrent/28265102")
out["stale_2_status"] = resp.status_code
out["stale_2"] = resp.json()

resp = client.post("/api/debrid/magnet", json={"info_hash": "4e8919ffc99ad81bd7ad10164c8e2898efcfaff3"})
out["blocked_status"] = resp.status_code
out["blocked"] = resp.json()

Path(r"c:\Users\conne\nomad-pi\.dbg\testclient-results.json").write_text(
    json.dumps(out, indent=2),
    encoding="utf-8",
)
