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

"""End-to-end tests for the two cross-stack tools.

These are the project's headline feature — joining an application view and a
machine view on the IP embedded in a SkyWalking service name — so both sides are
driven through mocked HTTP rather than stubbed helpers.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
import respx

from conftest import OAP, ZBX, FakeMCP, make_client, zbx_client, zbx_result
from skywalking_zabbix_mcp.backend import Backend
from skywalking_zabbix_mcp.tools import correlate
from skywalking_zabbix_mcp.zabbix.client import ZabbixError

CAPABILITIES = {
    "data": {
        "alarmMessage": {"fields": [{"name": "id"}, {"name": "message"}, {"name": "startTime"}]},
        "mqeValue": {"fields": [{"name": "value"}]},
        "expressionResult": {"fields": [{"name": "type"}]},
        "queryType": {"fields": [{"name": "execExpression", "args": [{"name": "expression"}]}]},
    }
}


def oap_router(
    mqe_value: float | None = 42.0,
    alarms: list[dict[str, Any]] | None = None,
    mqe_error: str | None = None,
):
    """Answer each OAP call by looking at which query document was sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        if "result: version" in query:
            return httpx.Response(200, json={"data": {"result": "9.7.0"}})
        if "getTimeInfo" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "result": {"timezone": "+0000", "currentTimestamp": int(time.time() * 1000)}
                    }
                },
            )
        if "__type" in query:
            return httpx.Response(200, json=CAPABILITIES)
        if "getService(" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "service": {
                            "id": "svc-1",
                            "name": "192.0.2.11::payment-service",
                            "normal": True,
                            "layers": ["GENERAL"],
                        }
                    }
                },
            )
        if "listServices" in query:
            # Entity resolution: the normal flag comes from the service registry.
            return httpx.Response(
                200,
                json={
                    "data": {
                        "services": [
                            {"id": "svc-1", "name": "192.0.2.11::payment-service"},
                            {"id": "svc-2", "name": "payment-service"},
                        ]
                    }
                },
            )
        if "execExpression" in query:
            if mqe_error is not None:
                return httpx.Response(200, json={"errors": [{"message": mqe_error}]})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "execExpression": {
                            "type": "TIME_SERIES_VALUES",
                            "error": None,
                            "results": [
                                {
                                    "values": [
                                        {"id": "1", "value": None},
                                        {"id": "2", "value": mqe_value},
                                    ]
                                }
                            ],
                        }
                    }
                },
            )
        if "getAlarm" in query:
            return httpx.Response(200, json={"data": {"result": {"msgs": alarms or []}}})
        raise AssertionError(f"unexpected OAP query: {query[:120]}")

    return handler


def zbx_router(responses: dict[str, Any]):
    """Answer each Zabbix JSON-RPC call by method name."""

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "user.login":
            return zbx_result("token-abc")
        if method not in responses:
            raise AssertionError(f"unexpected Zabbix method: {method}")
        value = responses[method]
        if isinstance(value, ZabbixError):
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "error": {"message": str(value)}, "id": 1}
            )
        return zbx_result(value)

    return handler


def build_tools(oap_handler, zbx_handler, read_only: bool = True) -> FakeMCP:
    respx.post(OAP).mock(side_effect=oap_handler)
    respx.post(ZBX).mock(side_effect=zbx_handler)
    mcp = FakeMCP()
    correlate.register(mcp, Backend(make_client()), zbx_client(read_only=read_only))
    return mcp


# --- diagnose_service ---------------------------------------------------------


@respx.mock
def test_diagnose_service_joins_both_sides_on_the_embedded_ip():
    host = {"hostid": "10084", "host": "192.0.2.11", "name": "app-01", "status": "0"}
    mcp = build_tools(
        oap_router(mqe_value=137.0, alarms=[{"id": "a1", "message": "slow", "startTime": 1000}]),
        zbx_router(
            {
                "host.get": [host],
                "problem.get": [{"eventid": "9", "name": "High CPU"}],
                "item.get": [{"itemid": "1", "key_": "system.cpu.load", "lastvalue": "8.2"}],
            }
        ),
    )

    out = json.loads(mcp.tools["diagnose_service"]("192.0.2.11::payment-service"))

    assert out["service"] == "192.0.2.11::payment-service"
    assert out["ip"] == "192.0.2.11"
    # Application side: latest non-null MQE value per metric.
    assert out["skywalking"]["metrics"] == {"cpm": 137.0, "resp_time_ms": 137.0, "sla": 137.0}
    assert out["skywalking"]["alarms"][0]["message"] == "slow"
    # Machine side: the host found by IP, with its problems and items.
    assert out["zabbix"]["host"] == host
    assert out["zabbix"]["problems"][0]["name"] == "High CPU"
    assert out["zabbix"]["items"][0]["key_"] == "system.cpu.load"


