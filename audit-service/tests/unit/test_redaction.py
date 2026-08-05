from audit_service.records.redaction import validate_and_redact


def test_sensitive_keys_are_rejected() -> None:
    try:
        validate_and_redact({"access_token": "x"})
        assert False
    except ValueError as error:
        assert str(error) == "SENSITIVE_FIELD_REJECTED"
