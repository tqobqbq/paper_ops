from pathlib import Path

from paper_ops.settings import RuntimeSettings, load_runtime_settings


def test_load_runtime_settings_reads_codex_files(tmp_path: Path):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        '[openai]\nbase_url = "https://api.example.com/v1"\nmodel = "gpt-5.4"\n',
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"OPENAI_API_KEY": "secret-key"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(codex_root=codex_root)

    assert isinstance(settings, RuntimeSettings)
    assert settings.base_url == "https://api.example.com/v1"
    assert settings.model == "gpt-5.4"
    assert settings.api_key == "secret-key"


def test_cli_overrides_replace_codex_defaults(tmp_path: Path):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        '[openai]\nbase_url = "https://api.example.com/v1"\nmodel = "gpt-5.4"\n',
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"OPENAI_API_KEY": "secret-key"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(
        codex_root=codex_root,
        model_override="gpt-5.2",
        base_url_override="https://override.example.com/v1",
    )

    assert settings.model == "gpt-5.2"
    assert settings.base_url == "https://override.example.com/v1"


def test_redacted_api_key_masks_after_first_four_chars():
    settings = RuntimeSettings(
        codex_root=Path("/tmp/.codex"),
        base_url="https://api.openai.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

    assert settings.redacted_api_key == "secr..."


def test_load_runtime_settings_uses_defaults_when_openai_values_missing(tmp_path: Path):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        "",
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"OPENAI_API_KEY": "secret-key"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(codex_root=codex_root)

    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.model == "gpt-5.4"


def test_load_runtime_settings_reads_api_key_fallback_field(tmp_path: Path):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        '[openai]\nbase_url = "https://api.example.com/v1"\nmodel = "gpt-5.4"\n',
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"api_key": "fallback-secret"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(codex_root=codex_root)

    assert settings.api_key == "fallback-secret"
