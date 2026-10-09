import base64
import json
import logging
from types import SimpleNamespace

import pymupdf

from app.config import Settings
from app.service import WireExtractionService


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.request: dict[str, object] | None = None

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.request = kwargs
        return SimpleNamespace(output_text=self.output_text)


def sample_pdf(page_count: int = 1) -> bytes:
    document = pymupdf.open()
    try:
        for page_number in range(page_count):
            page = document.new_page()
            page.insert_text((72, 72), f"Sample page {page_number + 1}")
        return document.tobytes()
    finally:
        document.close()


def test_service_renders_pdf_pages_as_images_and_flags_missing_values() -> None:
    output = {
        "beneficiary_name": {"value": "Ada Lovelace", "confidence": 0.99, "page": 1},
        "beneficiary_address": {"value": "1 Example Way", "confidence": 0.99, "page": 1},
        "bank_name": {"value": "Example Bank", "confidence": 0.99, "page": 1},
        "bank_address": {"value": "2 Bank Road", "confidence": 0.99, "page": 1},
        "routing_number_aba": {"value": "123456789", "confidence": 0.99, "page": 1},
        "account_number": {"value": None, "confidence": 0.0, "page": None},
    }
    responses = FakeResponses(json.dumps(output))
    client = SimpleNamespace(responses=responses)
    settings = Settings(
        azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/",
        azure_ai_foundry_api_key="test-key",
    )

    result = WireExtractionService(settings, client=client).extract(
        content=sample_pdf(page_count=2),
        filename="instruction.pdf",
        content_type="application/pdf",
        document_source="instruction.pdf",
    )

    assert result.manual_review_required is True
    assert result.fields.account_number.value is None
    assert responses.request is not None
    document_parts = responses.request["input"][1]["content"]
    assert [part["type"] for part in document_parts[:2]] == ["input_image", "input_image"]
    assert all(part["image_url"].startswith("data:image/png;base64,") for part in document_parts[:2])
    assert document_parts[2]["text"].startswith("The preceding images are PDF pages in order")


def test_service_sends_images_as_input_images() -> None:
    output = {
        "beneficiary_name": {"value": None, "confidence": 0.0, "page": None},
        "beneficiary_address": {"value": None, "confidence": 0.0, "page": None},
        "bank_name": {"value": None, "confidence": 0.0, "page": None},
        "bank_address": {"value": None, "confidence": 0.0, "page": None},
        "routing_number_aba": {"value": None, "confidence": 0.0, "page": None},
        "account_number": {"value": None, "confidence": 0.0, "page": None},
    }
    responses = FakeResponses(json.dumps(output))
    service = WireExtractionService(
        Settings(
            azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/",
            azure_ai_foundry_api_key="test-key",
        ),
        client=SimpleNamespace(responses=responses),
    )

    service.extract(
        content=b"image bytes",
        filename="instruction.png",
        content_type="image/png",
        document_source="instruction.png",
    )

    assert responses.request is not None
    image_part = responses.request["input"][1]["content"][0]
    assert image_part["type"] == "input_image"
    assert image_part["image_url"] == (
        "data:image/png;base64," + base64.b64encode(b"image bytes").decode("ascii")
    )


def test_service_logs_raw_model_response_when_enabled(caplog) -> None:
    output = {
        "beneficiary_name": {"value": None, "confidence": 0.0, "page": None},
        "beneficiary_address": {"value": None, "confidence": 0.0, "page": None},
        "bank_name": {"value": None, "confidence": 0.0, "page": None},
        "bank_address": {"value": None, "confidence": 0.0, "page": None},
        "routing_number_aba": {"value": None, "confidence": 0.0, "page": None},
        "account_number": {"value": None, "confidence": 0.0, "page": None},
    }
    responses = FakeResponses(json.dumps(output))
    service = WireExtractionService(
        Settings(
            azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/",
            azure_ai_foundry_api_key="test-key",
            log_model_responses=True,
        ),
        client=SimpleNamespace(responses=responses),
    )

    with caplog.at_level(logging.WARNING, logger="app.service"):
        service.extract(
            content=sample_pdf(),
            filename="instruction.pdf",
            content_type="application/pdf",
            document_source="instruction.pdf",
        )

    assert "Azure AI Foundry response for instruction.pdf" in caplog.text
    assert json.dumps(output) in caplog.text


