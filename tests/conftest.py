import pytest

from netpilot.client import DeviceClient
from netpilot.simulator import SimulatedNetwork


@pytest.fixture
def sim():
    return SimulatedNetwork(latency_s=0.02)


@pytest.fixture
async def client(sim):
    c = DeviceClient("http://controller.local", "admin", "demo-password", transport=sim.transport())
    yield c
    await c.close()
