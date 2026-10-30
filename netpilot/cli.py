"""Interactive command line: `python -m netpilot`."""

from __future__ import annotations

import argparse
import asyncio
import os

from .agent import Agent
from .client import DeviceClient
from .knowledge import default_index
from .planner import LLMPlanner, RuleBasedPlanner
from .simulator import SimulatedNetwork
from .validation import ValidatedCall

EXAMPLES = [
    "how are my devices doing?",
    "why is the network slow on sw-core-1?",
    "show port 12 on sw-core-1",
    "move port 5 on sw-lab-2 to vlan 30",
    "reboot rt-edge-1",
]


async def ask_human(call: ValidatedCall) -> bool:
    answer = await asyncio.to_thread(input, f"  {call.describe()} is disruptive. Run it? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


async def main_async(args: argparse.Namespace) -> None:
    sim = SimulatedNetwork()
    client = DeviceClient("http://controller.local", "admin", "demo-password", transport=sim.transport())
    planner = (
        LLMPlanner(args.llm_url, args.model, os.getenv("NETPILOT_LLM_API_KEY"))
        if args.llm_url
        else RuleBasedPlanner()
    )
    agent = Agent(client, planner, runbooks=default_index(), confirm=ask_human)

    print(f"netpilot: {len(await agent.devices())} simulated devices ({', '.join(await agent.devices())})")
    print("Planner:", f"LLM at {args.llm_url} ({args.model})" if args.llm_url else "rule-based (offline)")
    print("Try:", " | ".join(EXAMPLES))
    print("Enter a request, or 'quit' to leave.\n")

    async with client:
        while True:
            try:
                request = await asyncio.to_thread(input, "you> ")
            except EOFError:
                break
            if request.strip().lower() in ("quit", "exit", "q"):
                break
            if not request.strip():
                continue
            reply = await agent.handle(request)
            print(reply.render(), "\n")

    if isinstance(planner, LLMPlanner):
        await planner.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Talk to a simulated network in plain English.")
    p.add_argument("--llm-url", help="OpenAI-compatible base URL, e.g. http://localhost:11434/v1 for Ollama")
    p.add_argument("--model", default="llama3.1", help="Model name for --llm-url")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
