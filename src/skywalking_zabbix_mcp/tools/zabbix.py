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

"""Zabbix tools: zabbix_query, zabbix_list. Few generic tools rather than one tool
per API method, to keep the tool surface (and LLM context) small."""

from __future__ import annotations

from typing import Any

from ..zabbix.client import ZabbixClient, ZabbixError
from ._util import ToolError, to_json

# A short catalogue of commonly used read methods, returned by zabbix_list for
# discovery. Not exhaustive — any method the API exposes can be passed to
# zabbix_query (subject to the read-only guard).
_COMMON_METHODS = {
    "apiinfo.version": "Zabbix API version (no auth).",
    "host.get": "Hosts (filter/search by host, hostids, groupids).",
    "hostgroup.get": "Host groups.",
    "item.get": "Items/metrics of hosts (filter by hostids, key_, search).",
    "history.get": "Historical metric values (needs itemids + history type 0-4).",
    "trend.get": "Hourly trend aggregates (itemids).",
    "trigger.get": "Triggers (filter by hostids; only_true, active).",
    "problem.get": "Current problems/alarms (recent=true for active).",
    "event.get": "Events (problem/resolution history).",
    "service.get": "IT services.",
    "template.get": "Templates.",
    "graph.get": "Graphs.",
}


def register(mcp, client: ZabbixClient) -> None:
    @mcp.tool(name="zabbix_query")
    def zabbix_query(method: str, params: dict[str, Any] | None = None) -> str:
        """Execute any Zabbix JSON-RPC API method and return its result.

        Use zabbix_list first to discover method names. In read-only mode only *.get
        (plus apiinfo.version) are allowed; write methods are refused.

        - method: e.g. "host.get", "item.get", "problem.get", "history.get".
        - params: the method's params object.
        Examples:
          {"method": "host.get", "params": {"filter": {"host": ["192.0.2.11"]}, "output": ["hostid","host","name"]}}
          {"method": "problem.get", "params": {"recent": true, "output": "extend"}}
          {"method": "history.get", "params": {"itemids": ["12345"], "history": 3, "limit": 10, "sortfield": "clock", "sortorder": "DESC"}}"""
        try:
            result = client.call(method, params or {})
        except ZabbixError as exc:
            raise ToolError(str(exc)) from exc
        return to_json(result)

    @mcp.tool(name="zabbix_list")
    def zabbix_list() -> str:
        """List commonly used Zabbix API methods for discovery, with the live API
        version. Pass any method to zabbix_query (read-only mode limits it to *.get)."""
        try:
            version = client.call("apiinfo.version")
        except ZabbixError as exc:
            version = f"<unavailable: {exc}>"
        return to_json({"api_version": version, "common_methods": _COMMON_METHODS})
