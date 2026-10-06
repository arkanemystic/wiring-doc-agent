from app.models import ModelExtraction


def test_model_schema_disallows_undeclared_properties_for_strict_output() -> None:
    schema = ModelExtraction.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["ExtractedField"]["additionalProperties"] is False
