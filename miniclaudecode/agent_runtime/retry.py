"""指数退避 + 抖动重试机制。

用于 API 调用失败（网络抖动 / 429 限流 / 5xx 服务端错误）时的自动重试，
通过全抖动（full jitter）避免多个客户端同时重试造成"惊群"。
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional

# 默认可重试的 HTTP 状态码
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class RetryConfig:
    """重试参数。"""

    def __init__(
        self,
        max_retries: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter


def backoff_delay(attempt: int, cfg: RetryConfig) -> float:
    """计算第 attempt 次（从 0 开始）重试的等待秒数。

    公式：min(max_delay, base_delay * 2^attempt)，再加全抖动 [-50%, +50%]。
    """
    delay = min(cfg.max_delay, cfg.base_delay * (2 ** attempt))
    if cfg.jitter:
        delay = delay * (0.5 + random.random())  # full jitter: [0.5x, 1.5x]
    return delay


def is_retryable_error(exc: Exception) -> bool:
    """判断异常是否值得重试。"""
    import httpx

    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    # 手动抛出的 RateLimitError 也可重试
    return getattr(exc, "retryable", False)


async def retry_async(
    func: Callable[[], Awaitable[Any]],
    cfg: Optional[RetryConfig] = None,
    retryable: Optional[Callable[[Exception], bool]] = None,
) -> Any:
    """执行 async 函数，失败时按指数退避 + 抖动重试。

    Args:
        func: 要执行的异步函数（每次调用应无副作用或幂等）。
        cfg: 重试配置。
        retryable: 自定义可重试判断，默认使用 is_retryable_error。
    """
    cfg = cfg or RetryConfig()
    retryable = retryable or is_retryable_error

    last_exc: Optional[Exception] = None
    for attempt in range(cfg.max_retries + 1):
        try:
            return await func()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= cfg.max_retries or not retryable(exc):
                raise
            delay = backoff_delay(attempt, cfg)
            # 记录日志交由上层处理；这里直接等待
            await asyncio.sleep(delay)
    # 理论上到不了这里
    assert last_exc is not None
    raise last_exc


class RetryableError(Exception):
    """显式标记为可重试的业务异常。"""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
