"""
Groq Whisper STT + LLM Formatter Service.
Two-stage pipeline: Whisper transcription → LLM text correction/formatting.
"""

import re
import time
from typing import List, Optional, Tuple
import requests

from ..prompts import build_system_prompt

GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Pre-compiled patterns for LLM output cleaning
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
_LLM_PREFIX_PATTERNS = [
    "İşte metniniz:",
    "İşte düzeltilmiş metin:",
    "İşte düzenlenmiş metin:",
    "Düzenlenmiş hali:",
    "Düzeltilmiş hali:",
    "Düzeltilmiş metin:",
    "İşte:",
]


def _clean_llm_output(text: str) -> str:
    """
    Cleans common LLM artifacts from the formatted text output:
    1. Removes <think>...</think> blocks (Qwen reasoning mode leakage)
    2. Strips markdown code fences (```...```)
    3. Removes wrapping quotation marks
    4. Removes conversational LLM prefixes
    """
    if not text:
        return text

    # 1. Strip <think>...</think> reasoning blocks
    text = _THINK_TAG_RE.sub("", text).strip()

    # 2. Strip markdown code fences
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1]).strip()

    # 3. Strip wrapping quotation marks
    if len(text) >= 2:
        if (text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'"):
            text = text[1:-1].strip()

    # 4. Strip conversational LLM prefixes
    for prefix in _LLM_PREFIX_PATTERNS:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    return text


class GroqService:
    """Service utilizing Groq Whisper for ultra-fast STT and LLM for formatting."""

    def __init__(
        self,
        api_key: str,
        stt_model: str = "whisper-large-v3-turbo",
        llm_model: str = "qwen/qwen3.8-27b"
    ):
        self.api_key = api_key.strip() if api_key else ""
        self.stt_model = stt_model or "whisper-large-v3-turbo"
        self.llm_model = llm_model or "qwen/qwen3.8-27b"
        # Persistent HTTP session for connection reuse (avoids repeated TCP/TLS handshakes)
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def transcribe_and_format(
        self,
        audio_bytes: bytes,
        mode: str = "dictation",
        custom_vocabulary: Optional[List[str]] = None,
        language: str = "tr",
        timeout: int = 25
    ) -> Tuple[str, float]:
        """
        Transcribes audio with Groq Whisper and polishes text with Groq LLM.
        Returns (formatted_text, total_latency_seconds).
        """
        if not self.api_key:
            raise ValueError(
                "Groq API anahtarı bulunamadı!\n"
                "Lütfen Ayarlar'dan API anahtarınızı girin veya GROQ_API_KEY tanımlayın."
            )

        start_time = time.time()

        # ── Step 1: Groq Whisper Transcription ──
        files = {
            "file": ("audio.wav", audio_bytes, "audio/wav")
        }
        data = {
            "model": self.stt_model,
            "response_format": "json",
            "temperature": "0.0",
        }

        # Language handling: "auto" → omit language param for Whisper auto-detection
        # Explicit language codes (e.g. "tr", "en") → pass directly
        lang_lower = (language or "").lower().strip()
        if lang_lower and lang_lower not in ("auto", ""):
            data["language"] = lang_lower

        # Prime Whisper context for proper capitalization, Turkish punctuation & vocab
        whisper_priming = "Merhaba. Bu bir Türkçe konuşma diktesidir; noktalama işaretleri ve büyük harfler içerir."
        if custom_vocabulary:
            whisper_priming += " Terimler: " + ", ".join(custom_vocabulary)
        data["prompt"] = whisper_priming

        try:
            stt_resp = self._session.post(GROQ_AUDIO_URL, files=files, data=data, timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Groq Whisper bağlantı hatası: {e}")

        if stt_resp.status_code != 200:
            raise RuntimeError(f"Groq Whisper Hatası ({stt_resp.status_code}): {stt_resp.text[:200]}")

        raw_transcript = stt_resp.json().get("text", "").strip()
        print(f"[STT Ham Çıktı]: {raw_transcript}")
        if not raw_transcript:
            return ("", round(time.time() - start_time, 2))

        # ── Step 2: Groq LLM Formatting ──
        system_prompt = build_system_prompt(mode=mode, custom_vocabulary=custom_vocabulary)
        chat_payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Ham konuşma metni:\n{raw_transcript}"}
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            # Disable Qwen thinking mode — all tokens should go to the corrected text
            "reasoning_format": "hidden",
            "reasoning_effort": "none",
        }

        try:
            chat_resp = self._session.post(GROQ_CHAT_URL, json=chat_payload, timeout=timeout)
            if chat_resp.status_code == 200:
                raw_output = chat_resp.json()["choices"][0]["message"]["content"].strip()
                formatted_text = _clean_llm_output(raw_output)
                print(f"[LLM Düzeltilmiş]: {formatted_text[:80]}...")
            else:
                print(f"[Groq] LLM formatting HTTP {chat_resp.status_code}, using raw transcript.")
                formatted_text = raw_transcript
        except Exception as e:
            print(f"[Groq] LLM formatting error ({e}), using raw transcript.")
            formatted_text = raw_transcript

        # Final safety: if LLM returned empty after cleaning, fall back to raw
        if not formatted_text.strip():
            formatted_text = raw_transcript

        total_latency = round(time.time() - start_time, 2)
        return (formatted_text, total_latency)
