from functools import lru_cache
from urllib.parse import parse_qs, urlparse, urlunparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration supplied through local.settings.json or Azure app settings."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_ai_foundry_base_url: str
    azure_ai_foundry_api_key: SecretStr
    azure_ai_foundry_api_version: str | None = None
    azure_ai_foundry_deployment: str = "gpt-6-luna"
    manual_review_confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_archive_files: int = Field(default=100, gt=0)
    max_archive_uncompressed_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=25, gt=0)
    max_concurrent_extractions: int = Field(default=8, gt=0)
    request_timeout_seconds: float = Field(default=90, gt=0)
    # Azure Functions HTTP triggers are cut off at ~230 s; return the workbook before that.
    request_deadline_seconds: float = Field(default=200, gt=0)
    # Independent model reads per document; fields that disagree between reads are flagged.
    extraction_passes: int = Field(default=2, ge=1, le=3)
    log_model_responses: bool = False

    @model_validator(mode="after")
    def normalize_endpoint(self) -> "Settings":
        if "YOUR-RESOURCE" in self.azure_ai_foundry_base_url.upper():
            raise ValueError(
                "AZURE_AI_FOUNDRY_BASE_URL is still the .env.example placeholder; set your real endpoint"
            )
        if self.azure_ai_foundry_api_key.get_secret_value().strip() in {"", "replace-with-your-key"}:
            raise ValueError("AZURE_AI_FOUNDRY_API_KEY is empty or still the .env.example placeholder")
        parsed = urlparse(self.azure_ai_foundry_base_url)
        path = parsed.path.rstrip("/")

        if path.endswith("/openai/responses"):
            api_version = parse_qs(parsed.query).get("api-version", [None])[0]
            if not api_version:
                raise ValueError("a full /responses API URL must include an api-version query parameter")
            self.azure_ai_foundry_base_url = urlunparse(
                parsed._replace(path=f"{path.removesuffix('/responses')}/", query="")
            )
            self.azure_ai_foundry_api_version = api_version
        elif path.endswith("/openai/v1/responses"):
            # The v1 Responses URL copied from the portal; the SDK appends /responses itself.
            self.azure_ai_foundry_base_url = urlunparse(
                parsed._replace(path=f"{path.removesuffix('responses')}", query="")
            )
        elif path == "":
            self.azure_ai_foundry_base_url = f"{self.azure_ai_foundry_base_url.rstrip('/')}/openai/v1/"
        else:
            self.azure_ai_foundry_base_url = f"{self.azure_ai_foundry_base_url.rstrip('/')}/"

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
