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

"""GraphQL query texts for the OAP backend.

Most strings are ported verbatim from the Apache skywalking-cli GraphQL assets
(``assets/graphqls/*``); a few (trace v1/v2, MQE, alarm, capability probe) are
inline in the Go MCP source. All use the ``result:`` alias so callers read
``data["result"]`` uniformly.
"""

from __future__ import annotations

# --- common ------------------------------------------------------------------

VERSION = "query { result: version }"

SERVER_TIME_INFO = "query { result: getTimeInfo { timezone, currentTimestamp } }"

# --- metadata: layers / services ---------------------------------------------

LIST_LAYERS = "query { result: listLayers }"

LIST_SERVICE = """query ($layer: String!) {
    result: listServices(layer: $layer) {
        id name group shortName layers normal
    }
}"""

# metadata: instances (v2 / v1 select the query by protocol version)
INSTANCES_V2 = """query ($serviceId: ID!, $duration: Duration!) {
    result: listInstances(duration: $duration, serviceId: $serviceId) {
        id name language instanceUUID
        attributes { name value }
    }
}"""

INSTANCES_V1 = """query ($serviceId: ID!, $duration: Duration!) {
    result: getServiceInstances(duration: $duration, serviceId: $serviceId) {
        id name language instanceUUID
        attributes { name value }
    }
}"""

# metadata: endpoints (three variants by version)
FIND_ENDPOINTS_WITH_DURATION = """query ($keyword: String!, $serviceId: ID!, $limit: Int!, $duration: Duration) {
    result: findEndpoint(keyword: $keyword, serviceId: $serviceId, limit: $limit, duration: $duration) {
        id name
    }
}"""

FIND_ENDPOINTS_WITHOUT_DURATION = """query ($keyword: String!, $serviceId: ID!, $limit: Int!) {
    result: findEndpoint(keyword: $keyword, serviceId: $serviceId, limit: $limit) {
        id name
    }
}"""

SEARCH_ENDPOINTS_V1 = """query ($keyword: String!, $serviceId: ID!, $limit: Int!) {
    result: searchEndpoint(keyword: $keyword, serviceId: $serviceId, limit: $limit) {
        id name
    }
}"""

# metadata: processes (always v2)
PROCESSES = """query ($instanceId: ID!, $duration: Duration!) {
    result: listProcesses(instanceId: $instanceId, duration: $duration) {
        id name serviceId serviceName instanceId instanceName agentId detectType labels
        attributes { name value }
    }
}"""

# --- topology ----------------------------------------------------------------

GET_SERVICES_TOPOLOGY = """query ($serviceIds: [ID!]!, $duration: Duration!) {
    result: getServicesTopology(serviceIds: $serviceIds, duration: $duration) {
        nodes { id name type isReal layers }
        calls { id source detectPoints target sourceComponents targetComponents }
    }
}"""

GLOBAL_TOPOLOGY = """query ($layer: String, $duration: Duration!) {
    result: getGlobalTopology(duration: $duration, layer: $layer) {
        nodes { id name type isReal layers }
        calls { id source detectPoints target sourceComponents targetComponents }
    }
}"""

GLOBAL_TOPOLOGY_WITHOUT_LAYER = """query ($duration: Duration!) {
    result: getGlobalTopology(duration: $duration) {
        nodes { id name type isReal }
        calls { id source detectPoints target sourceComponents targetComponents }
    }
}"""

INSTANCE_TOPOLOGY = """query ($clientServiceId: ID!, $serverServiceId: ID!, $duration: Duration!) {
    result: getServiceInstanceTopology(duration: $duration, clientServiceId: $clientServiceId, serverServiceId: $serverServiceId) {
        nodes { id name type isReal serviceName serviceId }
        calls { id source detectPoints target sourceComponents targetComponents }
    }
}"""

ENDPOINT_DEPENDENCY = """query ($endpointId: ID!, $duration: Duration!) {
    result: getEndpointDependencies(duration: $duration, endpointId: $endpointId) {
        nodes { id name serviceId serviceName type isReal }
        calls { id source target detectPoints sourceComponents targetComponents }
    }
}"""

PROCESS_TOPOLOGY = """query ($serviceInstanceId: ID!, $duration: Duration!) {
    result: getProcessTopology(serviceInstanceId: $serviceInstanceId, duration: $duration) {
        nodes { id serviceId serviceName serviceInstanceId serviceInstanceName name isReal }
        calls { source target id detectPoints sourceComponents targetComponents }
    }
}"""

# --- trace (v2 / v1 selected by hasQueryTracesV2Support) ---------------------

_SPAN_SELECTION = """spans {
    traceId segmentId spanId parentSpanId
    refs { traceId parentSegmentId parentSpanId type }
    serviceCode serviceInstanceName
    startTime endTime endpointName type peer component isError layer
    tags { key value }
    logs { time data { key value } }
    attachedEvents {
        startTime { seconds nanos } event endTime { seconds nanos }
        tags { key value } summary { key value }
    }
}"""

HAS_QUERY_TRACES_V2_SUPPORT = "query { result: hasQueryTracesV2Support }"

