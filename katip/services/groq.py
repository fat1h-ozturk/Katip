"""Groq speech recognition and recoverable, structured text formatting."""

import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from typing import Optional

import requests

from ..config import normalize_vocabulary_aliases
from ..prompts import build_groq_formatter_prompt, build_whisper_prompt

GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_MODEL_CAPABILITIES = {
    "qwen/qwen3.8-27b": (131072, True),
    "llama-3.3-70b-versatile": (131072, False),
}
_FAILURE_WARNING = "Metin düzenlenemedi; eksiksiz ham transkript korundu."


@dataclass(frozen=True)
class GroqResult:
    raw_transcript: str
    formatted_text: Optional[str]
    latency: float
    warning: str = ""
    segments: tuple[dict, ...] = ()
    mode: str = "dictation"
    language: str = "tr"
    custom_vocabulary: tuple[str, ...] = ()
    vocabulary_aliases: tuple[tuple[str, str], ...] = ()
    llm_model: str = ""
    stt_model: str = ""
    omitted_stt_terms: int = 0
    omitted_formatter_terms: int = 0
    literal_changes: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return self.formatted_text if self.formatted_text is not None else self.raw_transcript


_LITERAL_RE = re.compile(
    r"```[^`]*(?:`(?!``)[^`]*)*```|`[^`\n]+`|https?://[^\s<>\"`]+"
    r"|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|\b[A-Z]{2,10}-[0-9]{2,12}\b", re.UNICODE
)


def compare_literals(raw: str, formatted: str) -> tuple[str, ...]:
    """Informational differences only; omission can be a valid correction/summary."""
    def extract(text):
        return Counter(match.group().rstrip(".,;!?") for match in _LITERAL_RE.finditer(text))
    before, after = extract(raw), extract(formatted)
    return tuple(f"{literal}: {before[literal]} → {after[literal]}"
                 for literal in sorted(before.keys() | after.keys())
                 if before[literal] != after[literal])