def ocr_service(output: dict, pages: list[str], status: int = 200, **settings: object):
    import httpx

    from app.service import MistralOcr

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        if status != 200:
            return httpx.Response(status, headers={"retry-after": "0"})
        return httpx.Response(200, json={"pages": [{"index": i, "markdown": md} for i, md in enumerate(pages)]})

    config = Settings(
        azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/",
        azure_ai_foundry_api_key="test-key",
        ocr_provider="mistral",
        mistral_ocr_url="https://example.services.ai.azure.com/providers/mistral/azure/ocr",
        extraction_passes=1,
        **settings,
    )
    responses = FakeResponses(json.dumps(output))
    ocr = MistralOcr(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return WireExtractionService(config, client=SimpleNamespace(responses=responses), ocr=ocr), responses, seen


OCR_OUTPUT = {
    "beneficiary_name": {"value": "Ada Lovelace Trust Account", "confidence": 0.95, "page": 1},
    "beneficiary_address": {"value": "1 Example Way, London", "confidence": 0.95, "page": 1},
    "bank_name": {"value": "Example Bank", "confidence": 0.95, "page": 1},
    "bank_address": {"value": "2 Bank Road", "confidence": 0.95, "page": 1},
    "routing_number_aba": {"value": "021000021", "confidence": 0.95, "page": 1},
    "account_number": {"value": "0012-345", "confidence": 0.95, "page": 1},
}


def test_ocr_provider_sends_pdf_to_mistral_and_ocr_text_to_the_model() -> None:
    pages = ["Account Name: Ada Lovelace Trust Account\n1 Example Way,\nLondon",
             "| Bank | Example Bank |\n2 Bank Road\nABA 021000021\nAccount 0012-345"]
    service, responses, seen = ocr_service(OCR_OUTPUT, pages)

    result = service.extract(content=sample_pdf(2), filename="w.pdf", content_type=None, document_source="w.pdf")

    assert seen["body"]["document"]["document_url"].startswith("data:application/pdf;base64,")
    assert seen["auth"] == "Bearer test-key"
    user = responses.request["input"][1]["content"]
    assert [part["type"] for part in user] == ["input_text", "input_text"]
    assert "--- Page 2 ---" in user[0]["text"] and "ABA 021000021" in user[0]["text"]
    # Line breaks and punctuation in the OCR text do not count as a mismatch.
    assert result.flagged_fields == [] and not result.manual_review_required


def test_ocr_provider_flags_values_that_are_not_in_the_ocr_text() -> None:
    output = {**OCR_OUTPUT, "account_number": {"value": "0012-3456", "confidence": 0.99, "page": 1}}
    service, _, _ = ocr_service(output, ["Ada Lovelace Trust Account 1 Example Way London Example Bank "
                                         "2 Bank Road ABA 021000021 Account 0012-345"])

    result = service.extract(content=sample_pdf(), filename="w.pdf", content_type=None, document_source="w.pdf")

    assert result.flagged_fields == ["account_number"]
    assert result.manual_review_required
    assert "does not appear in the OCR text" in result.warnings[0]


def test_ocr_failure_is_a_clear_error() -> None:
    import pytest

    from app.service import OcrError

    service, _, _ = ocr_service(OCR_OUTPUT, [], status=500)
    with pytest.raises(OcrError, match="HTTP 500"):
        service.extract(content=sample_pdf(), filename="w.pdf", content_type=None, document_source="w.pdf")


def test_ocr_provider_requires_its_endpoint() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="MISTRAL_OCR_URL"):
        Settings(azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/",
                 azure_ai_foundry_api_key="test-key", ocr_provider="mistral")
