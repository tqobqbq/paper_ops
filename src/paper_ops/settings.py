import json
import os
import tomllib
from pathlib import Path

from pydantic import BaseModel


class RuntimeSettings(BaseModel):
    codex_root: Path
    base_url: str
    model: str
    api_key: str
    model_provider: str | None = None

    @property
    def redacted_api_key(self) -> str:
        return f"{self.api_key[:4]}..." if self.api_key else ""


def resolve_library_root(
    library_root_override: Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path:
    if library_root_override is not None:
        return library_root_override.expanduser()

    env_value = os.environ.get("PAPER_OPS_LIBRARY_ROOT")
    if env_value:
        return Path(env_value).expanduser()

    return (cwd or Path.cwd()) / "papers"


def load_runtime_settings(
    codex_root: Path = Path("/root/.codex"),
    model_override: str | None = None,
    base_url_override: str | None = None,
    model_provider_override: str | None = None,
) -> RuntimeSettings:
    config_path = codex_root / "config.toml"
    auth_path = codex_root / "auth.json"

    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    with auth_path.open("r", encoding="utf-8") as handle:
        auth = json.load(handle)

    openai_config = config.get("openai", {})
    model_provider_name = (
        model_provider_override
        or openai_config.get("model_provider")
        or config.get("model_provider")
    )
    provider_config = {}
    model_providers = config.get("model_providers", {})
    if isinstance(model_provider_name, str) and isinstance(model_providers, dict):
        selected_provider = model_providers.get(model_provider_name, {})
        if isinstance(selected_provider, dict):
            provider_config = selected_provider
    if not provider_config and model_provider_name == "claude":
        provider_config = {
            "base_url": "https://api.anthropic.com/v1/",
            "model": "claude-sonnet-4-20250514",
        }

    base_url = (
        base_url_override
        or provider_config.get("base_url")
        or openai_config.get("base_url")
        or config.get("base_url")
        or "https://api.openai.com/v1"
    )
    model = (
        model_override
        or provider_config.get("model")
        or openai_config.get("model")
        or config.get("model")
        or "gpt-5.4"
    )
    if model_provider_name == "claude":
        api_key = (
            auth.get("ANTHROPIC_API_KEY")
            or auth.get("api_key")
            or auth.get("OPENAI_API_KEY")
            or ""
        )
    else:
        api_key = (
            auth.get("OPENAI_API_KEY")
            or auth.get("api_key")
            or auth.get("ANTHROPIC_API_KEY")
            or ""
        )

    return RuntimeSettings(
        codex_root=codex_root,
        base_url=base_url,
        model=model,
        api_key=api_key,
        model_provider=model_provider_name if isinstance(model_provider_name, str) else None,
    )
