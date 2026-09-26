import pytest
from katip.services.gemini import GeminiService

def test_gemini_missing_api_key():
    service = GeminiService(api_key="")
    with pytest.raises(ValueError, match="Gemini API anahtarı bulunamadı"):
        service.transcribe_and_format(b"fake_wav_data")

def test_gemini_init():
    service = GeminiService(api_key="test_key", model="gemini-2.0-flash")
    assert service.api_key == "test_key"
    assert service.model == "gemini-2.0-flash"
