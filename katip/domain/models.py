"""Values exchanged between providers, the session and desktop adapters."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DictationRequest:
    provider: str
    mode: str = "dictation"
    language: str = "auto"
    custom_vocabulary: tuple[str, ...] = ()
    vocabulary_aliases: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_config(cls, config):
        return cls(config.get("provider", "gemini"), config.get("mode", "dictation"),
                   config.get("language", "auto"), tuple(config.get("custom_vocabulary", [])),
                   tuple(config.get("vocabulary_aliases", {}).items()))


@dataclass(frozen=True)
class DictationResult:
    raw_transcript: Optional[str]
    formatted_text: Optional[str]
    latency: float
    warning: str = ""
    segments: tuple[dict, ...] = ()
    mode: str = "dictation"
    language: str = "auto"
    custom_vocabulary: tuple[str, ...] = ()
    vocabulary_aliases: tuple[tuple[str, str], ...] = ()
    llm_model: str = ""
    stt_model: str = ""
    omitted_stt_terms: int = 0
    omitted_formatter_terms: int = 0
    literal_changes: tuple[str, ...] = ()
    provider: str = "groq"
    job_id: str = ""

    @property
    def text(self) -> str:
        return self.formatted_text if self.formatted_text is not None else (self.raw_transcript or "")


@dataclass(frozen=True)
class ProviderCapabilities:
    audio_to_text: bool = False
    reformat: bool = True


CAPABILITIES = {name: ProviderCapabilities() for name in ("groq", "openai", "claude", "codex", "agy")}
CAPABILITIES["gemini"] = ProviderCapabilities(audio_to_text=True, reformat=False)
