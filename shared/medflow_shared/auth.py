from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
import bcrypt

from medflow_shared.config import Settings

ROLE_PERMISSIONS = {
    "ADMIN": {
        "events:write",
        "events:read",
        "alerts:read",
        "alerts:ack",
        "alerts:resolve",
        "models:read",
        "models:manage",
        "audit:read",
        "dlq:read",
        "dlq:replay",
        "simulator:run",
        "ops:read",
    },
    "ANALYST": {
        "events:write",
        "events:read",
        "alerts:read",
        "alerts:ack",
        "models:read",
        "ops:read",
        "simulator:run",
    },
    "VIEWER": {
        "events:read",
        "alerts:read",
        "models:read",
        "ops:read",
    },
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(settings: Settings, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "scope": sorted(ROLE_PERMISSIONS.get(role, set())),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("invalid token") from exc


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
