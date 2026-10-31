"""Offline Groq rejection/retry contracts; no real network or waiting."""

import json
from unittest.mock import Mock

import pytest
import requests

from katip.application.session import Job
from katip.diagnostics import Diagnostics
from katip.domain.errors import ProviderError
from katip.infrastructure.http_transport import Response, execution_scope
from katip.services.groq import GroqService
from katip.services.groq_rate_limit import rate_limit_headers, retry_delay


def response(status, headers=None, body=None):
    return Response(status, json.dumps(body or {}).encode(), headers or {})


def formatted():
    return response(200, body={"choices": [{"finish_reason": "stop", "message": {
        "content": '{"text":"Düzenlenmiş metin."}'}}]})


@pytest.fixture
def service(monkeypatch):
    service = GroqService("fake")
    monkeypatch.setattr("katip.services.groq.time.sleep", Mock())
    return service


def test_formatter_retry_after_returns_formatted_text_with_same_request(service, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("katip.services.groq.time.sleep", sleep)
    rejected = response(429, {"retry-after": "2", "x-ratelimit-remaining-tokens": "0",
                              "x-ratelimit-reset-tokens": "1m2.5s"})
    post = Mock(side_effect=[rejected, formatted()])
    monkeypatch.setattr(service._session, "post", post)
    result = service.format_transcript("Eksiksiz ham metin.")
    assert result.formatted_text == "Düzenlenmiş metin." and not result.warning
    assert result.raw_transcript == "Eksiksiz ham metin."
    assert post.call_count == 2 and post.call_args_list[0] == post.call_args_list[1]
    sleep.assert_called_once_with(2)
    event = next(e for e in service.diagnostics.snapshot() if e["event"] == "rate_limited")
    assert event["stage"] == "formatter" and event["http_status"] == 429
    assert event["retry_after_seconds"] == 2
    assert event["ratelimit_remaining_tokens"] == 0
    assert event["ratelimit_reset_tokens_seconds"] == 62.5


def test_two_formatter_rejections_preserve_complete_raw_and_final_retry_hint(service, monkeypatch):
    post = Mock(side_effect=[response(429, {"Retry-After": "1"}),
                             response(429, {"Retry-After": "7"})])
    monkeypatch.setattr(service._session, "post", post)
    raw = "Eksiksiz ham metin. " * 100
    result = service.format_transcript(raw)
    assert result.formatted_text is None and result.text == raw
    assert "HTTP 429" in result.warning and "7 saniye" in result.warning
    assert "eksiksiz ham transkript korundu" in result.warning
    assert service.last_warning == result.warning and post.call_count == 2
    limits = [e for e in service.diagnostics.snapshot() if e["event"] == "rate_limited"]
    assert [e["retry_after_seconds"] for e in limits] == [1, 7]


@pytest.mark.parametrize("headers, delay", [
    ({}, 1),
    ({"Retry-After": "nonsense", "x-ratelimit-reset-tokens": "7.66s"}, 7.66),
    ({"Retry-After": "900"}, 15),
    ({"Retry-After": "0"}, 0),
    ({"Retry-After": "0.25", "x-ratelimit-reset-tokens": "10s"}, .25),
    ({"x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-remaining-requests": "10",
      "x-ratelimit-reset-tokens": "7.66s", "x-ratelimit-remaining-tokens": "0"}, 7.66),
    ({"x-ratelimit-reset-requests": "1h2m3s", "x-ratelimit-remaining-requests": "0",
      "x-ratelimit-reset-tokens": "1s", "x-ratelimit-remaining-tokens": "10"}, 15),
    ({"x-ratelimit-reset-requests": "3s", "x-ratelimit-remaining-requests": "0",
      "x-ratelimit-reset-tokens": "5s", "x-ratelimit-remaining-tokens": "0"}, 5),
    ({"x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-reset-tokens": "7.66s"}, 7.66),
])
def test_header_delay_policy(headers, delay, service, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("katip.services.groq.time.sleep", sleep)
    post = Mock(side_effect=[response(429, headers), formatted()])
    monkeypatch.setattr(service._session, "post", post)
    assert service.format_transcript("Ham").formatted_text == "Düzenlenmiş metin."
    sleep.assert_called_once_with(delay)


@pytest.mark.parametrize("value", [None, 7, True, "", "nan", "inf", "-1", "1e4",
                                  "SECRET TRANSCRIPT", "１２", "1s private", "9" * 129])
def test_malformed_headers_are_never_retained(value):
    assert rate_limit_headers({"retry-after": value, "x-ratelimit-reset-tokens": value,
                               "x-ratelimit-remaining-tokens": value, "authorization": "SECRET"}) == {}
    assert retry_delay({}) == 1


def test_header_parsing_is_case_insensitive_and_converts_units():
    parsed = rate_limit_headers({"RETRY-AFTER": " 2.5 ", "X-RateLimit-Limit-Tokens": "8000",
        "x-ratelimit-reset-requests": "1d2h3m4.5s", "x-ratelimit-reset-tokens": "500ms",
        "x-ratelimit-remaining-requests": "10"})
    assert parsed == {"retry_after_seconds": 2.5, "ratelimit_limit_tokens": 8000,
                      "ratelimit_reset_requests_seconds": 93784.5,
                      "ratelimit_reset_tokens_seconds": .5, "ratelimit_remaining_requests": 10}
    assert rate_limit_headers(None) == {}


@pytest.mark.parametrize("value", ["PRIVATE", True, float("inf"), float("nan"), -1])
def test_diagnostics_reject_non_numeric_or_invalid_rate_limit_values(value):
    event = Diagnostics().event("rate_limited", retry_after_seconds=value,
                                ratelimit_remaining_tokens=0)
    assert "retry_after_seconds" not in event
    assert event["ratelimit_remaining_tokens"] == 0


def test_stt_rejection_retries_audio_once_then_formats(service, monkeypatch):
    post = Mock(side_effect=[response(429, {"Retry-After": "1"}),
        response(200, body={"text": "Eksiksiz ham metin."}), formatted()])
    monkeypatch.setattr(service._session, "post", post)
    result = service.transcribe_and_format(b"fake-audio")
    assert result.raw_transcript == "Eksiksiz ham metin."
    assert result.formatted_text == "Düzenlenmiş metin."
    assert post.call_count == 3 and post.call_args_list[0] == post.call_args_list[1]
    assert service.diagnostics.snapshot()[1]["stage"] == "stt"


def test_two_stt_rejections_keep_existing_recoverable_error(service, monkeypatch):
    post = Mock(return_value=response(429, {"Retry-After": "3"}))
    monkeypatch.setattr(service._session, "post", post)
    with pytest.raises(ProviderError, match="3 saniye") as error:
        service.transcribe_and_format(b"fake-audio")
    assert error.value.stage == "stt" and error.value.code == "HTTP_ERROR"
    assert post.call_count == 2


@pytest.mark.parametrize("failure", [response(500), requests.Timeout("PRIVATE"),
                                    requests.ConnectionError("PRIVATE")])
def test_other_errors_are_not_retried(service, monkeypatch, failure):
    post = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    monkeypatch.setattr(service._session, "post", post)
    assert service.format_transcript("Ham").warning
    assert post.call_count == 1


@pytest.mark.parametrize("stage", ["stt", "formatter"])
@pytest.mark.parametrize("code", ["CANCELLED", "DEADLINE"])
def test_cancellation_and_deadline_interrupt_wait_before_second_request(service, monkeypatch, stage, code):
    job = Job({})
    job.publish = Mock()
    def interrupt(_):
        if code == "CANCELLED":
            job.cancelled.set()
        else:
            job.deadline = 1
    monkeypatch.setattr(job.cancelled, "wait", interrupt)
    post = Mock(return_value=response(429, {"Retry-After": "15"}))
    monkeypatch.setattr(service._session, "post", post)
    with execution_scope(job), pytest.raises(ProviderError, match=code):
        if stage == "stt":
            service.transcribe_and_format(b"fake-audio")
        else:
            service.format_transcript("Ham")
    assert post.call_count == 1
    job.publish.assert_called_once_with("rate_limit_wait", 15)
