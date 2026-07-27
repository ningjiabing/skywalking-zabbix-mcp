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

"""Backend facade: OAP version detection, schema capability probing, server-time
context, and trace-protocol selection.

Ports internal/tools/capability.go (introspection) plus the version-selection
logic from skywalking-cli's metadata package. A single OAP URL is bound per
process, so probes are cached in-instance rather than in a global URL map.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from . import queries
from .client import GraphQLClient, GraphQLError
from .timeutil import TimeContext, new_time_context

_log = logging.getLogger(__name__)

_CAPABILITY_CACHE_TTL = 5 * 60  # seconds
# On a failed probe we assume modern caps but re-check soon, so a briefly
# unreachable backend doesn't get pinned to the fallback for the full TTL.
_CAP_FAIL_TTL = 30  # seconds
# Server time drifts slowly; cache it briefly to avoid a round-trip per tool call.
_TIME_CONTEXT_TTL = 30  # seconds
_BACKEND_VERSION_RE = re.compile(r"^(\d+)\.(\d+)")


@dataclass
class ServerCapabilities:
    """Which optional parts of the OAP GraphQL schema exist on the connected backend.
    Fields added in later OAP releases are absent on older servers, and asking for
    them fails the whole query with a validation error rather than a null field."""

    alarm_name: bool
    alarm_snapshot: bool
    mqe_debug_args: bool
    mqe_value_owner: bool
    mqe_debugging_trace: bool
    # Whether label selectors accept a named key such as service_percentile{p='50'}.
    # Older MQE grammars only accept the generic `_` key.
    mqe_named_label_keys: bool


# Assumed-everything-supported set, used when introspection is unavailable so
# behavior matches a current OAP instead of silently degrading.
MODERN_CAPABILITIES = ServerCapabilities(
    alarm_name=True,
    alarm_snapshot=True,
    mqe_debug_args=True,
    mqe_value_owner=True,
    mqe_debugging_trace=True,
    mqe_named_label_keys=True,
)


class Backend:
    def __init__(self, client: GraphQLClient):
        self.client = client
        self._caps: ServerCapabilities | None = None
        self._caps_at: float = 0.0
        self._caps_ttl: float = _CAPABILITY_CACHE_TTL
        self._version: tuple[int, int] | None = None
        self._tc: TimeContext | None = None
        self._tc_at: float = 0.0

    # --- raw execution -------------------------------------------------------

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.client.execute(query, variables)

    def result(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        """Execute and return the ``result`` alias every query uses."""
        return self.execute(query, variables).get("result")

    # --- version detection ---------------------------------------------------

    def backend_version(self) -> tuple[int, int]:
        """Return (major, minor) of the OAP backend, or raise GraphQLError.

        The version is immutable for the life of the process, so it is fetched
        once and cached — every metadata/trace tool needs it to pick v1 vs v2."""
        if self._version is not None:
            return self._version
        version = self.result(queries.VERSION)
        if not version:
            raise GraphQLError("failed to detect OAP version")
        m = _BACKEND_VERSION_RE.match(str(version))
        if not m:
            raise GraphQLError(f"parsing OAP version failure: {version}")
        self._version = (int(m.group(1)), int(m.group(2)))
        _log.debug("OAP backend version detected: %s.%s", *self._version)
        return self._version

    def protocol_version(self) -> str:
        """ "v2" for OAP >= 9, else "v1" (port of protocolVersion)."""
        major, _ = self.backend_version()
        return "v2" if major >= 9 else "v1"

    # --- server time ---------------------------------------------------------

    def get_time_context(self) -> TimeContext:
        """Fetch server time info (always v2 getTimeInfo); fall back to local UTC.

        Cached for a short TTL: nearly every tool asks for it, but server time
        drifts slowly, so one round-trip per ~30s is plenty."""
        now = time.monotonic()
        if self._tc is not None and (now - self._tc_at) < _TIME_CONTEXT_TTL:
            return self._tc
        try:
            info = self.result(queries.SERVER_TIME_INFO)
        except GraphQLError:
            return new_time_context(None)  # transient; don't cache the fallback
        tc = new_time_context(info if isinstance(info, dict) else None)
        self._tc = tc
        self._tc_at = now
        return tc

    # --- trace protocol ------------------------------------------------------

    def supports_trace_v2(self) -> bool:
        """Any error (field absent on older OAP, or unreachable backend) is treated
        as not supported so the v1 path is used (port of supportsTraceV2)."""
        try:
            return bool(self.result(queries.HAS_QUERY_TRACES_V2_SUPPORT))
        except GraphQLError:
            return False

    # --- capabilities --------------------------------------------------------

    def get_capabilities(self) -> ServerCapabilities:
        """Probe the backend schema once, cached for the TTL. Any probe failure
        yields MODERN_CAPABILITIES (port of GetServerCapabilities)."""
        now = time.monotonic()
        if self._caps is not None and (now - self._caps_at) < self._caps_ttl:
            return self._caps
        try:
            caps = self._probe_capabilities()
            ttl = _CAPABILITY_CACHE_TTL
        except GraphQLError as exc:
            # Cache the fallback briefly instead of re-probing every call while the
            # backend is down (port kept behavior: assume modern on probe failure).
            _log.warning(
                "capability probe failed (%s); assuming modern OAP for %ss", exc, _CAP_FAIL_TTL
            )
            caps = MODERN_CAPABILITIES
            ttl = _CAP_FAIL_TTL
        self._caps = caps
        self._caps_at = now
        self._caps_ttl = ttl
        return caps

    def _probe_capabilities(self) -> ServerCapabilities:
        data = self.execute(queries.CAPABILITY_INTROSPECTION)
        alarm_fields = _field_names(data.get("alarmMessage"))
        mqe_value_fields = _field_names(data.get("mqeValue"))
        expr_result_fields = _field_names(data.get("expressionResult"))
        return ServerCapabilities(
            alarm_name="name" in alarm_fields,
            alarm_snapshot="snapshot" in alarm_fields,
            mqe_debug_args=_query_field_has_arg(data.get("queryType"), "execExpression", "debug"),
            mqe_value_owner="owner" in mqe_value_fields,
            mqe_debugging_trace="debuggingTrace" in expr_result_fields,
            mqe_named_label_keys=self._probe_named_label_keys(),
        )

    def _probe_named_label_keys(self) -> bool:
        """Ask the server to parse a named-key label selector. The expression is
        parsed before any data is read, so an old grammar answers with a parse
        error ("mismatched input") instead of a result (port of probeNamedLabelKeys)."""
        query = queries.build_mqe_expression_gql(
            ServerCapabilities(False, False, False, False, False, False)
        )
        variables = {
            "expression": "service_percentile{p='50'}",
            "entity": {"scope": "Service", "normal": True},
            "duration": {"start": "1970-01-01 0000", "end": "1970-01-01 0000", "step": "MINUTE"},
        }
        try:
            data = self.execute(query, variables)
        except GraphQLError:
            return True
        return "mismatched input" not in _mqe_expression_error(data)


def _field_names(t: Any) -> set[str]:
    if not isinstance(t, dict):
        return set()
    fields = t.get("fields")
    if not isinstance(fields, list):
        return set()
    return {f["name"] for f in fields if isinstance(f, dict) and "name" in f}


def _query_field_has_arg(t: Any, field: str, arg: str) -> bool:
    if not isinstance(t, dict):
        return False
    for f in t.get("fields", []) or []:
        if not isinstance(f, dict) or f.get("name") != field:
            continue
        for a in f.get("args", []) or []:
            if isinstance(a, dict) and a.get("name") == arg:
                return True
    return False


def _mqe_expression_error(data: dict[str, Any]) -> str:
    expr = data.get("execExpression")
    if not isinstance(expr, dict):
        return ""
    msg = expr.get("error")
    return msg if isinstance(msg, str) else ""
