import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
from io import BytesIO
import json
import logging
from pathlib import Path, PurePosixPath
import time
from urllib.parse import urlparse
import zipfile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from openai import APIError, APIStatusError, APITimeoutError
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.models import ExtractionResponse
from app.service import InvalidDocumentError, WireExtractionService
from app.workbook import create_extraction_workbook

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail at startup, with the validation message, rather than on the first upload.
    get_settings()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Wiring Instruction Extractor",
    version="0.1.0",
    description="Extracts wire-instruction fields from uploaded documents using Azure AI Foundry.",
)

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DEMO_PAGE = Path(__file__).resolve().parent.parent / "demo.html"


# Office files are ZIP containers; they are documents, not archives of documents.
NON_ARCHIVE_SUFFIXES = (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".pdf")
JUNK_FILENAMES = {".ds_store", "thumbs.db", "desktop.ini"}
MAX_SOURCE_URL_LENGTH = 2048


def is_zip_upload(filename: str, content_type: str | None, content: bytes) -> bool:
    lowered = filename.lower()
    if lowered.endswith(".zip") or content_type in {"application/zip", "application/x-zip-compressed"}:
        return True
    return not lowered.endswith(NON_ARCHIVE_SUFFIXES) and zipfile.is_zipfile(BytesIO(content))


def is_junk_member(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1].lower() if parts else ""
    return "__MACOSX" in parts or name.startswith("._") or name in JUNK_FILENAMES


MAX_ARCHIVE_DEPTH = 3


def archive_documents(content: bytes, settings: Settings) -> list[tuple[str, bytes]]:
    budget = {"files": settings.max_archive_files, "bytes": settings.max_archive_uncompressed_bytes}
    documents = expand_archive(content, settings, budget, prefix="", depth=1)
    if not documents:
        raise HTTPException(status_code=400, detail="The ZIP archive contains no files.")
    return documents


def expand_archive(
    content: bytes, settings: Settings, budget: dict[str, int], prefix: str, depth: int
) -> list[tuple[str, bytes]]:
    """Read archive members in memory, expanding nested ZIPs within the same file and byte limits."""
    file_limit = HTTPException(
        status_code=413,
        detail=f"The ZIP archive exceeds the {settings.max_archive_files}-file limit.",
    )
    byte_limit = HTTPException(
        status_code=413,
        detail=(
            "The ZIP archive exceeds the "
            f"{settings.max_archive_uncompressed_bytes}-byte uncompressed limit."
        ),
    )
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and not is_junk_member(member.filename)
            ]
            if depth == 1 and not members:
                raise HTTPException(status_code=400, detail="The ZIP archive contains no files.")
            if len(members) > budget["files"]:
                raise file_limit
            if sum(member.file_size for member in members) > budget["bytes"]:
                raise byte_limit

            documents: list[tuple[str, bytes]] = []
            for member in members:
                if member.flag_bits & 0x1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"The ZIP archive contains encrypted file '{prefix}{member.filename}'.",
                    )
                filename = PurePosixPath(member.filename).name
                if not filename:
                    continue
                # Keep the in-archive path so identically named files stay distinguishable.
                display_path = f"{prefix}{member.filename.lstrip('/')}"
                member_too_large = HTTPException(
                    status_code=413,
                    detail=(
                        f"Archive file '{display_path}' exceeds the "
                        f"{settings.max_upload_bytes}-byte limit."
                    ),
                )
                if member.file_size > settings.max_upload_bytes:
                    raise member_too_large
                # zipfile stops at the declared size and fails the CRC check if the header lies.
                document_content = archive.read(member)
                if len(document_content) > settings.max_upload_bytes:
                    raise member_too_large
                if len(document_content) > budget["bytes"]:
                    raise byte_limit
                budget["bytes"] -= len(document_content)

                if is_zip_upload(filename, None, document_content):
                    if depth >= MAX_ARCHIVE_DEPTH:
                        raise HTTPException(
                            status_code=400,
                            detail=f"ZIP archives are nested more than {MAX_ARCHIVE_DEPTH} levels deep.",
                        )
                    documents.extend(
                        expand_archive(
                            document_content, settings, budget, f"{display_path}#", depth + 1
                        )
                    )
                    continue

                budget["files"] -= 1
                if budget["files"] < 0:
                    raise file_limit
                documents.append((display_path, document_content))
    except zipfile.BadZipFile as error:
        location = f" '{prefix.rstrip('#')}'" if prefix else ""
        raise HTTPException(
            status_code=400, detail=f"The uploaded ZIP archive{location} is invalid."
        ) from error

    return documents


