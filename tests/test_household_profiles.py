import json
import sqlite3

from app.services.household_profiles import HouseholdProfileStore, token_fingerprint


def seed_legacy_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                name TEXT,
                avatar TEXT,
                preferences TEXT,
                parental_controls INTEGER DEFAULT 0
            );
            """
        )
        conn.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (1,'owner','x',1)")
        conn.execute(
            "INSERT INTO profiles(id,user_id,name,preferences,parental_controls) VALUES (7,1,'Owner',?,?)",
            (json.dumps({"theme": "dark"}), json.dumps({"enabled": False})),
        )
        conn.commit()
    finally:
        conn.close()


def test_legacy_profile_is_mirrored_as_default(tmp_path):
    db = tmp_path / "nomad.db"
    seed_legacy_db(db)
    store = HouseholdProfileStore(str(db))

    profiles = store.list(1)
    assert len(profiles) == 1
    assert profiles[0].id == 7
    assert profiles[0].name == "Owner"
    assert profiles[0].is_default is True
    assert profiles[0].preferences["theme"] == "dark"


def test_multiple_profiles_pin_and_per_session_binding(tmp_path):
    db = tmp_path / "nomad.db"
    seed_legacy_db(db)
    store = HouseholdProfileStore(str(db))

    child = store.create(
        user_id=1,
        name="Kids",
        parental_controls={"enabled": True, "max_age": 12, "allow_debrid": False},
    )
    adult = store.default(1)
    assert {p.name for p in store.list(1)} == {"Owner", "Kids"}

    child = store.set_pin(user_id=1, profile_id=child.id, pin="1234")
    assert child.pin_required is True
    assert store.verify_pin(user_id=1, profile_id=child.id, pin="1234") is True
    assert store.verify_pin(user_id=1, profile_id=child.id, pin="9999") is False

    token_a = "session-a"
    token_b = "session-b"
    store.bind(user_id=1, token=token_a, profile_id=child.id)
    store.bind(user_id=1, token=token_b, profile_id=adult.id)

    assert store.binding(user_id=1, token=token_a).name == "Kids"
    assert store.binding(user_id=1, token=token_b).name == "Owner"
    assert token_fingerprint(token_a) != token_a

    store.unbind(user_id=1, token=token_a)
    assert store.binding(user_id=1, token=token_a) is None
    assert store.binding(user_id=1, token=token_b).id == adult.id


def test_profile_pin_validation_and_last_profile_protection(tmp_path):
    db = tmp_path / "nomad.db"
    seed_legacy_db(db)
    store = HouseholdProfileStore(str(db))
    only = store.default(1)

    try:
        store.set_pin(user_id=1, profile_id=only.id, pin="12ab")
        assert False, "non-numeric PIN should fail"
    except ValueError:
        pass

    try:
        store.delete(user_id=1, profile_id=only.id)
        assert False, "last household profile should not be deletable"
    except ValueError:
        pass
