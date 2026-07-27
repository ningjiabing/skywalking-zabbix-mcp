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

"""Trace tool: query_traces. Port of internal/tools/trace.go, including the
automatic v2 (queryTraces / BanyanDB) vs v1 (queryBasicTraces + queryTrace)
protocol selection and the summary / errors_only / full views."""

from __future__ import annotations

from typing import Any

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import (
    build_duration_with_context,
    build_pagination,
    parse_duration_with_context,
)
from ._util import ToolError, to_json

VIEW_FULL = "full"
VIEW_SUMMARY = "summary"
VIEW_ERRORS_ONLY = "errors_only"

_TRACE_STATE = {"success": "SUCCESS", "error": "ERROR", "all": "ALL", "": "ALL"}
_QUERY_ORDER = {"start_time": "BY_START_TIME", "duration": "BY_DURATION", "": "BY_START_TIME"}

DEFAULT_TRACE_PAGE_SIZE = 20
DEFAULT_TRACE_DURATION = "1h"


def register(mcp, backend: Backend) -> None:
    @mcp.tool(name="query_traces")
    def query_traces(
        service_id: str = "",
        service_instance_id: str = "",
        trace_id: str = "",
        endpoint_id: str = "",
        start: str = "",
        end: str = "",
        step: str = "",
        min_trace_duration: int = 0,
        max_trace_duration: int = 0,
        trace_state: str = "",
        query_order: str = "",
        page_size: int = 0,
        page_num: int = 0,
        view: str = "",
        slow_trace_threshold: int = 0,
        tags: list[dict] | None = None,
        cold: bool = False,
    ) -> str:
        """Query traces from SkyWalking OAP by various conditions, with intelligent
        processing for analysis.

        Conditions: service_id, service_instance_id, trace_id, endpoint_id, start/end,
        min_trace_duration/max_trace_duration (ms), trace_state (success/error/all),
        query_order (start_time/duration), tags ([{key,value}]).
        Views: full (default, raw), summary (metrics + insights), errors_only.
        Notes: OAP needs either a time range or trace_id; default 1h is used otherwise.
        The protocol is chosen automatically by backend storage. On non-BanyanDB
        storage page_size bounds trace segments not whole traces, so a broad query may
        return fewer distinct traces; narrow by service/endpoint."""
        _validate(
            service_id,
            service_instance_id,
            trace_id,
            endpoint_id,
            start,
            end,
            min_trace_duration,
            max_trace_duration,
            page_size,
            page_num,
        )
        if view == "":
            view = VIEW_FULL

        tc = backend.get_time_context()
        condition = _build_condition(
            service_id,
            service_instance_id,
            trace_id,
            endpoint_id,
            start,
            end,
            step,
            min_trace_duration,
            max_trace_duration,
            trace_state,
            query_order,
            page_size,
            page_num,
            tags,
            cold,
            tc,
        )

        try:
            trace_list = _query_traces_auto(backend, condition)
        except GraphQLError as exc:
            raise ToolError(f"failed to query traces: {exc}") from exc

        return _process_result(trace_list, view, slow_trace_threshold)


def _validate(
    service_id,
    service_instance_id,
    trace_id,
    endpoint_id,
    start,
    end,
    min_dur,
    max_dur,
    page_size,
    page_num,
) -> None:
    if (
        not any([service_id, service_instance_id, trace_id, endpoint_id, start, end])
        and min_dur == 0
        and max_dur == 0
    ):
        raise ToolError("at least one filter condition must be provided")
    if min_dur > 0 and max_dur > 0 and min_dur > max_dur:
        raise ToolError(
            f"invalid duration range: min_duration ({min_dur}) > max_duration ({max_dur})"
        )
    if page_size < 0:
        raise ToolError("page_size cannot be negative")
    if page_num < 0:
        raise ToolError("page_num cannot be negative")


