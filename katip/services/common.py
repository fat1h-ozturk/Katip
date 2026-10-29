"""Formatting wire contracts shared by all text providers."""

import json
from functools import wraps
from ..domain.models import DictationResult
from ..diagnostics import Diagnostics
from ..infrastructure.http_transport import current_job
from ..config import normalize_vocabulary_aliases
from .catalog import output_budget


def http_status_message(provider, response):
    message = f"{provider} hizmeti isteği tamamlayamadı (HTTP {response.status_code})."
    if response.status_code == 429:
        retry = getattr(response, "headers", {}).get("Retry-After", "")
        if isinstance(retry, str) and retry.isascii() and retry.isdigit() and len(retry) <= 6:
            message += f" {int(retry)} saniye sonra yeniden deneyin."
        else:
            message += " Kullanım sınırı; daha sonra yeniden deneyin."
    return message


def start_stt(service, size):
    diagnostics = getattr(service, "diagnostics", None)
    if not isinstance(diagnostics, Diagnostics):
        diagnostics = Diagnostics()
        service.diagnostics = diagnostics
    diagnostics.event("stt_started", stage="stt", audio_bytes=size)


def publish_transcript(service, raw, mode, vocabulary, language, aliases):
    diagnostics = getattr(service, "diagnostics", None)
    if isinstance(diagnostics, Diagnostics):
        diagnostics.event("stt_finished", stage="stt")
    job = current_job()
    if job and job.publish:
        provider = {"GroqService": "groq", "OpenAIService": "openai", "ClaudeService": "claude",
                    "CodexService": "codex", "AntigravityService": "agy"}[type(service).__name__]
        result = DictationResult(raw, None, 0, provider=provider, mode=mode, language=language,
            custom_vocabulary=tuple(vocabulary or ()), vocabulary_aliases=tuple((aliases or {}).items()),
            stt_model=service.stt_model,
            llm_model=getattr(service, "llm_model", getattr(service, "codex_model", getattr(service, "agy_model", ""))))
        job.publish("transcript", result)


def formatting_stage(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        diagnostics = getattr(self, "diagnostics", None)
        if not isinstance(diagnostics, Diagnostics):
            diagnostics = Diagnostics()
        diagnostics.event("formatter_started", stage="formatter")
        try:
            result = method(self, *args, **kwargs)
        except Exception as error:
            from ..domain.errors import ProviderError
            diagnostics.event("failed", stage="formatter",
                              code=error.code if isinstance(error, ProviderError) else "FORMATTER_ERROR")
            raise
        diagnostics.event("formatter_finished", stage="formatter",
                          code="OUTPUT_INCOMPLETE" if result.warning else "OK")
        return result
    return call


def user_data(transcript, language="auto", custom_vocabulary=None, vocabulary_aliases=None):
    return json.dumps({"transcript": transcript, "language": language,
                       "custom_vocabulary": list(custom_vocabulary or ()),
                       "vocabulary_aliases": normalize_vocabulary_aliases(vocabulary_aliases or {})},
                      ensure_ascii=False)


def formatter_input(transcript, language, vocabulary, aliases, system, profile):
    """Drop optional hints first; never cut the user's transcript to fit context."""
    terms = list(vocabulary or ())
    hints = dict(aliases or {})
    budget = output_budget(transcript, profile)
    omitted = 0
    while True:
        serialized = user_data(transcript, language, terms, hints)
        if len(system.encode("utf-8")) + len(serialized.encode("utf-8")) + budget + 512 <= profile.context_budget:
            return serialized, budget, omitted
        if hints:
            hints.popitem()
        elif terms:
            terms.pop()
        else:
            return None, budget, omitted
        omitted += 1


def parse_output(content, *, allow_fence=False):
    if not isinstance(content, str):
        raise ValueError("Expected JSON text")
    value = content.strip()
    if allow_fence and value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if lines[0] not in ("```", "```json"):
            raise ValueError("Invalid fence")
        value = "\n".join(lines[1:-1])

    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = item
        return result

    parsed = json.loads(value, object_pairs_hook=unique)
    if (not isinstance(parsed, dict) or set(parsed) != {"text"}
            or not isinstance(parsed["text"], str) or not parsed["text"].strip()):
        raise ValueError("Invalid text result")
    return parsed["text"]
