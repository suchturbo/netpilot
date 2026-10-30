from netpilot.agent import Agent
from netpilot.knowledge import default_index
from netpilot.planner import RuleBasedPlanner
from netpilot.validation import ToolCall


async def always_yes(_):
    return True


async def test_diagnoses_port_problems(client):
    agent = Agent(client, RuleBasedPlanner(), runbooks=default_index())
    reply = await agent.handle("why is the network slow on sw-core-1?")
    text = "\n".join(reply.findings)
    assert "port 12 has 4,312 CRC/input errors" in text
    assert "port 7 link is down" in text
    assert any("CRC" in g for g in reply.guidance)


async def test_disruptive_action_waits_for_confirmation(client, sim):
    agent = Agent(client, RuleBasedPlanner())
    reply = await agent.handle("reboot rt-edge-1")
    assert reply.declined and not reply.executed
    assert sim.devices["rt-edge-1"].uptime_s > 0


async def test_confirmed_disruptive_action_runs(client, sim):
    agent = Agent(client, RuleBasedPlanner(), confirm=always_yes)
    reply = await agent.handle("reboot rt-edge-1")
    assert reply.executed
    assert sim.devices["rt-edge-1"].uptime_s == 0


async def test_change_applies_to_device(client, sim):
    agent = Agent(client, RuleBasedPlanner())
    await agent.handle("move port 5 on sw-lab-2 to vlan 30")
    assert sim.devices["sw-lab-2"].ports[5].vlan == 30


class HallucinatingPlanner:
    async def plan(self, request, devices):
        return [
            ToolCall("format_flash", ["sw-core-1"]),
            ToolCall("set_port_vlan", ["sw-core-1"], {"port": 2, "vlan": 9999}),
            ToolCall("device_status", ["sw-imaginary"]),
        ]


async def test_bad_plans_never_reach_devices(client, sim):
    before = sim.request_count
    agent = Agent(client, HallucinatingPlanner(), confirm=always_yes)
    await agent.devices()
    after_listing = sim.request_count
    reply = await agent.handle("do something dangerous")
    assert len(reply.rejected) == 3 and not reply.executed
    assert sim.request_count == after_listing  # nothing was sent to a device
    assert sim.devices["sw-core-1"].ports[2].vlan == 1
