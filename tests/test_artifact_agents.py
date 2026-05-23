from pathlib import Path
import threading
import time
from unittest.mock import Mock, patch

from paper_ops.artifact_agents import (
    ARTIFACT_SPECS,
    ArtifactRunSummary,
    SourcePayload,
    _prepare_source_payload,
    _run_artifact_agent,
    generate_parallel_artifacts_from_pdf,
)
from paper_ops.models import PaperPaths
from paper_ops.settings import RuntimeSettings


def _artifact_spec(name: str):
    return next(spec for spec in ARTIFACT_SPECS if spec.name == name)


def test_generate_parallel_artifacts_from_pdf_uses_pdf_text_bundle(
    tmp_path: Path, monkeypatch
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    paths = PaperPaths(
        paper_dir=paper_dir,
        pdf_path=pdf_path,
        metadata_path=paper_dir / "metadata.json",
        translation_path=paper_dir / "translation_zh.md",
        summary_path=paper_dir / "summary_zh.md",
        experiments_path=paper_dir / "experiments_zh.md",
        notes_path=paper_dir / "notes_zh.md",
        code_links_path=paper_dir / "code_links.json",
        relevance_path=paper_dir / "relevance_to_my_research.md",
    )
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

    seen_sources: list[SourcePayload] = []

    monkeypatch.setattr(
        "paper_ops.artifact_agents._pdf_text_bundle",
        lambda pdf_path: "pdf text bundle",
    )
    monkeypatch.setattr(
        "paper_ops.artifact_agents._supports_file_upload",
        lambda base_url: False,
    )

    def fake_run_artifact_agent(*, source, spec, output_path, metadata, settings):
        seen_sources.append(source)
        assert source.file_id is None
        assert source.text == "pdf text bundle"
        if spec.output_kind == "json":
            output_path.write_text(
                '{"official":[],"community":[],"mentioned_but_unlinked":[],"baseline_ready":false,"baseline_ready_reason":"信息不足"}',
                encoding="utf-8",
            )
        else:
            output_path.write_text(f"# {spec.name}\n", encoding="utf-8")
        return output_path

    monkeypatch.setattr("paper_ops.artifact_agents._run_artifact_agent", fake_run_artifact_agent)

    summary = generate_parallel_artifacts_from_pdf(
        pdf_path=pdf_path,
        paths=paths,
        metadata={
            "title": "Example Paper",
            "authors": ["Author"],
            "year": 2026,
            "venue": "ICLR",
            "direction": "predictive_coding",
            "keywords": ["predictive coding"],
        },
        settings=settings,
    )

    assert isinstance(summary, ArtifactRunSummary)
    assert summary.failed == {}
    assert sorted(summary.completed) == sorted(spec.name for spec in ARTIFACT_SPECS)
    assert len(seen_sources) == len(ARTIFACT_SPECS)


def test_generate_parallel_artifacts_from_pdf_respects_model_concurrency_env(
    tmp_path: Path,
    monkeypatch,
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    paths = PaperPaths(
        paper_dir=paper_dir,
        pdf_path=pdf_path,
        metadata_path=paper_dir / "metadata.json",
        translation_path=paper_dir / "translation_zh.md",
        summary_path=paper_dir / "summary_zh.md",
        experiments_path=paper_dir / "experiments_zh.md",
        notes_path=paper_dir / "notes_zh.md",
        code_links_path=paper_dir / "code_links.json",
        relevance_path=paper_dir / "relevance_to_my_research.md",
    )
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )
    active = 0
    max_active = 0
    lock = threading.Lock()

    monkeypatch.setenv("PAPER_OPS_MAX_MODEL_CONCURRENCY", "1")
    monkeypatch.setattr(
        "paper_ops.artifact_agents._prepare_source_payload",
        lambda source_path, is_pdf, settings: SourcePayload(text="pdf text bundle"),
    )

    def fake_run_artifact_agent(*, source, spec, output_path, metadata, settings):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        output_path.write_text(f"# {spec.name}\n", encoding="utf-8")
        with lock:
            active -= 1
        return output_path

    monkeypatch.setattr(
        "paper_ops.artifact_agents._run_artifact_agent",
        fake_run_artifact_agent,
    )

    summary = generate_parallel_artifacts_from_pdf(
        pdf_path=pdf_path,
        paths=paths,
        metadata={
            "title": "Example Paper",
            "authors": ["Author"],
            "year": 2026,
            "venue": "ICLR",
            "direction": "predictive_coding",
            "keywords": ["predictive coding"],
        },
        settings=settings,
    )

    assert summary.failed == {}
    assert max_active == 1


def test_prepare_source_payload_uses_file_upload_for_pdf_when_supported(
    tmp_path: Path, monkeypatch
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

    pdf_bundle_mock = Mock(side_effect=AssertionError("pdf text fallback should not run"))
    monkeypatch.setattr("paper_ops.artifact_agents._pdf_text_bundle", pdf_bundle_mock)
    monkeypatch.setattr("paper_ops.artifact_agents._supports_file_upload", lambda base_url: True)
    monkeypatch.setattr("paper_ops.artifact_agents.upload_pdf_file", lambda pdf_path, settings: "file-123")

    source = _prepare_source_payload(pdf_path, is_pdf=True, settings=settings)

    assert source.file_id == "file-123"
    assert source.text is None
    pdf_bundle_mock.assert_not_called()


def test_run_artifact_agent_uses_chat_completions_for_markdown_output(
    tmp_path: Path, monkeypatch
):
    output_path = tmp_path / "translation_zh.md"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )
    source = SourcePayload(text="pdf text bundle")
    metadata = {
        "title": "Example Paper",
        "authors": ["Author"],
        "year": 2026,
        "venue": "ICLR",
        "direction": "predictive_coding",
        "keywords": ["predictive coding"],
    }

    response = Mock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "# 中文翻译\n\n这是测试翻译。",
                }
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("paper_ops.artifact_agents.requests.request", return_value=response) as request_mock:
        _run_artifact_agent(
            source=source,
            spec=ARTIFACT_SPECS[0],
            output_path=output_path,
            metadata=metadata,
            settings=settings,
        )

    assert output_path.read_text(encoding="utf-8").startswith("# 中文翻译")
    assert request_mock.call_count == 1
    call = request_mock.call_args
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["url"] == "https://api.example.com/v1/chat/completions"
    payload = call.kwargs["json"]
    assert payload["model"] == "gpt-5.4"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert "pdf text bundle" in payload["messages"][1]["content"]
    assert "max_tokens" not in payload
    assert "response_format" not in payload


