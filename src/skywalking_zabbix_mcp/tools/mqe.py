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

"""MQE tools: execute_mqe_expression, list_mqe_metrics, get_mqe_metric_type.
Port of internal/tools/mqe.go, including the legacy label-key rewriting that
adapts named percentile selectors to older OAP MQE grammars."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import DEFAULT_DURATION, build_duration_with_context
from ._util import ToolError, to_json

_MAX_MQE_EXPRESSION_LENGTH = 2048
_MAX_MQE_EXPRESSION_DEPTH = 12
_MAX_MQE_ENTITY_FIELD_LEN = 256
_MAX_MQE_REGEX_LENGTH = 256
_MAX_METRIC_NAME_LENGTH = 128
_MAX_REGEX_NODES = 50

_METRIC_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_LAYER_PATTERN = re.compile(r"^[A-Z0-9_]+$")

# The ranks OAL declares for percentile metrics; on an MQE grammar without named
# label keys, a percentile is selected by its index in this list.
_STANDARD_PERCENTILE_RANKS = ["50", "75", "90", "95", "99"]
_NAMED_LABEL_SELECTOR = re.compile(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']*)'\s*\}")

_ERR_LEGACY_LABEL_KEY = (
    "this OAP version's MQE only accepts the generic label key `_`, "
    "so the label selector {{{0}='{1}'}} cannot be used; "
    "select by index instead, e.g. service_percentile{{_='0,2'}} for p50 and p90"
)


def register(mcp, backend: Backend) -> None:
    @mcp.tool(name="execute_mqe_expression")
    def execute_mqe_expression(
        expression: str,
        service_name: str = "",
        layer: str = "",
        service_instance_name: str = "",
        endpoint_name: str = "",
        process_name: str = "",
        normal: bool | None = None,
        dest_service_name: str = "",
        dest_layer: str = "",
        dest_service_instance_name: str = "",
        dest_endpoint_name: str = "",
        dest_process_name: str = "",
        dest_normal: bool | None = None,
        start: str = "",
        end: str = "",
        step: str = "",
        cold: bool = False,
        debug: bool = False,
        dump_db_rsp: bool = False,
    ) -> str:
        """Execute MQE (Metrics Query Expression) to query and calculate metrics.

        MQE supports labels (service_percentile{p='50,90,99'}), calculations
        (service_sla * 100), comparisons, aggregations (avg/sum/max), top_n, trend
        (increase/rate), sort_values, baseline, relabels and logical ops.

        - expression is required.
        - For service queries set service_name (+ layer, defaults GENERAL). For relation
          metrics provide dest_* entity params.
        - start/end set the time range (default last 30m). cold queries cold storage.
        Examples: {expression: "service_sla * 100", service_name: "svc", start: "-1h"},
        {expression: "avg(service_cpm)", start: "-2h"},
        {expression: "top_n(service_cpm, 10, des)", step: "MINUTE"}."""
        data = run_mqe_expression(
            backend,
            expression,
            service_name=service_name,
            layer=layer,
            service_instance_name=service_instance_name,
            endpoint_name=endpoint_name,
            process_name=process_name,
            normal=normal,
            dest_service_name=dest_service_name,
            dest_layer=dest_layer,
            dest_service_instance_name=dest_service_instance_name,
            dest_endpoint_name=dest_endpoint_name,
            dest_process_name=dest_process_name,
            dest_normal=dest_normal,
            start=start,
            end=end,
            step=step,
            cold=cold,
            debug=debug,
            dump_db_rsp=dump_db_rsp,
        )
        return to_json(data)

    @mcp.tool(name="list_mqe_metrics")
    def list_mqe_metrics(regex: str = "") -> str:
        """List available metrics usable in MQE expressions, with type and catalog.

        Optionally filter by a regex on the metric name. Examples: {regex: "service_.*"},
        {regex: ".*_cpm"}, {} (all metrics)."""
        if regex:
            _validate_text_field("regex", regex, _MAX_MQE_REGEX_LENGTH)
            _validate_regex_complexity(regex)
        variables = {"regex": regex} if regex else {}
        try:
            data = backend.execute(queries.LIST_METRICS, variables)
        except GraphQLError as exc:
            raise ToolError(f"failed to list metrics: {exc}") from exc
        return to_json(data)

    @mcp.tool(name="get_mqe_metric_type")
    def get_mqe_metric_type(metric_name: str) -> str:
        """Get type and catalog information for a specific metric.

        Types: REGULAR_VALUE (single value), LABELED_VALUE (needs label selectors),
        SAMPLED_RECORD. Examples: {metric_name: "service_cpm"},
        {metric_name: "service_percentile"}."""
        if metric_name == "":
            raise ToolError("metric_name must be provided")
        _validate_metric_name(metric_name)
        try:
            data = backend.execute(queries.TYPE_OF_METRICS, {"name": metric_name})
        except GraphQLError as exc:
            raise ToolError(f"failed to get metric type: {exc}") from exc
        return to_json(data)


def run_mqe_expression(
    backend: Backend,
    expression: str,
    service_name: str = "",
    layer: str = "",
    service_instance_name: str = "",
    endpoint_name: str = "",
    process_name: str = "",
    normal: bool | None = None,
    dest_service_name: str = "",
    dest_layer: str = "",
    dest_service_instance_name: str = "",
    dest_endpoint_name: str = "",
    dest_process_name: str = "",
    dest_normal: bool | None = None,
    start: str = "",
    end: str = "",
    step: str = "",
    cold: bool = False,
    debug: bool = False,
    dump_db_rsp: bool = False,
) -> dict[str, Any]:
    """Execute an MQE expression and return the raw ``data`` dict. Shared by the
    execute_mqe_expression tool and the correlation tools. Raises ToolError."""
    if expression == "":
        raise ToolError("expression is required")
    _validate_expression_request(
        expression,
        service_name,
        service_instance_name,
        endpoint_name,
        process_name,
        dest_service_name,
        dest_service_instance_name,
        dest_endpoint_name,
        dest_process_name,
        layer,
        dest_layer,
    )

    entity = _build_entity(
        backend,
        service_name,
        layer,
        service_instance_name,
        endpoint_name,
        process_name,
        normal,
        dest_service_name,
        dest_service_instance_name,
        dest_endpoint_name,
        dest_process_name,
        dest_normal,
    )
    tc = backend.get_time_context()
    duration = build_duration_with_context(start, end, step, cold, DEFAULT_DURATION, tc)

    caps = backend.get_capabilities()
    query = queries.build_mqe_expression_gql(caps)

    expr = expression
    rewrote_labels = False
    if not caps.mqe_named_label_keys:
        rewritten = _rewrite_legacy_label_selectors(expression)
        rewrote_labels = rewritten != expression
        expr = rewritten

    variables: dict[str, Any] = {
        "expression": expr,
        "entity": entity,  # always included, even if empty
        "duration": duration,
    }
    if caps.mqe_debug_args:
        variables["debug"] = debug
        variables["dumpDBRsp"] = dump_db_rsp

    try:
        data = backend.execute(query, variables)
    except GraphQLError as exc:
        raise ToolError(f"failed to execute MQE expression: {exc}") from exc

    if rewrote_labels:
        _relabel_legacy_percentile_results(data)
    return data


# --- entity building ---------------------------------------------------------


def _build_entity(
    backend,
    service_name,
    layer,
    service_instance_name,
    endpoint_name,
    process_name,
    normal,
    dest_service_name,
    dest_service_instance_name,
    dest_endpoint_name,
    dest_process_name,
    dest_normal,
) -> dict[str, Any]:
    entity: dict[str, Any] = {}
    fields = {
        "serviceName": service_name,
        "serviceInstanceName": service_instance_name,
        "endpointName": endpoint_name,
        "processName": process_name,
        "destServiceName": dest_service_name,
        "destServiceInstanceName": dest_service_instance_name,
        "destEndpointName": dest_endpoint_name,
        "destProcessName": dest_process_name,
    }
    for key, value in fields.items():
        if value:
            entity[key] = value

    if service_name:
        if normal is None:
            entity["normal"] = _get_service_info(backend, service_name, layer)
        else:
            entity["normal"] = normal
    elif normal is not None:
        entity["normal"] = normal

    if dest_normal is not None:
        entity["destNormal"] = dest_normal
    return entity


def _get_service_info(backend: Backend, service_name: str, layer: str) -> bool:
    if not service_name:
        return False
    if not layer:
        layer = "GENERAL"
    try:
        normal = _get_service_by_name(backend, service_name, layer)
    except GraphQLError:
        return True
    if normal is not None:
        return normal
    return True


def _get_service_by_name(backend: Backend, service_name: str, layer: str) -> bool | None:
    service_id = _find_service_id(backend, service_name, layer)
    if not service_id:
        raise GraphQLError(f"service not found in layer {layer}: {service_name}")
    data = backend.execute(queries.GET_SERVICE_BY_ID, {"serviceId": service_id})
    service = data.get("service")
    if isinstance(service, dict) and isinstance(service.get("normal"), bool):
        return service["normal"]
    raise GraphQLError(f"invalid service data returned for: {service_name}")


def _find_service_id(backend: Backend, service_name: str, layer: str) -> str:
    data = backend.execute(queries.LIST_SERVICES_ID_NAME, {"layer": layer})
    for svc in data.get("services", []) or []:
        if isinstance(svc, dict) and svc.get("name") == service_name:
            sid = svc.get("id")
            if isinstance(sid, str):
                return sid
    return ""


# --- legacy label rewriting --------------------------------------------------


def _rewrite_legacy_label_selectors(expression: str) -> str:
    """Adapt named label selectors to the older MQE grammar (only the `_` key).
    Percentile ranks are translated to their index; anything else is reported."""

    def repl(match: re.Match) -> str:
        key, values = match.group(1), match.group(2)
        if key == "_":
            return match.group(0)
        if key != "p":
            raise ToolError(_ERR_LEGACY_LABEL_KEY.format(key, values))
        indexes = []
        for rank in values.split(","):
            rank = rank.strip()
            try:
                idx = _STANDARD_PERCENTILE_RANKS.index(rank)
            except ValueError:
                raise ToolError(
                    f"percentile p={rank} is not one of the standard ranks "
                    f"{','.join(_STANDARD_PERCENTILE_RANKS)} supported by this OAP version"
                ) from None
            indexes.append(str(idx))
        return "{{_='{}'}}".format(",".join(indexes))

    return _NAMED_LABEL_SELECTOR.sub(repl, expression)


def _relabel_legacy_percentile_results(data: Any) -> None:
    """Turn the `_` index labels an older grammar returns back into the rank labels
    the caller asked for, so a p90 series is not reported as `_ = 2`."""
    if not isinstance(data, dict):
        return
    expr = data.get("execExpression")
    if not isinstance(expr, dict):
        return
    for entry in expr.get("results", []) or []:
        if not isinstance(entry, dict):
            continue
        metric = entry.get("metric")
        if not isinstance(metric, dict):
            continue
        for pair in metric.get("labels", []) or []:
            if not isinstance(pair, dict) or pair.get("key") != "_":
                continue
            try:
                idx = int(str(pair.get("value")))
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(_STANDARD_PERCENTILE_RANKS):
                pair["key"] = "p"
                pair["value"] = _STANDARD_PERCENTILE_RANKS[idx]


# --- validation --------------------------------------------------------------


def _validate_expression_request(
    expression,
    service_name,
    service_instance_name,
    endpoint_name,
    process_name,
    dest_service_name,
    dest_service_instance_name,
    dest_endpoint_name,
    dest_process_name,
    layer,
    dest_layer,
) -> None:
    _validate_expression(expression)
    for field_name, value in {
        "service_name": service_name,
        "service_instance_name": service_instance_name,
        "endpoint_name": endpoint_name,
        "process_name": process_name,
        "dest_service_name": dest_service_name,
        "dest_service_instance_name": dest_service_instance_name,
        "dest_endpoint_name": dest_endpoint_name,
        "dest_process_name": dest_process_name,
    }.items():
        _validate_text_field(field_name, value, _MAX_MQE_ENTITY_FIELD_LEN)
    _validate_layer_field("layer", layer)
    _validate_layer_field("dest_layer", dest_layer)


def _validate_expression(expression: str) -> None:
    if len(expression.encode("utf-8")) > _MAX_MQE_EXPRESSION_LENGTH:
        raise ToolError(
            f"expression exceeds maximum length of {_MAX_MQE_EXPRESSION_LENGTH} characters"
        )
    if _contains_unsafe_control_chars(expression):
        raise ToolError("expression contains invalid control characters")
    if _nesting_depth(expression) > _MAX_MQE_EXPRESSION_DEPTH:
        raise ToolError(f"expression exceeds maximum nesting depth of {_MAX_MQE_EXPRESSION_DEPTH}")


def _validate_text_field(field_name: str, value: str, max_len: int) -> None:
    if value == "":
        return
    if len(value.encode("utf-8")) > max_len:
        raise ToolError(f"{field_name} exceeds maximum length of {max_len} characters")
    if _contains_unsafe_control_chars(value):
        raise ToolError(f"{field_name} contains invalid control characters")


def _validate_layer_field(field_name: str, value: str) -> None:
    if value == "":
        return
    _validate_text_field(field_name, value, _MAX_MQE_ENTITY_FIELD_LEN)
    if not _LAYER_PATTERN.match(value):
        raise ToolError(
            f"{field_name} contains invalid characters: only uppercase letters, "
            "digits, and underscores are allowed"
        )


def _validate_metric_name(metric_name: str) -> None:
    _validate_text_field("metric_name", metric_name, _MAX_METRIC_NAME_LENGTH)
    if not _METRIC_NAME_PATTERN.match(metric_name):
        raise ToolError("metric_name contains invalid characters")


def _validate_regex_complexity(pattern: str) -> None:
    try:
        import sre_parse
    except ImportError:  # Python 3.11+ moved it under re._parser
        from re import _parser as sre_parse  # type: ignore
    try:
        parsed = sre_parse.parse(pattern)
    except re.error as exc:
        raise ToolError(f"regex is invalid: {exc}") from exc
    if _regex_node_count(parsed) > _MAX_REGEX_NODES:
        raise ToolError("regex is too complex")


def _regex_node_count(node: Any) -> int:
    count = 1
    try:
        iterator = iter(node)
    except TypeError:
        return count
    for sub in iterator:
        if isinstance(sub, (list, tuple)):
            count += _regex_node_count(sub)
    return count


def _contains_unsafe_control_chars(value: str) -> bool:
    # Go's unicode.IsControl matches the Cc category only.
    return any(unicodedata.category(ch) == "Cc" and ch not in ("\n", "\r", "\t") for ch in value)


def _nesting_depth(value: str) -> int:
    depth = 0
    max_depth = 0
    for ch in value:
        if ch in "({[":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch in ")}]":
            if depth > 0:
                depth -= 1
    return max_depth
