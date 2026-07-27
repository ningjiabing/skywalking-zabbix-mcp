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

"""Event tool: query_events. Port of internal/tools/event.go."""

from __future__ import annotations

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import DEFAULT_DURATION, build_duration_with_context, build_pagination
from ._util import ToolError, to_json

_ORDER_ASC = "ASC"
_ORDER_DES = "DES"


def register(mcp, backend: Backend) -> None:
    @mcp.tool(name="query_events")
    def query_events(
        uuid: str = "",
        service: str = "",
        service_instance: str = "",
        endpoint: str = "",
        name: str = "",
        type: str = "",
        layer: str = "",
        start: str = "",
        end: str = "",
        step: str = "",
        order: str = "",
        page_num: int = 0,
        page_size: int = 0,
    ) -> str:
        """Query events from SkyWalking OAP. Events record changes or incidents on
        a service, instance or endpoint (deployments, restarts, scaling).

        - type: Normal or Error.
        - order: ASC (oldest first) or DES (newest first, default).
        Examples: {"service": "svc", "start": "-1h"}, {"type": "Error", "start": "-30m"}."""
        tc = backend.get_time_context()
        duration = build_duration_with_context(start, end, step, False, DEFAULT_DURATION, tc)

        condition: dict = {
            "time": duration,
            "paging": build_pagination(page_num, page_size),
        }
        if uuid:
            condition["uuid"] = uuid
        if service or service_instance or endpoint:
            src: dict = {}
            if service:
                src["service"] = service
            if service_instance:
                src["serviceInstance"] = service_instance
            if endpoint:
                src["endpoint"] = endpoint
            condition["source"] = src
        if name:
            condition["name"] = name
        if type:
            condition["type"] = type
        if layer:
            condition["layer"] = layer
        condition["order"] = _ORDER_ASC if order == _ORDER_ASC else _ORDER_DES

        try:
            result = backend.result(queries.QUERY_EVENTS, {"condition": condition})
        except GraphQLError as exc:
            raise ToolError(f"failed to query events: {exc}") from exc
        return to_json(result)
