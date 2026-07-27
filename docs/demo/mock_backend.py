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

"""A fake OAP + Zabbix backend, just big enough to drive the demo.

Everything it returns is synthetic: RFC 5737 documentation addresses
(``192.0.2.0/24``) and generic service names. It exists so the demo exercises the
real server code without pointing at anyone's production monitoring.

Run standalone:

    python docs/demo/mock_backend.py       # serves on http://127.0.0.1:18800
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SERVICE = "192.0.2.11::payment-service"
HOST_IP = "192.0.2.11"

NOW_MS = int(time.time() * 1000)


def _alarms() -> list[dict[str, Any]]:
    return [
        {
            "id": "alarm-1",
            "message": "Response time of service payment-service is more than 1000ms",
            "startTime": NOW_MS - 4 * 60 * 1000,
            "scope": "SERVICE",
        }
    ]


def _zabbix_problems() -> list[dict[str, Any]]:
    return [
        {
            "eventid": "80412",
            "name": "Disk I/O is overloaded on app-01",
            "severity": "4",
            # Six minutes ago: two minutes before the application alarm.
            "clock": str(NOW_MS // 1000 - 6 * 60),
        }
    ]


_MQE_SERIES = {
    "service_cpm": [1180, 1240, 1310, 980, 610],
    "service_resp_time": [142, 168, 402, 1180, 1460],
    "service_sla": [10000, 10000, 9980, 9210, 8740],
}


def _mqe_values(expression: str) -> list[dict[str, Any]]:
    series = _MQE_SERIES.get(expression, [0])
    return [{"id": str(i), "value": v} for i, v in enumerate(series)]


def _graphql(body: dict[str, Any]) -> dict[str, Any]:
    query = body.get("query", "")
    variables = body.get("variables") or {}

    if "result: version" in query:
        return {"data": {"result": "9.7.0"}}
    if "getTimeInfo" in query:
        return {"data": {"result": {"timezone": "+0000", "currentTimestamp": NOW_MS}}}
    if "__type" in query:
        return {
            "data": {
                "alarmMessage": {
                    "fields": [
                        {"name": "id"},
                        {"name": "message"},
                        {"name": "startTime"},
                        {"name": "scope"},
                    ]
                },
                "mqeValue": {"fields": [{"name": "value"}, {"name": "owner"}]},
                "expressionResult": {"fields": [{"name": "type"}, {"name": "debuggingTrace"}]},
                "queryType": {
                    "fields": [
                        {
                            "name": "execExpression",
                            "args": [{"name": "expression"}, {"name": "debug"}],
                        }
                    ]
                },
            }
        }
    if "result: listLayers" in query:
        return {"data": {"result": ["GENERAL", "OS_LINUX", "MESH"]}}
    if "getService(" in query:
        return {
            "data": {
                "service": {
                    "id": "svc-1",
                    "name": SERVICE,
                    "normal": True,
                    "layers": ["GENERAL"],
                }
            }
        }
    if "listServices" in query:
        return {
            "data": {
                "services": [
                    {"id": "svc-1", "name": SERVICE},
                    {"id": "svc-2", "name": "192.0.2.12::order-service"},
                ]
            }
        }
    if "execExpression" in query:
        return {
            "data": {
                "execExpression": {
                    "type": "TIME_SERIES_VALUES",
                    "error": None,
                    "results": [{"values": _mqe_values(variables.get("expression", ""))}],
                }
            }
        }
    if "getAlarm" in query:
        return {"data": {"result": {"msgs": _alarms()}}}
    return {"errors": [{"message": f"mock backend has no answer for: {query[:80]}"}]}


def _zabbix(body: dict[str, Any]) -> dict[str, Any]:
    method = body.get("method")
    params = body.get("params") or {}
    if method == "user.login":
        return {"jsonrpc": "2.0", "result": "mock-session-token", "id": 1}
    if method == "apiinfo.version":
        return {"jsonrpc": "2.0", "result": "4.0.44", "id": 1}
    if method == "host.get":
        search = params.get("search") or {}
        matched = HOST_IP in str(search.get("host", "")) or HOST_IP in str(search.get("name", ""))
        hosts = (
            [{"hostid": "10084", "host": HOST_IP, "name": "app-01", "status": "0"}]
            if matched
            else []
        )
        return {"jsonrpc": "2.0", "result": hosts, "id": 1}
    if method == "problem.get":
        return {"jsonrpc": "2.0", "result": _zabbix_problems(), "id": 1}
    if method == "item.get":
        return {
            "jsonrpc": "2.0",
            "result": [
                {
                    "itemid": "1",
                    "name": "CPU utilization",
                    "key_": "system.cpu.util",
                    "lastvalue": "94.6",
                    "units": "%",
                },
                {
                    "itemid": "2",
                    "name": "Memory available",
                    "key_": "vm.memory.size[available]",
                    "lastvalue": "412000000",
                    "units": "B",
                },
                {
                    "itemid": "3",
                    "name": "Disk await",
                    "key_": "vfs.dev.await",
                    "lastvalue": "182.4",
                    "units": "ms",
                },
            ],
            "id": 1,
        }
    return {
        "jsonrpc": "2.0",
        "error": {"code": -32601, "message": f"mock: no method {method}"},
        "id": 1,
    }


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        payload = _graphql(body) if self.path.endswith("/graphql") else _zabbix(body)
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args: Any) -> None:
        pass  # keep the demo output clean


def serve(port: int = 18800) -> ThreadingHTTPServer:
    """Start the mock in a daemon thread and return the server."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


if __name__ == "__main__":
    server = serve()
    host, port = server.server_address[:2]
    print(f"mock OAP + Zabbix backend on http://{host}:{port}")
    print(f"  SW_URL=http://{host}:{port}")
    print(f"  ZABBIX_URL=http://{host}:{port}/zabbix/api_jsonrpc.php")
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()
