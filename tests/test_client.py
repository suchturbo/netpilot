import time

import pytest

from netpilot.client import DeviceAPIError


async def test_lists_devices(client):
    ids = {d["id"] for d in await client.list_devices()}
    assert ids == {"sw-core-1", "sw-lab-2", "rt-edge-1"}


async def test_rpc_error_is_raised(client):
    with pytest.raises(DeviceAPIError) as e:
        await client.rpc("sw-lab-2", "get_port", {"port": 99})
    assert "no port 99" in e.value.message


async def test_relogs_in_when_session_expires(client, sim):
    await client.rpc("sw-core-1", "get_status")
    sim.expire_all_sessions()
    status = await client.rpc("sw-core-1", "get_status")
    assert status["id"] == "sw-core-1"


async def test_fleet_calls_run_concurrently(client, sim):
    sim.latency_s = 0.2
    await client.login()
    start = time.perf_counter()
    results = await client.rpc_many(["sw-core-1", "sw-lab-2", "rt-edge-1"], "get_status")
    elapsed = time.perf_counter() - start
    assert all(r.ok for r in results)
    assert elapsed < 0.45  # sequential would take ~0.6s


async def test_one_bad_device_does_not_sink_the_rest(client):
    results = await client.rpc_many(["sw-core-1", "nope"], "get_status")
    by_id = {r.device_id: r for r in results}
    assert by_id["sw-core-1"].ok
    assert not by_id["nope"].ok


async def test_method_discovery(client):
    found = await client.supported_methods("sw-core-1", ["get_status", "get_poe_budget", "get_ports"])
    assert found == ["get_status", "get_ports"]
