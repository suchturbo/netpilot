import json

import httpx

from netpilot.agent import Agent
from netpilot.planner import LLMPlanner


def fake_model(tool_calls):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "tool_calls": tool_calls}}]})

    return httpx.MockTransport(handler), seen


def call(name, args):
    return {"id": "1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


async def test_llm_tool_calls_are_parsed_and_sent_with_schemas(client):
    transport, seen = fake_model([call("port_detail", {"devices": ["sw-core-1"], "port": 12})])
    planner = LLMPlanner("http://llm.local/v1", "test-model", transport=transport)
    agent = Agent(client, planner)
    reply = await agent.handle("what's wrong with port 12 on the core switch?")
    assert reply.executed and reply.executed[0].results[0].result["rx_errors"] == 4312
    tool_names = {t["function"]["name"] for t in seen["body"]["tools"]}
    assert "reboot_device" in tool_names and seen["body"]["temperature"] == 0
    await planner.close()


async def test_llm_cannot_bypass_validation(client, sim):
    transport, _ = fake_model([
        call("set_port_vlan", {"devices": ["*"], "port": 1, "vlan": 99999}),
        call("rm_rf", {"devices": ["sw-core-1"]}),
        {"id": "3", "type": "function", "function": {"name": "port_detail", "arguments": "{not json"}},
    ])
    planner = LLMPlanner("http://llm.local/v1", "test-model", transport=transport)
    reply = await Agent(client, planner).handle("break everything")
    assert len(reply.rejected) == 3 and not reply.executed
    assert all(p.vlan == 1 for p in sim.devices["sw-core-1"].ports.values())
    await planner.close()
