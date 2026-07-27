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

"""HTTP-level tests: the GraphQL client, the Backend probes and the Zabbix client
against a mocked transport, plus one tool exercised end to end.

These cover the request/response wiring that the pure-logic tests in
``test_unit.py`` cannot reach: auth headers, error surfacing, probe caching,
version-dependent query selection and the Zabbix re-login retry.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from conftest import OAP, ZBX, FakeMCP, gql_response, make_client, zbx_client, zbx_result
from skywalking_zabbix_mcp.backend import MODERN_CAPABILITIES, Backend
from skywalking_zabbix_mcp.client import GraphQLError
from skywalking_zabbix_mcp.zabbix.client import ZabbixError

# --- GraphQL client -----------------------------------------------------------


@respx.mock
def test_graphql_posts_query_and_returns_data():
    route = respx.post(OAP).mock(return_value=gql_response(["GENERAL", "OS_LINUX"]))
    client = make_client()

    data = client.execute("query { result: listLayers }", {"k": "v"})

    assert data == {"result": ["GENERAL", "OS_LINUX"]}
    body = json.loads(route.calls.last.request.content)
    assert body["query"] == "query { result: listLayers }"
    assert body["variables"] == {"k": "v"}


@respx.mock
def test_graphql_omits_variables_when_empty():
    route = respx.post(OAP).mock(return_value=gql_response(None))
    make_client().execute("query { result: version }")

    assert "variables" not in json.loads(route.calls.last.request.content)


@respx.mock
def test_graphql_sends_basic_auth_when_credentials_are_set():
    route = respx.post(OAP).mock(return_value=gql_response("9.7.0"))
    make_client("admin", "s3cret").execute("query { result: version }")

    expected = base64.b64encode(b"admin:s3cret").decode()
    assert route.calls.last.request.headers["authorization"] == f"Basic {expected}"


@respx.mock
def test_graphql_sends_no_auth_header_without_credentials():
    route = respx.post(OAP).mock(return_value=gql_response("9.7.0"))
    make_client().execute("query { result: version }")

    assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_graphql_raises_on_non_200():
    respx.post(OAP).mock(return_value=httpx.Response(503, text="upstream down"))

    with pytest.raises(GraphQLError, match="HTTP status 503"):
        make_client().execute("query { result: version }")


@respx.mock
def test_graphql_raises_on_transport_error():
    respx.post(OAP).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(GraphQLError, match="failed to execute HTTP request"):
        make_client().execute("query { result: version }")


@respx.mock
def test_graphql_raises_on_undecodable_body():
    respx.post(OAP).mock(return_value=httpx.Response(200, text="<html>not json</html>"))

    with pytest.raises(GraphQLError, match="failed to decode"):
        make_client().execute("query { result: version }")


@respx.mock
def test_graphql_null_data_becomes_empty_dict():
    respx.post(OAP).mock(return_value=httpx.Response(200, json={"data": None}))

    assert make_client().execute("query { result: version }") == {}


# --- Backend: version, time, capabilities -------------------------------------


@respx.mock
def test_backend_version_is_parsed_and_cached():
    route = respx.post(OAP).mock(return_value=gql_response("9.7.0"))
    backend = Backend(make_client())

    assert backend.backend_version() == (9, 7)
    assert backend.protocol_version() == "v2"
    assert backend.backend_version() == (9, 7)
    assert route.call_count == 1  # immutable for the process lifetime


@respx.mock
def test_backend_v1_protocol_for_old_oap():
    respx.post(OAP).mock(return_value=gql_response("8.9.1"))

    assert Backend(make_client()).protocol_version() == "v1"


@respx.mock
def test_backend_version_unparseable_raises():
    respx.post(OAP).mock(return_value=gql_response("not-a-version"))

    with pytest.raises(GraphQLError, match="parsing OAP version failure"):
        Backend(make_client()).backend_version()


@respx.mock
def test_backend_missing_version_raises():
    respx.post(OAP).mock(return_value=gql_response(None))

    with pytest.raises(GraphQLError, match="failed to detect OAP version"):
        Backend(make_client()).backend_version()


@respx.mock
def test_time_context_falls_back_to_local_on_error_and_is_not_cached():
    route = respx.post(OAP).mock(return_value=httpx.Response(500, text="boom"))
    backend = Backend(make_client())

    assert backend.get_time_context() is not None
    backend.get_time_context()
    assert route.call_count == 2  # transient failure must not pin the fallback


@respx.mock
def test_time_context_is_cached_on_success():
    route = respx.post(OAP).mock(
        return_value=gql_response({"timezone": "+0800", "currentTimestamp": 1700000000000})
    )
    backend = Backend(make_client())

    first = backend.get_time_context()
    assert backend.get_time_context() is first
    assert route.call_count == 1


@respx.mock
def test_supports_trace_v2_is_false_when_the_field_is_absent():
    respx.post(OAP).mock(
        return_value=httpx.Response(
            200, json={"errors": [{"message": "Field 'hasQueryTracesV2Support' unknown"}]}
        )
    )

    assert Backend(make_client()).supports_trace_v2() is False


@respx.mock
def test_capability_probe_trims_to_backend_schema():
    introspection = {
        "data": {
            "alarmMessage": {"fields": [{"name": "id"}, {"name": "message"}]},
            "mqeValue": {"fields": [{"name": "value"}]},
            "expressionResult": {"fields": [{"name": "type"}]},
            "queryType": {"fields": [{"name": "execExpression", "args": [{"name": "expression"}]}]},
        }
    }
    # First call is the introspection probe, second is the named-label-key probe.
    responses = [
        httpx.Response(200, json=introspection),
        httpx.Response(200, json={"data": {"execExpression": {"error": "mismatched input '{'"}}}),
    ]
    route = respx.post(OAP).mock(side_effect=responses)
    backend = Backend(make_client())

    caps = backend.get_capabilities()

    assert caps.alarm_name is False
    assert caps.alarm_snapshot is False
    assert caps.mqe_value_owner is False
    assert caps.mqe_debugging_trace is False
    assert caps.mqe_debug_args is False
    assert caps.mqe_named_label_keys is False
    calls_after_probe = route.call_count
    assert backend.get_capabilities() is caps  # cached
    assert route.call_count == calls_after_probe


@respx.mock
def test_capability_probe_failure_assumes_modern_oap():
    respx.post(OAP).mock(return_value=httpx.Response(500, text="boom"))

    assert Backend(make_client()).get_capabilities() == MODERN_CAPABILITIES


# --- a tool end to end --------------------------------------------------------


@respx.mock
def test_list_services_tool_returns_backend_payload():
    from skywalking_zabbix_mcp.tools import metadata

    services = [{"id": "1", "name": "payment-service", "layers": ["GENERAL"], "normal": True}]
    route = respx.post(OAP).mock(return_value=gql_response(services))
    mcp = FakeMCP()
    metadata.register(mcp, Backend(make_client()))

    out = mcp.tools["list_services"]("GENERAL")

    assert json.loads(out) == services
    assert json.loads(route.calls.last.request.content)["variables"] == {"layer": "GENERAL"}


@respx.mock
def test_tool_wraps_backend_failure_in_tool_error():
    from skywalking_zabbix_mcp.tools import metadata
    from skywalking_zabbix_mcp.tools._util import ToolError

    respx.post(OAP).mock(return_value=httpx.Response(500, text="boom"))
    mcp = FakeMCP()
    metadata.register(mcp, Backend(make_client()))

    with pytest.raises(ToolError, match="failed to list layers"):
        mcp.tools["list_layers"]()


# --- Zabbix client ------------------------------------------------------------


@respx.mock
def test_zabbix_login_uses_legacy_user_param_and_carries_auth_in_the_body():
    route = respx.post(ZBX).mock(
        side_effect=[zbx_result("token-abc"), zbx_result([{"hostid": "1"}])]
    )

    assert zbx_client().call("host.get", {"output": "extend"}) == [{"hostid": "1"}]

    login = json.loads(route.calls[0].request.content)
    assert login["method"] == "user.login"
    assert login["params"] == {"user": "api-user", "password": "api-pass"}
    assert "auth" not in login  # older Zabbix rejects an auth key on user.login

    query = json.loads(route.calls[1].request.content)
    assert query["method"] == "host.get"
    assert query["auth"] == "token-abc"  # < 6.4 carries the token in the body


@respx.mock
def test_zabbix_strips_php_warning_pollution():
    polluted = (
        "<br /><b>Warning</b>: session_start(): open failed in <b>/x.php</b> on line <b>1</b><br />"
        '{"jsonrpc":"2.0","result":"4.0.44","id":1}'
    )
    respx.post(ZBX).mock(return_value=httpx.Response(200, text=polluted))

    assert zbx_client().call("apiinfo.version") == "4.0.44"


@respx.mock
def test_zabbix_apiinfo_version_skips_login():
    route = respx.post(ZBX).mock(return_value=zbx_result("4.0.44"))

    zbx_client().call("apiinfo.version")

    assert route.call_count == 1  # no user.login round-trip
    assert json.loads(route.calls.last.request.content)["method"] == "apiinfo.version"


@respx.mock
def test_zabbix_surfaces_api_errors():
    respx.post(ZBX).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": "Invalid params.", "data": "No such host."},
                "id": 1,
            },
        )
    )

    with pytest.raises(ZabbixError, match="No such host"):
        zbx_client().call("apiinfo.version")


@respx.mock
def test_zabbix_relogins_once_on_an_expired_session():
    route = respx.post(ZBX).mock(
        side_effect=[
            zbx_result("stale-token"),
            httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {"message": "Not authorised.", "data": "Session terminated."},
                    "id": 1,
                },
            ),
            zbx_result("fresh-token"),
            zbx_result([{"hostid": "7"}]),
        ]
    )

    assert zbx_client().call("host.get") == [{"hostid": "7"}]
    assert route.call_count == 4
    assert json.loads(route.calls[3].request.content)["auth"] == "fresh-token"


@respx.mock
def test_zabbix_does_not_retry_a_non_auth_error():
    route = respx.post(ZBX).mock(
        side_effect=[
            zbx_result("token-abc"),
            httpx.Response(
                200,
                json={"jsonrpc": "2.0", "error": {"message": "Invalid params."}, "id": 1},
            ),
        ]
    )

    with pytest.raises(ZabbixError, match="Invalid params"):
        zbx_client().call("host.get")
    assert route.call_count == 2


@respx.mock
def test_zabbix_read_only_blocks_writes_before_any_request():
    route = respx.post(ZBX).mock(return_value=zbx_result("token-abc"))

    with pytest.raises(ZabbixError, match="blocked in read-only mode"):
        zbx_client(read_only=True).call("host.create", {"host": "new"})
    assert route.call_count == 0  # refused without touching the network


@respx.mock
def test_zabbix_read_only_allows_get_methods():
    respx.post(ZBX).mock(side_effect=[zbx_result("token-abc"), zbx_result([])])

    assert zbx_client(read_only=True).call("problem.get", {"recent": True}) == []


@respx.mock
def test_zabbix_non_json_response_is_reported_with_the_status():
    respx.post(ZBX).mock(return_value=httpx.Response(404, text="<h1>404 Not Found</h1>"))

    with pytest.raises(ZabbixError, match="non-JSON response \\(HTTP 404\\)"):
        zbx_client().call("apiinfo.version")


@respx.mock
def test_zabbix_login_without_token_raises():
    respx.post(ZBX).mock(return_value=zbx_result(None))

    with pytest.raises(ZabbixError, match="did not return an auth token"):
        zbx_client().call("host.get")


@respx.mock
def test_zabbix_transport_error_is_wrapped():
    respx.post(ZBX).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(ZabbixError, match="Zabbix request failed"):
        zbx_client().call("apiinfo.version")
