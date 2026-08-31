"""统一 LLM 后端 —— 同时支持 OpenAI 兼容接口与 Anthropic 原生接口。

规范化输入为 OpenAI 风格的消息列表与 tools 列表，输出为 LLMResult。
内部使用 httpx 异步客户端，天然支持流式（SSE）输出。

OpenAI 兼容协议（chat/completions）几乎被所有国产/主流厂商支持，
因此本项目默认 provider="openai"；需要走 Anthropic 原生 /v1/messages 时切 provider="anthropic"。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Optional

import httpx

from ..config import Config
from .messages import LLMResult, ToolCall, Usage
from .retry import RetryConfig, retry_async

# 流式输出回调：收到文本增量时调用
StreamCallback = Callable[[str], Any]


class BackendError(Exception):
    """后端调用失败（含非重试错误）。"""


class LLMBackend:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0))
        self._retry = RetryConfig()

    # ------------------------------------------------------------------ #
    # 公共入口
    # ------------------------------------------------------------------ #
    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream_cb: Optional[StreamCallback] = None,
    ) -> LLMResult:
        """发送一轮对话。

        Args:
            messages: 规范化消息列表。
            tools: 规范化（OpenAI function 风格）工具 schema 列表。
            stream_cb: 可选流式回调，收到文本增量时触发（用于实时渲染）。
        """
        stream = self.config.enable_stream and stream_cb is not None

        async def _call() -> LLMResult:
            if self.config.is_anthropic:
                return await self._chat_anthropic(messages, tools, stream, stream_cb)
            return await self._chat_openai(messages, tools, stream, stream_cb)

        try:
            return await retry_async(_call, cfg=self._retry)
        except Exception as exc:  # noqa: BLE001
            raise BackendError(f"LLM 调用失败: {exc}") from exc

    # ------------------------------------------------------------------ #
    # OpenAI 兼容实现
    # ------------------------------------------------------------------ #
    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def _chat_openai(
        self, messages: list[dict], tools: Optional[list[dict]], stream: bool, stream_cb: Optional[StreamCallback]
    ) -> LLMResult:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if not stream:
            resp = await self._client.post(url, json=payload, headers=self._auth_headers())
            resp.raise_for_status()
            return self._parse_openai(resp.json())

        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return await self._stream_openai(url, payload, stream_cb)

    async def _stream_openai(self, url: str, payload: dict, stream_cb: Optional[StreamCallback]) -> LLMResult:
        content_parts: list[str] = []
        tool_calls_raw: dict[int, dict] = {}   # index -> {id, name, arguments}
        usage = Usage()

        async with self._client.stream("POST", url, json=payload, headers=self._auth_headers()) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                for choice in choices:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        content_parts.append(text)
                        if stream_cb:
                            stream_cb(text)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tool_calls_raw.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                if chunk.get("usage"):
                    u = chunk["usage"]
                    usage = Usage(input_tokens=u.get("prompt_tokens", 0),
                                  output_tokens=u.get("completion_tokens", 0))

        return self._assemble(content_parts, tool_calls_raw, usage)

    def _parse_openai(self, data: dict) -> LLMResult:
        content = ""
        tool_calls_raw: dict[int, dict] = {}
        usage = Usage()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        for tc in msg.get("tool_calls") or []:
            idx = tc.get("index", len(tool_calls_raw))
            tool_calls_raw[idx] = {
                "id": tc.get("id", ""),
                "name": (tc.get("function") or {}).get("name", ""),
                "arguments": (tc.get("function") or {}).get("arguments", ""),
            }
        if data.get("usage"):
            usage = Usage(input_tokens=data["usage"].get("prompt_tokens", 0),
                          output_tokens=data["usage"].get("completion_tokens", 0))
        return self._assemble([content], tool_calls_raw, usage, data.get("choices", [{}])[0].get("finish_reason", "stop"))

    # ------------------------------------------------------------------ #
    # Anthropic 原生实现
    # ------------------------------------------------------------------ #
    def _to_anthropic_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """把 OpenAI 风格消息翻译为 Anthropic 的 system 字符串 + messages 列表。"""
        system_parts: list[str] = []
        out: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                system_parts.append(m.get("content", ""))
                continue
            if role == "tool":
                # 工具结果 -> user 消息中的 tool_result 块
                out.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }]})
                continue
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}") or "{}")
                    except Exception:
                        args = {}
                    blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                                   "name": fn.get("name", ""), "input": args})
                out.append({"role": "assistant", "content": blocks})
                continue
            out.append({"role": role, "content": m.get("content", "")})
        return "\n\n".join(system_parts), out

    @staticmethod
    def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
        result = []
        for t in tools:
            fn = t.get("function", {})
            result.append({"name": fn.get("name", ""), "description": fn.get("description", ""),
                           "input_schema": fn.get("parameters", {"type": "object", "properties": {}})})
        return result

    async def _chat_anthropic(
        self, messages: list[dict], tools: Optional[list[dict]], stream: bool, stream_cb: Optional[StreamCallback]
    ) -> LLMResult:
        url = f"{self.config.base_url.rstrip('/')}/v1/messages"
        system, an_messages = self._to_anthropic_messages(messages)
        headers = {**self._auth_headers(), "anthropic-version": "2023-06-01"}
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": an_messages,
            "temperature": self.config.temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._tools_to_anthropic(tools)

        if not stream:
            resp = await self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return self._parse_anthropic(resp.json())

        payload["stream"] = True
        return await self._stream_anthropic(url, payload, headers, stream_cb)

    async def _stream_anthropic(self, url: str, payload: dict, headers: dict, stream_cb: Optional[StreamCallback]) -> LLMResult:
        content_parts: list[str] = []
        tool_blocks: dict[int, dict] = {}
        usage = Usage()
        stop_reason = "stop"

        async with self._client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            event_type = ""
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "content_block_delta":
                    d = obj.get("delta") or {}
                    if d.get("type") == "text_delta":
                        content_parts.append(d.get("text", ""))
                        if stream_cb:
                            stream_cb(d.get("text", ""))
                    elif d.get("type") == "input_json_delta":
                        idx = obj.get("index", 0)
                        tool_blocks.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        tool_blocks[idx]["arguments"] += d.get("partial_json", "")
                elif t == "content_block_start":
                    block = obj.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        idx = obj.get("index", 0)
                        tool_blocks.setdefault(idx, {"id": block.get("id", ""), "name": block.get("name", ""), "arguments": ""})
                        tool_blocks[idx]["id"] = block.get("id", "")
                        tool_blocks[idx]["name"] = block.get("name", "")
                elif t == "message_delta":
                    if obj.get("usage"):
                        stop_reason = obj.get("delta", {}).get("stop_reason", stop_reason)
                    usage = Usage(input_tokens=obj.get("usage", {}).get("input_tokens", 0),
                                  output_tokens=obj.get("usage", {}).get("output_tokens", 0))
                elif t == "message_stop":
                    break

        return self._assemble(content_parts, tool_blocks, usage, stop_reason)

    def _parse_anthropic(self, data: dict) -> LLMResult:
        content_parts: list[str] = []
        tool_blocks: dict[int, dict] = {}
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_blocks[len(tool_blocks)] = {
                    "id": block.get("id", ""), "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {})),
                }
        usage = Usage(input_tokens=data.get("usage", {}).get("input_tokens", 0),
                      output_tokens=data.get("usage", {}).get("output_tokens", 0))
        return self._assemble(content_parts, tool_blocks, usage, data.get("stop_reason", "stop"))

    # ------------------------------------------------------------------ #
    # 结果组装
    # ------------------------------------------------------------------ #
    def _assemble(
        self,
        content_parts: list[str],
        tool_calls_raw: dict[int, dict],
        usage: Usage,
        stop_reason: str = "stop",
    ) -> LLMResult:
        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_calls_raw):
            raw = tool_calls_raw[idx]
            if raw.get("name"):
                tool_calls.append(ToolCall.from_openai({
                    "id": raw.get("id", f"call_{idx}"),
                    "function": {"name": raw["name"], "arguments": raw.get("arguments", "{}")},
                }))
        content = "".join(content_parts)
        if tool_calls and stop_reason == "stop":
            stop_reason = "tool_use"
        return LLMResult(content=content, tool_calls=tool_calls, usage=usage, stop_reason=stop_reason)
