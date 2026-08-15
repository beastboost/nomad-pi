from pathlib import Path


def test_dockerfile_contains_nomad2_media_runtime_dependencies():
    text = Path("Dockerfile").read_text()
    assert "ffmpeg" in text
    assert "NOMAD_RUNTIME_MODE=server" in text
    assert "NOMAD_HW_ACCEL=off" in text


def test_compose_declares_server_mode_and_persistent_data():
    text = Path("docker-compose.yml").read_text()
    assert "NOMAD_RUNTIME_MODE: server" in text
    assert "NOMAD_HW_ACCEL:" in text
    assert "NOMAD_ABR:" in text
    assert "./data:/app/data" in text


def test_docker_docs_do_not_claim_native_host_management():
    text = Path("DOCKER.md").read_text().lower()
    assert "media/server runtime" in text
    assert "networkmanager" in text
    assert "systemd" in text
    assert "native" in text
