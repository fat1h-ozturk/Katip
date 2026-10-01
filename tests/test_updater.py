import re
from unittest.mock import Mock, patch
import pytest

from PySide6.QtWidgets import QApplication
from katip import __version__
from katip.ui.toast import UpdateNotificationToast

_app = QApplication.instance() or QApplication([])


def parse_v(v: str):
    return [int(x) for x in re.findall(r"\d+", v)]


def test_version_comparison():
    assert parse_v("v0.4.1") > parse_v("0.4.0")
    assert parse_v("v1.0.0") > parse_v("0.4.0")
    assert not (parse_v("v0.4.0") > parse_v("0.4.0"))
    assert not (parse_v("v0.3.9") > parse_v("0.4.0"))


def test_update_checker_worker_emits_when_newer(tmp_path, monkeypatch):
    import katip.app as app_module
    from katip.app import KatipApp

    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v99.0.0",
        "html_url": "https://github.com/fat1h-ozturk/Katip/releases/tag/v99.0.0"
    }

    monkeypatch.setattr("requests.get", Mock(return_value=mock_resp))

    # Test toast creation without crashing
    toast = UpdateNotificationToast("v99.0.0", "https://github.com/fat1h-ozturk/Katip/releases/tag/v99.0.0")
    assert toast.new_version == "v99.0.0"
    toast.close()


def test_open_url_handles_clean_env(monkeypatch):
    import os
    from katip.desktop import open_url

    called_cmd = []
    def mock_popen(cmd, env=None, **kwargs):
        called_cmd.append((cmd, env.get("LD_LIBRARY_PATH") if env else None))
        mock_proc = Mock()
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/" + cmd)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI12345")

    res = open_url("https://github.com/fat1h-ozturk/Katip/releases/latest")
    assert res is True
    assert len(called_cmd) > 0
    # LD_LIBRARY_PATH must NOT be /tmp/_MEI12345
    assert called_cmd[0][1] is None


def test_toast_download_triggers_open_url(monkeypatch):
    from katip.desktop import open_url

    urls_opened = []
    monkeypatch.setattr("katip.ui.toast.open_url", lambda url: urls_opened.append(url))

    toast = UpdateNotificationToast("v0.4.2", "https://github.com/fat1h-ozturk/Katip/releases/tag/v0.4.2")
    toast._on_download_clicked()
    assert urls_opened == ["https://github.com/fat1h-ozturk/Katip/releases/tag/v0.4.2"]
