"""
Google Gemini Multimodal Audio-to-Formatted-Text Service.
"""

import base64
import time
from typing import List, Optional, Tuple
import requests

from ..prompts import build_system_prompt

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_LLM_PREFIX_PATTERNS = [
    "İşte metniniz:",
    "İşte düzeltilmiş metin:",
    "İşte düzenlenmiş metin:",
    "Düzenlenmiş hali:",
    "Düzeltilmiş hali:",
    "Düzeltilmiş metin:",
    "İşte:",
]


class GeminiService:
    """Service for processing audio into polished text using Gemini Multimodal models."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key.strip() if api_key else ""
        self.model = model or "gemini-2.0-flash"
        self._session = requests.Session()

    def transcribe_and_format(
        self,
        audio_bytes: bytes,
        mode: str = "dictation",
        custom_vocabulary: Optional[List[str]] = None,
        timeout: int = 25
    ) -> Tuple[str, float]:
        """
        Sends audio WAV bytes to Gemini and returns (formatted_text, latency_seconds).
        """
        if not self.api_key:
            raise ValueError(
                "Gemini API anahtarı bulunamadı!\n"
                "Lütfen Ayarlar'dan API anahtarınızı girin veya GEMINI_API_KEY tanımlayın."
            )

        start_time = time.time()
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        prompt = build_system_prompt(mode=mode, custom_vocabulary=custom_vocabulary)

        url = f"{GEMINI_API_URL.format(model=self.model)}?key={self.api_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": b64_audio
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            }
        }

        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            raise RuntimeError("Gemini API zaman aşımına uğradı (Timeout). Lütfen internet bağlantınızı kontrol edin.")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ağ bağlantı hatası: {e}")

        latency = round(time.time() - start_time, 2)

        if resp.status_code != 200:
            err_msg = f"HTTP {resp.status_code}"
            try:
                err_data = resp.json()
                if "error" in err_data and "message" in err_data["error"]:
                    err_msg = err_data["error"]["message"]
            except Exception:
                err_msg = resp.text[:200]
            raise RuntimeError(f"Gemini API Hatası ({resp.status_code}): {err_msg}")

        data = resp.json()
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                # Might have been blocked or silence
                return ("", latency)

            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])
            if not parts:
                return ("", latency)

            text = parts[0].get("text", "").strip()

            # Strip markdown code blocks if the model accidentally wrapped it
            if text.startswith("```") and text.endswith("```"):
                lines = text.splitlines()
                if len(lines) >= 2:
                    text = "\n".join(lines[1:-1]).strip()

            # Strip leading/trailing quotation marks if whole text was quoted
            if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
                text = text[1:-1].strip()

            # Strip conversational LLM prefixes
            for prefix in _LLM_PREFIX_PATTERNS:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
                    break

            return (text, latency)
        except Exception as e:
            raise RuntimeError(f"Gemini yanıtı ayrıştırılamadı: {e}")
