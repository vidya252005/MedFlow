from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar

from medflow_shared.errors import MedFlowError

T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_ms: int,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            allowed = retryable(exc) if retryable else isinstance(exc, MedFlowError) and exc.retryable
            if not allowed or attempt == attempts - 1:
                raise
            delay = (base_ms / 1000) * (2**attempt) + random.random() * 0.05
            await asyncio.sleep(delay)
    assert last is not None
    raise last
