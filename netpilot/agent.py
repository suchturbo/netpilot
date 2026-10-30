"""The agent loop: plan, validate, confirm, execute, explain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .client import DeviceClient, FleetResult
from .knowledge import RunbookIndex
from .planner import Planner
from .validation import Policy, Rejection, ValidatedCall, validate

Confirm = Callable[[ValidatedCall], Awaitable[bool]]


async def deny_all(_: ValidatedCall) -> bool:
    return False


@dataclass
class StepResult:
    call: ValidatedCall
    results: list[FleetResult]


@dataclass
class AgentReply:
    request: str
    executed: list[StepResult] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    declined: list[ValidatedCall] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    def render(self) -> str:
        out: list[str] = []
        for r in self.rejected:
            out.append(f"✗ {r.describe()}")
        for c in self.declined:
            out.append(f"⏸ not run (needs confirmation): {c.describe()}")
        for step in self.executed:
            ok = sum(r.ok for r in step.results)
            out.append(f"✓ {step.call.describe()}: {ok}/{len(step.results)} devices answered")
            for r in step.results:
                if not r.ok:
                    out.append(f"    {r.device_id}: {r.error}")
        if self.findings:
            out.append("\nFindings")
            out.extend(f"  • {f}" for f in self.findings)
        if self.guidance:
            out.append("\nFrom the runbooks")
            out.extend(f"  • {g}" for g in self.guidance)
        if not out:
            out.append("Nothing to do for that request.")
        return "\n".join(out)


class Agent:
    def __init__(
        self,
        client: DeviceClient,
        planner: Planner,
        *,
        runbooks: RunbookIndex | None = None,
        policy: Policy | None = None,
        confirm: Confirm = deny_all,
    ):
        self.client = client
        self.planner = planner
        self.runbooks = runbooks
        self.policy = policy or Policy()
        self.confirm = confirm
        self._devices: list[str] | None = None

    async def devices(self) -> list[str]:
        if self._devices is None:
            self._devices = [d["id"] for d in await self.client.list_devices()]
        return self._devices

    async def handle(self, request: str) -> AgentReply:
        reply = AgentReply(request)
        known = await self.devices()
        proposals = await self.planner.plan(request, known)

        for proposal in proposals:
            checked = validate(proposal, set(known), self.policy)
            if isinstance(checked, Rejection):
                reply.rejected.append(checked)
                continue
            if checked.needs_confirmation and not await self.confirm(checked):
                reply.declined.append(checked)
                continue
            results = await self.client.rpc_many(checked.devices, checked.op.rpc_method, checked.params)
            reply.executed.append(StepResult(checked, results))

        reply.findings = _findings(reply.executed)
        if self.runbooks and reply.findings:
            seen = set()
            for f in reply.findings:
                for _, p in self.runbooks.search(f, k=1):
                    key = (p.source, p.heading)
                    if key not in seen:
                        seen.add(key)
                        reply.guidance.append(f"{p.heading}: {p.text.splitlines()[0]}")
        return reply


def _findings(steps: list[StepResult]) -> list[str]:
    """Turn raw results into plain statements a person can act on."""
    found: list[str] = []
    for step in steps:
        for r in step.results:
            if not r.ok:
                continue
            if step.call.op.name == "device_status":
                s = r.result
                if s["cpu_pct"] >= 80:
                    found.append(f"{r.device_id} CPU is high at {s['cpu_pct']:.0f}%")
                down = s["ports_total"] - s["ports_up"]
                if down:
                    found.append(f"{r.device_id} has {down} of {s['ports_total']} ports with link down")
            elif step.call.op.name in ("list_ports", "port_detail"):
                ports = r.result if isinstance(r.result, list) else [r.result]
                for p in ports:
                    if not p["enabled"]:
                        found.append(f"{r.device_id} port {p['number']} is administratively disabled")
                    elif not p["link_up"]:
                        found.append(f"{r.device_id} port {p['number']} link is down")
                    if p["rx_errors"] >= 100:
                        found.append(f"{r.device_id} port {p['number']} has {p['rx_errors']:,} CRC/input errors")
            elif step.call.op.name == "recent_logs":
                for line in r.result:
                    if line.startswith(("WARN", "ERROR")):
                        found.append(f"{r.device_id} log: {line}")
    return list(dict.fromkeys(found))
