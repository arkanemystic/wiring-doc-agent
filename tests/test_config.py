from app.config import Settings


def test_settings_normalizes_a_full_responses_api_url() -> None:
    settings = Settings(
        azure_ai_foundry_base_url=(
            "https://example.cognitiveservices.azure.com/openai/responses?"
            "api-version=2025-04-01-preview"
        ),
        azure_ai_foundry_api_key="test-key",
    )

    assert settings.azure_ai_foundry_base_url == "https://example.cognitiveservices.azure.com/openai/"
    assert settings.azure_ai_foundry_api_version == "2025-04-01-preview"


def test_settings_expands_an_azure_resource_root_to_the_v1_base_url() -> None:
    settings = Settings(
        azure_ai_foundry_base_url="https://example.openai.azure.com/",
        azure_ai_foundry_api_key="test-key",
    )

    assert settings.azure_ai_foundry_base_url == "https://example.openai.azure.com/openai/v1/"


def test_settings_strips_responses_from_a_v1_responses_url() -> None:
    settings = Settings(
        azure_ai_foundry_base_url="https://example.openai.azure.com/openai/v1/responses",
        azure_ai_foundry_api_key="test-key",
    )

    assert settings.azure_ai_foundry_base_url == "https://example.openai.azure.com/openai/v1/"
    assert settings.azure_ai_foundry_api_version is None
