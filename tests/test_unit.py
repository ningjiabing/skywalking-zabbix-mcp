# Licensed to Apache Software Foundation (ASF) under the Apache License, Version 2.0.
"""Unit tests for the pure logic that does not need a live OAP backend."""

from datetime import datetime, timezone

from skywalking_zabbix_mcp.backend import ServerCapabilities
from skywalking_zabbix_mcp.config import normalize_oap_url
from skywalking_zabbix_mcp.timeutil import (
    TimeContext,
    build_duration_with_context,
    go_parse_duration,
    parse_duration_with_context,
)
from skywalking_zabbix_mcp.tools.mqe import (
    _nesting_depth,
    _relabel_legacy_percentile_results,
    _rewrite_legacy_label_selectors,
)

FIXED = TimeContext(
    now_utc=datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc), location=timezone.utc
)


def test_normalize_url():
    assert normalize_oap_url("http://h:12800") == "http://h:12800/graphql"
    assert normalize_oap_url("http://h:12800/") == "http://h:12800/graphql"
    assert normalize_oap_url("http://h:12800/graphql") == "http://h:12800/graphql"
    assert normalize_oap_url("http://h/base") == "http://h/base/graphql"


def _duration_seconds(text: str) -> float:
    parsed = go_parse_duration(text)
    assert parsed is not None
    return parsed.total_seconds()


def test_go_parse_duration():
    assert _duration_seconds("-30m") == -1800
    assert _duration_seconds("1h") == 3600
    assert _duration_seconds("2h45m") == 2 * 3600 + 45 * 60
    assert _duration_seconds("1.5h") == 5400
    assert go_parse_duration("7d") is None  # legacy form, not a Go duration
    assert go_parse_duration("garbage") is None


def test_relative_duration_step_adaptive():
    d = parse_duration_with_context("-30m", False, FIXED)
    assert d["step"] == "MINUTE"
    assert d["start"] == "2026-07-21 1130"
    assert d["end"] == "2026-07-21 1200"
    assert "coldStage" not in d


def test_legacy_duration_days():
    d = parse_duration_with_context("7d", False, FIXED)
    assert d["step"] == "DAY"
    assert d["start"] == "2026-07-14"
    assert d["end"] == "2026-07-21"


def test_cold_stage_only_when_requested():
    assert "coldStage" not in build_duration_with_context("", "", "", False, 30, FIXED)
    assert build_duration_with_context("", "", "", True, 30, FIXED)["coldStage"] is True


def test_absolute_range_step():
    d = build_duration_with_context(
        "2026-07-21 10:00:00", "2026-07-21 11:00:00", "", False, 30, FIXED
    )
    # exactly 1h -> MINUTE per adaptive rule
    assert d["step"] == "MINUTE"


def test_mqe_legacy_label_rewrite():
    assert (
        _rewrite_legacy_label_selectors("service_percentile{p='50,90'}")
        == "service_percentile{_='0,2'}"
    )
    # already-generic key is left untouched
    assert _rewrite_legacy_label_selectors("m{_='0,2'}") == "m{_='0,2'}"


def test_mqe_relabel_roundtrip():
    data = {
        "execExpression": {
            "results": [
                {"metric": {"labels": [{"key": "_", "value": "2"}]}},
                {"metric": {"labels": [{"key": "_", "value": "0"}]}},
            ]
        }
    }
    _relabel_legacy_percentile_results(data)
    labels = [r["metric"]["labels"][0] for r in data["execExpression"]["results"]]
    assert labels[0] == {"key": "p", "value": "90"}
    assert labels[1] == {"key": "p", "value": "50"}


def test_nesting_depth():
    assert _nesting_depth("a(b(c))") == 2
    assert _nesting_depth("top_n(service_cpm, 10, des)") == 1


def test_build_mqe_gql_respects_caps():
    from skywalking_zabbix_mcp import queries

    modern = ServerCapabilities(True, True, True, True, True, True)
    old = ServerCapabilities(False, False, False, False, False, False)
    assert "debuggingTrace" in queries.build_mqe_expression_gql(modern)
    assert "owner" in queries.build_mqe_expression_gql(modern)
    assert "debug" in queries.build_mqe_expression_gql(modern)
    gql_old = queries.build_mqe_expression_gql(old)
    assert "debuggingTrace" not in gql_old
    assert "owner" not in gql_old
    assert "$debug" not in gql_old


