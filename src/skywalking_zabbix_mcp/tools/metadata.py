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

"""Metadata tools: list_layers, list_services, list_instances, list_endpoints,
list_processes. Ports internal/tools/metadata.go plus the version-selection logic
from skywalking-cli's metadata package."""

from __future__ import annotations

from .. import queries
from ..backend import Backend
from ..client import GraphQLError
from ..timeutil import DEFAULT_DURATION, build_duration_with_context
from ._util import ToolError, to_json


def register(mcp, backend: Backend) -> None:
    @mcp.tool(name="list_layers")
    def list_layers() -> str:
        """List all available layers registered in SkyWalking OAP.

        A layer represents a technology or deployment environment (GENERAL, MESH, K8S,
        OS_LINUX, etc.). Use the returned names when querying services or metrics that
        require a layer filter. Takes no parameters."""
        try:
            return to_json(backend.result(queries.LIST_LAYERS))
        except GraphQLError as exc:
            raise ToolError(f"failed to list layers: {exc}") from exc

    @mcp.tool(name="list_services")
    def list_services(layer: str) -> str:
        """List all services registered in SkyWalking OAP under a specific layer.

        Each service belongs to one or more layers. Use list_layers first to discover
        available layers. The response includes each service's id, name, group,
        shortName, layers and normal flag; the id filters other tools (query_logs,
        query_traces). Example: {"layer": "GENERAL"}."""
        try:
            return to_json(backend.result(queries.LIST_SERVICE, {"layer": layer}))
        except GraphQLError as exc:
            raise ToolError(f"failed to list services: {exc}") from exc

    @mcp.tool(name="list_instances")
    def list_instances(
        service_id: str,
        start: str = "",
        end: str = "",
        step: str = "",
        cold: bool = False,
    ) -> str:
        """List all instances of a service registered in SkyWalking OAP.

        A service instance is an individual running process (pod / JVM). Use
        list_services to obtain a service ID. The response includes each instance's id,
        name, language, instanceUUID and attributes. Time range via start/end (e.g.
        "-1h", "now"); step is adaptive if omitted."""
        tc = backend.get_time_context()
        duration = build_duration_with_context(start, end, step, cold, DEFAULT_DURATION, tc)
        try:
            query = (
                queries.INSTANCES_V2 if backend.protocol_version() == "v2" else queries.INSTANCES_V1
            )
            result = backend.result(query, {"serviceId": service_id, "duration": duration})
        except GraphQLError as exc:
            raise ToolError(f"failed to list instances: {exc}") from exc
        return to_json(result)

    @mcp.tool(name="list_endpoints")
    def list_endpoints(
        service_id: str,
        keyword: str = "",
        limit: int = 0,
        start: str = "",
        end: str = "",
        step: str = "",
        cold: bool = False,
    ) -> str:
        """List endpoints of a service registered in SkyWalking OAP.

        An endpoint is an individual API path or operation exposed by a service. Use
        list_services to obtain a service ID first. The response includes each
        endpoint's id and name. keyword filters by name; limit defaults to 100."""
        if limit <= 0:
            limit = 100
        duration = None
        if start != "" or end != "":
            tc = backend.get_time_context()
            duration = build_duration_with_context(start, end, step, cold, DEFAULT_DURATION, tc)
        try:
            result = _search_endpoints(backend, service_id, keyword, limit, duration)
        except GraphQLError as exc:
            raise ToolError(f"failed to list endpoints: {exc}") from exc
        return to_json(result)

    @mcp.tool(name="list_processes")
    def list_processes(
        instance_id: str,
        start: str,
        end: str = "",
        step: str = "",
        cold: bool = False,
    ) -> str:
        """List processes of a service instance registered in SkyWalking OAP.

        A process is an individual OS or language-level process within a service
        instance. Use list_instances to obtain an instance ID. The response includes
        each process's id, name, serviceId, serviceName, instanceId, instanceName,
        agentId, detectType, labels and attributes. start is required (e.g. "-1h")."""
        tc = backend.get_time_context()
        duration = build_duration_with_context(start, end, step, cold, DEFAULT_DURATION, tc)
        try:
            result = backend.result(
                queries.PROCESSES, {"instanceId": instance_id, "duration": duration}
            )
        except GraphQLError as exc:
            raise ToolError(f"failed to list processes: {exc}") from exc
        return to_json(result)


def _search_endpoints(backend: Backend, service_id, keyword, limit, duration):
    """Port of skywalking-cli metadata.SearchEndpoints version selection."""
    major, minor = backend.backend_version()
    variables = {"serviceId": service_id, "keyword": keyword, "limit": limit}
    if major >= 10 and minor >= 2:
        variables["duration"] = duration  # may be None; findEndpoint duration is nullable
        return backend.result(queries.FIND_ENDPOINTS_WITH_DURATION, variables)
    if major >= 9:
        return backend.result(queries.FIND_ENDPOINTS_WITHOUT_DURATION, variables)
    return backend.result(queries.SEARCH_ENDPOINTS_V1, variables)
