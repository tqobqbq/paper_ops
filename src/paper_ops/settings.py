import json
import tomllib
from pathlib import Path

from pydantic import BaseModel


class RuntimeSettings(BaseModel):
    codex_root: Path
    base_url: str
    model: str
    api_key: str

    @property
    def redacted_api_key(self) -> str:
        return f"{self.api_key[:4]}..." if self.api_key else ""


def load_runtime_settings(
    codex_root: Path = Path("/root/.codex"),
    model_override: str | None = None,
    base_url_override: str | None = None,
) -> RuntimeSettings:
    config_path = codex_root / "config.toml"
    auth_path = codex_root / "auth.json"

    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    with auth_path.open("r", encoding="utf-8") as handle:
        auth = json.load(handle)

    openai_config = config.get("openai", {})
    base_url = (
        base_url_override
        or openai_config.get("base_url")
        or "https://api.openai.com/v1"
    )
    model = model_override or openai_config.get("model") or "gpt-5.4"
    api_key = auth.get("OPENAI_API_KEY") or auth.get("api_key") or ""

    return RuntimeSettings(
        codex_root=codex_root,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
