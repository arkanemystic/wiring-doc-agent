from io import BytesIO
import json
import struct
from threading import Lock
import time
from types import SimpleNamespace

import httpx
import openai
import pymupdf
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import ValidationError

from app.config import Settings
from app.main import app, get_extraction_service, get_settings
from app.models import ExtractedField, ExtractionResponse, ModelExtraction
from app.service import WireExtractionService, detect_mime_type, strict_json_schema
from tests.test_api import FakeExtractionService, configure_app, result_sheet, teardown_app, zip_content
from tests.test_service import FakeResponses, sample_pdf

FIELD_NAMES = list(ModelExtraction.model_fields)


def settings(**overrides: object) -> Settings:
    return Settings(
        azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/",
        azure_ai_foundry_api_key="test-key",
        **overrides,
    )


def valid_output() -> str:
    return json.dumps({name: {"value": "v", "confidence": 0.9, "page": 1} for name in FIELD_NAMES})


def real_service(**overrides: object) -> tuple[WireExtractionService, FakeResponses]:
    responses = FakeResponses(valid_output())
    return WireExtractionService(settings(**overrides), client=SimpleNamespace(responses=responses)), responses


def post(content: bytes, filename: str, content_type: str, service=None):
    configure_app(service or FakeExtractionService())
    try:
        return TestClient(app).post("/extract", files={"file": (filename, content, content_type)})
    finally:
        teardown_app()


def tiny_tiff() -> bytes:
    # 2x2 8-bit grayscale, uncompressed, little-endian.
    entries = [(256, 3, 1, 2), (257, 3, 1, 2), (258, 3, 1, 8), (259, 3, 1, 1), (262, 3, 1, 1),
               (273, 4, 1, 8 + 2 + 12 * 8 + 4), (278, 3, 1, 2), (279, 4, 1, 4)]
    ifd = struct.pack("<H", len(entries)) + b"".join(struct.pack("<HHII", *e) for e in entries) + b"\0\0\0\0"
    return b"II*\x00" + struct.pack("<I", 8) + ifd + bytes([0, 85, 170, 255])


# --- ZIP handling -------------------------------------------------------------------------


def test_office_files_are_documents_not_archives() -> None:
    service = FakeExtractionService()
    workbook_bytes = BytesIO()
    from openpyxl import Workbook
    Workbook().save(workbook_bytes)

    response = post(workbook_bytes.getvalue(), "wire.xlsx", "application/octet-stream", service)

    assert response.status_code == 200
    assert [call["filename"] for call in service.calls] == ["wire.xlsx"]


def test_macos_archive_metadata_is_skipped() -> None:
    service = FakeExtractionService()
    archive = zip_content(
        ("wires/a.pdf", b"a"), ("__MACOSX/wires/._a.pdf", b"x"), (".DS_Store", b"x"), ("Thumbs.db", b"x")
    )
    response = post(archive, "w.zip", "application/zip", service)

    assert response.status_code == 200
    assert [call["filename"] for call in service.calls] == ["a.pdf"]


def test_duplicate_member_names_stay_distinguishable() -> None:
    response = post(zip_content(("a/x.pdf", b"1"), ("b/x.pdf", b"2")), "w.zip", "application/zip")

    sheet = result_sheet(response.content)
    assert [sheet.cell(row=r, column=1).value for r in (6, 7)] == ["w.zip#a/x.pdf", "w.zip#b/x.pdf"]


class FailsOn(FakeExtractionService):
    def extract(self, **kwargs: object) -> ExtractionResponse:
        if "bad" in str(kwargs["filename"]):
            raise ValueError("The uploaded PDF could not be rendered.")
        return super().extract(**kwargs)


def test_one_failed_archive_member_does_not_discard_the_batch() -> None:
    archive = zip_content(("a.pdf", b"a"), ("bad.pdf", b"b"), ("c.pdf", b"c"))
    response = post(archive, "w.zip", "application/zip", FailsOn())

    assert response.status_code == 200
    sheet = result_sheet(response.content)
    assert sheet["I5"].value == "Notes"
    assert [sheet.cell(row=r, column=9).value for r in (6, 7, 8)] == [
        None, "The uploaded PDF could not be rendered.", None,
    ]
    assert sheet["H7"].value == "Yes"
    assert sheet["B6"].value == "Ada Lovelace"


