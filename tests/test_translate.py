from pathlib import Path
from unittest.mock import Mock, patch

from paper_ops.settings import RuntimeSettings
from paper_ops.translate import translate_pdf_to_markdown


def test_translate_pdf_to_markdown_uploads_file_and_writes_output(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    output_path = tmp_path / "translation_zh.md"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

    file_response = Mock()
    file_response.json.return_value = {"id": "file-123"}
    file_response.raise_for_status.return_value = None

    translate_response = Mock()
    translate_response.json.return_value = {
        "output_text": "# 中文翻译\n\n这是测试翻译。"
    }
    translate_response.raise_for_status.return_value = None

    with patch(
        "paper_ops.translate.requests.post",
        side_effect=[file_response, translate_response],
    ) as post_mock:
        translate_pdf_to_markdown(pdf_path, output_path, settings)

    assert output_path.read_text(encoding="utf-8").startswith("# 中文翻译")
    assert post_mock.call_count == 2

    upload_call = post_mock.call_args_list[0]
    assert upload_call.args[0] == "https://api.example.com/v1/files"
    assert upload_call.kwargs["headers"] == {"Authorization": "Bearer secret-key"}
    assert upload_call.kwargs["data"] == {"purpose": "user_data"}
    assert upload_call.kwargs["timeout"] == 120
    assert "file" in upload_call.kwargs["files"]
    upload_file = upload_call.kwargs["files"]["file"]
    assert upload_file[0] == "paper.pdf"
    assert upload_file[2] == "application/pdf"

    response_call = post_mock.call_args_list[1]
    assert response_call.args[0] == "https://api.example.com/v1/responses"
    assert response_call.kwargs["headers"] == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
    }
    assert response_call.kwargs["timeout"] == 300
    assert response_call.kwargs["json"]["model"] == "gpt-5.4"
    user_input = response_call.kwargs["json"]["input"][0]["content"]
    assert user_input[0]["type"] == "input_text"
    assert "Chinese" in user_input[0]["text"]
    assert user_input[1] == {"type": "input_file", "file_id": "file-123"}


def test_translate_prompt_asset_exists():
    prompt_path = Path(
        "/root/projects/paper_ops/src/paper_ops/prompts/translate_fulltext.md"
    )
    assert prompt_path.exists()
    assert "Chinese" in prompt_path.read_text(encoding="utf-8")
