import os
import subprocess
import sys

from honeycomb_studio.platform_support import config_directory, default_data_root, lock_engine


def test_engine_lock_excludes_another_process_and_releases_on_close(tmp_path):
    path = tmp_path / "engine.lock"
    code = (
        "import sys; from honeycomb_studio.platform_support import lock_engine; "
        "f=open(sys.argv[1],'a+b'); lock_engine(f)"
    )
    with path.open("a+b") as stream:
        lock_engine(stream)
        child = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True)
        assert child.returncode != 0
    assert subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True).returncode == 0


def test_platform_defaults_use_user_directories_on_linux(tmp_path, monkeypatch):
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert config_directory() == tmp_path / "HoneycombStudio"
        assert default_data_root() == "C:/UET/DO_AN/honeycomb-data"
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        assert config_directory() == tmp_path / "config/honeycomb-studio"
        assert default_data_root() == str(tmp_path / "data/honeycomb-studio")