def _build_condition(
    service_id,
    service_instance_id,
    trace_id,
    endpoint_id,
    start,
    end,
    step,
    min_dur,
    max_dur,
    trace_state,
    query_order,
    page_size,
    page_num,
    tags,
    cold,
    tc,
) -> dict[str, Any]:
    condition: dict[str, Any] = {}
    if service_id:
        condition["serviceId"] = service_id
    if service_instance_id:
        condition["serviceInstanceId"] = service_instance_id
    if trace_id:
        condition["traceId"] = trace_id
    if endpoint_id:
        condition["endpointId"] = endpoint_id
    if min_dur > 0:
        condition["minTraceDuration"] = min_dur
    if max_dur > 0:
        condition["maxTraceDuration"] = max_dur

    if tags:
        condition["tags"] = [{"key": t.get("key"), "value": t.get("value")} for t in tags]

    # Duration: explicit range wins; otherwise default 1h unless a traceId is given.
    if start != "" or end != "":
        condition["queryDuration"] = build_duration_with_context(start, end, step, cold, 60, tc)
    elif trace_id == "":
        condition["queryDuration"] = parse_duration_with_context(DEFAULT_TRACE_DURATION, cold, tc)

    state = _TRACE_STATE.get(trace_state)
    if state is None:
        raise ToolError(
            f"invalid trace_state '{trace_state}', available states: success, error, all"
        )
    condition["traceState"] = state

    order = _QUERY_ORDER.get(query_order)
    if order is None:
        raise ToolError(
            f"invalid query_order '{query_order}', available orders: start_time, duration"
        )
    condition["queryOrder"] = order

    condition["paging"] = build_pagination(page_num, page_size or DEFAULT_TRACE_PAGE_SIZE)
    return condition


# --- protocol selection ------------------------------------------------------


def _query_traces_auto(backend: Backend, condition: dict[str, Any]) -> dict[str, Any]:
    if backend.supports_trace_v2():
        return backend.result(queries.QUERY_TRACES_V2, {"condition": condition}) or {}
    return _traces_v1(backend, condition)


def _traces_v1(backend: Backend, condition: dict[str, Any]) -> dict[str, Any]:
    """queryBasicTraces returns summaries only, so each unique trace's spans are
    fetched via queryTrace and de-duplicated (port of tracesV1)."""
    brief = backend.result(queries.QUERY_BASIC_TRACES_V1, {"condition": condition}) or {}
    traces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for basic in brief.get("traces", []) or []:
        trace_ids = (basic or {}).get("traceIds") or []
        if not trace_ids:
            continue
        trace_id = trace_ids[0]
        if trace_id in seen:
            continue
        seen.add(trace_id)
        trace = backend.result(queries.QUERY_TRACE_V1, {"traceId": trace_id}) or {}
        spans = trace.get("spans") or []
        if not spans:
            # Trace vanished between the two calls; skip so it is not counted as empty.
            continue
        traces.append({"spans": spans})
    return {"traces": traces}


# --- result processing -------------------------------------------------------


def _process_result(trace_list: dict[str, Any], view: str, slow_threshold: int) -> str:
    traces = (trace_list or {}).get("traces") or []
    if not traces:
        raise ToolError("no traces found matching the query criteria")

    if view == VIEW_SUMMARY:
        return to_json(_generate_summary(traces, slow_threshold))
    if view == VIEW_ERRORS_ONLY:
        return to_json(_filter_error_traces(traces))
    if view == VIEW_FULL:
        return to_json(trace_list)
    raise ToolError(f"invalid view '{view}', available views: full, summary, errors_only")