def _segments(value) -> tuple[dict, ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        cleaned = {}
        for key in ("start", "end", "avg_logprob", "no_speech_prob", "compression_ratio"):
            number = item.get(key)
            if type(number) in (int, float):
                try:
                    if math.isfinite(number):
                        cleaned[key] = number
                except OverflowError:
                    pass
        if isinstance(item.get("text"), str):
            cleaned["text"] = item["text"]
        if cleaned:
            result.append(cleaned)
    return tuple(result)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_output(content):
    # ASVS 2.2.1: accept exactly the expected structure, including unique keys.
    if not isinstance(content, str):
        raise ValueError("invalid content")
    value = json.loads(content, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != {"text"}:
        raise ValueError("invalid schema")
    if not isinstance(value["text"], str) or not value["text"].strip():
        raise ValueError("empty or invalid text")
    return value["text"]


class GroqService:
    def __init__(self, api_key: str, stt_model: str = "whisper-large-v3-turbo",
                 llm_model: str = "qwen/qwen3.8-27b"):
        self.last_warning = ""
        self.api_key = api_key.strip() if api_key else ""
        self.stt_model = stt_model or "whisper-large-v3-turbo"
        self.llm_model = llm_model or "qwen/qwen3.8-27b"
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="tr", timeout=25, vocabulary_aliases=None) -> GroqResult:
        self.last_warning = ""
        if not self.api_key:
            raise ValueError("Groq API anahtarı bulunamadı! Lütfen Ayarlar'dan API anahtarınızı girin.")
        start = time.monotonic()
        aliases = normalize_vocabulary_aliases(vocabulary_aliases or {})
        vocabulary = tuple(custom_vocabulary or ())
        prompt, omitted = build_whisper_prompt(vocabulary, aliases)
        data = {"model": self.stt_model, "response_format": "verbose_json", "temperature": "0.0"}
        lang = (language or "").strip().lower()
        if lang and lang != "auto":
            data["language"] = lang
        if prompt:
            data["prompt"] = prompt
        try:
            response = self._session.post(GROQ_AUDIO_URL,
                files={"file": ("audio.wav", audio_bytes, "audio/wav")}, data=data, timeout=timeout)
        except requests.exceptions.RequestException:
            # ASVS 16.5.1: never expose raw exceptions containing keys or transcripts.
            raise RuntimeError("Groq Whisper bağlantı hatası. Lütfen tekrar deneyin.") from None
        if response.status_code != 200:
            if response.status_code == 401:
                raise RuntimeError("Groq API anahtarı geçersiz veya iptal edilmiş (401). Ayarlar'dan güncelleyin.")
            raise RuntimeError(f"Groq Whisper Hatası (HTTP {response.status_code}). Lütfen tekrar deneyin.")
        try:
            body = response.json()
            raw = body["text"]
            if not isinstance(raw, str):
                raise ValueError("invalid text")
        except (ValueError, TypeError, KeyError):
            raise RuntimeError("Groq Whisper yanıtı ayrıştırılamadı.") from None
        result = self.format_transcript(raw, mode, vocabulary, language, aliases, timeout,
                                        _segments(body.get("segments")), omitted)
        return replace(result, latency=round(time.monotonic() - start, 2))

    def format_transcript(self, raw_transcript, mode="dictation", custom_vocabulary=None,
                          language="tr", vocabulary_aliases=None, timeout=25,
                          segments=(), omitted_stt_terms=0) -> GroqResult:
        start = time.monotonic()
        self.last_warning = ""
        aliases = normalize_vocabulary_aliases(vocabulary_aliases or {})
        vocabulary = tuple(custom_vocabulary or ())
        base = GroqResult(raw_transcript, None, 0, segments=_segments(list(segments)), mode=mode,
            language=language, custom_vocabulary=vocabulary, vocabulary_aliases=tuple(aliases.items()),
            llm_model=self.llm_model, stt_model=self.stt_model, omitted_stt_terms=omitted_stt_terms)
        omitted = 0
        failure_detail = ""
        try:
            if not self.api_key or not raw_transcript.strip():
                raise ValueError("empty input or key")
            budget = min(8192, max(2048, math.ceil(len(raw_transcript.encode("utf-8")) *
                         (1.25 if mode in ("email", "prompt") else 1)) + 128))
            context, strict = _MODEL_CAPABILITIES.get(self.llm_model, (32768, False))
            system = build_groq_formatter_prompt(mode)
            user = {"transcript": raw_transcript, "language": language,
                    "custom_vocabulary": list(vocabulary), "vocabulary_aliases": dict(aliases)}
            while True:
                serialized = json.dumps(user, ensure_ascii=False)
                # Byte estimate is deliberately conservative, not a tokenizer count.
                if len(system.encode("utf-8")) + len(serialized.encode("utf-8")) + budget + 512 <= context:
                    break
                if user["vocabulary_aliases"]:
                    user["vocabulary_aliases"].popitem()
                elif user["custom_vocabulary"]:
                    user["custom_vocabulary"].pop()
                else:
                    raise ValueError("context budget exceeded")
                omitted += 1
            response_format = {"type": "json_object"}
            if strict:
                response_format = {"type": "json_schema", "json_schema": {
                    "name": "formatted_transcript", "strict": True, "schema": {
                        "type": "object", "properties": {"text": {"type": "string"}},
                        "required": ["text"], "additionalProperties": False}}}
            payload = {"model": self.llm_model, "messages": [
                {"role": "system", "content": system}, {"role": "user", "content": serialized}],
                "temperature": 0.1, "max_tokens": budget, "response_format": response_format}
            if self.llm_model == "qwen/qwen3.8-27b":
                payload.update(reasoning_format="hidden", reasoning_effort="none")
            failure_detail = "Groq metin hizmetine bağlantı kurulamadı veya istek zaman aşımına uğradı."
            response = self._session.post(GROQ_CHAT_URL, json=payload,
                timeout=min(60, max(timeout, 25 + (budget - 2048) * 35 / 6144)))
            if response.status_code != 200:
                # ASVS 16.5.1: report actionable status, never the private response body.
                failure_detail = {
                    401: "Groq API anahtarı geçersiz (HTTP 401).",
                    403: "Seçili metin modeline erişim reddedildi (HTTP 403).",
                    404: "Seçili metin modeli bulunamadı veya erişilemiyor (HTTP 404). Ayarlar'dan erişilebilir bir metin modeli seçin.",
                    429: "Groq metin isteği kullanım sınırına takıldı (HTTP 429). Daha sonra yeniden deneyin.",
                }.get(response.status_code, f"Groq metin isteği başarısız (HTTP {response.status_code}).")
                raise ValueError("formatter HTTP error")
            failure_detail = "Groq metin yanıtının biçimi doğrulanamadı."
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") != "stop":
                failure_detail = "Groq metin yanıtı tamamlanmadan sona erdi."
                raise ValueError("incomplete formatter response")
            text = _parse_output(choice["message"]["content"])
            return replace(base, formatted_text=text, latency=round(time.monotonic() - start, 2),
                           omitted_formatter_terms=omitted, literal_changes=compare_literals(raw_transcript, text))
        except Exception:
            # ASVS 16.5.2: preserve complete input without logging private response data.
            self.last_warning = f"{failure_detail} {_FAILURE_WARNING}".strip()
            return replace(base, latency=round(time.monotonic() - start, 2), warning=self.last_warning,
                           omitted_formatter_terms=omitted)
