# Copyright 2026 ningjiabing
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Drive the real server over MCP against the mock backend and print a transcript.

This is what the README's demo image is generated from. The server, the MCP
client and every tool are the real thing; only the backend is a stand-in, so no
production hostname or address ends up in a published screenshot.

    uv run python docs/demo/run_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import Client
from mock_backend import serve

from skywalking_zabbix_mcp.config import load_config, load_zabbix_config
from skywalking_zabbix_mcp.server import build_server

PORT = 18800
SERVICE = "192.0.2.11::payment-service"

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def say(text: str = "") -> None:
    print(text, flush=True)


def prompt(text: str) -> None:
    say(f"{BOLD}{CYAN}>{RESET} {BOLD}{text}{RESET}")


def tool_call(name: str, args: dict[str, Any]) -> None:
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    say(f"  {DIM}⏺ {name}({rendered}){RESET}")


async def main() -> None:
    serve(PORT)
    os.environ["SW_URL"] = f"http://127.0.0.1:{PORT}"
    os.environ["ZABBIX_URL"] = f"http://127.0.0.1:{PORT}/zabbix/api_jsonrpc.php"
    os.environ["ZABBIX_USER"] = "demo"
    os.environ["ZABBIX_PASSWORD"] = "demo"
    os.environ["READ_ONLY"] = "true"

    mcp = build_server(load_config(), load_zabbix_config())

    async with Client(mcp) as client:
        tools = await client.list_tools()
        say(
            f"{DIM}skywalking-zabbix-mcp{RESET}  "
            f"{GREEN}{len(tools)} tools{RESET} "
            f"{DIM}(16 SkyWalking + 2 Zabbix + 2 correlation){RESET}"
        )
        say()

        prompt(f"What is wrong with {SERVICE}?")
        tool_call("diagnose_service", {"service_name": SERVICE})
        result = await client.call_tool("diagnose_service", {"service_name": SERVICE})
        data = json.loads(result.content[0].text)

        metrics = data["skywalking"]["metrics"]
        alarms = data["skywalking"]["alarms"]
        zbx = data["zabbix"]
        items = {i["key_"]: i for i in zbx["items"]}

        say()
        say(f"  {BOLD}Application{RESET} {DIM}— SkyWalking{RESET}")
        say(f"    cpm           {metrics['cpm']}")
        say(f"    resp_time_ms  {YELLOW}{metrics['resp_time_ms']}{RESET}")
        say(f"    sla           {metrics['sla']}")
        say(f"    alarm         {alarms[0]['message']}")
        say()
        say(
            f"  {BOLD}Machine{RESET} {DIM}— Zabbix host {zbx['host']['name']} ({zbx['host']['host']}){RESET}"
        )
        say(f"    cpu util      {YELLOW}{items['system.cpu.util']['lastvalue']}%{RESET}")
        say(f"    disk await    {YELLOW}{items['vfs.dev.await']['lastvalue']} ms{RESET}")
        say(f"    problem       {zbx['problems'][0]['name']}")
        say()

        prompt("Which side failed first?")
        tool_call("correlate_incident", {"start": "-1h", "end": "now"})
        result = await client.call_tool("correlate_incident", {"start": "-1h", "end": "now"})
        verdict = json.loads(result.content[0].text)

        say()
        say(f"  {GREEN}{BOLD}{verdict['first_failure']}{RESET}")
        say(f"  {DIM}Zabbix problem opened 2 min before the SkyWalking alarm.{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