QUERY_TRACES_V2 = (
    """query ($condition: TraceQueryCondition) {
    result: queryTraces(condition: $condition) {
        traces { %s }
        retrievedTimeRange { startTime endTime }
    }
}"""
    % _SPAN_SELECTION
)

QUERY_BASIC_TRACES_V1 = """query ($condition: TraceQueryCondition!) {
    result: queryBasicTraces(condition: $condition) {
        traces { segmentId endpointNames duration start isError traceIds }
    }
}"""

# queryTraceV1 omits the queryTrace `duration` argument deliberately: it is
# BanyanDB-only and absent on OAP < 10.3.0, so including it would break this
# fallback on older backends.
QUERY_TRACE_V1 = (
    """query ($traceId: ID!) {
    result: queryTrace(traceId: $traceId) {
        %s
    }
}"""
    % _SPAN_SELECTION
)

# --- events / logs -----------------------------------------------------------

QUERY_EVENTS = """query ($condition: EventQueryCondition) {
    result: queryEvents(condition: $condition) {
        events {
            uuid
            source { service serviceInstance endpoint }
            name type message
            parameters { key value }
            startTime endTime layer
        }
    }
}"""

QUERY_LOGS = """query ($condition: LogQueryCondition!) {
    result: queryLogs(condition: $condition) {
        logs {
            serviceName serviceId serviceInstanceName serviceInstanceId
            endpointName endpointId traceId timestamp contentType content
            tags { key value }
        }
    }
}"""

# --- MQE ---------------------------------------------------------------------

LIST_METRICS = """query listMetrics($regex: String) {
    listMetrics(regex: $regex) { name type catalog }
}"""

TYPE_OF_METRICS = """query typeOfMetrics($name: String!) {
    typeOfMetrics(name: $name)
}"""

GET_SERVICE_BY_ID = """query getService($serviceId: String!) {
    service: getService(serviceId: $serviceId) { id name normal layers }
}"""

LIST_SERVICES_ID_NAME = """query getServices($layer: String!) {
    services: listServices(layer: $layer) { id name }
}"""

# Capability introspection (drives which optional schema fields are requested).
CAPABILITY_INTROSPECTION = """query {
    alarmMessage: __type(name: "AlarmMessage") { fields { name } }
    mqeValue: __type(name: "MQEValue") { fields { name } }
    expressionResult: __type(name: "ExpressionResult") { fields { name } }
    queryType: __type(name: "Query") { fields { name args { name } } }
}"""


def build_mqe_expression_gql(caps) -> str:
    """Render the execExpression query, omitting debug args and result fields that
    older OAP releases do not define (port of buildMQEExpressionGQL)."""
    debug_params = ", $debug: Boolean, $dumpDBRsp: Boolean" if caps.mqe_debug_args else ""
    debug_args = ", debug: $debug, dumpDBRsp: $dumpDBRsp" if caps.mqe_debug_args else ""

    owner = ""
    if caps.mqe_value_owner:
        owner = """owner {
                                scope
                                serviceID
                                serviceName
                                normal
                                serviceInstanceID
                                serviceInstanceName
                                endpointID
                                endpointName
                            }"""

    debugging_trace = ""
    if caps.mqe_debugging_trace:
        debugging_trace = """debuggingTrace {
                    traceId
                    condition
                    duration
                    spans {
                        spanId
                        operation
                        msg
                        startTime
                        endTime
                        duration
                    }
                }"""

    return f"""
        query execExpression($expression: String!, $entity: Entity!, $duration: Duration!{debug_params}) {{
            execExpression(expression: $expression, entity: $entity, duration: $duration{debug_args}) {{
                type
                error
                results {{
                    metric {{
                        labels {{
                            key
                            value
                        }}
                    }}
                    values {{
                        id
                        value
                        traceID
                        {owner}
                    }}
                }}
                {debugging_trace}
            }}
        }}
    """


def _alarm_message_fields(caps) -> str:
    """Render the AlarmMessage selection set, skipping fields absent on older OAP
    (port of alarmMessageFields)."""
    parts = ["startTime scope id message tags { key value }"]
    if caps.alarm_name:
        parts.append("name")
    parts.append(
        """events {
    name
    source { service serviceInstance endpoint }
    startTime endTime message
    parameters { key value }
    uuid layer
}"""
    )
    if caps.alarm_snapshot:
        owner = ""
        if caps.mqe_value_owner:
            owner = (
                "owner { scope serviceID serviceName normal serviceInstanceID "
                "serviceInstanceName endpointID endpointName }"
            )
        parts.append(
            f"""snapshot {{
    expression
    metrics {{
        name
        results {{
            metric {{ labels {{ key value }} }}
            values {{ id value traceID {owner} }}
        }}
    }}
}}"""
        )
    return "\n".join(parts)


def build_alarm_query_gql(caps) -> str:
    """Port of buildAlarmQueryGQL."""
    return f"""
query ($duration: Duration!, $scope: Scope, $keyword: String, $paging: Pagination!, $tags: [AlarmTag]) {{
    result: getAlarm(duration: $duration, scope: $scope, keyword: $keyword, paging: $paging, tags: $tags) {{
        msgs {{
{_alarm_message_fields(caps)}
        }}
    }}
}}"""
