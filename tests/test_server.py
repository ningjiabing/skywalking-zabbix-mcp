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

"""Server assembly tests.

The documented contract is that a SkyWalking-only configuration exposes 16 tools
and that setting ``ZABBIX_URL`` adds exactly the 4 Zabbix/correlation tools. This
pins that down so a registration mistake cannot ship silently.
"""

from __future__ import annotations

import asyncio

from skywalking_zabbix_mcp.config import Config, ZabbixConfig
from skywalking_zabbix_mcp.server import build_server

SKYWALKING_TOOLS = {
    "list_layers",
    "list_services",
    "list_instances",
    "list_endpoints",
    "list_processes",
    "query_services_topology",
    "query_instances_topology",
    "query_endpoints_topology",
    "query_processes_topology",
    "query_traces",
    "execute_mqe_expression",
    "list_mqe_metrics",
    "get_mqe_metric_type",
    "query_alarms",
    "query_events",
    "query_logs",
}

ZABBIX_TOOLS = {"zabbix_query", "zabbix_list", "diagnose_service", "correlate_incident"}

PROMPTS = {
    "analyze-performance",
    "compare-services",
    "top-services",
    "investigate-traces",
    "trace-deep-dive",
    "analyze-logs",
    "explore-service-topology",
    "generate_duration",
    "build-mqe-query",
    "explore-metrics",
}


def sw_config() -> Config:
    return Config(
        url="http://oap.example:12800",
        username="",
        password="",
        insecure=False,
        read_only=True,
        log_level="info",
    )


def zabbix_config(url: str) -> ZabbixConfig:
    return ZabbixConfig(
        url=url,
        user="api-user",
        password="api-pass",
        verify_ssl=True,
        read_only=True,
        skip_version_check=False,
    )


def tool_names(mcp) -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_skywalking_only_registers_16_tools():
    mcp = build_server(sw_config(), zabbix_config(""))

    names = tool_names(mcp)

    assert names == SKYWALKING_TOOLS
    assert len(names) == 16


def test_zabbix_url_adds_exactly_4_tools():
    mcp = build_server(sw_config(), zabbix_config("http://zabbix.example/api_jsonrpc.php"))

    names = tool_names(mcp)

    assert names == SKYWALKING_TOOLS | ZABBIX_TOOLS
    assert len(names) == 20


def test_prompts_and_resources_are_registered():
    mcp = build_server(sw_config(), zabbix_config(""))

    assert {p.name for p in asyncio.run(mcp.list_prompts())} == PROMPTS

    static = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
    assert static == {
        "mqe://docs/syntax",
        "mqe://docs/examples",
        "mqe://docs/ai_prompt",
        "mqe://metrics/available",
    }


def test_every_tool_has_a_description_for_the_model():
    mcp = build_server(sw_config(), zabbix_config("http://zabbix.example/api_jsonrpc.php"))

    for tool in asyncio.run(mcp.list_tools()):
        assert tool.description, f"{tool.name} has no description"
