from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication
from katip import __version__
from katip.app import KatipApp
from katip.ui.toast import UpdateNotificationToast

_app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize('tag,expected', [('v99.0.0', True), (f'v{__version__}', False),
    ('v0.3.9', False), (f'v{__version__}-rc99', False), ('malformed', False)])
def test_update_checker_worker_emits_only_for_newer_stable_release(monkeypatch, tag, expected):
    url = 'https://github.com/fat1h-ozturk/Katip/releases/tag/v99.0.0'
    response = Mock(status_code=200, json=lambda: {'tag_name': tag, 'html_url': url})
    get = Mock(return_value=response)
    monkeypatch.setattr('requests.get', get)
    app = object.__new__(KatipApp)
    app.signals = SimpleNamespace(update_available=Mock())
    app._update_checker_worker()
    get.assert_called_once()
    assert app.signals.update_available.emit.called is expected
    if expected:
        app.signals.update_available.emit.assert_called_once_with(tag, url)


def test_open_url_handles_clean_env(monkeypatch):
    import sys
    from katip.desktop import open_url

    called_cmd = []
    def mock_popen(cmd, env=None, **kwargs):
        called_cmd.append((cmd, env.get("LD_LIBRARY_PATH") if env else None))
        mock_proc = Mock()
        return mock_proc

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/" + cmd)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI12345")

    res = open_url("https://github.com/fat1h-ozturk/Katip/releases/latest")
    assert res is True
    assert len(called_cmd) > 0
    # LD_LIBRARY_PATH must NOT be /tmp/_MEI12345
    assert called_cmd[0][1] is None


def test_toast_download_triggers_open_url(monkeypatch):
    urls_opened = []
    monkeypatch.setattr("katip.ui.toast.open_url", lambda url: urls_opened.append(url))

    toast = UpdateNotificationToast("v0.4.2", "https://github.com/fat1h-ozturk/Katip/releases/tag/v0.4.2")
    toast._on_download_clicked()
    assert urls_opened == ["https://github.com/fat1h-ozturk/Katip/releases/tag/v0.4.2"]
