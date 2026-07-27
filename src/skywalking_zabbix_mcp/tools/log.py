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

"""Log tool: query_logs. Port of internal/tools/log.go."""

from __future__ import annotations

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import DEFAULT_DURATION, build_duration_with_context, build_pagination
from ._util import ToolError, to_json


def register(mcp, backend: Backend) -> None:
    @mcp.tool(name="query_logs")
    def query_logs(
        service_id: str = "",
        service_instance_id: str = "",
        endpoint_id: str = "",
        trace_id: str = "",
        segment_id: str = "",
        span_id: int | None = None,
        tags: list[dict] | None = None,
        start: str = "",
        end: str = "",
        step: str = "",
        cold: bool = False,
        page_num: int = 0,
        page_size: int = 0,
        query_order: str = "",
    ) -> str:
        """Query logs from SkyWalking OAP with flexible filters.

        Filter by service, instance, endpoint, trace/segment/span, tags and time.
        query_order: ASC (oldest first) or DES (newest first, default). Supports cold
        storage and pagination. Examples: {"service_id": "svc", "start": "-1h"},
        {"trace_id": "abc..."}, {"tags": [{"key": "level", "value": "ERROR"}]}."""
        tc = backend.get_time_context()
        duration = build_duration_with_context(start, end, step, cold, DEFAULT_DURATION, tc)

        order = "ASC" if query_order == "ASC" else "DES"
        # serviceId / serviceInstanceId / endpointId are always sent (as the Go
        # code sends &req.X even when empty), so the backend sees "" not null.
        condition: dict = {
            "serviceId": service_id,
            "serviceInstanceId": service_instance_id,
            "endpointId": endpoint_id,
            "queryDuration": duration,
            "paging": build_pagination(page_num, page_size),
            "queryOrder": order,
        }

        if trace_id or segment_id or span_id is not None:
            trace_scope: dict = {}
            if trace_id:
                trace_scope["traceId"] = trace_id
            if segment_id:
                trace_scope["segmentId"] = segment_id
            if span_id is not None:
                trace_scope["spanId"] = span_id
            condition["relatedTrace"] = trace_scope

        if tags:
            condition["tags"] = [{"key": t.get("key"), "value": t.get("value")} for t in tags]

        try:
            result = backend.result(queries.QUERY_LOGS, {"condition": condition})
        except GraphQLError as exc:
            raise ToolError(f"failed to query logs: {exc}") from exc
        return to_json(result)
