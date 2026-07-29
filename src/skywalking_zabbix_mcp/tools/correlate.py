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

"""Correlation tools that join SkyWalking (application view) and Zabbix (machine
view) using the IP embedded in a SkyWalking service name.

Join key: a SkyWalking service name is ``<IP>::<service>``; that IP segment
matches the Zabbix host name (observed to align naturally, no mapping table)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import (
    DEFAULT_DURATION,
    build_duration_with_context,
    build_pagination,
    go_parse_duration,
)
from ..zabbix.client import ZabbixClient, ZabbixError
from ._util import ToolError, to_json
from .mqe import run_mqe_expression

_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# Item key fragments worth surfacing for a machine's health snapshot.
_ITEM_KEY_HINTS = ["system.cpu", "vm.memory", "proc.", "vfs.fs", "net.if", "system.swap"]


def register(mcp, backend: Backend, client: ZabbixClient) -> None:
    @mcp.tool(name="diagnose_service")
    def diagnose_service(service_name: str, start: str = "-30m", end: str = "now") -> str:
        """One-shot cross-stack health of a service: SkyWalking metrics + alarms
        plus the underlying machine's Zabbix CPU/memory/IO and current problems.

        - service_name: the SkyWalking service name, e.g. "192.0.2.11::payment-service"
          (the IP is extracted to locate the Zabbix host). A bare name works too, but
          then the Zabbix side is skipped unless an IP is present.
        Pass the exact registered name — confirm it with list_services first, do not
        guess. Null/zero metrics here do NOT mean the service is absent or down:
        request-based metrics (cpm/sla) are structurally null for WebSocket/long-
        connection services regardless of load, and a briefly quiet service still
        exists in list_services. Check there before telling the user a service does
        not exist, and see the "hint" field returned when all metrics are null.
        Returns {service, ip, skywalking:{metrics,alarms}, zabbix:{host,problems,items}}."""
        ip = _extract_ip(service_name)
        out: dict[str, Any] = {"service": service_name, "ip": ip}

        # --- SkyWalking side ---
        sw: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        for label, expr in (
            ("cpm", "service_cpm"),
            ("resp_time_ms", "service_resp_time"),
            ("sla", "service_sla"),
        ):
            try:
                data = run_mqe_expression(
                    backend, expr, service_name=service_name, start=start, end=end
                )
                metrics[label] = _latest_mqe_value(data)
            except ToolError as exc:
                metrics[label] = f"<error: {exc}>"
        sw["metrics"] = metrics
        # If every metric is empty (not an error), the service is registered but had
        # no sampled traffic in this window. Guide the caller to the right follow-up
        # tools instead of concluding the service is down.
        real_vals = [
            v for v in metrics.values() if not (isinstance(v, str) and v.startswith("<error"))
        ]
        if real_vals and all(v in (None, "", [], {}, "null") for v in real_vals):
            sw["hint"] = (
                "cpm/resp_time/sla are null. These count discrete HTTP request-"
                "response calls per minute. For a WebSocket or other long-connection "
                "service this is STRUCTURAL, not a problem: held connections carry "
                "frames over a socket that was opened once, so they generate no per-"
                "minute request count — a fully loaded WS server with thousands of "
                "live sessions still reports null here. Do NOT read null as idle or "
                "down. To judge a long-connection service's real load, use signals "
                "that reflect held connections rather than request rate: (1) "
                "list_instances + instance JVM metrics — live thread count and a heap "
                "GC sawtooth (a busy WS server holds many threads and churns heap "
                "steadily); (2) the host's Zabbix network throughput (net.if in/out "
                "bps) and TCP established connection count; (3) query_traces / "
                "query_logs (start=-24h) for the background work it still does. Only "
                "conclude the service is quiet if JVM threads are low AND host network/"
                "connections are low. To find upstream callers use "
                "query_services_topology(layer=...) filtered by name (the scoped, "
                "service_ids form may 400 on some OAP versions). Host health is in the "
                "zabbix section below."
            )
        try:
            sw["alarms"] = _sw_alarms(backend, keyword=service_name, start=start, end=end)
        except GraphQLError as exc:
            sw["alarms"] = f"<error: {exc}>"
        out["skywalking"] = sw

        # --- Zabbix side ---
        if ip:
            out["zabbix"] = _zabbix_host_snapshot(client, ip)
        else:
            out["zabbix"] = {"note": "no IP in service name; Zabbix lookup skipped"}
        return to_json(out)

    @mcp.tool(name="correlate_incident")
    def correlate_incident(start: str = "-1h", end: str = "now") -> str:
        """Align SkyWalking alarms and Zabbix problems in a time window to judge
        "machine failed first" vs "application failed first".

        Returns both alarm lists plus a first_failure verdict based on the earliest
        event on each side. Example: {"start": "-2h", "end": "now"}."""
        sw_alarms: Any
        try:
            sw_alarms = _sw_alarms(backend, keyword="", start=start, end=end)
        except GraphQLError as exc:
            sw_alarms = f"<error: {exc}>"

        # Bound the Zabbix side to the same window; without time_from a
        # long-standing unresolved problem would dominate and skew the verdict.
        time_from, time_till = _epoch_window(start, end)
        try:
            zbx_problems = client.call(
                "problem.get",
                {
                    "output": "extend",
                    "time_from": time_from,
                    "time_till": time_till,
                    "sortfield": ["eventid"],
                    "sortorder": "DESC",
                    "limit": 100,
                },
            )
        except ZabbixError as exc:
            zbx_problems = f"<error: {exc}>"

        sw_first = _earliest_ms(sw_alarms, "startTime")
        zbx_first = _earliest_zbx_clock(zbx_problems)
        verdict = _first_failure_verdict(sw_first, zbx_first)

        return to_json(
            {
                "window": {"start": start, "end": end},
                "first_failure": verdict,
                "skywalking_first_ms": sw_first,
                "zabbix_first_ms": zbx_first,
                "skywalking_alarms": sw_alarms,
                "zabbix_problems": zbx_problems,
            }
        )


# --- helpers -----------------------------------------------------------------


def _resolve_epoch(time_str: str, now: datetime, default: datetime) -> int:
    """Resolve a start/end string (relative "-1h", "now", or absolute) to epoch seconds."""
    s = (time_str or "").strip()
    if s == "":
        return int(default.timestamp())
    if s.lower() == "now":
        return int(now.timestamp())
    rel = go_parse_duration(s)
    if rel is not None:
        return int((now + rel).timestamp())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return int(default.timestamp())


def _epoch_window(start: str, end: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    default_start = now.timestamp() - 3600
    time_from = _resolve_epoch(start, now, datetime.fromtimestamp(default_start, tz=timezone.utc))
    time_till = _resolve_epoch(end, now, now)
    return time_from, time_till


def _extract_ip(service_name: str) -> str:
    head = service_name.split("::", 1)[0]
    m = _IP_RE.search(head) or _IP_RE.search(service_name)
    return m.group(1) if m else ""


def _latest_mqe_value(data: dict[str, Any]) -> Any:
    """Pull the most recent non-null value out of an execExpression result."""
    expr = (data or {}).get("execExpression") or {}
    results = expr.get("results") or []
    if not results:
        return None
    values = (results[0] or {}).get("values") or []
    for v in reversed(values):
        if isinstance(v, dict) and v.get("value") is not None:
            return v["value"]
    return None


def _sw_alarms(backend: Backend, keyword: str, start: str, end: str) -> Any:
    tc = backend.get_time_context()
    duration = build_duration_with_context(start, end, "", False, DEFAULT_DURATION, tc)
    caps = backend.get_capabilities()
    variables = {
        "duration": duration,
        "keyword": keyword,
        "paging": build_pagination(0, 0),
        "tags": None,
    }
    result = backend.execute(queries.build_alarm_query_gql(caps), variables).get("result") or {}
    return result.get("msgs", [])


def _zabbix_host_snapshot(client: ZabbixClient, ip: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    try:
        hosts = client.call(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "search": {"host": ip},
                "searchWildcardsEnabled": False,
            },
        )
    except ZabbixError as exc:
        return {"error": str(exc)}
    if not hosts:
        # fall back to matching the IP against the host visible name
        try:
            hosts = client.call(
                "host.get", {"output": ["hostid", "host", "name", "status"], "search": {"name": ip}}
            )
        except ZabbixError as exc:
            return {"error": str(exc)}
    if not hosts:
        return {"host": None, "note": f"no Zabbix host matched IP {ip}"}

    host = hosts[0]
    hostid = host["hostid"]
    snapshot["host"] = host
    try:
        snapshot["problems"] = client.call(
            "problem.get",
            {
                "hostids": [hostid],
                "output": "extend",
                "recent": True,
                "limit": 50,
            },
        )
    except ZabbixError as exc:
        snapshot["problems"] = f"<error: {exc}>"
    try:
        items = client.call(
            "item.get",
            {
                "hostids": [hostid],
                "output": ["itemid", "name", "key_", "lastvalue", "lastclock", "units"],
                "search": {"key_": _ITEM_KEY_HINTS},
                "searchByAny": True,
                "sortfield": "name",
            },
        )
        snapshot["items"] = items[:60]
    except ZabbixError as exc:
        snapshot["items"] = f"<error: {exc}>"
    return snapshot


def _earliest_ms(alarms: Any, field: str) -> int | None:
    if not isinstance(alarms, list):
        return None
    times = [a[field] for a in alarms if isinstance(a, dict) and isinstance(a.get(field), int)]
    return min(times) if times else None


def _earliest_zbx_clock(problems: Any) -> int | None:
    if not isinstance(problems, list):
        return None
    clocks = []
    for p in problems:
        if isinstance(p, dict) and str(p.get("clock", "")).isdigit():
            clocks.append(int(p["clock"]) * 1000)  # Zabbix clock is epoch seconds
    return min(clocks) if clocks else None


def _first_failure_verdict(sw_first: int | None, zbx_first: int | None) -> str:
    if sw_first is None and zbx_first is None:
        return "no alarms on either side in the window"
    if zbx_first is None:
        return "application only (SkyWalking alarms, no Zabbix problems)"
    if sw_first is None:
        return "machine only (Zabbix problems, no SkyWalking alarms)"
    if zbx_first < sw_first:
        return "machine failed first (infra alarm precedes application alarm)"
    if sw_first < zbx_first:
        return "application failed first (application alarm precedes infra alarm)"
    return "simultaneous"
