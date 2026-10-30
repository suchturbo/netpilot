"""The safety layer between the planner and the network.

Nothing the planner (rule-based or LLM) proposes reaches a device until it
passes these checks:

1. The operation exists in the catalog. Unknown names are rejected, so a
   model cannot invent a call.
2. Parameters match the operation's schema exactly: right types, in range,
   no extra fields.
3. Every target device exists. "*" expands to the full fleet.
4. Writes are capped to a maximum number of devices per request.
5. Disruptive operations need an explicit confirmation from a human.

The result is deterministic: the same plan always validates the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .operations import OPERATIONS, Operation, Risk


@dataclass
class ToolCall:
    """What a planner proposes."""

    name: str
    devices: list[str]
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedCall:
    op: Operation
    devices: list[str]
    params: dict[str, Any]

    @property
    def needs_confirmation(self) -> bool:
        return self.op.risk is Risk.DISRUPTIVE

    def describe(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.op.name}({args}) on {', '.join(self.devices)}"


@dataclass
class Rejection:
    call: ToolCall
    reasons: list[str]

    def describe(self) -> str:
        return f"{self.call.name} rejected: " + "; ".join(self.reasons)


@dataclass
class Policy:
    max_write_targets: int = 3


def validate(call: ToolCall, known_devices: set[str], policy: Policy | None = None) -> ValidatedCall | Rejection:
    policy = policy or Policy()
    reasons: list[str] = []

    op = OPERATIONS.get(call.name)
    if op is None:
        return Rejection(call, [f"unknown operation '{call.name}'"])

    # targets
    if not call.devices:
        reasons.append("no target devices given")
    targets = sorted(known_devices) if "*" in call.devices else list(dict.fromkeys(call.devices))
    unknown = [d for d in targets if d not in known_devices]
    if unknown:
        reasons.append(f"unknown device(s): {', '.join(unknown)}")
    if op.risk is not Risk.READ and len(targets) > policy.max_write_targets:
        reasons.append(
            f"{op.risk.value} operations are limited to {policy.max_write_targets} devices per request "
            f"(asked for {len(targets)})"
        )

    # parameters
    params: dict[str, Any] = {}
    try:
        params = op.params.model_validate(call.args).model_dump()
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "arguments"
            reasons.append(f"{loc}: {err['msg']}")

    if reasons:
        return Rejection(call, reasons)
    return ValidatedCall(op, targets, params)