def test_artifact_specs_cover_all_single_paper_outputs():
    spec_paths = {spec.output_path_attr for spec in ARTIFACT_SPECS}

    assert spec_paths == {
        "summary_path",
        "experiments_path",
        "notes_path",
        "code_links_path",
        "relevance_path",
    }


def test_run_artifact_agent_uses_file_input_when_source_has_file_id(
    tmp_path: Path,
):
    output_path = tmp_path / "translation_zh.md"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )
    source = SourcePayload(file_id="file-abc")
    metadata = {
        "title": "Example Paper",
        "authors": ["Author"],
        "year": 2026,
        "venue": "ICLR",
        "direction": "predictive_coding",
        "keywords": ["predictive coding"],
    }

    response = Mock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "# 中文翻译\n\n这是测试翻译。",
                }
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("paper_ops.artifact_agents.requests.request", return_value=response) as request_mock:
        _run_artifact_agent(
            source=source,
            spec=ARTIFACT_SPECS[0],
            output_path=output_path,
            metadata=metadata,
            settings=settings,
        )

    payload = request_mock.call_args.kwargs["json"]
    content = payload["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "file", "file": {"file_id": "file-abc"}}
    assert content[1]["type"] == "text"
    assert "Paper metadata" in content[1]["text"]


def test_run_artifact_agent_uses_one_hour_timeout_by_default(
    tmp_path: Path, monkeypatch
):
    output_path = tmp_path / "translation_zh.md"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )
    source = SourcePayload(text="pdf text bundle")
    metadata = {
        "title": "Example Paper",
        "authors": ["Author"],
        "year": 2026,
        "venue": "ICLR",
        "direction": "predictive_coding",
        "keywords": ["predictive coding"],
    }

    monkeypatch.delenv("PAPER_OPS_RESPONSE_TIMEOUT_SECONDS", raising=False)

    response = Mock()
    response.json.return_value = {
        "choices": [{"message": {"content": "# 中文翻译\n\n这是测试翻译。"}}]
    }
    response.raise_for_status.return_value = None

    with patch("paper_ops.artifact_agents.requests.request", return_value=response) as request_mock:
        _run_artifact_agent(
            source=source,
            spec=ARTIFACT_SPECS[0],
            output_path=output_path,
            metadata=metadata,
            settings=settings,
        )

    assert request_mock.call_args.kwargs["timeout"] == 3600


