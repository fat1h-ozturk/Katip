"""Offline contract checks; these do not measure model transcription accuracy."""
import json
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from katip.services.groq import GroqService, compare_literals


def reply(content, reason="stop"):
    return MagicMock(status_code=200, json=lambda: {"choices": [
        {"finish_reason": reason, "message": {"content": content}}]})


@pytest.mark.parametrize("text", ['İşte: bugün.', '"Alıntı"', '```py\nx = 1\n```', '<think>literal</think>', '  içerik  '])
def test_json_preserves_user_content_exactly(text):
    service = GroqService("fake")
    with patch.object(service._session, "post", return_value=reply(json.dumps({"text": text}))) as post:
        result = service.format_transcript(text)
    assert result.formatted_text == text
    assert result.raw_transcript == text
    assert result.warning == ""
    assert post.call_count == 1
    payload = post.call_args.kwargs["json"]
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert json.loads(payload["messages"][1]["content"])["transcript"] == text
    with pytest.raises(FrozenInstanceError):
        result.raw_transcript = "changed"


@pytest.mark.parametrize("content", ['plain text', '[]', '{}', '{"text":""}', '{"text":"  "}',
    '{"text":7}', '{"text":"x","extra":1}', '{"text":"x","text":"y"}', None])
def test_invalid_json_preserves_raw_without_retry(content):
    service = GroqService("fake")
    with patch.object(service._session, "post", return_value=reply(content)) as post:
        result = service.format_transcript("Özgün metin.")
    assert result.text == "Özgün metin."
    assert result.formatted_text is None
    assert result.warning
    assert post.call_count == 1


def test_full_pipeline_snapshots_context_and_tolerates_metadata():
    service = GroqService("fake")
    vocabulary = ["PySide6"]
    aliases = {"paysayd": "PySide6"}
    stt = MagicMock(status_code=200, json=lambda: {"text": "paysayd", "segments": [None,
        {"start": 0, "end": float("inf"), "avg_logprob": -.3, "no_speech_prob": None,
         "compression_ratio": True, "text": "paysayd"}]})
    with patch.object(service._session, "post", side_effect=[stt, reply('{"text":"PySide6"}')]) as post:
        result = service.transcribe_and_format(b"fake", custom_vocabulary=vocabulary,
                                               vocabulary_aliases=aliases, language="auto")
    vocabulary.clear()
    aliases.clear()
    assert result.custom_vocabulary == ("PySide6",)
    assert result.vocabulary_aliases == (("paysayd", "PySide6"),)
    assert result.segments == ({"start": 0, "avg_logprob": -.3, "text": "paysayd"},)
    assert result.raw_transcript == "paysayd"
    assert result.formatted_text == "PySide6"
    assert post.call_count == 2
    data = post.call_args_list[0].kwargs["data"]
    assert data["response_format"] == "verbose_json"
    assert "language" not in data


@pytest.mark.parametrize("model", ["llama-3.3-70b-versatile", "unknown/model"])
def test_json_object_models_have_no_assumed_reasoning(model):
    service = GroqService("fake", llm_model=model)
    with patch.object(service._session, "post", return_value=reply('{"text":"Sonuç"}')) as post:
        assert service.format_transcript("Ham").formatted_text == "Sonuç"
    payload = post.call_args.kwargs["json"]
    assert payload["response_format"] == {"type": "json_object"}
    assert "reasoning_format" not in payload
    assert "reasoning_effort" not in payload


def test_bounded_budgets_and_context_overflow_never_cut_input():
    service = GroqService("fake")
    with patch.object(service._session, "post", return_value=reply('{"text":"Sonuç"}')) as post:
        service.format_transcript("Kısa")
        assert post.call_args.kwargs["json"]["max_tokens"] == 2048
        service.format_transcript("uzun " * 2000, mode="email")
        assert post.call_args.kwargs["json"]["max_tokens"] == 8192
        assert post.call_args.kwargs["timeout"] == 60
        raw = "ğ" * 100000
        result = service.format_transcript(raw)
        assert result.raw_transcript == raw and result.warning
        assert post.call_count == 2


def test_context_drops_glossary_before_transcript_and_counts_omissions():
    service = GroqService("fake")
    raw = "Özgün metin"
    with patch.object(service._session, "post", return_value=reply('{"text":"Özgün metin"}')) as post:
        result = service.format_transcript(raw, custom_vocabulary=["x" * 140000])
    assert result.omitted_formatter_terms == 1
    data = json.loads(post.call_args.kwargs["json"]["messages"][1]["content"])
    assert data["transcript"] == raw and data["custom_vocabulary"] == []
    assert result.custom_vocabulary == ("x" * 140000,)


def test_literal_changes_are_information_not_a_semantic_gate():
    raw = "a@example.com değil b@example.com; ABC-123. `x=1` https://example.com"
    formatted = "b@example.com"
    assert compare_literals(raw, formatted)
    service = GroqService("fake")
    with patch.object(service._session, "post", return_value=reply(json.dumps({"text": formatted}))):
        result = service.format_transcript(raw, mode="bullets")
    assert result.literal_changes and not result.warning
    assert result.formatted_text == formatted
    assert not compare_literals("onaylamıyorum", "onaylıyorum")


def test_truncation_and_network_failure_keep_complete_input():
    service = GroqService("fake")
    with patch.object(service._session, "post", return_value=reply('{"text":"partial"}', "length")):
        result = service.format_transcript("Complete original")
    assert result.formatted_text is None and result.text == "Complete original"
    with patch.object(service._session, "post", side_effect=RuntimeError("SECRET PRIVATE")):
        result = service.format_transcript("Complete original")
    assert "SECRET" not in result.warning and "PRIVATE" not in result.warning


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_formatter_http_failure_reports_status_without_private_body(status):
    service = GroqService("fake", llm_model="llama-3.3-70b-versatile")
    response = MagicMock(status_code=status, text="SECRET PRIVATE TRANSCRIPT")
    with patch.object(service._session, "post", return_value=response) as post:
        result = service.format_transcript("Özgün metin")
    assert f"HTTP {status}" in result.warning
    assert "SECRET" not in result.warning and "PRIVATE" not in result.warning
    assert result.raw_transcript == "Özgün metin" and result.formatted_text is None
    assert post.call_count == 1
    response.json.assert_not_called()
    if status == 404:
        assert "modeli bulunamadı" in result.warning
