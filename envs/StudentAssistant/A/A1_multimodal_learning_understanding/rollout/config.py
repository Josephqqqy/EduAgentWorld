"""Local configuration for the OpenAI-compatible model endpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[5]


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    api_type: str
    temperature: float
    max_tokens: int
    timeout: float


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_config(
    env_file: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> ModelConfig:
    """Load .env, allowing explicit process variables to override it."""
    values = _read_dotenv(Path(env_file) if env_file is not None else PROJECT_ROOT / ".env")
    values.update(os.environ if environ is None else environ)

    for key in ("AGENT_API_KEY", "AGENT_BASE_URL", "AGENT_MODEL"):
        if not values.get(key, "").strip():
            raise ValueError(f"{key} is required")

    api_type = values.get("AGENT_API_TYPE", "openai_compatible").strip()
    if api_type != "openai_compatible":
        raise ValueError("AGENT_API_TYPE must be openai_compatible")

    base_url = values["AGENT_BASE_URL"].strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("AGENT_BASE_URL must be an HTTP(S) URL")

    try:
        temperature = float(values.get("AGENT_TEMPERATURE", "0.2"))
        max_tokens = int(values.get("AGENT_MAX_TOKENS", "4096"))
        timeout = float(values.get("AGENT_TIMEOUT", "120"))
    except ValueError as error:
        raise ValueError("Invalid numeric AGENT_* configuration") from error
    if not 0 <= temperature <= 2 or max_tokens <= 0 or timeout <= 0:
        raise ValueError("AGENT_TEMPERATURE, AGENT_MAX_TOKENS or AGENT_TIMEOUT out of range")

    return ModelConfig(
        api_key=values["AGENT_API_KEY"].strip(),
        base_url=base_url,
        model=values["AGENT_MODEL"].strip(),
        api_type=api_type,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
