"""The catalog of operations the agent is allowed to perform.

Each operation declares its parameters as a pydantic model, a risk level,
and which device RPC it maps to. The same catalog drives validation, the
LLM tool schemas, and the MCP server, so there is one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Type

from pydantic import BaseModel, ConfigDict, Field


class Risk(str, Enum):
    READ = "read"              # no side effects
    CHANGE = "change"          # changes config, easy to undo
    DISRUPTIVE = "disruptive"  # drops traffic or restarts hardware: needs confirmation


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoParams(_Params):
    pass


class PortParams(_Params):
    port: int = Field(ge=1, le=52, description="Port number on the device")


class PortEnableParams(_Params):
    port: int = Field(ge=1, le=52)
    enabled: bool


class PortVlanParams(_Params):
    port: int = Field(ge=1, le=52)
    vlan: int = Field(ge=1, le=4094, description="802.1Q VLAN ID")


class LogParams(_Params):
    limit: int = Field(default=20, ge=1, le=200)


@dataclass(frozen=True)
class Operation:
    name: str
    description: str
    rpc_method: str
    params: Type[_Params]
    risk: Risk

    def tool_schema(self) -> dict:
        """OpenAI-style function schema for LLM tool calling."""
        schema = self.params.model_json_schema()
        props = dict(schema.get("properties", {}))
        props["devices"] = {
            "type": "array",
            "items": {"type": "string"},
            "description": "Device IDs to run on. Use [\"*\"] for every device.",
        }
        required = ["devices", *schema.get("required", [])]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"{self.description} (risk: {self.risk.value})",
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        }


OPERATIONS: dict[str, Operation] = {
    op.name: op
    for op in [
        Operation("device_status", "Model, firmware, uptime, CPU, and how many ports are up", "get_status", NoParams, Risk.READ),
        Operation("list_ports", "Every port with link state, speed, VLAN, and error counters", "get_ports", NoParams, Risk.READ),
        Operation("port_detail", "One port's link state, speed, VLAN, and error counters", "get_port", PortParams, Risk.READ),
        Operation("recent_logs", "The device's most recent log lines", "get_logs", LogParams, Risk.READ),
        Operation("set_port_vlan", "Move a port to a different VLAN", "set_port_vlan", PortVlanParams, Risk.CHANGE),
        Operation("set_port_enabled", "Administratively enable or disable a port", "set_port_enabled", PortEnableParams, Risk.DISRUPTIVE),
        Operation("reboot_device", "Restart the device", "reboot", NoParams, Risk.DISRUPTIVE),
    ]
}


def tool_schemas() -> list[dict]:
    return [op.tool_schema() for op in OPERATIONS.values()]
