"""Public provider contracts: complete, typed output or a recoverable transcript."""
import json
from unittest.mock import Mock, patch

import pytest

from katip.services.openai import OpenAIService
from katip.services.claude import ClaudeService
from katip.services.antigravity import AntigravityService


@pytest.mark.parametrize('provider', ['openai', 'claude'])
def test_stt_success_reaches_formatter_with_real_prompt(provider):
    service = (OpenAIService('fake') if provider == 'openai' else
               ClaudeService('fake', stt_provider='groq', stt_api_key='fake', stt_model='whisper'))
    stt = Mock(status_code=200, text='Yarın belki gelirim.')
    formatted = Mock(status_code=200)
    formatted.json.return_value = ({'choices': [{'finish_reason': 'stop', 'message': {
        'content': json.dumps({'text': 'Yarın belki gelirim.'})}}]} if provider == 'openai' else
        {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps({'text': 'Yarın belki gelirim.'})}]})
    with patch.object(service._session, 'post', side_effect=[stt, formatted] if provider == 'openai' else [formatted]) as post, \
         patch('katip.services.claude.http_post', return_value=stt):
        result = service.transcribe_and_format(b'fake', vocabulary_aliases={'yarin': 'yarın'})
    assert result.raw_transcript == 'Yarın belki gelirim.'
    assert result.formatted_text == 'Yarın belki gelirim.'
    assert not result.warning
    payload = post.call_args.kwargs['json']
    assert json.loads(payload['messages'][-1]['content'])['vocabulary_aliases'] == {'yarin': 'yarın'}


@pytest.mark.parametrize('content', ['diagnostic banner', '{}', '[]', '{"text":7}', '{"text":"x","extra":true}'])
def test_cli_protocol_violation_preserves_transcript(content):
    with patch('katip.services.antigravity.http_post', return_value=Mock(status_code=200, text='Ham metin.')), \
         patch('katip.services.antigravity._find_agy_binary', return_value='fake-agy'), \
         patch('katip.services.antigravity.run_process', return_value=Mock(returncode=0, stdout=content)):
        result = AntigravityService('groq', 'fake', 'whisper').transcribe_and_format(b'fake')
    assert result.text == 'Ham metin.'
    assert result.formatted_text is None
    assert result.warning


@pytest.mark.parametrize('provider', ['openai', 'claude'])
def test_truncated_formatter_never_publishes_partial_text(provider):
    service = (OpenAIService('fake') if provider == 'openai' else
               ClaudeService('fake', stt_provider='groq', stt_api_key='fake', stt_model='whisper'))
    reply = Mock(status_code=200)
    reply.json.return_value = ({'choices': [{'finish_reason': 'length', 'message': {'content': '{"text":"partial"}'}}]}
                              if provider == 'openai' else {'stop_reason': 'max_tokens', 'content': [
                                  {'type': 'text', 'text': '{"text":"partial"}'}]})
    with patch.object(service._session, 'post', return_value=reply):
        result = service.format_transcript('Complete original transcript')
    assert result.raw_transcript == 'Complete original transcript'
    assert result.formatted_text is None and result.warning


def test_unknown_openai_model_receives_no_optional_sampling_settings():
    service = OpenAIService('fake', llm_model='gpt-5-mini')
    response = Mock(status_code=200, json=lambda: {'choices': [{'finish_reason': 'stop',
        'message': {'content': '{"text":"Complete"}'}}]})
    with patch.object(service._session, 'post', return_value=response) as post:
        assert service.format_transcript('Complete').text == 'Complete'
    payload = post.call_args.kwargs['json']
    assert 'temperature' not in payload and payload['store'] is False
    assert payload['max_completion_tokens'] >= 2048


@pytest.mark.parametrize('provider', ['openai', 'claude'])
def test_context_limit_keeps_transcript_and_skips_format_request(provider):
    service = (OpenAIService('fake') if provider == 'openai' else ClaudeService('fake'))
    raw = 'Anlamlı uzun konuşma. ' * 20000
    with patch.object(service._session, 'post') as post:
        result = service.format_transcript(raw)
    assert result.raw_transcript == raw and result.formatted_text is None
    assert 'CONTEXT_LIMIT' in result.warning
    post.assert_not_called()


