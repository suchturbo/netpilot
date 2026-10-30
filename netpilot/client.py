"""Async client for device APIs: session login, JSON-RPC calls, fleet fan-out."""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from typing import Any

import httpx


class DeviceAPIError(Exception):
    """A device answered, but with an error."""

    def __init__(self, device_id: str, message: str, code: int | None = None):
        super().__init__(f"{device_id}: {message}")
        self.device_id = device_id
        self.message = message
        self.code = code


@dataclass
class FleetResult:
    device_id: str
    ok: bool
    result: Any = None
    error: str | None = None


class DeviceClient:
    """Talks to a controller that fronts many devices.

    - Logs in once and reuses the session token.
    - Logs in again automatically when the token expires (HTTP 401).
    - Sends JSON-RPC 2.0 calls to individual devices.
    - Fans a call out to many devices concurrently, with a concurrency cap.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_concurrency: int = 16,
        timeout_s: float = 10.0,
    ):
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout_s)
        self._username = username
        self._password = password
        self._token: str | None = None
        self._login_lock = asyncio.Lock()
        self._ids = itertools.count(1)
        self._sem = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> "DeviceClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    # ---------------------------------------------------------------- session

    async def login(self) -> None:
        async with self._login_lock:
            resp = await self._http.post(
                "/api/session", json={"username": self._username, "password": self._password}
            )
            if resp.status_code != 200:
                raise DeviceAPIError("controller", f"login failed ({resp.status_code})")
            self._token = resp.json()["token"]

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self._token is None:
            await self.login()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._token}"}
            resp = await self._http.request(method, path, headers=headers, **kwargs)
            if resp.status_code != 401 or attempt == 1:
                return resp
            stale = self._token
            async with self._login_lock:
                needs_login = self._token == stale
            if needs_login:
                await self.login()
        return resp  # pragma: no cover

    # ---------------------------------------------------------------- calls

    async def list_devices(self) -> list[dict]:
        resp = await self._request("GET", "/api/devices")
        resp.raise_for_status()
        return resp.json()

    async def rpc(self, device_id: str, method: str, params: dict | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        async with self._sem:
            resp = await self._request("POST", f"/api/devices/{device_id}/rpc", json=payload)
        if resp.status_code != 200:
            raise DeviceAPIError(device_id, f"HTTP {resp.status_code}")
        body = resp.json()
        if "error" in body:
            err = body["error"]
            raise DeviceAPIError(device_id, err.get("message", "unknown error"), err.get("code"))
        return body["result"]

    async def rpc_many(self, device_ids: list[str], method: str, params: dict | None = None) -> list[FleetResult]:
        """Run the same call on many devices at once. One failure never sinks the rest."""

        async def one(device_id: str) -> FleetResult:
            try:
                return FleetResult(device_id, True, await self.rpc(device_id, method, params))
            except DeviceAPIError as e:
                return FleetResult(device_id, False, error=e.message)
            except httpx.HTTPError as e:
                return FleetResult(device_id, False, error=f"transport error: {e}")

        return list(await asyncio.gather(*(one(d) for d in device_ids)))

    async def supported_methods(self, device_id: str, candidates: list[str]) -> list[str]:
        """Probe which methods a device implements. Firmware versions differ,
        so the agent checks before relying on a method."""
        found = []
        for m in candidates:
            try:
                await self.rpc(device_id, m)
                found.append(m)
            except DeviceAPIError as e:
                if e.code != -32601:  # anything but "method not found" means it exists
                    found.append(m)
        return found