def validate_source_url(source_url: str | None) -> str | None:
    if source_url is None or not source_url.strip():
        return None
    source_url = source_url.strip()
    parsed = urlparse(source_url)
    if len(source_url) > MAX_SOURCE_URL_LENGTH or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail=f"source_url must be an absolute http(s) URL of at most {MAX_SOURCE_URL_LENGTH} characters.",
        )
    return source_url


def describe_member_error(error: Exception) -> str:
    if isinstance(error, APITimeoutError):
        return "Azure AI Foundry did not respond in time."
    if isinstance(error, APIStatusError):
        return f"Azure AI Foundry returned HTTP {error.status_code}."
    if isinstance(error, APIError):
        return "Azure AI Foundry could not be reached."
    return str(error)


def archive_member_source(archive_source: str, filename: str) -> str:
    return f"{archive_source}#{filename}"


@lru_cache
def get_extraction_service() -> WireExtractionService:
    return WireExtractionService(get_settings())


@app.api_route("/health", methods=["GET", "HEAD"], tags=["health"])
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
        document_source = validate_source_url(source_url) or file.filename
        # Stop before the hosting platform's HTTP limit; unfinished documents become rows.
        deadline = time.monotonic() + settings.request_deadline_seconds

        def remaining() -> float:
            return deadline - time.monotonic()

        async def extract_before_deadline(**kwargs: object) -> ExtractionResponse:
            # The SDK timeout lets the worker thread finish; wait_for also bounds SDK retries.
            timeout = min(settings.request_timeout_seconds, remaining())
            return await asyncio.wait_for(
                run_in_threadpool(extraction_service.extract, timeout=timeout, **kwargs),
                timeout=remaining(),
            )

        if is_zip_upload(file.filename, file.content_type, content):
            documents = archive_documents(content, settings)
            limiter = asyncio.Semaphore(settings.max_concurrent_extractions)
            not_processed = (
                f"Not processed: the {settings.request_deadline_seconds:g}-second request "
                "time budget ran out. Resubmit this document separately."
            )

            async def extract_member(path: str, document_content: bytes) -> ExtractionResponse:
                source = archive_member_source(document_source, path)
                async with limiter:
                    if remaining() <= 0:
                        return ExtractionResponse.failed(source, not_processed)
                    try:
                        return await extract_before_deadline(
                            content=document_content,
                            filename=PurePosixPath(path).name,
                            content_type=None,
                            document_source=source,
                        )
                    except asyncio.TimeoutError:
                        return ExtractionResponse.failed(source, not_processed)
                    except (APIError, ValueError) as error:
                        # One bad document must not discard the rest of the batch.
                        logger.warning("Extraction failed for %s: %s", source, error)
                        return ExtractionResponse.failed(source, describe_member_error(error))

            results = await asyncio.gather(
                *(extract_member(path, data) for path, data in documents)
            )
        else:
            results = [
                await extract_before_deadline(
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
        if error.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="Azure AI Foundry rate limit reached. Retry shortly.",
                headers={"Retry-After": error.response.headers.get("retry-after", "30")},
            ) from error
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
    except (APITimeoutError, asyncio.TimeoutError) as error:
        raise HTTPException(
            status_code=504,
            detail="Azure AI Foundry did not respond within the request time budget.",
        ) from error
    except APIError as error:
        raise HTTPException(
            status_code=502,
            detail="Azure AI Foundry could not process the document. Verify network connectivity.",
        ) from error
    except InvalidDocumentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        await file.close()
