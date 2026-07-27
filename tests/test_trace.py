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

"""Tests for query_traces: v1/v2 protocol selection, argument validation and the
three result views."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
import respx

from conftest import OAP, FakeMCP, make_client
from skywalking_zabbix_mcp.backend import Backend
from skywalking_zabbix_mcp.tools import trace
from skywalking_zabbix_mcp.tools._util import ToolError


def span(
    span_id: int = 0,
    parent: int = -1,
    trace_id: str = "t-1",
    service: str = "payment-service",
    endpoint: str = "/pay",
    start: int = 1_000,
    end: int = 1_500,
    is_error: bool = False,
) -> dict[str, Any]:
    return {
        "spanId": span_id,
        "parentSpanId": parent,
        "traceId": trace_id,
        "serviceCode": service,
        "endpointName": endpoint,
        "startTime": start,
        "endTime": end,
        "isError": is_error,
    }


def oap_router(
    *,
    supports_v2: bool,
    v2_traces: list[dict[str, Any]] | None = None,
    v1_basic: list[dict[str, Any]] | None = None,
    v1_traces: dict[str, list[dict[str, Any]]] | None = None,
    seen: list[str] | None = None,
):
    """Answer OAP calls by query document, so the tool picks its own protocol."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        if seen is not None:
            seen.append(query)
        if "getTimeInfo" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "result": {"timezone": "+0000", "currentTimestamp": int(time.time() * 1000)}
                    }
                },
            )
        if "hasQueryTracesV2Support" in query:
            return httpx.Response(200, json={"data": {"result": supports_v2}})
        if "queryTraces(" in query:
            return httpx.Response(200, json={"data": {"result": {"traces": v2_traces or []}}})
        if "queryBasicTraces(" in query:
            return httpx.Response(200, json={"data": {"result": {"traces": v1_basic or []}}})
        if "queryTrace(" in query:
            trace_id = body["variables"]["traceId"]
            spans = (v1_traces or {}).get(trace_id)
            return httpx.Response(
                200,
                json={"data": {"result": {"spans": spans} if spans is not None else None}},
            )
        raise AssertionError(f"unexpected OAP query: {query[:120]}")

    return handler


def build_tool(handler) -> FakeMCP:
    respx.post(OAP).mock(side_effect=handler)
    mcp = FakeMCP()
    trace.register(mcp, Backend(make_client()))
    return mcp


# --- validation ---------------------------------------------------------------


@respx.mock
def test_query_traces_requires_a_filter():
    mcp = build_tool(oap_router(supports_v2=True))

    with pytest.raises(ToolError, match="at least one filter condition"):
        mcp.tools["query_traces"]()


@respx.mock
def test_query_traces_rejects_an_inverted_duration_range():
    mcp = build_tool(oap_router(supports_v2=True))

    with pytest.raises(ToolError, match="invalid duration range"):
        mcp.tools["query_traces"](
            service_id="svc-1", min_trace_duration=900, max_trace_duration=100
        )


@respx.mock
def test_query_traces_rejects_negative_paging():
    mcp = build_tool(oap_router(supports_v2=True))

    with pytest.raises(ToolError, match="page_size cannot be negative"):
        mcp.tools["query_traces"](service_id="svc-1", page_size=-1)


@respx.mock
def test_query_traces_rejects_an_unknown_view():
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=[{"spans": [span()]}]))

    with pytest.raises(ToolError, match="invalid view 'graph'"):
        mcp.tools["query_traces"](service_id="svc-1", view="graph")


@respx.mock
def test_query_traces_rejects_an_unknown_trace_state():
    mcp = build_tool(oap_router(supports_v2=True))

    with pytest.raises(ToolError, match="invalid trace_state"):
        mcp.tools["query_traces"](service_id="svc-1", trace_state="flaky")


@respx.mock
def test_empty_result_is_reported_as_a_tool_error():
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=[]))

    with pytest.raises(ToolError, match="no traces found"):
        mcp.tools["query_traces"](service_id="svc-1")


@respx.mock
def test_backend_failure_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        if "getTimeInfo" in query or "hasQueryTracesV2Support" in query:
            return httpx.Response(200, json={"data": {"result": True}})
        return httpx.Response(500, text="boom")

    mcp = build_tool(handler)

    with pytest.raises(ToolError, match="failed to query traces"):
        mcp.tools["query_traces"](service_id="svc-1")


# --- protocol selection -------------------------------------------------------


@respx.mock
def test_v2_protocol_is_used_when_the_backend_supports_it():
    seen: list[str] = []
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=[{"spans": [span()]}], seen=seen))

    mcp.tools["query_traces"](service_id="svc-1")

    assert any("queryTraces(" in q for q in seen)
    assert not any("queryBasicTraces(" in q for q in seen)


@respx.mock
def test_v1_falls_back_to_basic_traces_and_expands_each_trace():
    seen: list[str] = []
    mcp = build_tool(
        oap_router(
            supports_v2=False,
            v1_basic=[{"traceIds": ["t-1"]}, {"traceIds": ["t-2"]}],
            v1_traces={
                "t-1": [span(trace_id="t-1")],
                "t-2": [span(trace_id="t-2", start=2_000, end=2_400)],
            },
            seen=seen,
        )
    )

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1"))

    assert any("queryBasicTraces(" in q for q in seen)
    assert len(out["traces"]) == 2


