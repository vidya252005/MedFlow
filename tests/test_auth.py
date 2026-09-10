from medflow_shared.auth import create_token, decode_token, has_permission, hash_password, verify_password
from medflow_shared.config import Settings


def test_password_roundtrip() -> None:
    hashed = hash_password("medflow")
    assert verify_password("medflow", hashed)
    assert not verify_password("nope", hashed)


def test_jwt_contains_role_and_scope() -> None:
    settings = Settings(jwt_secret="unit-test-secret")
    token = create_token(settings, "admin", "ADMIN")
    payload = decode_token(settings, token)
    assert payload["sub"] == "admin"
    assert payload["role"] == "ADMIN"
    assert "dlq:replay" in payload["scope"]
    assert has_permission("VIEWER", "events:read")
    assert not has_permission("VIEWER", "dlq:replay")
