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
    processing_error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    flagged_fields: list[str] = Field(default_factory=list)

    @classmethod
    def failed(cls, document_source: str, error: str) -> "ExtractionResponse":
        empty = ExtractedField(value=None, confidence=0, page=None)
        return cls(
            document_source=document_source,
            manual_review_required=True,
            fields=WireInstructionFields(
                **{name: empty for name in WireInstructionFields.model_fields}
            ),
            processing_error=error,
        )