@respx.mock
def test_v1_deduplicates_segments_of_the_same_trace():
    mcp = build_tool(
        oap_router(
            supports_v2=False,
            # Two segments of one trace: OAP returns a row per segment.
            v1_basic=[{"traceIds": ["t-1"]}, {"traceIds": ["t-1"]}],
            v1_traces={"t-1": [span(trace_id="t-1")]},
        )
    )

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1"))

    assert len(out["traces"]) == 1


@respx.mock
def test_v1_skips_a_trace_that_vanished_between_the_two_calls():
    mcp = build_tool(
        oap_router(
            supports_v2=False,
            v1_basic=[{"traceIds": ["t-1"]}, {"traceIds": ["gone"]}],
            v1_traces={"t-1": [span(trace_id="t-1")]},
        )
    )

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1"))

    assert len(out["traces"]) == 1


# --- views --------------------------------------------------------------------


@respx.mock
def test_full_view_returns_the_raw_payload():
    traces = [{"spans": [span()]}]
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=traces))

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1", view="full"))

    assert out["traces"] == traces


@respx.mock
def test_summary_view_aggregates_counts_durations_and_slow_traces():
    traces = [
        {"spans": [span(trace_id="ok", start=1_000, end=1_100)]},
        {"spans": [span(trace_id="bad", start=2_000, end=2_900, is_error=True)]},
        {
            "spans": [
                span(
                    trace_id="slow",
                    service="order-service",
                    endpoint="/order",
                    start=3_000,
                    end=3_500,
                )
            ]
        },
    ]
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=traces))

    out = json.loads(
        mcp.tools["query_traces"](service_id="svc-1", view="summary", slow_trace_threshold=400)
    )

    assert out["total_traces"] == 3
    assert out["success_count"] == 2
    assert out["error_count"] == 1
    assert out["services"] == ["order-service", "payment-service"]  # sorted, deterministic
    assert out["min_duration_ms"] == 100
    assert out["max_duration_ms"] == 900
    assert out["avg_duration_ms"] == pytest.approx((100 + 900 + 500) / 3)
    assert out["time_range"] == {
        "start_time_ms": 1_000,
        "end_time_ms": 3_500,
        "duration_ms": 2_500,
    }
    assert [t["trace_id"] for t in out["error_traces"]] == ["bad"]
    # Slow traces are ordered by duration, descending.
    assert [t["trace_id"] for t in out["slow_traces"]] == ["bad", "slow"]


@respx.mock
def test_summary_view_omits_error_and_slow_sections_when_empty():
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=[{"spans": [span()]}]))

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1", view="summary"))

    assert "error_traces" not in out
    assert "slow_traces" not in out


@respx.mock
def test_errors_only_view_keeps_failing_traces_sorted_by_duration():
    traces = [
        {"spans": [span(trace_id="ok")]},
        {"spans": [span(trace_id="bad-short", start=0, end=100, is_error=True)]},
        {"spans": [span(trace_id="bad-long", start=0, end=900, is_error=True)]},
    ]
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=traces))

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1", view="errors_only"))

    assert [t["trace_id"] for t in out] == ["bad-long", "bad-short"]
    assert all(t["is_error"] for t in out)


@respx.mock
def test_error_on_any_span_marks_the_whole_trace_failed():
    traces = [
        {
            "spans": [
                span(span_id=0, parent=-1, trace_id="t", start=1_000, end=1_900),
                span(span_id=1, parent=0, trace_id="t", start=1_100, end=1_800, is_error=True),
            ]
        }
    ]
    mcp = build_tool(oap_router(supports_v2=True, v2_traces=traces))

    out = json.loads(mcp.tools["query_traces"](service_id="svc-1", view="errors_only"))

    assert len(out) == 1
    assert out[0]["span_count"] == 2
    assert out[0]["duration_ms"] == 900


# --- condition building -------------------------------------------------------


@respx.mock
def test_condition_carries_filters_and_normalized_enums():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        if "getTimeInfo" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "result": {"timezone": "+0000", "currentTimestamp": int(time.time() * 1000)}
                    }
                },
            )
        if "hasQueryTracesV2Support" in query:
            return httpx.Response(200, json={"data": {"result": True}})
        captured.update(body["variables"]["condition"])
        return httpx.Response(200, json={"data": {"result": {"traces": [{"spans": [span()]}]}}})

    mcp = build_tool(handler)

    mcp.tools["query_traces"](
        service_id="svc-1",
        endpoint_id="ep-1",
        min_trace_duration=100,
        max_trace_duration=900,
        trace_state="error",
        query_order="duration",
        page_size=5,
        tags=[{"key": "http.status_code", "value": "500"}],
    )

    assert captured["serviceId"] == "svc-1"
    assert captured["endpointId"] == "ep-1"
    assert captured["minTraceDuration"] == 100
    assert captured["maxTraceDuration"] == 900
    assert captured["traceState"] == "ERROR"
    assert captured["queryOrder"] == "BY_DURATION"
    assert captured["tags"] == [{"key": "http.status_code", "value": "500"}]
