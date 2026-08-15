from app.services.watch_party import WatchPartyStore


def test_watch_party_host_join_revision_and_close(tmp_path):
    store = WatchPartyStore(str(tmp_path / "party.db"))

    party = store.create(
        user_id=1,
        host_device_id="tv",
        host_name="Living Room TV",
        path="/data/movies/Test/Test.mp4",
        state="playing",
        position=42.5,
        rate=1.0,
        quality="720p",
        adaptive=False,
        audio_track=2,
        subtitle_track=4,
        subtitle_burned=False,
    )
    assert len(party.id) == 6
    assert party.revision == 1
    assert party.position == 42.5

    joined = store.join(user_id=1, party_id=party.id, device_id="phone", name="Phone")
    assert joined.id == party.id
    members = store.members(user_id=1, party_id=party.id)
    assert {member.device_id for member in members} == {"tv", "phone"}

    updated = store.host_update(
        user_id=1,
        party_id=party.id,
        host_device_id="tv",
        state="paused",
        position=55.0,
        rate=1.0,
    )
    assert updated.revision == 2
    assert updated.state == "paused"
    assert updated.position == 55.0

    assert store.host_update(
        user_id=1,
        party_id=party.id,
        host_device_id="phone",
        state="playing",
        position=99,
        rate=1,
    ) is None

    assert store.touch_member(user_id=1, party_id=party.id, device_id="phone", revision=2)
    assert store.leave(user_id=1, party_id=party.id, device_id="phone") is True
    assert store.close(user_id=1, party_id=party.id, host_device_id="phone") is False
    assert store.close(user_id=1, party_id=party.id, host_device_id="tv") is True
    assert store.get(user_id=1, party_id=party.id) is None


def test_watch_party_is_scoped_to_account(tmp_path):
    store = WatchPartyStore(str(tmp_path / "party.db"))
    party = store.create(
        user_id=7,
        host_device_id="host",
        host_name="Host",
        path="/data/movies/Test.mp4",
        state="paused",
        position=0,
    )
    assert store.get(user_id=7, party_id=party.id) is not None
    assert store.get(user_id=8, party_id=party.id) is None
    assert store.join(user_id=8, party_id=party.id, device_id="other", name="Other") is None
