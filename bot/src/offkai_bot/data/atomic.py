# src/offkai_bot/data/atomic.py
import contextlib
import json
import logging
import os
import shutil
import tempfile
from datetime import UTC, datetime

_log = logging.getLogger(__name__)


def atomic_write_json(file_path: str, data: object, **json_kwargs) -> None:
    """
    Writes `data` to `file_path` as JSON atomically.

    Writes to a temp file in the same directory, flushes and fsyncs it, then
    uses os.replace() to swap it into place. os.replace() is atomic on both
    POSIX and Windows, so a crash or power loss mid-write can never leave
    `file_path` truncated or partially written.
    """
    directory = os.path.dirname(file_path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f"{os.path.basename(file_path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, **json_kwargs)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, file_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def backup_corrupted_file(file_path: str) -> None:
    """
    Preserves a data file that failed to parse before it can be silently
    overwritten by the next save.

    Without this, a load failure resets the in-memory cache to empty and the
    next save destroys the corrupted-but-possibly-recoverable file for good.
    """
    if not os.path.exists(file_path):
        return

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = f"{file_path}.corrupted-{timestamp}.bak"
    try:
        shutil.copy2(file_path, backup_path)
        _log.warning("Backed up unparseable file %s to %s before it could be overwritten.", file_path, backup_path)
    except OSError as e:
        _log.error("Could not back up unparseable file %s: %s", file_path, e)
