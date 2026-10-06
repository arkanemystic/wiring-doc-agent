import base64
import json
import logging
from types import SimpleNamespace

import fitz

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
    document = fitz.open()
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
