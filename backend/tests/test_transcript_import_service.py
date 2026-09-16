from fastapi import HTTPException

from app.services.transcript_import_service import parse_transcript_bytes


def test_parses_webvtt_from_txt_with_original_timestamps_and_speakers():
    parsed = parse_transcript_bytes(
        """WEBVTT

00:18:32.000 --> 00:18:34.000
Jia min: 嗯嗯。

00:18:38.000 --> 00:18:42.000
yj: 赵女士，您先稍等一下。
""".encode("utf-8"),
        "线上面试.txt",
    )

    assert parsed["format"] == "webvtt"
    assert parsed["has_timestamps"] is True
    assert parsed["speakers"] == ["Jia min", "yj"]
    assert parsed["segments"][0] == {
        "id": "import-1",
        "start": 1112.0,
        "end": 1114.0,
        "speaker": "Jia min",
        "text": "嗯嗯。",
    }


def test_plain_text_is_kept_and_warns_about_missing_timestamps():
    parsed = parse_transcript_bytes("候选人：我负责质量体系。\n面试官：请继续。".encode("gb18030"), "面试.txt")

    assert parsed["format"] == "plain_text"
    assert parsed["has_timestamps"] is False
    assert parsed["segments"][0]["speaker"] == "候选人"
    assert "不包含可靠时间戳" in parsed["warnings"][0]


def test_rejects_unsupported_extension():
    try:
        parse_transcript_bytes(b"content", "interview.srt")
    except HTTPException as error:
        assert error.status_code == 422
        assert error.detail == "仅支持 .txt 和 .vtt 文件"
    else:
        raise AssertionError("unsupported extension was accepted")
