from unittest.mock import MagicMock, patch

import pytest
import requests

from katip.services.gemini import GeminiService
from katip.services.groq import GroqService


def response(data, status=200):
    return MagicMock(status_code=status, json=lambda: data)


def test_gemini_collects_all_text_parts_except_thoughts():
    service = GeminiService("secret")
    result = response({"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "private reasoning", "thought": True},
        {"text": "First. "}, {"text": "Second."},
    ]}}]})
    with patch.object(service._session, "post", return_value=result) as post:
        assert service.transcribe_and_format(b"fake")[0] == "First. Second."
    assert "secret" not in post.call_args.args[0]
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "secret"


@pytest.mark.parametrize("reason", ["MAX_TOKENS", "SAFETY", None])
def test_gemini_rejects_incomplete_output(reason):
    service = GeminiService("secret")
    result = response({"candidates": [{"finishReason": reason, "content": {"parts": [{"text": "partial"}]}}]})
    with patch.object(service._session, "post", return_value=result):
        with pytest.raises(RuntimeError, match="tamamlanamadı"):
            service.transcribe_and_format(b"fake")


@pytest.mark.parametrize("service_type", [GeminiService, GroqService])
def test_network_errors_do_not_expose_secret_or_transcript(service_type, capsys):
    service = service_type("SECRET_MARKER")
    with patch.object(service._session, "post", side_effect=requests.ConnectionError("SECRET_MARKER PRIVATE_TRANSCRIPT")):
        with pytest.raises(RuntimeError) as error:
            service.transcribe_and_format(b"fake")
    assert "SECRET_MARKER" not in str(error.value)
    assert "PRIVATE_TRANSCRIPT" not in str(error.value)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("failure", ["length", "http", "empty", "malformed"])
def test_groq_preserves_complete_transcript_and_warns_on_formatting_failure(failure):
    service = GroqService("secret")
    stt = response({"text": "Complete original transcript."})
    chat = response({"choices": [{"finish_reason": "length" if failure == "length" else "stop",
                                 "message": {"content": '{"text":""}' if failure == "empty" else '{"text":"partial"}'}}]},
                    status=500 if failure == "http" else 200)
    if failure == "malformed":
        chat = response({"choices": []})
    with patch.object(service._session, "post", side_effect=[stt, chat]):
        assert service.transcribe_and_format(b"fake").text == "Complete original transcript."
    assert "ham transkript" in service.last_warning


def test_llama_omits_reasoning_options_and_success_clears_warning(capsys):
    service = GroqService("secret", llm_model="llama-3.3-70b-versatile")
    service.last_warning = "old failure"
    replies = [response({"text": "PRIVATE_TRANSCRIPT"}),
               response({"choices": [{"finish_reason": "stop", "message": {"content": '{"text":"Formatted."}'}}]})]
    with patch.object(service._session, "post", side_effect=replies) as post:
        assert service.transcribe_and_format(b"fake", language="en").formatted_text == "Formatted."
        payload = post.call_args_list[1].kwargs["json"]
        assert "reasoning_effort" not in payload
        assert "reasoning_format" not in payload
        assert "Türkçe" not in post.call_args_list[0].kwargs["data"].get("prompt", "")
    assert service.last_warning == ""
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("data", [None, [], {"text": None}, {"text": 123}])
def test_groq_rejects_invalid_transcription_shape(data):
    service = GroqService("secret")
    with patch.object(service._session, "post", return_value=response(data)):
        with pytest.raises(RuntimeError, match="ayrıştırılamadı"):
            service.transcribe_and_format(b"fake")
