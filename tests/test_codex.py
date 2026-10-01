import json
from unittest.mock import MagicMock, patch

import pytest

from katip.services.codex import CodexService


@pytest.mark.parametrize("failure", [None, "fenced", "malformed", "empty", "wrong_type", "missing_message", "incomplete", "failed"])
@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_codex_jsonl_response_and_safe_command(failure, platform, monkeypatch):
    monkeypatch.setattr("katip.services.codex.sys.platform", platform)
    monkeypatch.setattr("katip.services.codex.subprocess.CREATE_NO_WINDOW", 0x08000000, raising=False)
    answer = json.dumps({"text": "Türkçe: ıİşğüöç."}, ensure_ascii=False)
    if failure == "fenced":
        answer = f"```json\n{answer}\n```"
    elif failure == "malformed":
        answer = "not JSON"
    elif failure == "empty":
        answer = '{"text":" "}'
    elif failure == "wrong_type":
        answer = '{"text":123}'
    events = [
        {"type": "thread.started", "thread_id": "test"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "ignore"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
        {"type": "turn.completed", "usage": {}},
    ]
    if failure == "missing_message":
        del events[2]
    elif failure == "incomplete":
        events.pop()
    elif failure == "failed":
        events[-1] = {"type": "turn.failed", "error": {"message": "private"}}
    output = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
    with patch("katip.services.codex.requests.post", return_value=MagicMock(status_code=200, text="Original transcript.")), \
         patch("katip.services.codex.subprocess.run", return_value=MagicMock(returncode=0, stdout=output)) as run:
        result = CodexService("groq", "secret", "whisper", "selected-model").transcribe_and_format(b"fake")
    cmd = run.call_args.args[0]
    assert 'sandbox_mode="read-only"' in cmd
    assert 'sandbox_mode="none"' not in cmd
    assert cmd[cmd.index("-m") + 1] == "selected-model"
    assert run.call_args.kwargs["encoding"] == "utf-8"
    assert run.call_args.kwargs["creationflags"] == (0x08000000 if platform == "win32" else 0)
    assert not run.call_args.kwargs.get("shell", False)
    if failure in (None, "fenced"):
        assert result.formatted_text == "Türkçe: ıİşğüöç."
        assert not result.warning
    else:
        assert result.formatted_text is None
        assert result.text == "Original transcript."
        assert result.warning
        assert "private" not in result.warning
