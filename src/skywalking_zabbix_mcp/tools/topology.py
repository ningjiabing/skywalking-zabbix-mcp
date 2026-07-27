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

"""Topology tools: query_services_topology, query_instances_topology,
query_endpoints_topology, query_processes_topology. Port of internal/tools/topology.go."""

from __future__ import annotations

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import DEFAULT_DURATION, build_duration_with_context
from ._util import ToolError, to_json


def register(mcp, backend: Backend) -> None:
    def _duration(start: str, end: str, step: str):
        tc = backend.get_time_context()
        return build_duration_with_context(start, end, step, False, DEFAULT_DURATION, tc)

    @mcp.tool(name="query_services_topology")
    def query_services_topology(
        service_ids: list[str] | None = None,
        layer: str = "",
        start: str = "",
        end: str = "",
        step: str = "",
    ) -> str:
        """Query the service topology from SkyWalking OAP.

        - If service_ids is provided, returns topology scoped to those services
          (getServicesTopology).
        - Otherwise returns the global topology (getGlobalTopology), optionally filtered
          by layer. Examples: {}, {"layer": "GENERAL"},
          {"service_ids": ["svc-1", "svc-2"], "start": "-1h"}."""
        duration = _duration(start, end, step)
        try:
            if service_ids:
                result = backend.result(
                    queries.GET_SERVICES_TOPOLOGY,
                    {"serviceIds": service_ids, "duration": duration},
                )
            elif layer:
                result = backend.result(
                    queries.GLOBAL_TOPOLOGY, {"layer": layer, "duration": duration}
                )
            else:
                result = backend.result(
                    queries.GLOBAL_TOPOLOGY_WITHOUT_LAYER, {"duration": duration}
                )
        except GraphQLError as exc:
            raise ToolError(f"failed to query topology: {exc}") from exc
        return to_json(result)

    @mcp.tool(name="query_instances_topology")
    def query_instances_topology(
        client_service_id: str,
        server_service_id: str,
        start: str = "",
        end: str = "",
        step: str = "",
    ) -> str:
        """Query the service instance topology between two services
        (getServiceInstanceTopology). Returns instance nodes and the calls between them.
        Example: {"client_service_id": "svc-1", "server_service_id": "svc-2"}."""
        duration = _duration(start, end, step)
        try:
            result = backend.result(
                queries.INSTANCE_TOPOLOGY,
                {
                    "clientServiceId": client_service_id,
                    "serverServiceId": server_service_id,
                    "duration": duration,
                },
            )
        except GraphQLError as exc:
            raise ToolError(f"failed to query instances topology: {exc}") from exc
        return to_json(result)

    @mcp.tool(name="query_endpoints_topology")
    def query_endpoints_topology(
        endpoint_id: str, start: str = "", end: str = "", step: str = ""
    ) -> str:
        """Query the endpoint dependency topology for a given endpoint
        (getEndpointDependencies). Returns endpoint nodes and the calls between them.
        Example: {"endpoint_id": "ep-1"}."""
        duration = _duration(start, end, step)
        try:
            result = backend.result(
                queries.ENDPOINT_DEPENDENCY,
                {"endpointId": endpoint_id, "duration": duration},
            )
        except GraphQLError as exc:
            raise ToolError(f"failed to query endpoints topology: {exc}") from exc
        return to_json(result)

    @mcp.tool(name="query_processes_topology")
    def query_processes_topology(
        service_instance_id: str, start: str = "", end: str = "", step: str = ""
    ) -> str:
        """Query the process topology for a given service instance
        (getProcessTopology). Returns process nodes and the calls between them.
        Example: {"service_instance_id": "instance-1"}."""
        duration = _duration(start, end, step)
        try:
            result = backend.result(
                queries.PROCESS_TOPOLOGY,
                {"serviceInstanceId": service_instance_id, "duration": duration},
            )
        except GraphQLError as exc:
            raise ToolError(f"failed to query processes topology: {exc}") from exc
        return to_json(result)
