"""Conservative wire capabilities, not a promise of account/model availability."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    context_budget: int = 32768
    output_limit: int = 8192
    temperature: bool = False


# Unrecognized model IDs get no optional sampling/reasoning parameters.
_OPENAI = {
    "gpt-4o-mini": ModelProfile(128000, temperature=True),
    "gpt-4o": ModelProfile(128000, temperature=True),
    "gpt-5-mini": ModelProfile(400000),
}


def model_profile(provider, model):
    return _OPENAI.get(model, ModelProfile()) if provider == "openai" else ModelProfile()


def output_budget(text, profile):
    return min(profile.output_limit, max(2048, len(text.encode("utf-8")) * 2 + 128))
