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
#
# Self-built Zabbix JSON-RPC client. Deliberately does NOT depend on any
# third-party Zabbix library (avoids GPL) — it is derived from an in-house
# probe script and tuned for the quirks of Zabbix 4.0 (see notes below).

"""Zabbix 4.0 JSON-RPC client.

Handles the traps observed against the production Zabbix 4.0 backends:

1. PHP warning pollution: the endpoint may prefix HTML/PHP warnings before the
   JSON body, so the JSON object is extracted with a regex rather than parsing
   the raw response directly.
2. Login parameter: Zabbix < 5.4 uses ``user`` (not ``username``).
3. Auth transport: Zabbix < 6.4 carries the token in the request body ``auth``
   field, not an ``Authorization: Bearer`` header.
4. URL: some deployments live under a ``/zabbix/`` sub-path, others at the root;
   the caller supplies the full ``.../api_jsonrpc.php`` URL.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

_log = logging.getLogger(__name__)

_JSON_OBJECT = re.compile(r'\{"jsonrpc".*\}', re.S)

# Methods allowed under READ_ONLY: any *.get, plus a few auth/info calls.
_READ_ONLY_ALLOWED = {"apiinfo.version", "user.login", "user.logout", "user.checkauthentication"}

# Substrings that mark an expired/invalid session, triggering one re-login retry.
_AUTH_ERROR_MARKERS = ("re-login", "not authori", "session terminated", "authentication")


class ZabbixError(Exception):
    """A Zabbix transport or API error."""


class ZabbixClient:
    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        verify_ssl: bool = True,
        read_only: bool = False,
        timeout: float = 20.0,
    ):
        if not url:
            raise ValueError("ZABBIX_URL is required to build a ZabbixClient")
        self._url = url
        self._user = user
        self._password = password
        self._read_only = read_only
        self._auth: str | None = None
        self._http = httpx.Client(
            timeout=timeout,
            verify=verify_ssl,
            headers={"Content-Type": "application/json-rpc"},
        )

    # --- low-level ----------------------------------------------------------

    def _post(self, method: str, params: Any, auth: str | None) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
        # login carries no auth; older Zabbix rejects an `auth` key on user.login.
        if auth is not None and method != "user.login":
            body["auth"] = auth
        try:
            resp = self._http.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise ZabbixError(f"Zabbix request failed: {exc}") from exc

        raw = resp.text
        match = _JSON_OBJECT.search(raw)  # strip any PHP warning noise before the JSON
        if not match:
            raise ZabbixError(
                f"Zabbix returned a non-JSON response (HTTP {resp.status_code}): {raw[:200]!r}"
            )
        try:
            payload = json.loads(match.group(0))
        except ValueError as exc:
            raise ZabbixError(f"failed to decode Zabbix response: {exc}") from exc

        if "error" in payload:
            err = payload["error"]
            raise ZabbixError(f"{err.get('message', 'error')}: {err.get('data', '')}")
        return payload.get("result")

    # --- session ------------------------------------------------------------

    def login(self) -> str:
        """Authenticate and cache the session token (Zabbix < 5.4 uses ``user``)."""
        if self._auth:
            return self._auth
        token = self._post(
            "user.login", {"user": self._user, "password": self._password}, auth=None
        )
        if not isinstance(token, str) or not token:
            raise ZabbixError("Zabbix login did not return an auth token")
        self._auth = token
        _log.info("Zabbix login OK (user=%s)", self._user)
        return token

    # --- public API ---------------------------------------------------------

    def call(self, method: str, params: Any = None) -> Any:
        """Execute any Zabbix API method, logging in on first use.

        Under read-only mode, only ``*.get`` and a small allow-list are permitted;
        write methods (create/update/delete/...) are refused before any request.
        """
        method = method.strip()
        if self._read_only and not self._is_read_method(method):
            raise ZabbixError(
                f"method '{method}' is blocked in read-only mode (only *.get and "
                f"{sorted(_READ_ONLY_ALLOWED)} are allowed)"
            )
        if method == "apiinfo.version":
            # version needs no auth
            return self._post(method, params, auth=None)
        auth = self.login()
        try:
            return self._post(method, params, auth=auth)
        except ZabbixError as exc:
            # The cached session may have expired; drop it, re-login once, retry.
            if not self._is_auth_error(exc):
                raise
            _log.info("Zabbix session rejected (%s); re-logging in and retrying", exc)
            self._auth = None
            auth = self.login()
            return self._post(method, params, auth=auth)

    @staticmethod
    def _is_read_method(method: str) -> bool:
        return method.endswith(".get") or method in _READ_ONLY_ALLOWED

    @staticmethod
    def _is_auth_error(exc: ZabbixError) -> bool:
        msg = str(exc).lower()
        return any(marker in msg for marker in _AUTH_ERROR_MARKERS)

    def close(self) -> None:
        self._http.close()
