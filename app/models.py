from pydantic import BaseModel, ConfigDict, Field


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(
        description="The extracted value, or null when the value is not present or cannot be read."
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Model confidence in the extracted value, from 0.0 to 1.0.",
    )
    page: int | None = Field(
        ge=1,
        description="One-based page where the value appears, or null when unavailable.",
    )


class WireInstructionFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beneficiary_name: ExtractedField
    beneficiary_address: ExtractedField
    bank_name: ExtractedField
    bank_address: ExtractedField
    routing_number_aba: ExtractedField
    account_number: ExtractedField


class ModelExtraction(WireInstructionFields):
    """The schema returned by the language model, without application-owned metadata."""


class ExtractionResponse(BaseModel):
    document_source: str
    manual_review_required: bool
    fields: WireInstructionFields