def test_archive_extraction_concurrency_is_bounded() -> None:
    active = peak = 0
    lock = Lock()

    class Counting(FakeExtractionService):
        def extract(self, **kwargs: object) -> ExtractionResponse:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return super().extract(**kwargs)

    configure_app(Counting())
    app.dependency_overrides[get_settings] = lambda: settings(max_concurrent_extractions=3)
    try:
        archive = zip_content(*((f"{i}.pdf", b"x") for i in range(12)))
        response = TestClient(app).post("/extract", files={"file": ("w.zip", archive, "application/zip")})
    finally:
        teardown_app()

    assert response.status_code == 200
    assert 1 < peak <= 3


# --- Workbook safety ----------------------------------------------------------------------


def test_extracted_text_is_never_interpreted_as_a_formula() -> None:
    class Hostile(FakeExtractionService):
        def extract(self, **kwargs: object) -> ExtractionResponse:
            result = super().extract(**kwargs)
            result.fields.beneficiary_name.value = '=HYPERLINK("http://evil.example","pay here")'
            result.fields.bank_name.value = "+1+1"
            return result

    response = post(b"x", "a.pdf", "application/pdf", Hostile())

    sheet = result_sheet(response.content)
    assert sheet["B6"].data_type == "s"
    assert sheet["B6"].value.startswith("=HYPERLINK")
    assert sheet["D6"].data_type == "s"


def test_control_characters_do_not_break_the_workbook() -> None:
    class Dirty(FakeExtractionService):
        def extract(self, **kwargs: object) -> ExtractionResponse:
            result = super().extract(**kwargs)
            result.fields.account_number.value = "00\x00\x0712"
            return result

    response = post(b"x", "a.pdf", "application/pdf", Dirty())

    assert response.status_code == 200
    assert result_sheet(response.content)["G6"].value == "0012"


# --- Document routing and validation ------------------------------------------------------


def test_pdf_is_recognised_by_content_not_declared_type() -> None:
    pdf = sample_pdf()
    assert detect_mime_type(pdf, "upload", "application/octet-stream") == "application/pdf"
    assert detect_mime_type(pdf, "a.bin", None) == "application/pdf"
    assert detect_mime_type(b"x", "a.PDF", None) == "application/pdf"

    service, responses = real_service()
    service.extract(content=pdf, filename="a.pdf", content_type="application/octet-stream", document_source="s")
    parts = responses.request["input"][1]["content"]
    assert [p["type"] for p in parts] == ["input_image", "input_text"]


def test_tiff_pages_are_rendered_to_png() -> None:
    service, responses = real_service()
    service.extract(content=tiny_tiff(), filename="scan.tif", content_type="image/tiff", document_source="s")

    parts = responses.request["input"][1]["content"]
    assert parts[0]["image_url"].startswith("data:image/png;base64,")
    assert "TIFF pages" in parts[-1]["text"]


@pytest.mark.parametrize("content", [b"not a pdf", sample_pdf()[:200]])
def test_unreadable_pdf_is_a_client_error(content: bytes) -> None:
    service, _ = real_service()
    configure_app(service)
    try:
        response = TestClient(app).post("/extract", files={"file": ("a.pdf", content, "application/pdf")})
    finally:
        teardown_app()
    assert response.status_code == 422


def test_password_protected_pdf_is_a_client_error() -> None:
    document = pymupdf.open()
    document.new_page()
    encrypted = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    service, _ = real_service()
    configure_app(service)
    try:
        response = TestClient(app).post("/extract", files={"file": ("a.pdf", encrypted, "application/pdf")})
    finally:
        teardown_app()
    assert response.status_code == 422
    assert "password-protected" in response.json()["detail"]


def test_pdf_page_limit_is_enforced() -> None:
    service, responses = real_service(max_pdf_pages=3)
    configure_app(service)
    try:
        response = TestClient(app).post("/extract", files={"file": ("a.pdf", sample_pdf(4), "application/pdf")})
    finally:
        teardown_app()
    assert response.status_code == 422
    assert "limit is 3" in response.json()["detail"]
    assert responses.request is None


# --- Provider interaction -----------------------------------------------------------------


def test_rate_limit_is_passed_through_with_retry_after() -> None:
    class Limited(FakeExtractionService):
        def extract(self, **kwargs: object) -> ExtractionResponse:
            request = httpx.Request("POST", "https://example.invalid/openai/v1/responses")
            response = httpx.Response(429, request=request, headers={"retry-after": "7"},
                                      json={"error": {"message": "slow down"}})
            raise openai.RateLimitError("rate limited", response=response, body=response.json())

    response = post(b"x", "a.pdf", "application/pdf", Limited())

    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"


