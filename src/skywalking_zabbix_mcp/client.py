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

"""OAP GraphQL client (port of the Go executeGraphQLWithContext + skywalking-cli
client). Synchronous httpx; basic auth and optional TLS-skip come from Config.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Config

_log = logging.getLogger(__name__)


class GraphQLError(Exception):
    """A GraphQL transport or query error, mirroring the Go error surface."""


class GraphQLClient:
    def __init__(self, config: Config, timeout: float = 30.0):
        self._config = config
        auth = None
        if config.username and config.password:
            auth = httpx.BasicAuth(config.username, config.password)
        self._client = httpx.Client(
            timeout=timeout,
            verify=not config.insecure,
            auth=auth,
            headers={"Content-Type": "application/json"},
        )

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL request and return its ``data`` object.

        Raises GraphQLError on a non-200 status or a non-empty ``errors`` array,
        matching the Go client which treats any GraphQL error as a hard failure.
        """
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables

        try:
            resp = self._client.post(self._config.graphql_url, json=body)
        except httpx.HTTPError as exc:
            _log.error("OAP GraphQL HTTP request failed: %s", exc)
            raise GraphQLError(f"failed to execute HTTP request: {exc}") from exc

        if resp.status_code != 200:
            _log.error("OAP GraphQL HTTP status %s: %s", resp.status_code, resp.text[:300])
            raise GraphQLError(f"GraphQL request failed with HTTP status {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise GraphQLError(f"failed to decode GraphQL response: {exc}") from exc

        errors = payload.get("errors")
        if errors:
            # Surface the backend's own messages instead of a generic string, so a
            # missing field / bad argument is diagnosable from the client error.
            detail = "; ".join(
                str(e.get("message", e)) for e in errors if isinstance(e, dict)
            ) or str(errors)
            _log.warning("OAP GraphQL query returned errors: %s", detail)
            raise GraphQLError(f"GraphQL query failed: {detail}")

        data = payload.get("data")
        if data is None:
            return {}
        return data

    def close(self) -> None:
        self._client.close()