@respx.mock
def test_diagnose_service_skips_zabbix_without_an_ip():
    def no_zabbix(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Zabbix must not be called when the service name has no IP")

    mcp = build_tools(oap_router(), no_zabbix)

    out = json.loads(mcp.tools["diagnose_service"]("payment-service"))

    assert out["ip"] == ""
    assert "Zabbix lookup skipped" in out["zabbix"]["note"]


@respx.mock
def test_diagnose_service_falls_back_to_the_host_visible_name():
    calls: list[dict[str, Any]] = []
    host = {"hostid": "1", "host": "app-01", "name": "192.0.2.11", "status": "0"}

    def zbx(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "user.login":
            return zbx_result("token-abc")
        if body["method"] == "host.get":
            calls.append(body["params"])
            # First lookup searches `host`, second searches `name`.
            return zbx_result([] if len(calls) == 1 else [host])
        return zbx_result([])

    mcp = build_tools(oap_router(), zbx)

    out = json.loads(mcp.tools["diagnose_service"]("192.0.2.11::payment-service"))

    assert [next(iter(p["search"])) for p in calls] == ["host", "name"]
    assert out["zabbix"]["host"] == host


@respx.mock
def test_diagnose_service_reports_a_missing_zabbix_host_instead_of_failing():
    mcp = build_tools(oap_router(), zbx_router({"host.get": []}))

    out = json.loads(mcp.tools["diagnose_service"]("192.0.2.11::payment-service"))

    assert out["zabbix"]["host"] is None
    assert "no Zabbix host matched IP 192.0.2.11" in out["zabbix"]["note"]


@respx.mock
def test_diagnose_service_degrades_when_one_side_errors():
    mcp = build_tools(
        oap_router(mqe_error="metric not found"),
        zbx_router({"host.get": ZabbixError("Not authorised.")}),
    )

    out = json.loads(mcp.tools["diagnose_service"]("192.0.2.11::payment-service"))

    # A failure on either side is reported inline; the other side still answers.
    assert all("<error:" in str(v) for v in out["skywalking"]["metrics"].values())
    assert "Not authorised" in out["zabbix"]["error"]


# --- correlate_incident -------------------------------------------------------


@respx.mock
def test_correlate_incident_says_machine_failed_first():
    now_ms = int(time.time() * 1000)
    mcp = build_tools(
        oap_router(alarms=[{"id": "a1", "message": "app slow", "startTime": now_ms}]),
        zbx_router({"problem.get": [{"eventid": "9", "clock": str(now_ms // 1000 - 300)}]}),
    )

    out = json.loads(mcp.tools["correlate_incident"]("-1h", "now"))

    assert "machine failed first" in out["first_failure"]
    assert out["zabbix_first_ms"] < out["skywalking_first_ms"]


@respx.mock
def test_correlate_incident_says_application_failed_first():
    now_ms = int(time.time() * 1000)
    mcp = build_tools(
        oap_router(alarms=[{"id": "a1", "message": "app slow", "startTime": now_ms - 600_000}]),
        zbx_router({"problem.get": [{"eventid": "9", "clock": str(now_ms // 1000)}]}),
    )

    out = json.loads(mcp.tools["correlate_incident"]())

    assert "application failed first" in out["first_failure"]


@respx.mock
def test_correlate_incident_bounds_the_zabbix_query_to_the_window():
    captured: dict[str, Any] = {}

    def zbx(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "user.login":
            return zbx_result("token-abc")
        captured.update(body["params"])
        return zbx_result([])

    mcp = build_tools(oap_router(alarms=[]), zbx)

    mcp.tools["correlate_incident"]("-2h", "now")

    # Without time_from a long-standing problem would dominate the verdict.
    assert captured["time_till"] - captured["time_from"] == pytest.approx(7200, abs=5)


@respx.mock
def test_correlate_incident_with_no_alarms_on_either_side():
    mcp = build_tools(oap_router(alarms=[]), zbx_router({"problem.get": []}))

    out = json.loads(mcp.tools["correlate_incident"]())

    assert "no alarms" in out["first_failure"]
    assert out["skywalking_first_ms"] is None
    assert out["zabbix_first_ms"] is None