def test_context_budget_drops_hints_before_transcript():
    from katip.services.common import formatter_input
    from katip.services.catalog import ModelProfile
    transcript = 'Eksiksiz konuşma'
    serialized, budget, omitted = formatter_input(transcript, 'tr', ['V' * 500] * 5,
        {'A': 'B' * 200}, 'System', ModelProfile(context_budget=3000))
    assert json.loads(serialized)['transcript'] == transcript
    assert budget == 2048 and omitted > 0


@pytest.fixture(params=['groq', 'openai', 'claude', 'codex', 'agy', 'gemini'])
def adapter(request, monkeypatch):
    from types import SimpleNamespace
    from katip.services.groq import GroqService
    from katip.services.codex import CodexService
    from katip.services.gemini import GeminiService
    provider = request.param
    raw = 'Tam ve özgün ham metin.'
    stt_response = Mock(status_code=200, text=raw, json=lambda: {'text': raw})
    stt, formatter = Mock(return_value=stt_response), Mock()
    json_answer = json.dumps({'text': 'Tam sonuç.'})
    reply = Mock(status_code=200, json=lambda: {'choices': [{'finish_reason': 'stop', 'message': {'content': json_answer}}]})
    formatter.return_value = reply
    if provider == 'groq':
        service = GroqService('fake')
    elif provider == 'openai':
        service = OpenAIService('fake')
    elif provider == 'claude':
        service = ClaudeService('fake', stt_provider='groq', stt_api_key='fake', stt_model='whisper')
        reply.json = lambda: {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json_answer}]}
        monkeypatch.setattr('katip.services.claude.http_post', stt)
    elif provider == 'codex':
        service = CodexService('groq', 'fake', 'whisper')
        formatter.return_value = Mock(returncode=0, stdout='\n'.join([
            json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json_answer}}),
            json.dumps({'type': 'turn.completed'})]))
        monkeypatch.setattr('katip.services.codex.http_post', stt)
        monkeypatch.setattr('katip.services.codex.run_process', formatter)
        monkeypatch.setattr('katip.services.codex._find_codex_binary', lambda: 'fake-codex')
    elif provider == 'agy':
        service = AntigravityService('groq', 'fake', 'whisper')
        formatter.return_value = Mock(returncode=0, stdout=json_answer)
        monkeypatch.setattr('katip.services.antigravity.http_post', stt)
        monkeypatch.setattr('katip.services.antigravity.run_process', formatter)
        monkeypatch.setattr('katip.services.antigravity._find_agy_binary', lambda: 'fake-agy')
    else:
        service = GeminiService('fake')
        stt = formatter
        reply.json = lambda: {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'Tam sonuç.'}]}}]}
    if provider in ('groq', 'openai'):
        monkeypatch.setattr(service._session, 'post', lambda url, **kwargs: (
            stt(url, **kwargs) if '/audio/' in url else formatter(url, **kwargs)))
    elif provider in ('claude', 'gemini'):
        monkeypatch.setattr(service._session, 'post', formatter)
    return SimpleNamespace(service=service, stt=stt, formatter=formatter, provider=provider, raw=raw)


def test_all_providers_share_result_contract(adapter):
    from katip.domain.models import DictationResult
    result = adapter.service.transcribe_and_format(b'fake-audio')
    assert isinstance(result, DictationResult)
    assert result.provider == adapter.provider and result.formatted_text == 'Tam sonuç.'
    assert result.raw_transcript == (None if adapter.provider == 'gemini' else adapter.raw)
    assert not result.warning


def test_all_providers_classify_stt_timeout_without_private_error(adapter):
    import requests
    from katip.domain.errors import ProviderError
    adapter.stt.side_effect = requests.Timeout('PRIVATE KEY AND TRANSCRIPT')
    with pytest.raises(ProviderError) as error:
        adapter.service.transcribe_and_format(b'fake-audio')
    assert error.value.code == 'NETWORK_TIMEOUT' and 'PRIVATE' not in str(error.value)


def test_invalid_provider_output_is_never_ready_for_delivery(adapter):
    if adapter.provider in ('codex', 'agy'):
        adapter.formatter.return_value = Mock(returncode=0, stdout='diagnostic banner')
    else:
        adapter.formatter.return_value = Mock(status_code=200, json=lambda: {})
    if adapter.provider == 'gemini':
        result = adapter.service.transcribe_and_format(b'fake-audio')
        assert not result.text
    else:
        result = adapter.service.transcribe_and_format(b'fake-audio')
        assert result.raw_transcript == adapter.raw and result.warning
        assert result.formatted_text is None
