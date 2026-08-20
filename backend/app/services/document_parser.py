import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx


logger = logging.getLogger(__name__)

DEFAULT_DOCUMENT_PARSER_URL = "http://10.10.60.20:10021"
DEFAULT_VLM_SERVER_URL = "http://127.0.0.1:10020"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_PAGES = 20


class DocumentParserError(RuntimeError):
    """Sanitized error raised when remote document extraction fails."""


class HttpDocumentParser:
    """Extract document text through the owned remote parsing service."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        vlm_server_url: str | None = None,
        timeout_seconds: float | None = None,
        max_pages: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("DOCUMENT_PARSER_URL") or DEFAULT_DOCUMENT_PARSER_URL
        ).rstrip("/")
        self.vlm_server_url = (
            vlm_server_url
            or os.getenv("DOCUMENT_PARSER_VLM_SERVER_URL")
            or DEFAULT_VLM_SERVER_URL
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("DOCUMENT_PARSER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )
        self.max_pages = max_pages or int(
            os.getenv("DOCUMENT_PARSER_MAX_PAGES", DEFAULT_MAX_PAGES)
        )
        self.client = client

    def extract_text(self, file_path: str) -> str:
        path = Path(file_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = {
            "backend": "vlm-http-client",
            "server_url": self.vlm_server_url,
            "formula_enable": "false",
            "table_enable": "true",
            "image_analysis": "false",
            "return_md": "true",
            "return_middle_json": "true",
            "return_model_output": "false",
            "return_content_list": "true",
            "return_images": "false",
            "response_format_zip": "false",
            "start_page_id": "0",
            "end_page_id": str(max(self.max_pages - 1, 0)),
        }

        try:
            with path.open("rb") as document:
                files = {"files": (path.name, document, content_type)}
                if self.client is None:
                    with httpx.Client(timeout=self.timeout_seconds) as client:
                        response = client.post(
                            f"{self.base_url}/file_parse", data=data, files=files
                        )
                else:
                    response = self.client.post(
                        f"{self.base_url}/file_parse", data=data, files=files
                    )
            response.raise_for_status()
            return self._extract_markdown(response.json())
        except (OSError, httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            status_code = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else None
            )
            logger.warning(
                "Document parser request failed",
                extra={
                    "error_code": "document_parser_request",
                    "exception_type": type(error).__name__,
                    "provider_status": status_code,
                },
            )
            raise DocumentParserError("document parsing failed") from None

    @staticmethod
    def _extract_markdown(payload: Any) -> str:
        if not isinstance(payload, dict) or payload.get("status") != "completed":
            raise ValueError("Invalid document parser response")

        results = payload.get("results")
        if not isinstance(results, dict) or not results:
            raise ValueError("Missing document parser results")

        markdown_parts = []
        for result in results.values():
            if not isinstance(result, dict):
                continue
            markdown = result.get("md_content")
            if isinstance(markdown, str) and markdown.strip():
                headers = HttpDocumentParser._extract_headers(result)
                parts = [*headers, markdown.strip()]
                markdown_parts.append("\n\n".join(parts))

        if not markdown_parts:
            raise ValueError("Missing document parser markdown")
        return "\n\n".join(markdown_parts)

    @staticmethod
    def _extract_headers(result: dict[str, Any]) -> list[str]:
        """Recover header blocks omitted from the parser's Markdown output."""
        blocks: list[tuple[int, float, float, int, str]] = []
        sequence = 0

        content_list = HttpDocumentParser._decode_optional_json(
            result.get("content_list")
        )
        if isinstance(content_list, list):
            for item in content_list:
                if not isinstance(item, dict) or item.get("type") != "header":
                    continue
                text = HttpDocumentParser._block_text(item)
                if text:
                    page = HttpDocumentParser._as_int(item.get("page_idx"), 0)
                    y, x = HttpDocumentParser._block_position(item)
                    blocks.append((page, y, x, sequence, text))
                    sequence += 1

        middle_json = HttpDocumentParser._decode_optional_json(
            result.get("middle_json")
        )
        if isinstance(middle_json, dict):
            pdf_info = middle_json.get("pdf_info")
            if isinstance(pdf_info, list):
                for page_index, page_info in enumerate(pdf_info):
                    if not isinstance(page_info, dict):
                        continue
                    page = HttpDocumentParser._as_int(
                        page_info.get("page_idx"), page_index
                    )
                    discarded = page_info.get("discarded_blocks")
                    if not isinstance(discarded, list):
                        continue
                    for item in discarded:
                        if (
                            not isinstance(item, dict)
                            or item.get("type") != "header"
                        ):
                            continue
                        text = HttpDocumentParser._block_text(item)
                        if text:
                            y, x = HttpDocumentParser._block_position(item)
                            blocks.append((page, y, x, sequence, text))
                            sequence += 1

        headers = []
        seen = set()
        for _page, _y, _x, _sequence, text in sorted(blocks):
            normalized = " ".join(text.split()).casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                headers.append(text)
        return headers

    @staticmethod
    def _decode_optional_json(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _block_text(block: dict[str, Any]) -> str:
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        lines = block.get("lines")
        if not isinstance(lines, list):
            return ""
        line_texts = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            spans = line.get("spans")
            if not isinstance(spans, list):
                continue
            span_text = "".join(
                span.get("content", "")
                for span in spans
                if isinstance(span, dict)
                and isinstance(span.get("content"), str)
            ).strip()
            if span_text:
                line_texts.append(span_text)
        return "\n".join(line_texts)

    @staticmethod
    def _block_position(block: dict[str, Any]) -> tuple[float, float]:
        bbox = block.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 2:
            try:
                return float(bbox[1]), float(bbox[0])
            except (TypeError, ValueError):
                pass
        return 0.0, 0.0

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

def extract_document_text(file_path: str) -> str:
    """Small interface used by resume processing for all document extraction."""
    return HttpDocumentParser().extract_text(file_path)
