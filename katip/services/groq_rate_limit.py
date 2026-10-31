"""Groq rate-limit hints, reduced to safe numeric diagnostics and a bounded delay."""

from collections.abc import Mapping
import math
import re

_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_DURATION = re.compile(
    rf"(?:(?P<days>{_NUMBER})d)?(?:(?P<hours>{_NUMBER})h)?"
    rf"(?:(?P<minutes>{_NUMBER})m)?(?:(?P<seconds>{_NUMBER})s)?"
    rf"(?:(?P<milliseconds>{_NUMBER})ms)?"
)
_UNITS = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1,
          "milliseconds": .001}


def _number(value, *, duration=False):
    if not isinstance(value, str) or len(value) > 128:
        return None
    value = value.strip()
    if re.fullmatch(_NUMBER, value):
        number = float(value)
    elif duration and value and (match := _DURATION.fullmatch(value)):
        number = sum(float(part) * _UNITS[unit]
                     for unit, part in match.groupdict().items() if part is not None)
    else:
        return None
    return number if math.isfinite(number) else None


def rate_limit_headers(headers):
    """Never retain arbitrary header text, even when a server sends malformed values."""
    if not isinstance(headers, Mapping):
        return {}
    headers = {key.lower(): value for key, value in headers.items() if isinstance(key, str)}
    result = {}
    retry = _number(headers.get("retry-after"))
    if retry is not None:
        result["retry_after_seconds"] = retry
    for window in ("requests", "tokens"):
        for kind in ("limit", "remaining", "reset"):
            value = _number(headers.get(f"x-ratelimit-{kind}-{window}"), duration=kind == "reset")
            if value is not None:
                suffix = "_seconds" if kind == "reset" else ""
                result[f"ratelimit_{kind}_{window}{suffix}"] = value
    return result


def retry_delay(headers):
    if "retry_after_seconds" in headers:
        return min(headers["retry_after_seconds"], 15)
    resets, exhausted = [], []
    for window in ("requests", "tokens"):
        reset = headers.get(f"ratelimit_reset_{window}_seconds")
        if reset is not None:
            resets.append(reset)
            if headers.get(f"ratelimit_remaining_{window}") == 0:
                exhausted.append(reset)
    # If multiple windows are exhausted, both must reset before retrying.
    delay = max(exhausted) if exhausted else min(resets, default=1)
    return min(delay, 15)
