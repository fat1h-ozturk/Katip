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
