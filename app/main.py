import asyncio
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import zipfile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from openai import APIError, APIStatusError
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.models import ExtractionResponse
from app.service import WireExtractionService
from app.workbook import create_extraction_workbook

app = FastAPI(
    title="Wiring Instruction Extractor",
    version="0.1.0",
    description="Extracts wire-instruction fields from uploaded documents using Azure AI Foundry.",
)

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DEMO_PAGE = Path(__file__).resolve().parent.parent / "demo.html"


def is_zip_upload(filename: str, content_type: str | None, content: bytes) -> bool:
    return (
        filename.lower().endswith(".zip")
        or content_type in {"application/zip", "application/x-zip-compressed"}
        or zipfile.is_zipfile(BytesIO(content))
    )


def archive_documents(content: bytes, settings: Settings) -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if not members:
                raise HTTPException(status_code=400, detail="The ZIP archive contains no files.")
            if len(members) > settings.max_archive_files:
                raise HTTPException(
                    status_code=413,
                    detail=f"The ZIP archive exceeds the {settings.max_archive_files}-file limit.",
                )

            total_size = sum(member.file_size for member in members)
            if total_size > settings.max_archive_uncompressed_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "The ZIP archive exceeds the "
                        f"{settings.max_archive_uncompressed_bytes}-byte uncompressed limit."
                    ),
                )

            documents: list[tuple[str, bytes]] = []
            extracted_size = 0
            for member in members:
                if member.flag_bits & 0x1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"The ZIP archive contains encrypted file '{member.filename}'.",
                    )
                filename = PurePosixPath(member.filename).name
                if not filename:
                    continue
                if member.file_size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Archive file '{filename}' exceeds the "
                            f"{settings.max_upload_bytes}-byte limit."
                        ),
                    )
                document_content = archive.read(member)
                if len(document_content) > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Archive file '{filename}' exceeds the "
                            f"{settings.max_upload_bytes}-byte limit."
                        ),
                    )
                extracted_size += len(document_content)
                if extracted_size > settings.max_archive_uncompressed_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "The ZIP archive exceeds the "
                            f"{settings.max_archive_uncompressed_bytes}-byte uncompressed limit."
                        ),
                    )
                documents.append((filename, document_content))
    except zipfile.BadZipFile as error:
        raise HTTPException(status_code=400, detail="The uploaded ZIP archive is invalid.") from error

    if not documents:
        raise HTTPException(status_code=400, detail="The ZIP archive contains no files.")
    return documents


def archive_member_source(archive_source: str, filename: str) -> str:
    return f"{archive_source}#{filename}"


@lru_cache
def get_extraction_service() -> WireExtractionService:
    return WireExtractionService(get_settings())


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    return FileResponse(DEMO_PAGE, media_type="text/html")


@app.post(
    "/extract",
    status_code=status.HTTP_200_OK,
    tags=["extraction"],
    response_description="An Excel workbook containing one row per extracted document.",
)
async def extract_wire_instruction(
    file: UploadFile = File(..., description="The wiring-instruction document to extract."),
    source_url: str | None = Form(
        default=None,
        description="Optional original Blob URL. It is returned as document_source when supplied.",
    ),
    settings: Settings = Depends(get_settings),
    extraction_service: WireExtractionService = Depends(get_extraction_service),
) -> Response:
    if not file.filename:
        raise HTTPException(status_code=400, detail="An uploaded filename is required.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded document is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"The uploaded document exceeds the {settings.max_upload_bytes}-byte limit.",
        )

    try:
        document_source = source_url or file.filename
        if is_zip_upload(file.filename, file.content_type, content):
            documents = archive_documents(content, settings)
            results = await asyncio.gather(
                *(
                    run_in_threadpool(
                        extraction_service.extract,
                        content=document_content,
                        filename=filename,
                        content_type=None,
                        document_source=archive_member_source(document_source, filename),
                    )
                    for filename, document_content in documents
                )
            )
        else:
            results = [
                await run_in_threadpool(
                    extraction_service.extract,
                    content=content,
                    filename=file.filename,
                    content_type=file.content_type,
                    document_source=document_source,
                )
            ]

        return Response(
            content=create_extraction_workbook(
                results, confidence_threshold=settings.manual_review_confidence_threshold
            ),
            media_type=EXCEL_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="wire-instruction-results.xlsx"'},
        )
    except APIStatusError as error:
        request_id = error.request_id or "unavailable"
        provider_error = error.body.get("error", {}) if isinstance(error.body, dict) else {}
        raw_error = error.response.text.strip()
        if not provider_error and raw_error:
            try:
                raw_body = json.loads(raw_error)
                provider_error = raw_body.get("error", raw_body) if isinstance(raw_body, dict) else {}
            except json.JSONDecodeError:
                provider_error = {"message": raw_error[:1000]}

        provider_message = provider_error.get("message", "No provider details were returned.")
        provider_code = provider_error.get(
            "code", error.response.headers.get("x-ms-error-code", "unavailable")
        )
        provider_param = provider_error.get("param")
        parameter_detail = f", parameter: {provider_param}" if provider_param else ""
        raise HTTPException(
            status_code=502,
            detail=(
                f"Azure AI Foundry returned HTTP {error.status_code} "
                f"(request ID: {request_id}, code: {provider_code}{parameter_detail}): "
                f"{provider_message}"
            ),
        ) from error
    except APIError as error:
        raise HTTPException(
            status_code=502,
            detail="Azure AI Foundry could not process the document. Verify network connectivity.",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        await file.close()
