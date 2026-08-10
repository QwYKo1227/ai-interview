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
    assert b'end_page_id' in body and b'19' in body


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
