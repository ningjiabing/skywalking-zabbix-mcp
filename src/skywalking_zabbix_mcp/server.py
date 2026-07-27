# Licensed to Apache Software Foundation (ASF) under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Apache Software Foundation (ASF) licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Server assembly: build the FastMCP instance, a Backend bound to the configured
OAP URL, and register all SkyWalking tools."""

from __future__ import annotations

import atexit

from fastmcp import FastMCP

from . import prompts, resources, tools
from .backend import Backend
from .client import GraphQLClient
from .config import Config, ZabbixConfig, load_config, load_zabbix_config
from .zabbix.client import ZabbixClient


def build_server(
    config: Config | None = None, zabbix_config: ZabbixConfig | None = None
) -> FastMCP:
    if config is None:
        config = load_config()
    if zabbix_config is None:
        zabbix_config = load_zabbix_config()

    mcp = FastMCP(name="skywalking-zabbix")
    gql_client = GraphQLClient(config)
    backend = Backend(gql_client)
    # Release the HTTP connection pool on process exit (best-effort).
    atexit.register(gql_client.close)

    # SkyWalking (16 tools)
    tools.metadata.register(mcp, backend)
    tools.topology.register(mcp, backend)
    tools.trace.register(mcp, backend)
    tools.mqe.register(mcp, backend)
    tools.alarm.register(mcp, backend)
    tools.event.register(mcp, backend)
    tools.log.register(mcp, backend)

    # SkyWalking prompts + MQE documentation resources
    prompts.register(mcp)
    resources.register(mcp, backend)

    # Zabbix + correlation (only when a Zabbix backend is configured)
    if zabbix_config.enabled:
        zclient = ZabbixClient(
            url=zabbix_config.url,
            user=zabbix_config.user,
            password=zabbix_config.password,
            verify_ssl=zabbix_config.verify_ssl,
            read_only=zabbix_config.read_only,
        )
        atexit.register(zclient.close)
        tools.zabbix.register(mcp, zclient)
        tools.correlate.register(mcp, backend, zclient)

    return mcp
