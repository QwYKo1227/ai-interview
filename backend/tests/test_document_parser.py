import logging

import httpx
import pytest

from app.services import document_parser, resume_service


def test_http_document_parser_returns_markdown_and_sends_resume_options(tmp_path):
    document = tmp_path / "candidate.pdf"
    document.write_bytes(b"synthetic-pdf")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "results": {
                    "candidate": {
                        "md_content": "# Candidate\n\nPython engineer"
                    }
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        parser = document_parser.HttpDocumentParser(
            base_url="http://parser.test",
            vlm_server_url="http://vlm.test",
            max_pages=20,
            client=client,
        )
        result = parser.extract_text(str(document))

    assert result == "# Candidate\n\nPython engineer"
    assert seen["url"] == "http://parser.test/file_parse"
    body = seen["body"]
    assert b'candidate.pdf' in body
    assert b'vlm-http-client' in body
    assert b'http://vlm.test' in body
    assert b'formula_enable' in body and b'false' in body
    assert b'table_enable' in body and b'true' in body
    assert b'return_middle_json' in body and b'true' in body
    assert b'return_content_list' in body and b'true' in body
    assert b'end_page_id' in body and b'19' in body


def test_http_document_parser_merges_discarded_headers_before_markdown():
    result = document_parser.HttpDocumentParser._extract_markdown(
        {
            "status": "completed",
            "results": {
                "candidate": {
                    "md_content": "# 教育背景\n\n香港科技大学",
                    "content_list": """[
                        {
                            "type": "header",
                            "text": "手机：13600000000｜邮箱：candidate@example.com",
                            "bbox": [50, 80, 400, 100],
                            "page_idx": 0
                        }
                    ]""",
                    "middle_json": {
                        "pdf_info": [
                            {
                                "page_idx": 0,
                                "discarded_blocks": [
                                    {
                                        "type": "header",
                                        "bbox": [50, 30, 120, 55],
                                        "lines": [
                                            {
                                                "spans": [
                                                    {"content": "宋卓飞"}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "type": "header",
                                        "bbox": [50, 80, 400, 100],
                                        "text": "手机：13600000000｜邮箱：candidate@example.com"
                                    },
                                    {
                                        "type": "footer",
                                        "bbox": [50, 800, 100, 820],
                                        "text": "第 1 页"
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
    )

    assert result == (
        "宋卓飞\n\n"
        "手机：13600000000｜邮箱：candidate@example.com\n\n"
        "# 教育背景\n\n香港科技大学"
    )


def test_http_document_parser_returns_remote_markdown_without_native_identity(
    tmp_path,
):
    document = tmp_path / "candidate.pdf"
    document.write_bytes(b"synthetic-pdf")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "results": {
                    "candidate": {
                        "md_content": "# 教育背景\n\n香港科技大学"
                    }
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        parser = document_parser.HttpDocumentParser(
            base_url="http://parser.test", client=client
        )
        result = parser.extract_text(str(document))

    assert result == "# 教育背景\n\n香港科技大学"


@pytest.mark.parametrize(
    ("parsed_data", "document", "expected"),
    [
        (
            {
                "candidate_name": "洪梦娇",
                "contact": "",
                "email": "",
            },
            "姓名：其他人\n电话：15808669005\n邮箱：candidate@example.com",
            {
                "candidate_name": "洪梦娇",
                "contact": "15808669005",
                "email": "candidate@example.com",
            },
        ),
        (
            {
                "candidate_name": "Jennifer Garcia Vega",
                "contact": "+1 (510) 459-2741",
                "email": "JENGARCIAVEGA@ICLOUD.COM",
            },
            (
                "Jennifer Garcia Vega, Director of Marketing\n"
                "(510) 459-2741, jengarciavega@icloud.com"
            ),
            {
                "candidate_name": "Jennifer Garcia Vega",
                "contact": "15104592741",
                "email": "jengarciavega@icloud.com",
            },
        ),
        (
            {
                "candidate_name": "候选人",
                "contact": "未提供",
                "email": "未提供",
            },
            "姓 名 ：郑冬梅\n教育背景",
            {"candidate_name": "", "contact": "", "email": ""},
        ),
    ],
)
def test_resume_identity_uses_llm_then_validates_and_falls_back_exact_fields(
    parsed_data, document, expected
):
    assert resume_service._resolve_resume_identity(parsed_data, document) == expected


def test_resume_identity_does_not_guess_ambiguous_contact_fields():
    assert resume_service._resolve_resume_identity(
        {
            "candidate_name": "Jane Doe",
            "contact": "",
            "email": "",
        },
        (
            "手机：13662660569，备用：15808669005\n"
            "candidate@example.com，other@example.com"
        ),
    ) == {
        "candidate_name": "Jane Doe",
        "contact": "",
        "email": "",
    }


def test_http_document_parser_rejects_empty_result_without_leaking_response(
    tmp_path, caplog
):
    document = tmp_path / "candidate.pdf"
    document.write_bytes(b"synthetic-pdf")
    secret = "Authorization: Bearer SECRET"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=secret)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        parser = document_parser.HttpDocumentParser(
            base_url="http://parser.test", client=client
        )
        with caplog.at_level(logging.WARNING), pytest.raises(
            document_parser.DocumentParserError,
            match="document parsing failed",
        ):
            parser.extract_text(str(document))

    assert secret not in caplog.text


def test_resume_processing_uses_document_parser_for_normal_pdf(
    db, tenant_a, test_position, test_resume, monkeypatch
):
    extracted = "# Unified parser candidate\n\nFive years of Python experience"
    seen = []

    monkeypatch.setattr(
        resume_service,
        "extract_document_text",
        lambda path: seen.append(path) or extracted,
    )
    monkeypatch.setattr(
        resume_service,
        "analyze_resume",
        lambda *_args, **_kwargs: {
            "candidate_name": "Unified Candidate",
            "contact": "",
            "email": "candidate@example.invalid",
            "match_score": 75,
            "screening_result": "passed",
            "ai_review": "Suitable",
            "other_position_matches": [],
        },
    )
    monkeypatch.setattr(
        resume_service,
        "read_file_content",
        lambda _path: pytest.fail("local PDF extraction must not be used"),
    )

    resume_service._process_resume_task(
        db,
        tenant_a.id,
        test_resume.id,
        {"position_id": test_position.id},
    )

    db.refresh(test_resume)
    assert seen == [test_resume.file_path]
    assert test_resume.raw_text == extracted
    assert test_resume.resume_markdown == extracted
    assert test_resume.parse_status == "success"
    assert test_resume.candidate_name == "Unified Candidate"


def test_resume_processing_protects_only_user_supplied_identity_fields(
    db, tenant_a, test_position, test_resume, monkeypatch
):
    extracted = (
        "# 宋卓飞\n"
        "手机：13662660569\n"
        "邮箱：candidate@example.com\n\n"
        "# 教育背景\n\n香港科技大学"
    )
    monkeypatch.setattr(
        resume_service, "extract_document_text", lambda _path: extracted
    )
    monkeypatch.setattr(
        resume_service,
        "analyze_resume",
        lambda *_args, **_kwargs: {
            "candidate_name": "宋卓飞",
            "contact": "13662660569",
            "email": "candidate@example.com",
            "match_score": 75,
            "screening_result": "passed",
            "ai_review": "Suitable",
            "other_position_matches": [],
        },
    )
    test_resume.candidate_name = "解析中..."
    test_resume.contact = None
    test_resume.email = "user@example.com"
    db.commit()

    resume_service._process_resume_task(
        db,
        tenant_a.id,
        test_resume.id,
        {
            "position_id": test_position.id,
            "protected_identity_fields": ["email"],
        },
    )

    db.refresh(test_resume)
    assert test_resume.parse_status == "success"
    assert test_resume.candidate_name == "宋卓飞"
    assert test_resume.contact == "13662660569"
    assert test_resume.email == "user@example.com"
    assert test_resume.parsed_data["email"] == "user@example.com"
