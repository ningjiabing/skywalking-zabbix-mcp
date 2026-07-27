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

"""SkyWalking analysis prompts, ported verbatim from internal/prompts/*.go.
Each prompt returns a single user-message text template."""

from __future__ import annotations

_DEFAULT_DURATION = "-1h"
_DEFAULT_END = "now"
_ALL_METRICS = "all"

# Tool capability mapping + recommended chains (port of prompts/tools.go).
_TOOL_CAPABILITIES = {
    "performance_analysis": ["execute_mqe_expression", "query_traces"],
    "trace_investigation": ["query_traces"],
    "log_analysis": ["query_logs"],
    "mqe_query_building": ["execute_mqe_expression", "list_mqe_metrics", "get_mqe_metric_type"],
    "service_comparison": ["execute_mqe_expression"],
    "metrics_exploration": ["list_mqe_metrics", "get_mqe_metric_type"],
}
_ANALYSIS_CHAINS = {
    "performance_analysis": [
        (
            "execute_mqe_expression",
            "Query metrics like CPM, SLA, response time, percentiles, and top entities",
        ),
        ("query_traces", "Find error traces for deeper investigation"),
    ],
    "trace_investigation": [
        ("query_traces", "Search for traces with specific filters and analyze results"),
    ],
    "log_analysis": [
        ("query_logs", "Search and analyze log entries with filters"),
    ],
    "mqe_query_building": [
        ("list_mqe_metrics", "Discover available metrics"),
        ("get_mqe_metric_type", "Understand metric types and usage"),
        ("execute_mqe_expression", "Test and execute the built expression"),
    ],
}


def _tool_instructions(analysis_type: str) -> str:
    tools = _TOOL_CAPABILITIES.get(analysis_type, [])
    chain = _ANALYSIS_CHAINS.get(analysis_type, [])
    if not tools:
        return "No specific tools defined for this analysis type."
    out = "**Available Tools:**\n"
    for t in tools:
        out += f"- {t}\n"
    if chain:
        out += "\n**Recommended Analysis Workflow:**\n"
        for i, (tool, purpose) in enumerate(chain, 1):
            out += f"{i}. {tool}: {purpose}\n"
    return out


