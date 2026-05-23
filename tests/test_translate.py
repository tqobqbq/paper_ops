from pathlib import Path
from unittest.mock import Mock, patch

from paper_ops.settings import RuntimeSettings
from paper_ops.translate import _extract_output_text, translate_pdf_to_markdown


def test_translate_pdf_to_markdown_uses_chat_completions_and_writes_output(
    tmp_path: Path,
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    output_path = tmp_path / "translation_zh.md"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

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

    with (
        patch(
            "paper_ops.artifact_agents._pdf_text_bundle",
            return_value="pdf text bundle",
        ) as pdf_bundle_mock,
        patch(
            "paper_ops.artifact_agents._supports_file_upload",
            return_value=False,
        ),
        patch(
            "paper_ops.artifact_agents.requests.request",
            return_value=response,
        ) as request_mock,
    ):
        translate_pdf_to_markdown(pdf_path, output_path, settings)

    assert output_path.read_text(encoding="utf-8").startswith("# 中文翻译")
    pdf_bundle_mock.assert_called_once_with(pdf_path)

    assert request_mock.call_count == 1
    call = request_mock.call_args
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["url"] == "https://api.example.com/v1/chat/completions"
    payload = call.kwargs["json"]
    assert payload["model"] == "gpt-5.4"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert "Paper metadata" in payload["messages"][1]["content"]
    assert "pdf text bundle" in payload["messages"][1]["content"]
    assert "response_format" not in payload


def test_translate_prompt_asset_exists():
    prompt_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "paper_ops"
        / "prompts"
        / "translate_fulltext.md"
    )
    assert prompt_path.exists()
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "source of truth" in prompt_text
    assert "Do not summarize" in prompt_text


def test_extract_output_text_reads_chat_completions_shape():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": {"value": "# 中文翻译"}},
                        {"type": "text", "text": "第二段"},
                    ]
                }
            }
        ]
    }

    output = _extract_output_text(payload)
    assert "# 中文翻译" in output
    assert "第二段" in output
