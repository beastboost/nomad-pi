import errno
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.playback import appliance_runtime


def test_storage_eio_is_a_hard_storage_failure():
    exc = OSError(errno.EIO, "Input/output error")
    assert appliance_runtime.is_storage_error(exc) is True
    detail = appliance_runtime.storage_error_detail("/media/ssd/movie.mp4", exc)
    assert "Storage unavailable" in detail
    assert "Input/output error" in detail


def test_tiny_and_lite_memory_classes(monkeypatch):
    monkeypatch.setattr(
        appliance_runtime.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=512 * 1024 ** 2),
    )
    assert appliance_runtime.appliance_memory_class() == "tiny"

    monkeypatch.setattr(
        appliance_runtime.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1024 * 1024 ** 2),
    )
    assert appliance_runtime.appliance_memory_class() == "lite"

    monkeypatch.setattr(
        appliance_runtime.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=4 * 1024 ** 3),
    )
    assert appliance_runtime.appliance_memory_class() == "normal"


def test_missing_source_is_404(tmp_path):
    with pytest.raises(HTTPException) as raised:
        appliance_runtime.assert_source_readable(str(tmp_path / "missing.mp4"))
    assert raised.value.status_code == 404


def test_regular_source_is_readable(tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"nomad")
    assert appliance_runtime.assert_source_readable(str(source)) == 5