def test_strict_schema_has_no_numeric_bounds_but_local_validation_keeps_them() -> None:
    assert not {"minimum", "maximum"} & set(json.dumps(strict_json_schema(ModelExtraction.model_json_schema())).replace('"', " ").split())
    bad = json.loads(valid_output())
    bad["account_number"]["confidence"] = 1.5
    with pytest.raises(ValidationError):
        ModelExtraction.model_validate(bad)


def test_schema_mismatch_does_not_leak_validation_internals() -> None:
    service = WireExtractionService(
        settings(), client=SimpleNamespace(responses=FakeResponses(json.dumps({"rogue": 1})))
    )
    with pytest.raises(ValueError, match="did not match the extraction schema") as info:
        service.extract(content=b"x", filename="a.png", content_type="image/png", document_source="s")
    assert "pydantic" not in str(info.value)


# --- Configuration ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"azure_ai_foundry_base_url": "https://YOUR-RESOURCE.openai.azure.com/openai/v1/"},
        {"azure_ai_foundry_api_key": "replace-with-your-key"},
        {"azure_ai_foundry_api_key": "   "},
    ],
)
def test_example_placeholders_are_rejected(overrides: dict[str, str]) -> None:
    values = {
        "azure_ai_foundry_base_url": "https://example.openai.azure.com/openai/v1/",
        "azure_ai_foundry_api_key": "test-key",
        **overrides,
    }
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(**values)


# --- Routing number validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "valid"),
    [("021000021", True), ("011401533", True), ("02100021", False), ("021000022", False), ("12345678a", False)],
)
def test_aba_checksum(value: str, valid: bool) -> None:
    from app.service import is_valid_aba

    assert is_valid_aba(value) is valid


def test_invalid_routing_number_is_flagged_even_with_high_confidence() -> None:
    output = json.loads(valid_output())
    output["routing_number_aba"]["value"] = "02100021"  # dropped digit, model still 0.9 confident
    output["routing_number_aba"]["confidence"] = 0.99
    service = WireExtractionService(
        settings(), client=SimpleNamespace(responses=FakeResponses(json.dumps(output)))
    )

    result = service.extract(content=b"x", filename="a.png", content_type="image/png", document_source="s")

    assert result.manual_review_required
    assert result.flagged_fields == ["routing_number_aba"]
    assert "not a valid 9-digit ABA" in result.warnings[0]


# --- Open items from ISSUES.md --------------------------------------------------------------


def test_health_supports_head() -> None:
    assert TestClient(app).head("/health").status_code == 200


@pytest.mark.parametrize("source_url", ["javascript:alert(1)", "not a url", "ftp://x/y", "https://" + "a" * 2050])
def test_invalid_source_url_is_rejected(source_url: str) -> None:
    configure_app(FakeExtractionService())
    try:
        response = TestClient(app).post(
            "/extract",
            files={"file": ("w.pdf", b"x", "application/pdf")},
            data={"source_url": source_url},
        )
    finally:
        teardown_app()

    assert response.status_code == 400
    assert "source_url" in response.json()["detail"]


@pytest.mark.parametrize(
    ("content", "filename"),
    [(b"PK\x03\x04 docx bytes", "wire.docx"), (b"plain text", "wire.txt")],
)
def test_unsupported_document_types_are_rejected_before_the_model_call(content: bytes, filename: str) -> None:
    service, responses = real_service()
    response = post(content, filename, "application/octet-stream", service)

    assert response.status_code == 422
    assert "Unsupported document type" in response.json()["detail"]
    assert responses.request is None


def test_images_declared_as_octet_stream_are_sent_as_images() -> None:
    service, responses = real_service()
    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False).tobytes("png")

    assert post(png, "scan", "application/octet-stream", service).status_code == 200
    part = responses.request["input"][1]["content"][0]
    assert part["type"] == "input_image"
    assert part["image_url"].startswith("data:image/png;base64,")


def test_nested_zips_are_expanded() -> None:
    service = FakeExtractionService()
    inner = zip_content(("x.pdf", b"x"), ("__MACOSX/._x.pdf", b"j"))
    response = post(zip_content(("a.pdf", b"a"), ("more/inner.zip", inner)), "w.zip", "application/zip", service)

    assert response.status_code == 200
    sheet = result_sheet(response.content)
    assert [sheet.cell(row=r, column=1).value for r in (6, 7)] == ["w.zip#a.pdf", "w.zip#more/inner.zip#x.pdf"]


