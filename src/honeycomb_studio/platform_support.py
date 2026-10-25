"""Platform paths and an OS-owned engine lock; no persisted cloud credentials."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


def config_directory() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "HoneycombStudio"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "honeycomb-studio"


def default_data_root() -> str:
    if os.name == "nt":
        return "C:/UET/DO_AN/honeycomb-data"
    return str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "honeycomb-studio")


def lock_engine(stream: BinaryIO):
    """The lock is released by the OS when the handle closes or the process exits."""
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