def register(mcp) -> None:
    @mcp.prompt(
        name="analyze-performance", description="Analyze service performance using metrics tools"
    )
    def analyze_performance(service_name: str, start: str = "", end: str = "") -> str:
        start = start or _DEFAULT_DURATION
        end = end or _DEFAULT_END
        ti = _tool_instructions("performance_analysis")
        return f"""Please analyze the performance of service '{service_name}' for the time range start="{start}", end="{end}".

{ti}

**Analysis Required:**

Use start="{start}", end="{end}" on every tool call below.

**Response Time Analysis**
- Use execute_mqe_expression with expression="service_resp_time", start="{start}", end="{end}"
- Use execute_mqe_expression with expression="service_percentile{{p='50,75,90,95,99'}}", start="{start}", end="{end}"
- Identify trends and anomalies

**Success Rate and SLA**
- Use execute_mqe_expression with expression="service_sla / 100", start="{start}", end="{end}"
- Use execute_mqe_expression with expression="service_apdex / 10000", start="{start}", end="{end}"
- Track SLA compliance over time

**Traffic Analysis**
- Use execute_mqe_expression with expression="service_cpm", start="{start}", end="{end}"
- Identify traffic patterns and peak periods

**Error Analysis**
- Use query_traces with trace_state="error", start="{start}", end="{end}" to find error traces
- Identify most common error types and affected endpoints

**Performance Bottlenecks**
- Use execute_mqe_expression with expression="top_n(endpoint_resp_time, 5, DES)", start="{start}", end="{end}"
- Use execute_mqe_expression with expression="top_n(endpoint_cpm, 5, DES)", start="{start}", end="{end}"

Please provide actionable insights and specific recommendations based on the data."""

    @mcp.prompt(
        name="compare-services", description="Compare performance metrics between multiple services"
    )
    def compare_services(services: str, metrics: str = "", start: str = "", end: str = "") -> str:
        metrics = metrics or _ALL_METRICS
        start = start or _DEFAULT_DURATION
        end = end or _DEFAULT_END
        return f"""Please compare the following services: {services}

Time Range: start="{start}", end="{end}"
Metrics to Compare: {metrics}

Use start="{start}", end="{end}" on every execute_mqe_expression call.

Comparison should include:

1. **Performance Comparison**
   - Response time comparison (average and percentiles)
   - Throughput (CPM) comparison
   - Success rate (SLA) comparison

2. **Resource Utilization**
   - CPU and memory usage if available
   - Connection pool usage

3. **Error Patterns**
   - Error rate comparison
   - Types of errors by service

4. **Dependency Impact**
   - How each service affects others
   - Cascade failure risks

5. **Relative Performance**
   - Which service is the bottleneck
   - Performance ratios
   - Efficiency metrics

Please present the comparison in a clear, tabular format where possible, and highlight significant differences."""

    @mcp.prompt(name="top-services", description="Find top N services by various metrics")
    def top_services(metric_name: str, top_n: str = "", order: str = "") -> str:
        top_n = top_n or "10"
        order = order or "DES"
        return f"""Find top services using execute_mqe_expression tool:

**Tool Configuration:**
- execute_mqe_expression with expression: "top_n({metric_name}, {top_n}, {order})"

**Analysis Focus:**

**Service Ranking**
- Get top {top_n} services by {metric_name}
- Compare values against baseline
- Identify outliers or anomalies

**Performance Insights**
- For CPM metrics: Find busiest services
- For response time: Find slowest services
- For SLA: Find services with issues

**Actionable Recommendations**
- Services needing immediate attention
- Capacity planning insights
- Performance optimization targets

**Follow-up Analysis**
- Use query_traces for error investigation
- Use execute_mqe_expression for additional metric analysis

Provide ranked results with specific recommendations."""

    @mcp.prompt(
        name="investigate-traces",
        description="Investigate traces for errors and performance issues",
    )
    def investigate_traces(
        service_id: str = "", trace_state: str = "", start: str = "", end: str = ""
    ) -> str:
        start = start or _DEFAULT_DURATION
        end = end or _DEFAULT_END
        trace_state = trace_state or "all"
        ti = _tool_instructions("trace_investigation")
        return f"""Investigate traces with filters: service_id="{service_id}", trace_state="{trace_state}", start="{start}", end="{end}".

{ti}

**Analysis Steps:**

**Find Problematic Traces**
- First use query_traces with start="{start}", end="{end}", view="summary" to get overview
- Look for patterns in error traces, slow traces, or anomalies
- Note trace IDs that need deeper investigation

**Deep Dive on Specific Traces**
- Use query_traces with the identified trace_id
- Start with view="summary" for quick insights
- Use view="full" for complete span analysis
- Use view="errors_only" if focusing on errors

**Performance Analysis**
- Look for traces with high duration using min_trace_duration filter
- Identify bottlenecks in span timings
- Check for cascading delays

**Error Pattern Analysis**
- Use query_traces with trace_state="error"
- Group errors by type and service
- Identify error propagation paths

Provide specific findings and actionable recommendations."""

    @mcp.prompt(name="trace-deep-dive", description="Deep dive analysis of a specific trace")
    def trace_deep_dive(trace_id: str, view: str = "") -> str:
        view = view or "summary"
        return f"""Perform deep dive analysis of trace {trace_id}:

**Primary Analysis:**
- Use query_traces with trace_id: "{trace_id}" and view: "{view}"
- Start with summary view for quick insights
- Use full view for complete span analysis
- Use errors_only view if trace has errors

**Trace Structure Analysis**
- Service call flow and dependencies
- Span duration breakdown
- Critical path identification
- Parallel vs sequential operations

**Performance Investigation**
- Identify bottleneck spans
- Database query performance
- External API call latency
- Resource wait times

**Error Analysis** (if applicable)
- Error location and propagation
- Root cause identification
- Impact assessment

**Optimization Opportunities**
- Redundant operations
- Caching possibilities
- Parallel processing potential
- Database query optimization

Provide detailed trace analysis with specific optimization recommendations."""

    @mcp.prompt(name="analyze-logs", description="Analyze service logs for errors and patterns")
    def analyze_logs(
        service_id: str = "", log_level: str = "", start: str = "", end: str = ""
    ) -> str:
        start = start or _DEFAULT_DURATION
        end = end or _DEFAULT_END
        log_level = log_level or "ERROR"
        return f"""Analyze service logs using the query_logs tool:

**Tool Configuration:**
- query_logs with following parameters:
  - service_id: "{service_id}" (if specified)
  - tags: [{{"key": "level", "value": "{log_level}"}}] for log level filtering
  - start: "{start}", end: "{end}" for time range
  - cold: true if historical data needed

**Analysis Steps:**

**Log Pattern Analysis**
- Use query_logs to get recent logs for the service
- Filter by log level (ERROR, WARN, INFO)
- Look for recurring error patterns
- Identify frequency of different log types

**Error Investigation**
- Focus on ERROR level logs first
- Group similar error messages
- Check for correlation with trace IDs
- Look for timestamp patterns

**Performance Correlation**
- Compare log timestamps with performance issues
- Look for resource exhaustion indicators
- Check for timeout or connection errors

**Troubleshooting Workflow**
- Start with ERROR logs in the specified time range
- Use trace_id from logs to get detailed trace analysis
- Cross-reference with metrics for full picture

Provide specific log analysis findings and recommendations."""

    @mcp.prompt(
        name="explore-service-topology",
        description="Explore the service topology of a layer: list services, instances, endpoints, and processes within a time range",
    )
    def explore_service_topology(layer: str, start: str, end: str = "") -> str:
        end = end or _DEFAULT_END
        return f"""Explore the service topology of layer "{layer}" within the time range from "{start}" to "{end}".

**Workflow:**

**Step 1 – Discover services**
- Use list_services with layer="{layer}" to get all services in this layer
- Note the id of each service for the next steps

**Step 2 – List instances per service**
- For each service of interest, use list_instances with:
  - service_id: <id from step 1>
  - start: "{start}"
  - end: "{end}"
- Review instance names, languages, and attributes

**Step 3 – List endpoints per service**
- Use list_endpoints with:
  - service_id: <id from step 1>
  - start: "{start}"
  - end: "{end}"
- Note endpoint ids for use in metrics or trace queries

**Step 4 – List processes per instance**
- For each instance of interest, use list_processes with:
  - instance_id: <id from step 2>
  - start: "{start}"
  - end: "{end}"
- Review process names, detect types, and labels

**Summary to provide:**
- Total number of services, instances, endpoints, and processes found
- Any notable attributes or labels worth highlighting
- Suggested follow-up queries (e.g. metrics, traces, logs) for specific services or instances"""

    @mcp.prompt(
        name="generate_duration",
        description="Convert a natural-language time range into a {start, end} duration object for use with list_instances, list_endpoints, list_processes, and similar tools",
    )
    def generate_duration(time_range: str) -> str:
        return f"""Convert the following time range description into a duration object with "start" and "end" fields.

Time range: "{time_range}"

Rules:
- "start" and "end" must be strings in one of these formats:
  - Relative: "-30m" (30 minutes ago), "-1h" (1 hour ago), "-7d" (7 days ago)
  - Absolute: "2024-01-01 12:00:00" (YYYY-MM-DD HH:MM:SS)
- If the end of the range is the current time, set "end" to "now"
- Relative values are always negative (e.g. "-1h", not "1h")

Output only a JSON object, for example:
{{"start": "-1h", "end": "now"}}

This duration can be passed directly to tools such as list_instances, list_endpoints, and list_processes."""

    @mcp.prompt(
        name="build-mqe-query",
        description="Help build MQE (Metrics Query Expression) for complex queries",
    )
    def build_mqe_query(query_type: str, metrics: str, conditions: str = "") -> str:
        ti = _tool_instructions("mqe_query_building")
        return f"""Help me build an MQE (Metrics Query Expression) for the following requirement:

Query Type: {query_type}
Metrics: {metrics}
Additional Conditions: {conditions}

{ti}

**MQE Building Process:**

**Step-by-step approach:**
- Explain the MQE syntax for this use case
- Provide the complete MQE expression
- Show example usage with different parameters
- Explain what each part of the expression does
- Suggest variations for different scenarios

If there are multiple ways to achieve this, please show alternatives with pros and cons."""

    @mcp.prompt(name="explore-metrics", description="Explore available metrics and their types")
    def explore_metrics(pattern: str = "", show_examples: str = "") -> str:
        pattern = pattern or ".*"
        ti = _tool_instructions("metrics_exploration")
        return f"""Explore available metrics with pattern: "{pattern}".

{ti}

**Exploration Workflow:**

**Discover Metrics**
- Use list_mqe_metrics to get all available metrics
- Filter by pattern if specified
- Review metric names and types

**Understand Metric Types**
- For each interesting metric, use get_mqe_metric_type
- REGULAR_VALUE: Direct arithmetic operations
- LABELED_VALUE: Requires label selectors
- SAMPLED_RECORD: Complex record-based metrics

**Usage Examples** (if show_examples is "{show_examples}"):
- REGULAR_VALUE: service_cpm, service_sla * 100
- LABELED_VALUE: service_percentile{{p='50,75,90,95,99'}}
- Complex: avg(service_cpm), top_n(service_resp_time, 10, des)

**Metric Categories:**
- Service metrics: service_sla, service_cpm, service_resp_time
- Instance metrics: service_instance_*
- Endpoint metrics: endpoint_*
- Relation metrics: service_relation_*
- Infrastructure metrics: service_cpu, service_memory

**Best Practices:**
- Check metric type before using in expressions
- Use appropriate label selectors for LABELED_VALUE
- Combine metrics for comprehensive analysis
- Use aggregation functions for trend analysis

Provide a comprehensive guide to available metrics and their usage."""
