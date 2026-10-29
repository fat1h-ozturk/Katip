"""Safe, actionable errors; never serialize external exception messages."""


class ProviderError(RuntimeError):
    def __init__(self, code: str, stage: str, message: str):
        self.code = code
        self.stage = stage
        super().__init__(f"[{code}] {message}")


class ConfigurationError(ValueError):
    """An application-authored configuration message, safe for presentation."""


class CaptureError(ProviderError):
    def __init__(self, message):
        code = message[1:message.index("]")] if message.startswith("[") and "]" in message else "CAPTURE_ERROR"
        detail = message.split("]", 1)[1].strip() if message.startswith("[") and "]" in message else message
        super().__init__(code, "capture", detail)
