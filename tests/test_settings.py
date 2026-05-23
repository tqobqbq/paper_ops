from pathlib import Path

from paper_ops.settings import RuntimeSettings, load_runtime_settings, resolve_library_root


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


def test_load_runtime_settings_uses_selected_model_provider_config(tmp_path: Path):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        '[openai]\n'
        'base_url = "https://api.example.com/v1"\n'
        'model = "gpt-5.4"\n'
        '\n'
        'model_provider = "custom_provider"\n'
        '\n'
        "[model_providers.custom_provider]\n"
        'base_url = "http://127.0.0.1:8317/v1"\n'
        'model = "gpt-5.6"\n',
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"OPENAI_API_KEY": "secret-key"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(codex_root=codex_root)

    assert settings.base_url == "http://127.0.0.1:8317/v1"
    assert settings.model == "gpt-5.6"


def test_load_runtime_settings_uses_selected_model_provider_config_without_openai_block(
    tmp_path: Path,
):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        'model_provider = "custom_provider"\n'
        '\n'
        "[model_providers.custom_provider]\n"
        'base_url = "http://127.0.0.1:8317/v1"\n',
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"OPENAI_API_KEY": "secret-key"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(codex_root=codex_root)

    assert settings.base_url == "http://127.0.0.1:8317/v1"
    assert settings.model == "gpt-5.4"


def test_load_runtime_settings_supports_claude_provider_override(tmp_path: Path):
    codex_root = tmp_path / ".codex"
    codex_root.mkdir()
    (codex_root / "config.toml").write_text(
        "",
        encoding="utf-8",
    )
    (codex_root / "auth.json").write_text(
        '{"ANTHROPIC_API_KEY": "claude-secret"}',
        encoding="utf-8",
    )

    settings = load_runtime_settings(
        codex_root=codex_root,
        model_provider_override="claude",
    )

    assert settings.model_provider == "claude"
    assert settings.base_url == "https://api.anthropic.com/v1/"
    assert settings.model == "claude-sonnet-4-20250514"
    assert settings.api_key == "claude-secret"


def test_resolve_library_root_prefers_explicit_override(
    tmp_path: Path,
    monkeypatch,
):
    explicit_root = tmp_path / "explicit-papers"
    monkeypatch.setenv("PAPER_OPS_LIBRARY_ROOT", str(tmp_path / "env-papers"))

    assert (
        resolve_library_root(library_root_override=explicit_root, cwd=tmp_path)
        == explicit_root
    )


def test_resolve_library_root_uses_env_when_no_override(
    tmp_path: Path,
    monkeypatch,
):
    env_root = tmp_path / "env-papers"
    monkeypatch.setenv("PAPER_OPS_LIBRARY_ROOT", str(env_root))

    assert resolve_library_root(cwd=tmp_path) == env_root


def test_resolve_library_root_defaults_to_cwd_papers(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("PAPER_OPS_LIBRARY_ROOT", raising=False)

    assert resolve_library_root(cwd=tmp_path) == tmp_path / "papers"
