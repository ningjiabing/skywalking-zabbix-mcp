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

"""MQE documentation resources (mqe://...), ported from internal/resources/mqe_docs.go.
Three static docs bundled as package data, plus one dynamic resource that lists the
backend's live metrics."""

from __future__ import annotations

import json
from importlib import resources as importlib_resources

from . import queries
from .backend import Backend
from .client import GraphQLError

_DATA_PKG = "skywalking_zabbix_mcp.resources_data"


def _read_data(filename: str) -> str:
    return importlib_resources.files(_DATA_PKG).joinpath(filename).read_text(encoding="utf-8")


def register(mcp, backend: Backend) -> None:
    @mcp.resource(
        "mqe://docs/syntax",
        name="MQE Detailed Syntax Rules",
        description="Comprehensive syntax rules and grammar for MQE expressions",
        mime_type="text/markdown",
    )
    def mqe_syntax() -> str:
        return _read_data("mqe_detailed_syntax.md")

    @mcp.resource(
        "mqe://docs/examples",
        name="MQE Examples",
        description="Common MQE expression examples with natural language descriptions",
        mime_type="application/json",
    )
    def mqe_examples() -> str:
        return _read_data("mqe_examples.json")

    @mcp.resource(
        "mqe://docs/ai_prompt",
        name="MQE AI Understanding Guide",
        description="Guide for AI models to understand natural language queries and convert to MQE",
        mime_type="text/markdown",
    )
    def mqe_ai_prompt() -> str:
        return _read_data("mqe_ai_prompt.md")

    @mcp.resource(
        "mqe://metrics/available",
        name="Available Metrics",
        description="List of all available metrics in the current SkyWalking instance",
        mime_type="application/json",
    )
    def mqe_metrics_available() -> str:
        try:
            data = backend.execute(queries.LIST_METRICS, {})
        except GraphQLError as exc:
            raise RuntimeError(f"failed to list metrics: {exc}") from exc
        # Match the Go resource's pretty-printed (2-space indent) output.
        return json.dumps(data, ensure_ascii=False, indent=2)