def test_build_alarm_gql_respects_caps():
    from skywalking_zabbix_mcp import queries

    old = ServerCapabilities(False, False, False, False, False, False)
    modern = ServerCapabilities(True, True, True, True, True, True)
    old_gql = queries.build_alarm_query_gql(old)
    modern_gql = queries.build_alarm_query_gql(modern)
    # snapshot only requested when the backend has it
    assert "snapshot" not in old_gql
    assert "snapshot" in modern_gql
    # AlarmMessage `name` field appears in the modern selection set but not the old one
    assert modern_gql.count("name") > old_gql.count("name")


# --- Zabbix client (pure logic, no network) ---------------------------------


def test_zabbix_read_only_guard():
    import pytest

    from skywalking_zabbix_mcp.zabbix.client import ZabbixClient, ZabbixError

    c = ZabbixClient("http://x/api_jsonrpc.php", "u", "p", read_only=True)
    # write methods refused before any request
    for m in ("hostgroup.create", "host.update", "item.delete", "host.massadd"):
        with pytest.raises(ZabbixError):
            c.call(m, {})
    # read methods pass the guard
    assert ZabbixClient._is_read_method("host.get")
    assert ZabbixClient._is_read_method("apiinfo.version")
    assert not ZabbixClient._is_read_method("host.create")


def test_zabbix_php_pollution_strip():
    from skywalking_zabbix_mcp.zabbix import client as zc

    polluted = '<br /><b>Warning</b>: something in file on line 1\n{"jsonrpc":"2.0","result":"4.0.0","id":1}'
    m = zc._JSON_OBJECT.search(polluted)
    assert m is not None
    import json

    assert json.loads(m.group(0))["result"] == "4.0.0"


def test_correlate_ip_extraction():
    from skywalking_zabbix_mcp.tools.correlate import _extract_ip

    assert _extract_ip("192.0.2.11::payment-service") == "192.0.2.11"
    assert _extract_ip("payment-service") == ""
    assert _extract_ip("192.0.2.12::order_service") == "192.0.2.12"


def test_correlate_verdict():
    from skywalking_zabbix_mcp.tools.correlate import _first_failure_verdict

    assert "machine failed first" in _first_failure_verdict(2000, 1000)
    assert "application failed first" in _first_failure_verdict(1000, 2000)
    assert "application only" in _first_failure_verdict(1000, None)
    assert "machine only" in _first_failure_verdict(None, 1000)
    assert "no alarms" in _first_failure_verdict(None, None)


# --- O1: GraphQL error detail is surfaced, not swallowed --------------------


def test_graphql_error_includes_backend_messages():
    import httpx
    import pytest

    from skywalking_zabbix_mcp.client import GraphQLClient, GraphQLError
    from skywalking_zabbix_mcp.config import Config

    def handler(_request):
        return httpx.Response(
            200, json={"errors": [{"message": "Cannot query field 'foo'"}], "data": None}
        )

    cfg = Config(
        url="http://oap:12800",
        username="",
        password="",
        insecure=False,
        read_only=False,
        log_level="info",
    )
    c = GraphQLClient(cfg)
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GraphQLError) as ei:
        c.execute("{ x }")
    assert "Cannot query field 'foo'" in str(ei.value)


# --- O2: expired Zabbix session triggers one re-login retry -----------------


def test_zabbix_reauth_retry_on_expired_session():
    from skywalking_zabbix_mcp.zabbix.client import ZabbixClient, ZabbixError

    c = ZabbixClient("http://x/api_jsonrpc.php", "u", "p")
    calls = {"post": 0, "login": 0}

    def fake_login():
        calls["login"] += 1
        c._auth = f"tok{calls['login']}"
        return c._auth

    def fake_post(method, params, auth):
        calls["post"] += 1
        if calls["post"] == 1:
            raise ZabbixError("Session terminated, re-login, please.")
        return [{"hostid": "1"}]

    c.login = fake_login  # type: ignore[method-assign]
    c._post = fake_post  # type: ignore[method-assign]
    assert c.call("host.get", {}) == [{"hostid": "1"}]
    assert calls["login"] == 2  # initial login + one re-login
    assert calls["post"] == 2  # failed call + successful retry

    assert ZabbixClient._is_auth_error(ZabbixError("Not authorised."))
    assert not ZabbixClient._is_auth_error(ZabbixError("No permissions to referred object"))
