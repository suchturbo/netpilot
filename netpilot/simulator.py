"""In-memory simulated network devices served over an httpx transport.

The simulator stands in for real switches and routers so the agent can be
developed and tested without hardware. It exposes a small, generic API:

    POST /api/session               -> {"token": "..."}      (username/password)
    GET  /api/devices               -> [{"id": ..., ...}]
    POST /api/devices/{id}/rpc      -> JSON-RPC 2.0 call

Every call except /api/session needs `Authorization: Bearer <token>`.
Tokens expire after `token_ttl` seconds to exercise re-authentication.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Port:
    number: int
    enabled: bool = True
    link_up: bool = True
    speed_mbps: int = 1000
    vlan: int = 1
    rx_errors: int = 0


@dataclass
class Device:
    id: str
    kind: str  # "switch" or "router"
    model: str
    firmware: str
    ports: dict[int, Port] = field(default_factory=dict)
    uptime_s: int = 86_400
    cpu_pct: float = 12.0
    logs: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "model": self.model,
            "firmware": self.firmware,
            "port_count": len(self.ports),
        }


def demo_fleet() -> dict[str, Device]:
    """A small fleet with a couple of realistic problems baked in."""

    def ports(n: int) -> dict[int, Port]:
        return {i: Port(number=i) for i in range(1, n + 1)}

    sw1 = Device("sw-core-1", "switch", "Generic 24-port managed switch", "2.4.1", ports(24))
    sw2 = Device("sw-lab-2", "switch", "Generic 8-port managed switch", "2.3.9", ports(8))
    rt1 = Device("rt-edge-1", "router", "Generic edge router", "5.1.0", ports(4))

    # Problems for the agent to find.
    sw1.ports[7].link_up = False
    sw1.ports[7].rx_errors = 0
    sw1.ports[12].rx_errors = 4_312
    sw2.ports[3].enabled = False
    sw2.ports[3].link_up = False
    rt1.cpu_pct = 91.5
    rt1.logs.append("WARN high CPU on control plane")
    sw1.logs.append("INFO port 7 link down")
    sw1.logs.append("WARN port 12 CRC errors rising")

    return {d.id: d for d in (sw1, sw2, rt1)}


class RPCError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SimulatedNetwork:
    """Holds device state and answers HTTP requests for it."""

    def __init__(
        self,
        devices: dict[str, Device] | None = None,
        *,
        username: str = "admin",
        password: str = "demo-password",
        latency_s: float = 0.05,
        token_ttl: float = 300.0,
    ):
        self.devices = devices if devices is not None else demo_fleet()
        self._username = username
        self._password = password
        self.latency_s = latency_s
        self.token_ttl = token_ttl
        self._tokens: dict[str, float] = {}
        self.request_count = 0

    # ---------------------------------------------------------------- transport

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        await asyncio.sleep(self.latency_s)
        path = request.url.path

        if request.method == "POST" and path == "/api/session":
            return self._login(request)

        if not self._authorized(request):
            return httpx.Response(401, json={"error": "invalid or expired session"})

        if request.method == "GET" and path == "/api/devices":
            return httpx.Response(200, json=[d.summary() for d in self.devices.values()])

        parts = path.strip("/").split("/")
        if request.method == "POST" and len(parts) == 4 and parts[:2] == ["api", "devices"] and parts[3] == "rpc":
            return self._rpc(parts[2], request)

        return httpx.Response(404, json={"error": "not found"})

    def _login(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if body.get("username") != self._username or body.get("password") != self._password:
            return httpx.Response(403, json={"error": "bad credentials"})
        token = secrets.token_hex(16)
        self._tokens[token] = time.monotonic() + self.token_ttl
        return httpx.Response(200, json={"token": token, "expires_in": self.token_ttl})

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return False
        expiry = self._tokens.get(header[7:])
        return expiry is not None and expiry > time.monotonic()

    def expire_all_sessions(self) -> None:
        self._tokens.clear()

    # ---------------------------------------------------------------- JSON-RPC

    def _rpc(self, device_id: str, request: httpx.Request) -> httpx.Response:
        try:
            msg = json.loads(request.content)
        except json.JSONDecodeError:
            return httpx.Response(200, json=_rpc_error(None, -32700, "parse error"))

        req_id = msg.get("id")
        device = self.devices.get(device_id)
        if device is None:
            return httpx.Response(200, json=_rpc_error(req_id, -32001, f"unknown device {device_id}"))

        method = msg.get("method")
        params = msg.get("params") or {}
        handler = getattr(self, f"_m_{method}", None)
        if handler is None:
            return httpx.Response(200, json=_rpc_error(req_id, -32601, f"unknown method {method}"))
        try:
            result = handler(device, **params)
        except RPCError as e:
            return httpx.Response(200, json=_rpc_error(req_id, e.code, e.message))
        except TypeError as e:
            return httpx.Response(200, json=_rpc_error(req_id, -32602, f"invalid params: {e}"))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "result": result})

    @staticmethod
    def _port(device: Device, port: int) -> Port:
        p = device.ports.get(port)
        if p is None:
            raise RPCError(-32002, f"{device.id} has no port {port}")
        return p

    def _m_get_status(self, device: Device) -> dict:
        return {
            "id": device.id,
            "model": device.model,
            "firmware": device.firmware,
            "uptime_s": device.uptime_s,
            "cpu_pct": device.cpu_pct,
            "ports_up": sum(p.link_up for p in device.ports.values()),
            "ports_total": len(device.ports),
        }

    def _m_get_ports(self, device: Device) -> list[dict]:
        return [vars(p).copy() for p in device.ports.values()]

    def _m_get_port(self, device: Device, port: int) -> dict:
        return vars(self._port(device, port)).copy()

    def _m_set_port_enabled(self, device: Device, port: int, enabled: bool) -> dict:
        p = self._port(device, port)
        p.enabled = enabled
        p.link_up = enabled
        device.logs.append(f"INFO port {port} {'enabled' if enabled else 'disabled'} by agent")
        return vars(p).copy()

    def _m_set_port_vlan(self, device: Device, port: int, vlan: int) -> dict:
        p = self._port(device, port)
        p.vlan = vlan
        device.logs.append(f"INFO port {port} moved to VLAN {vlan} by agent")
        return vars(p).copy()

    def _m_get_logs(self, device: Device, limit: int = 20) -> list[str]:
        return device.logs[-limit:]

    def _m_reboot(self, device: Device) -> dict:
        device.uptime_s = 0
        device.cpu_pct = 5.0
        device.logs.append("INFO reboot requested by agent")
        return {"rebooting": True}


def _rpc_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