def test_nested_zips_share_the_file_limit() -> None:
    configure_app(FakeExtractionService())
    app.dependency_overrides[get_settings] = lambda: settings(max_archive_files=2)
    try:
        inner = zip_content(("x.pdf", b"x"), ("y.pdf", b"y"))
        archive = zip_content(("a.pdf", b"a"), ("inner.zip", inner))
        response = TestClient(app).post("/extract", files={"file": ("w.zip", archive, "application/zip")})
    finally:
        teardown_app()

    assert response.status_code == 413


def test_archive_member_larger_than_declared_is_rejected() -> None:
    archive = bytearray(zip_content(("a.pdf", b"\0" * 100_000)))
    for signature, offset in ((b"PK\x01\x02", 24), (b"PK\x03\x04", 22)):
        index = archive.find(signature)
        archive[index + offset:index + offset + 4] = struct.pack("<I", 100)

    response = post(bytes(archive), "w.zip", "application/zip")

    assert response.status_code == 400


def test_documents_left_when_the_deadline_passes_become_rows() -> None:
    class Slow(FakeExtractionService):
        def extract(self, **kwargs: object) -> ExtractionResponse:
            assert 0 < kwargs["timeout"] <= 0.3
            time.sleep(0.2)
            return super().extract(**kwargs)

    configure_app(Slow())
    app.dependency_overrides[get_settings] = lambda: settings(
        request_deadline_seconds=0.3, max_concurrent_extractions=1
    )
    try:
        archive = zip_content(*((f"{i}.pdf", b"x") for i in range(4)))
        response = TestClient(app).post("/extract", files={"file": ("w.zip", archive, "application/zip")})
    finally:
        teardown_app()

    assert response.status_code == 200
    sheet = result_sheet(response.content)
    notes = [sheet.cell(row=r, column=9).value for r in range(6, 10)]
    assert notes[0] is None
    assert all(note and note.startswith("Not processed") for note in notes[2:])


def test_single_document_past_the_deadline_is_a_gateway_timeout() -> None:
    class Slow(FakeExtractionService):
        def extract(self, **kwargs: object) -> ExtractionResponse:
            time.sleep(0.3)
            return super().extract(**kwargs)

    configure_app(Slow())
    app.dependency_overrides[get_settings] = lambda: settings(request_deadline_seconds=0.1)
    try:
        response = TestClient(app).post("/extract", files={"file": ("w.pdf", b"x", "application/pdf")})
    finally:
        teardown_app()

    assert response.status_code == 504


class SequencedResponses:
    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)

    def create(self, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(output_text=self.outputs.pop(0))


def extraction_output(account_number: str, name: str = "Brightwater Escrow") -> str:
    output = {field: {"value": "v", "confidence": 0.95, "page": 1} for field in FIELD_NAMES}
    output["routing_number_aba"]["value"] = "021000021"
    output["account_number"]["value"] = account_number
    output["beneficiary_name"]["value"] = name
    return json.dumps(output)


def test_disagreeing_passes_flag_fields_without_a_checksum() -> None:
    responses = SequencedResponses(
        extraction_output("7712-58-203"), extraction_output("7712-558-203", "brightwater  escrow")
    )
    service = WireExtractionService(settings(extraction_passes=2), client=SimpleNamespace(responses=responses))

    result = service.extract(content=sample_pdf(), filename="w.pdf", content_type=None, document_source="w.pdf")

    assert result.manual_review_required is True
    # Whitespace and case differences are not disagreements.
    assert result.flagged_fields == ["account_number"]
    assert "'7712-58-203' vs '7712-558-203'" in result.warnings[0]


def test_agreeing_passes_are_not_flagged() -> None:
    responses = SequencedResponses(extraction_output("7712-558-203"), extraction_output("7712-558-203"))
    service = WireExtractionService(settings(extraction_passes=2), client=SimpleNamespace(responses=responses))

    result = service.extract(content=sample_pdf(), filename="w.pdf", content_type=None, document_source="w.pdf")

    assert result.manual_review_required is False
    assert result.flagged_fields == []


def test_documents_are_read_twice_by_default() -> None:
    responses = SequencedResponses(extraction_output("7712-558-203"), extraction_output("7712-558-203"))
    service = WireExtractionService(settings(), client=SimpleNamespace(responses=responses))

    service.extract(content=sample_pdf(), filename="w.pdf", content_type=None, document_source="w.pdf")

    assert responses.outputs == []
