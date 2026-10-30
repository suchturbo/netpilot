# netpilot

Talk to network switches and routers in plain English, with a safety layer that makes sure only valid, approved operations ever reach a device.

```
you> why is the network slow on sw-core-1?
✓ list_ports() on sw-core-1: 1/1 devices answered
✓ recent_logs(limit=10) on sw-core-1: 1/1 devices answered

Findings
  • sw-core-1 port 7 link is down
  • sw-core-1 port 12 has 4,312 CRC/input errors
  • sw-core-1 log: WARN port 12 CRC errors rising

From the runbooks
  • CRC and input errors on a port: Rising CRC or input errors usually mean a physical layer problem, not a configuration problem.

you> reboot rt-edge-1
  reboot_device() on rt-edge-1 is disruptive. Run it? [y/N]
```

## Why

Letting a language model drive network gear is risky: models invent commands, pass out-of-range values, and target the wrong device. netpilot splits the job in two:

- A **planner** turns a request into proposed tool calls. It can be a local LLM or an offline rule-based planner.
- A **deterministic validation layer** decides what actually runs. A model can propose anything, but it cannot bypass this layer.

## How it works

```
request ──► planner ──► proposed calls ──► validation ──► confirmation ──► devices
            (LLM or        (untrusted)     (catalog,       (disruptive      (async,
             rules)                         schema, policy)  ops only)       concurrent)
                                                                   │
                                     findings + runbook guidance ◄─┘
```

**Operation catalog** (`operations.py`). Every allowed action is declared once, with a typed parameter schema and a risk level: `read`, `change`, or `disruptive`. The same catalog generates the LLM tool schemas and the MCP tools.

**Validation** (`validation.py`). Before anything is sent:
- unknown operations are rejected, so a model can't invent a call
- parameters must match the schema exactly (types, ranges such as VLAN 1–4094, no extra fields)
- every target device must exist
- writes are capped to a set number of devices per request
- disruptive operations need explicit human confirmation

**Device client** (`client.py`). An async `httpx` client with session-token login, automatic re-login when a session expires, JSON-RPC 2.0 calls, concurrent fleet queries with a concurrency cap, and probing for which methods a device's firmware supports.

**Runbook retrieval** (`knowledge.py`). A small TF-IDF index over local Markdown runbooks attaches relevant troubleshooting steps to each finding. It runs offline with no model downloads.

**Simulator** (`simulator.py`). Three in-memory devices with realistic problems baked in (a dead link, a port full of CRC errors, a router with high CPU), served over an `httpx` mock transport. Everything runs and tests without hardware.

## Run it

```bash
pip install -e ".[dev]"
python -m netpilot                      # offline rule-based planner
```

With a local model through any OpenAI-compatible server, for example [Ollama](https://ollama.com):

```bash
ollama pull llama3.1
python -m netpilot --llm-url http://localhost:11434/v1 --model llama3.1
```

As an MCP server, so an MCP client can use the tools. Disruptive operations are refused here because there is no human to confirm them:

```bash
pip install -e ".[mcp]"
python -m netpilot.mcp_server
```

## Tests

```bash
pytest
```

The tests cover the validation rules, session expiry and re-login, concurrency of fleet calls, method discovery, runbook retrieval, end-to-end diagnosis, and that a misbehaving planner (invented operations, bad arguments, unparseable JSON) never causes a single request to reach a device.

## Note

This is an independent personal project. It is not affiliated with, endorsed by, or derived from the code of any network equipment vendor. It talks only to the built-in simulator and a generic API defined in this repository.

## License

MIT