def _collect_span_stats(spans: list[Any]) -> dict[str, Any]:
    root = None
    trace_id = ""
    start_time = 0
    end_time = 0
    is_error = False
    for span in spans:
        if span is None:
            continue
        if span.get("spanId") == 0 and span.get("parentSpanId") == -1 and root is None:
            root = span
        if trace_id == "":
            trace_id = span.get("traceId", "") or ""
        st = span.get("startTime", 0) or 0
        et = span.get("endTime", 0) or 0
        if start_time == 0 or st < start_time:
            start_time = st
        if et > end_time:
            end_time = et
        if span.get("isError") is True:
            is_error = True
    return {
        "root": root,
        "traceId": trace_id,
        "startTime": start_time,
        "endTime": end_time,
        "isError": is_error,
    }


def _basic_trace_summary(trace_item: dict) -> dict[str, Any]:
    spans = (trace_item or {}).get("spans") or []
    if not spans:
        return {}
    stats = _collect_span_stats(spans)
    root = stats["root"] or spans[0]
    return {
        "trace_id": stats["traceId"],
        "service_name": root.get("serviceCode", "") or "",
        "endpoint_name": root.get("endpointName") or "",
        "start_time_ms": stats["startTime"],
        "duration_ms": stats["endTime"] - stats["startTime"],
        "is_error": stats["isError"],
        "span_count": len(spans),
    }


def _generate_summary(traces: list[dict], slow_threshold: int) -> dict[str, Any]:
    services: set[str] = set()
    endpoints: set[str] = set()
    durations: list[int] = []
    error_traces: list[dict] = []
    slow_traces: list[dict] = []
    min_start = 0
    max_end = 0
    total_duration = 0
    success_count = 0
    error_count = 0

    for trace_item in traces:
        spans = (trace_item or {}).get("spans") or []
        if not spans:
            continue
        basic = _basic_trace_summary(trace_item)
        if not basic.get("trace_id"):
            continue
        end_time_ms = basic["start_time_ms"] + basic["duration_ms"]
        if min_start == 0 or basic["start_time_ms"] < min_start:
            min_start = basic["start_time_ms"]
        if end_time_ms > max_end:
            max_end = end_time_ms
        durations.append(basic["duration_ms"])
        total_duration += basic["duration_ms"]
        if basic["is_error"]:
            error_count += 1
            error_traces.append(basic)
        else:
            success_count += 1
        if slow_threshold > 0 and basic["duration_ms"] > slow_threshold:
            slow_traces.append(basic)
        for span in spans:
            if not span:
                continue
            if span.get("serviceCode"):
                services.add(span["serviceCode"])
            if span.get("endpointName"):
                endpoints.add(span["endpointName"])

    avg_duration = 0.0
    min_duration = 0
    max_duration = 0
    if durations:
        durations_sorted = sorted(durations)
        avg_duration = total_duration / len(durations_sorted)
        min_duration = durations_sorted[0]
        max_duration = durations_sorted[-1]

    error_traces.sort(key=lambda b: b["duration_ms"], reverse=True)
    slow_traces.sort(key=lambda b: b["duration_ms"], reverse=True)

    summary: dict[str, Any] = {
        "total_traces": len(traces),
        "success_count": success_count,
        "error_count": error_count,
        "services": sorted(services),  # deterministic order, matching Go sort.Strings
        "endpoints": list(endpoints),
        "avg_duration_ms": avg_duration,
        "min_duration_ms": min_duration,
        "max_duration_ms": max_duration,
        "time_range": {
            "start_time_ms": min_start,
            "end_time_ms": max_end,
            "duration_ms": max_end - min_start,
        },
    }
    # error_traces / slow_traces are omitempty in Go.
    if error_traces:
        summary["error_traces"] = error_traces
    if slow_traces:
        summary["slow_traces"] = slow_traces
    return summary


def _filter_error_traces(traces: list[dict]) -> list[dict]:
    error_traces = []
    for trace_item in traces:
        if not trace_item:
            continue
        basic = _basic_trace_summary(trace_item)
        if basic.get("is_error"):
            error_traces.append(basic)
    error_traces.sort(key=lambda b: b["duration_ms"], reverse=True)
    return error_traces
