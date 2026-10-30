from netpilot.operations import Risk
from netpilot.validation import Policy, Rejection, ToolCall, ValidatedCall, validate

FLEET = {"sw-core-1", "sw-lab-2", "rt-edge-1"}


def test_unknown_operation_is_rejected():
    r = validate(ToolCall("drop_all_tables", ["sw-core-1"]), FLEET)
    assert isinstance(r, Rejection)
    assert "unknown operation" in r.reasons[0]


def test_unknown_device_is_rejected():
    r = validate(ToolCall("device_status", ["sw-ghost-9"]), FLEET)
    assert isinstance(r, Rejection)
    assert "sw-ghost-9" in r.reasons[0]


def test_out_of_range_vlan_is_rejected():
    r = validate(ToolCall("set_port_vlan", ["sw-lab-2"], {"port": 5, "vlan": 5000}), FLEET)
    assert isinstance(r, Rejection)
    assert any("vlan" in reason for reason in r.reasons)


def test_extra_arguments_are_rejected():
    r = validate(ToolCall("port_detail", ["sw-core-1"], {"port": 3, "force": True}), FLEET)
    assert isinstance(r, Rejection)


def test_wrong_type_is_rejected():
    r = validate(ToolCall("port_detail", ["sw-core-1"], {"port": "all"}), FLEET)
    assert isinstance(r, Rejection)


def test_wildcard_expands_to_fleet():
    r = validate(ToolCall("device_status", ["*"]), FLEET)
    assert isinstance(r, ValidatedCall)
    assert set(r.devices) == FLEET


def test_write_fanout_is_capped():
    r = validate(ToolCall("set_port_vlan", ["*"], {"port": 1, "vlan": 10}), FLEET, Policy(max_write_targets=2))
    assert isinstance(r, Rejection)
    assert "limited to 2 devices" in r.reasons[0]


def test_disruptive_calls_need_confirmation():
    r = validate(ToolCall("reboot_device", ["rt-edge-1"]), FLEET)
    assert isinstance(r, ValidatedCall)
    assert r.op.risk is Risk.DISRUPTIVE and r.needs_confirmation


def test_validation_is_deterministic():
    call = ToolCall("set_port_vlan", ["sw-lab-2"], {"port": 5, "vlan": 30})
    a, b = validate(call, FLEET), validate(call, FLEET)
    assert a.devices == b.devices and a.params == b.params
