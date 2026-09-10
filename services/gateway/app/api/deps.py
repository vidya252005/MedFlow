from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from medflow_shared.auth import decode_token, has_permission
from medflow_shared.config import Settings

bearer = HTTPBearer(auto_error=False)


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")
    try:
        payload = decode_token(settings, creds.credentials)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from None
    request.state.user = payload
    return payload


def require(permission: str):
    async def _inner(user: Annotated[dict, Depends(current_user)]) -> dict:
        if not has_permission(user.get("role", ""), permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return user

    return _inner


async def rate_limit(
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    minute = int(time.time() // 60)
    key = f"ratelimit:{user.get('sub', 'anon')}:{minute}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    remaining = max(0, settings.rate_limit_per_minute - count)
    request.state.rate_remaining = remaining
    if count > settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": "60"},
        )


async def idempotency_key(x_idempotency_key: Annotated[str | None, Header()] = None) -> str | None:
    return x_idempotency_key
