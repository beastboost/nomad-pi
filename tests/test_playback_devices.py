from datetime import datetime, timedelta, timezone

from app.services.playback.devices import PlaybackDeviceStore


def test_devices_are_persistent_and_user_scoped(tmp_path):
    db = str(tmp_path / "devices.db")
    first = PlaybackDeviceStore(db_path=db)
    first.register(
        user_id=1,
        device_id="phone",
        name="Phone",
        kind="pwa",
        capabilities={"screen_width": 390},
        current_session_id="session-a",
    )
    first.register(user_id=2, device_id="tv", name="Other TV")

    second = PlaybackDeviceStore(db_path=db)
    devices = second.list_for_user(1)
    assert [d.device_id for d in devices] == ["phone"]
    assert devices[0].capabilities["screen_width"] == 390
    assert devices[0].current_session_id == "session-a"
    assert devices[0].to_dict()["online"] is True
    assert second.get(user_id=1, device_id="tv") is None


def test_device_touch_updates_current_session(tmp_path):
    store = PlaybackDeviceStore(db_path=str(tmp_path / "devices.db"))
    store.register(user_id=1, device_id="tablet", name="Tablet")
    assert store.touch(user_id=1, device_id="tablet", current_session_id="playing-1") is True
    assert store.get(user_id=1, device_id="tablet").current_session_id == "playing-1"
    assert store.touch(user_id=2, device_id="tablet", current_session_id="wrong") is False


def test_handoff_command_can_only_be_claimed_by_target_user_and_device(tmp_path):
    store = PlaybackDeviceStore(db_path=str(tmp_path / "commands.db"))
    store.register(user_id=1, device_id="phone", name="Phone")
    store.register(user_id=1, device_id="tv", name="TV")
    command = store.enqueue(
        user_id=1,
        target_device_id="tv",
        source_device_id="phone",
        command="handoff",
        payload={"path": "/data/movies/Test.mkv", "position": 123.4},
    )

    assert store.claim(user_id=1, target_device_id="phone") == []
    assert store.claim(user_id=2, target_device_id="tv") == []
    claimed = store.claim(user_id=1, target_device_id="tv")
    assert [item.id for item in claimed] == [command.id]
    assert claimed[0].status == "claimed"
    assert claimed[0].payload["position"] == 123.4

    # A freshly claimed command is not delivered twice.
    assert store.claim(user_id=1, target_device_id="tv") == []


def test_abandoned_claim_is_retried_after_grace_period(tmp_path):
    store = PlaybackDeviceStore(db_path=str(tmp_path / "commands.db"))
    store.register(user_id=1, device_id="tv", name="TV")
    command = store.enqueue(
        user_id=1,
        target_device_id="tv",
        command="handoff",
        payload={"path": "/data/movies/Test.mkv"},
    )
    first = store.claim(user_id=1, target_device_id="tv", retry_after_seconds=30)
    assert first and first[0].id == command.id

    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE playback_device_commands SET claimed_at=? WHERE id=?",
            (old, command.id),
        )
        conn.commit()
    finally:
        conn.close()

    retried = store.claim(user_id=1, target_device_id="tv", retry_after_seconds=30)
    assert retried and retried[0].id == command.id


def test_acknowledgement_finishes_command_and_prevents_retry(tmp_path):
    store = PlaybackDeviceStore(db_path=str(tmp_path / "commands.db"))
    store.register(user_id=1, device_id="tv", name="TV")
    command = store.enqueue(
        user_id=1,
        target_device_id="tv",
        source_device_id="phone",
        command="handoff",
        payload={"path": "/data/movies/Test.mkv"},
    )
    store.claim(user_id=1, target_device_id="tv")
    acknowledged = store.acknowledge(
        user_id=1,
        target_device_id="tv",
        command_id=command.id,
        status="completed",
        result={"session_id": "target-session"},
    )
    assert acknowledged is not None
    assert acknowledged.status == "completed"
    assert acknowledged.result["session_id"] == "target-session"
    assert acknowledged.acknowledged_at
    assert store.claim(user_id=1, target_device_id="tv", retry_after_seconds=0) == []


def test_failed_command_records_detail_for_source_device(tmp_path):
    store = PlaybackDeviceStore(db_path=str(tmp_path / "commands.db"))
    store.register(user_id=1, device_id="tv", name="TV")
    command = store.enqueue(
        user_id=1,
        target_device_id="tv",
        command="handoff",
        payload={"path": "/missing.mkv"},
    )
    failed = store.acknowledge(
        user_id=1,
        target_device_id="tv",
        command_id=command.id,
        status="failed",
        result={"detail": "media missing"},
    )
    assert failed.status == "failed"
    assert store.get_command(user_id=1, command_id=command.id).result["detail"] == "media missing"
