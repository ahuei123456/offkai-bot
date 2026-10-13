# tests/data/test_atomic.py
import glob
import os
from unittest.mock import patch

import pytest

from offkai_bot.data import atomic


def test_atomic_write_json_writes_data(tmp_path):
    """Data written via atomic_write_json can be read back correctly."""
    target = tmp_path / "data.json"

    atomic.atomic_write_json(str(target), {"a": 1, "b": [1, 2, 3]}, indent=4)

    assert target.exists()
    expected = '{\n    "a": 1,\n    "b": [\n        1,\n        2,\n        3\n    ]\n}'
    assert target.read_text(encoding="utf-8") == expected


def test_atomic_write_json_no_leftover_temp_files(tmp_path):
    """No .tmp files should remain in the directory after a successful write."""
    target = tmp_path / "data.json"

    atomic.atomic_write_json(str(target), {"a": 1})

    leftovers = glob.glob(str(tmp_path / "*.tmp"))
    assert leftovers == []


def test_atomic_write_json_preserves_original_on_dump_failure(tmp_path):
    """If json.dump fails mid-write, the original file must be untouched and the temp file cleaned up."""
    target = tmp_path / "data.json"
    target.write_text("original content", encoding="utf-8")

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic.atomic_write_json(str(target), {"bad": Unserializable()})

    assert target.read_text(encoding="utf-8") == "original content"
    leftovers = glob.glob(str(tmp_path / "*.tmp"))
    assert leftovers == []


def test_atomic_write_json_replaces_existing_file(tmp_path):
    """A pre-existing target file is fully replaced by the new content."""
    target = tmp_path / "data.json"
    target.write_text('{"old": true}', encoding="utf-8")

    atomic.atomic_write_json(str(target), {"new": True})

    assert target.read_text(encoding="utf-8") == '{"new": true}'


def test_backup_corrupted_file_creates_copy(tmp_path):
    """A corrupted file is copied aside before it would be overwritten."""
    target = tmp_path / "data.json"
    target.write_text("not valid json", encoding="utf-8")

    atomic.backup_corrupted_file(str(target))

    backups = glob.glob(str(tmp_path / "data.json.corrupted-*.bak"))
    assert len(backups) == 1
    with open(backups[0], encoding="utf-8") as backup_file:
        assert backup_file.read() == "not valid json"
    # Original file is left in place too.
    assert target.read_text(encoding="utf-8") == "not valid json"


def test_backup_corrupted_file_missing_file_is_noop(tmp_path):
    """Backing up a nonexistent file should do nothing and not raise."""
    target = tmp_path / "does_not_exist.json"

    atomic.backup_corrupted_file(str(target))

    assert glob.glob(str(tmp_path / "*.bak")) == []


def test_backup_corrupted_file_logs_on_os_error(tmp_path):
    """An OSError while copying is logged, not raised."""
    target = tmp_path / "data.json"
    target.write_text("not valid json", encoding="utf-8")

    with (
        patch("shutil.copy2", side_effect=OSError("disk full")),
        patch("offkai_bot.data.atomic._log") as mock_log,
    ):
        atomic.backup_corrupted_file(str(target))

    mock_log.error.assert_called_once()
    assert "Could not back up" in mock_log.error.call_args[0][0]


def test_backup_corrupted_file_uses_same_directory(tmp_path):
    """The temp file used during atomic_write_json lives in the target's directory (so os.replace stays atomic)."""
    target = tmp_path / "data.json"

    original_mkstemp = None
    captured = {}

    import tempfile as tempfile_module

    original_mkstemp = tempfile_module.mkstemp

    def spy_mkstemp(*args, **kwargs):
        result = original_mkstemp(*args, **kwargs)
        captured["dir"] = kwargs.get("dir")
        return result

    with patch("tempfile.mkstemp", side_effect=spy_mkstemp):
        atomic.atomic_write_json(str(target), {"a": 1})

    assert os.path.normpath(captured["dir"]) == os.path.normpath(str(tmp_path))