def test_run_artifact_agent_uses_timeout_override_from_env(
    tmp_path: Path, monkeypatch
):
    output_path = tmp_path / "translation_zh.md"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )
    source = SourcePayload(text="pdf text bundle")
    metadata = {
        "title": "Example Paper",
        "authors": ["Author"],
        "year": 2026,
        "venue": "ICLR",
        "direction": "predictive_coding",
        "keywords": ["predictive coding"],
    }

    monkeypatch.setenv("PAPER_OPS_RESPONSE_TIMEOUT_SECONDS", "42")

    response = Mock()
    response.json.return_value = {
        "choices": [{"message": {"content": "# 中文翻译\n\n这是测试翻译。"}}]
    }
    response.raise_for_status.return_value = None

    with patch("paper_ops.artifact_agents.requests.request", return_value=response) as request_mock:
        _run_artifact_agent(
            source=source,
            spec=ARTIFACT_SPECS[0],
            output_path=output_path,
            metadata=metadata,
            settings=settings,
        )

    assert request_mock.call_args.kwargs["timeout"] == 42


def test_run_artifact_agent_enforces_json_object_response_format(
    tmp_path: Path, monkeypatch
):
    output_path = tmp_path / "code_links.json"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )
    source = SourcePayload(text="pdf text bundle")
    metadata = {
        "title": "Example Paper",
        "authors": ["Author"],
        "year": 2026,
        "venue": "ICLR",
        "direction": "predictive_coding",
        "keywords": ["predictive coding"],
    }

    response = Mock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"official":[],"community":[],"mentioned_but_unlinked":'
                        '[],"baseline_ready":false,"baseline_ready_reason":"信息不足"}'
                    ),
                }
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("paper_ops.artifact_agents.requests.request", return_value=response) as request_mock:
        _run_artifact_agent(
            source=source,
            spec=_artifact_spec("code_links"),
            output_path=output_path,
            metadata=metadata,
            settings=settings,
        )

    parsed = output_path.read_text(encoding="utf-8")
    assert '"baseline_ready": false' in parsed
    assert request_mock.call_count == 1
    payload = request_mock.call_args.kwargs["json"]
    assert payload["response_format"] == {"type": "json_object"}


def test_run_artifact_agent_omits_response_format_for_claude(
    tmp_path: Path, monkeypatch
):
    output_path = tmp_path / "code_links.json"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.anthropic.com/v1/",
        model="claude-sonnet-4-20250514",
        api_key="secret-key",
        model_provider="claude",
    )
    source = SourcePayload(text="pdf text bundle")
    metadata = {
        "title": "Example Paper",
        "authors": ["Author"],
        "year": 2026,
        "venue": "ICLR",
        "direction": "predictive_coding",
        "keywords": ["predictive coding"],
    }

    response = Mock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"official":[],"community":[],"mentioned_but_unlinked":'
                        '[],"baseline_ready":false,"baseline_ready_reason":"信息不足"}'
                    ),
                }
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("paper_ops.artifact_agents.requests.request", return_value=response) as request_mock:
        _run_artifact_agent(
            source=source,
            spec=_artifact_spec("code_links"),
            output_path=output_path,
            metadata=metadata,
            settings=settings,
        )

    payload = request_mock.call_args.kwargs["json"]
    assert "response_format" not in payload
