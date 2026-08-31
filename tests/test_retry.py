"""retry.py 单元测试：退避计算、可重试判定、重试成功/耗尽。"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from miniclaudecode.agent_runtime.retry import (
    RetryConfig,
    backoff_delay,
    is_retryable_error,
    retry_async,
)


def test_backoff_no_jitter():
    cfg = RetryConfig(base_delay=1.0, max_delay=30.0, jitter=False)
    assert backoff_delay(0, cfg) == 1.0
    assert backoff_delay(1, cfg) == 2.0
    assert backoff_delay(2, cfg) == 4.0


def test_backoff_caps_at_max():
    cfg = RetryConfig(base_delay=1.0, max_delay=30.0, jitter=False)
    assert backoff_delay(10, cfg) == 30.0  # 2^10=1024，被 30 封顶


def test_backoff_jitter_range():
    cfg = RetryConfig(base_delay=1.0, max_delay=30.0, jitter=True)
    d = backoff_delay(1, cfg)  # 期望落在 [1.0, 3.0]
    assert 1.0 <= d <= 3.0


def test_is_retryable():
    assert is_retryable_error(httpx.TimeoutException("t"))
    assert is_retryable_error(httpx.ConnectError("c"))
    assert not is_retryable_error(ValueError("x"))

    req = httpx.Request("GET", "http://example.com")
    assert is_retryable_error(httpx.HTTPStatusError("e", request=req, response=httpx.Response(429, request=req)))
    assert not is_retryable_error(httpx.HTTPStatusError("e", request=req, response=httpx.Response(400, request=req)))


def test_retry_async_success():
    async def f():
        return "ok"

    assert asyncio.run(retry_async(f)) == "ok"


def test_retry_then_succeed():
    calls = {"n": 0}

    async def f():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.TimeoutException("x")
        return "done"

    cfg = RetryConfig(max_retries=5, base_delay=0.001, max_delay=0.01, jitter=False)
    assert asyncio.run(retry_async(f, cfg)) == "done"
    assert calls["n"] == 3


def test_retry_exhausts():
    async def f():
        raise httpx.TimeoutException("always")

    cfg = RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01, jitter=False)
    with pytest.raises(httpx.TimeoutException):
        asyncio.run(retry_async(f, cfg))


def test_retry_not_on_non_retryable():
    calls = {"n": 0}

    async def f():
        calls["n"] += 1
        raise ValueError("business error")

    cfg = RetryConfig(max_retries=5, base_delay=0.001, max_delay=0.01, jitter=False)
    with pytest.raises(ValueError):
        asyncio.run(retry_async(f, cfg))
    assert calls["n"] == 1  # 不重试
