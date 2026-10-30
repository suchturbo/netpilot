"""Expose the operation catalog as MCP tools, so any MCP client
(Claude Desktop, an IDE agent) can drive the simulated network.

Every tool call goes through the same validation as the CLI agent.
Disruptive operations are refused here, because an MCP client has no way
to ask a human for confirmation through this server.

Run with:  pip install "netpilot[mcp]"  then  python -m netpilot.mcp_server
"""

from __future__ import annotations

import json

from .client import DeviceClient
from .operations import OPERATIONS, Risk
from .simulator import SimulatedNetwork
from .validation import Rejection, ToolCall, validate


def build_server():
    from fastmcp import FastMCP  # optional dependency

    sim = SimulatedNetwork()
    client = DeviceClient("http://controller.local", "admin", "demo-password", transport=sim.transport())
    mcp = FastMCP("netpilot")

    async def run(name: str, devices: list[str], args: dict) -> str:
        known = {d["id"] for d in await client.list_devices()}
        checked = validate(ToolCall(name, devices, args), known)
        if isinstance(checked, Rejection):
            return checked.describe()
        if checked.op.risk is Risk.DISRUPTIVE:
            return f"Refused: {checked.describe()} is disruptive and needs a human to confirm it in the CLI."
        results = await client.rpc_many(checked.devices, checked.op.rpc_method, checked.params)
        return json.dumps([r.__dict__ for r in results], indent=2)

    @mcp.tool()
    async def list_devices() -> str:
        """List every device in the network."""
        return json.dumps(await client.list_devices(), indent=2)

    for op in OPERATIONS.values():
        def make(op_name: str, doc: str):
            async def tool(devices: list[str], args: dict | None = None) -> str:
                return await run(op_name, devices, args or {})
            tool.__name__ = op_name
            tool.__doc__ = doc
            return tool

        mcp.tool()(make(op.name, f"{op.description}. Risk: {op.risk.value}. Args schema: {op.params.model_json_schema()}"))

    return mcp


if __name__ == "__main__":
    build_server().run()
