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

"""Shared fixtures and helpers for the HTTP-mocked tests."""

from __future__ import annotations

from typing import Any

import httpx

from skywalking_zabbix_mcp.client import GraphQLClient
from skywalking_zabbix_mcp.config import Config
from skywalking_zabbix_mcp.zabbix.client import ZabbixClient

OAP = "http://oap.example:12800/graphql"
ZBX = "http://zabbix.example/zabbix/api_jsonrpc.php"


def make_client(username: str = "", password: str = "") -> GraphQLClient:
    return GraphQLClient(
        Config(
            url="http://oap.example:12800",
            username=username,
            password=password,
            insecure=False,
            read_only=False,
            log_level="info",
        )
    )


def gql_response(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": {"result": result}})


def zbx_client(read_only: bool = False) -> ZabbixClient:
    return ZabbixClient(ZBX, "api-user", "api-pass", read_only=read_only)


def zbx_result(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": 1})


class FakeMCP:
    """Minimal stand-in for FastMCP that just captures the registered callables."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str, **_kwargs: Any):
        def decorator(fn):
            self.tools[name] = fn
            return fn

        return decorator
