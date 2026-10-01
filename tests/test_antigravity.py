import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from katip.services.antigravity import AntigravityService, _find_agy_binary


def test_find_agy_binary_in_path():
    with patch("katip.services.antigravity.shutil.which", return_value="/custom/bin/agy"):
        assert _find_agy_binary() == "/custom/bin/agy"


def test_find_agy_binary_fallback_local_bin(tmp_path):
    fake_agy = tmp_path / "agy"
    fake_agy.write_text("#!/bin/sh\nexit 0")
    fake_agy.chmod(0o755)

    with patch("katip.services.antigravity.shutil.which", return_value=None), \
         patch("katip.services.antigravity.os.path.expanduser", return_value=str(fake_agy)):
        assert _find_agy_binary() == str(fake_agy)


def test_find_agy_binary_not_found():
    with patch("katip.services.antigravity.shutil.which", return_value=None), \
         patch("katip.services.antigravity.os.path.isfile", return_value=False):
        assert _find_agy_binary() == "agy"


@pytest.mark.parametrize("failure", [None, "fenced", "malformed", "empty_text", "empty_output", "timeout", "not_found", "error_code"])
def test_antigravity_transcribe_and_format(failure):
    answer = json.dumps({"text": "Türkçe: test metni."}, ensure_ascii=False)
    if failure == "fenced":
        answer = f"```json\n{answer}\n```"
    elif failure == "malformed":
        answer = "Düz metin cevabı"
    elif failure == "empty_text":
        answer = '{"text": "   "}'
    elif failure == "empty_output":
        answer = ""

    with patch("katip.services.antigravity.requests.post", return_value=MagicMock(status_code=200, text="Ham transkript")):
        if failure == "not_found":
            with patch("katip.services.antigravity.subprocess.run", side_effect=FileNotFoundError()):
                result = AntigravityService("groq", "secret", "whisper", "pro").transcribe_and_format(b"fake")
            assert result.formatted_text is None
            assert "bulunamadı" in result.warning
        elif failure == "timeout":
            with patch("katip.services.antigravity.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="agy", timeout=60)):
                result = AntigravityService("groq", "secret", "whisper", "pro").transcribe_and_format(b"fake")
            assert result.formatted_text is None
            assert "Zaman aşımı" in result.warning
        elif failure == "error_code":
            with patch("katip.services.antigravity.subprocess.run", return_value=MagicMock(returncode=1, stderr="Model unavailable")):
                result = AntigravityService("groq", "secret", "whisper", "pro").transcribe_and_format(b"fake")
            assert result.formatted_text is None
            assert "Model unavailable" in result.warning
        else:
            with patch("katip.services.antigravity.subprocess.run", return_value=MagicMock(returncode=0, stdout=answer)) as mock_run:
                result = AntigravityService("groq", "secret", "whisper", "pro").transcribe_and_format(b"fake")
            cmd = mock_run.call_args.args[0]
            assert "--new-project" in cmd
            assert "--model" in cmd
            assert cmd[cmd.index("--model") + 1] == "pro"
            env = mock_run.call_args.kwargs.get("env", {})
            assert "PATH" in env
            assert os.path.expanduser("~/.local/bin") in env["PATH"].split(os.pathsep)

            if failure in (None, "fenced"):
                assert result.formatted_text == "Türkçe: test metni."
                assert result.warning == ""
            elif failure == "malformed":
                assert result.formatted_text == "Düz metin cevabı"
                assert result.warning == ""
            else:
                assert result.formatted_text is None
                assert "ayrıştırılamadı" in result.warning
