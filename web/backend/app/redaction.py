import re


def mask_secrets(value: str, secrets: tuple[str, ...] | list[str] = ()) -> str:
    """Redact known secret values and common key-like query parameters from a log line."""

    masked = value
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            masked = masked.replace(secret, "[비밀 값]")
    return re.sub(
        r"(?i)((?:service[_-]?key|api[_-]?key|access[_-]?token|secret|password)\s*[=:]\s*)[^\s&,;]+",
        r"\1[비밀 값]",
        masked,
    )
