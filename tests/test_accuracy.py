"""
Unit tests for accuracy improvements, VAD trimming, and LLM output cleaning.
"""

import math
import pytest
import struct
from unittest.mock import MagicMock, patch
from katip.prompts import build_system_prompt
from katip.services.groq import GroqService
from katip.prompts import clean_llm_output as _clean_llm_output
from katip.audio import AudioRecorder


@pytest.fixture(autouse=True)
def no_microphone(monkeypatch):
    monkeypatch.setattr("katip.audio.pyaudio.PyAudio", MagicMock())


def test_silence_instruction_in_prompts():
    prompt = build_system_prompt("dictation")
    assert "sessizlik" in prompt
    assert "boş bir yanıt" in prompt


def test_clean_llm_output_think_tags():
    raw = "<think>\nBurada kullanıcının metnini düzeltiyoruz...\n</think>Merhaba dünya, nasılsın?"
    cleaned = _clean_llm_output(raw)
    assert cleaned == "Merhaba dünya, nasılsın?"


def test_clean_llm_output_markdown_fences():
    raw = "```\nBu bir test cümlesidir.\n```"
    cleaned = _clean_llm_output(raw)
    assert cleaned == "Bu bir test cümlesidir."


def test_clean_llm_output_wrapping_quotes():
    raw1 = '"Çift tırnaklı metin"'
    assert _clean_llm_output(raw1) == "Çift tırnaklı metin"

    raw2 = "'Tek tırnaklı metin'"
    assert _clean_llm_output(raw2) == "Tek tırnaklı metin"


def test_clean_llm_output_prefixes():
    raw = "İşte düzeltilmiş metin: Bugün hava çok güzel."
    assert _clean_llm_output(raw) == "Bugün hava çok güzel."

    raw2 = "Düzenlenmiş hali: Toplantı saat 14:00'te."
    assert _clean_llm_output(raw2) == "Toplantı saat 14:00'te."


def test_groq_payload_reasoning_and_language():
    service = GroqService(api_key="fake_key", stt_model="whisper-large-v3", llm_model="qwen/qwen3.8-27b")
    
    with patch.object(service._session, "post") as mock_post:
        # Mock STT response
        mock_stt_resp = MagicMock()
        mock_stt_resp.status_code = 200
        mock_stt_resp.json.return_value = {"text": "deneme ses"}

        # Mock LLM response
        mock_llm_resp = MagicMock()
        mock_llm_resp.status_code = 200
        mock_llm_resp.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"text":"Deneme ses."}'}}]
        }

        mock_post.side_effect = [mock_stt_resp, mock_llm_resp]

        # Case 1: language="auto" -> language should NOT be in STT payload
        result = service.transcribe_and_format(b"fake_wav", language="auto")
        assert result.formatted_text == "Deneme ses."

        stt_call = mock_post.call_args_list[0]
        stt_data = stt_call.kwargs["data"]
        assert "language" not in stt_data

        llm_call = mock_post.call_args_list[1]
        llm_json = llm_call.kwargs["json"]
        assert llm_json["reasoning_format"] == "hidden"
        assert llm_json["reasoning_effort"] == "none"


def test_groq_payload_explicit_language():
    service = GroqService(api_key="fake_key")
    with patch.object(service._session, "post") as mock_post:
        mock_stt = MagicMock(status_code=200, json=lambda: {"text": "test"})
        mock_llm = MagicMock(status_code=200, json=lambda: {"choices": [{"finish_reason": "stop", "message": {"content": '{"text":"Test."}'}}]})
        mock_post.side_effect = [mock_stt, mock_llm]

        service.transcribe_and_format(b"fake_wav", language="tr")
        stt_call = mock_post.call_args_list[0]
        assert stt_call.kwargs["data"]["language"] == "tr"


def test_audio_vad_pure_silence_rejection():
    recorder = AudioRecorder()
    # 20 frames of 30ms silence = 600ms = 20 * 960 bytes
    frames = [b"\x00" * 960] * 20
    assert recorder._encode_wav(frames) == b""


def test_audio_vad_speech_preservation():
    recorder = AudioRecorder()
    # Generate 1 second of 300Hz sine wave (simulating voice)
    speech = bytearray()
    for i in range(16000):
        sample = int(12000 * math.sin(2 * math.pi * 300 * i / 16000))
        speech.extend(struct.pack("<h", sample))

    lead_silence = b"\x00" * (960 * 10)  # 300ms silence
    trail_silence = b"\x00" * (960 * 10)  # 300ms silence
    raw_pcm = lead_silence + bytes(speech) + trail_silence

    recorder._vad = MagicMock()
    recorder._vad.is_speech.side_effect = lambda frame, rate: any(frame)
    trimmed = recorder._process_dsp(raw_pcm)
    assert len(trimmed) > 0
    # Trimmed audio should preserve speech and be shorter than full padded audio
    assert len(trimmed) <= len(raw_pcm)


def test_audio_rms_calculation():
    recorder = AudioRecorder()
    silence = b"\x00" * 3200
    assert recorder._compute_rms(silence) == 0.0

    # Max volume sine wave
    loud = bytearray()
    for i in range(1600):
        loud.extend(struct.pack("<h", 20000))
    rms = recorder._compute_rms(bytes(loud))
    assert rms > 0.5


def test_audio_normalize_pcm():
    recorder = AudioRecorder()
    samples = [1000, -1000, 2000, -2000]
    raw = struct.pack(f"<{len(samples)}h", *samples)
    norm = recorder._normalize_pcm(raw, target_peak=24000)
    norm_samples = struct.unpack(f"<{len(samples)}h", norm)
    # Gain should scale to target_peak (max 12x)
    assert norm_samples[2] == 24000
