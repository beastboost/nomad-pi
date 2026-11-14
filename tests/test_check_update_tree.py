"""In-place updates must not erase user edits to tracked files."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "update_guard", Path(__file__).resolve().parents[1] / "scripts/check_update_tree.py"
)
update_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_guard)


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.DEVNULL)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app/static").mkdir(parents=True)
    (tmp_path / "app/static/index.html").write_text('<script src="/js/app.js?v=old"></script>')
    (tmp_path / "app/static/sw.js").write_text("const CACHE_NAME = 'old';\n")
    (tmp_path / "app/main.py").write_text("print('version 1')\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "add", ".")
    git(tmp_path, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial")
    return tmp_path


def test_clean_checkout(repo):
    assert update_guard.unsafe_changes(repo) == []


def test_stamp_only_files_are_allowed(repo):
    (repo / "app/static/index.html").write_text('<script src="/js/app.js?v=new-version"></script>')
    (repo / "app/static/sw.js").write_text("const CACHE_NAME = 'new-version';\n")
    assert update_guard.unsafe_changes(repo) == []


def test_unrelated_tracked_edit_is_rejected(repo):
    (repo / "app/main.py").write_text("print('my fixes')\n")
    assert update_guard.unsafe_changes(repo) == ["app/main.py"]


def test_changed_javascript_beyond_stamp_is_rejected(repo):
    (repo / "app/static/sw.js").write_text("const CACHE_NAME = 'new';\nalert('change');\n")
    assert update_guard.unsafe_changes(repo) == ["app/static/sw.js"]


def test_deleted_generated_file_is_rejected(repo):
    (repo / "app/static/index.html").unlink()
    assert update_guard.unsafe_changes(repo) == ["app/static/index.html"]
