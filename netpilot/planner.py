"""Planners turn a plain-English request into proposed tool calls.

Two planners share one interface:

- RuleBasedPlanner works offline with no model, so the demo and tests are
  deterministic.
- LLMPlanner uses any OpenAI-compatible chat endpoint with tool calling,
  for example a local model served by Ollama or llama.cpp.

Either way, the output is only a proposal. validation.py decides what runs.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from .operations import tool_schemas
from .validation import ToolCall


class Planner(Protocol):
    async def plan(self, request: str, devices: list[str]) -> list[ToolCall]: ...


_DEVICE_RE = re.compile(r"\b((?:sw|rt|ap)-[a-z0-9-]+)\b", re.I)
_PORT_RE = re.compile(r"\bport\s+(\d+)\b", re.I)
_VLAN_RE = re.compile(r"\bvlan\s+(\d+)\b", re.I)


class RuleBasedPlanner:
    """Keyword planner. Small on purpose: it covers the demo intents."""

    async def plan(self, request: str, devices: list[str]) -> list[ToolCall]:
        text = request.lower()
        named = [d.lower() for d in _DEVICE_RE.findall(request)]
        targets = named or ["*"]
        port = _PORT_RE.search(request)
        vlan = _VLAN_RE.search(request)

        if "reboot" in text or "restart" in text:
            return [ToolCall("reboot_device", targets)]
        if vlan and port:
            return [ToolCall("set_port_vlan", targets, {"port": int(port.group(1)), "vlan": int(vlan.group(1))})]
        if port and any(w in text for w in ("disable", "shut", "turn off")):
            return [ToolCall("set_port_enabled", targets, {"port": int(port.group(1)), "enabled": False})]
        if port and any(w in text for w in ("enable", "bring up", "turn on")):
            return [ToolCall("set_port_enabled", targets, {"port": int(port.group(1)), "enabled": True})]
        if port:
            return [ToolCall("port_detail", targets, {"port": int(port.group(1))})]
        if "log" in text:
            return [ToolCall("recent_logs", targets, {"limit": 10})]
        if any(w in text for w in ("port", "link", "error", "slow", "drop", "down")):
            return [ToolCall("list_ports", targets), ToolCall("recent_logs", targets, {"limit": 10})]
        return [ToolCall("device_status", targets)]


class LLMPlanner:
    """Plans with an OpenAI-compatible /v1/chat/completions endpoint."""

    SYSTEM = (
        "You operate network devices by calling tools. Only use the tools provided. "
        "Prefer read-only tools when the user is asking a question. "
        "Known device IDs: {devices}. Use [\"*\"] for all devices."
    )

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport
        )
        self._model = model

    async def plan(self, request: str, devices: list[str]) -> list[ToolCall]:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.SYSTEM.format(devices=", ".join(devices))},
                {"role": "user", "content": request},
            ],
            "tools": tool_schemas(),
            "tool_choice": "auto",
            "temperature": 0,
        }
        resp = await self._http.post("/chat/completions", json=body)
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable": fn.get("arguments")}
            devices_arg = args.pop("devices", ["*"])
            if isinstance(devices_arg, str):
                devices_arg = [devices_arg]
            calls.append(ToolCall(fn.get("name", ""), list(devices_arg), args))
        return calls

    async def close(self) -> None:
        await self._http.aclose()
