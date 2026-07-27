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
#
# NOTICE: This file has been modified from the original Apache SkyWalking MCP
# source by the skywalking-zabbix-mcp project to support older SkyWalking OAP
# versions.

"""Alarm tool: query_alarms. Port of internal/tools/alarm.go (capability-aware
selection set, so `name`/`snapshot` are only requested where the backend has them)."""

from __future__ import annotations

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import DEFAULT_DURATION, build_duration_with_context, build_pagination
from ._util import ToolError, to_json


def register(mcp, backend: Backend) -> None:
    @mcp.tool(name="query_alarms")
    def query_alarms(
        scope: str = "",
        keyword: str = "",
        tags: list[dict] | None = None,
        start: str = "",
        end: str = "",
        step: str = "",
        page_num: int = 0,
        page_size: int = 0,
    ) -> str:
        """Query alarms from SkyWalking OAP. Alarms fire when metrics breach
        configured thresholds.

        - scope: one of All, Service, ServiceInstance, Endpoint, Process,
          ServiceRelation, ServiceInstanceRelation, EndpointRelation, ProcessRelation.
        - tags: array of {"key","value"} filters.
        Examples: {"start": "-1h"}, {"scope": "Service", "start": "-30m"},
        {"keyword": "timeout", "start": "-1h"}."""
        tc = backend.get_time_context()
        duration = build_duration_with_context(start, end, step, False, DEFAULT_DURATION, tc)

        tag_list = None
        if tags:
            tag_list = [{"key": t.get("key"), "value": t.get("value")} for t in tags]

        variables = {
            "duration": duration,
            "keyword": keyword,
            "paging": build_pagination(page_num, page_size),
            "tags": tag_list,
        }
        if scope:
            variables["scope"] = scope

        caps = backend.get_capabilities()
        try:
            result = backend.result(queries.build_alarm_query_gql(caps), variables)
        except GraphQLError as exc:
            raise ToolError(f"failed to query alarms: {exc}") from exc
        return to_json(result)
