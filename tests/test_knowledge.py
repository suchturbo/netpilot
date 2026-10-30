from netpilot.knowledge import default_index


def test_finds_the_right_runbook():
    idx = default_index()
    top = idx.search("port 12 has many CRC errors", k=1)[0][1]
    assert top.source == "port-errors.md"


def test_high_cpu_query():
    top = default_index().search("rt-edge-1 CPU is high", k=1)[0][1]
    assert top.source == "high-cpu.md"
