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

"""Configuration loaded from SW_* environment variables.

Mirrors the Go server: env prefix ``SW`` with ``SW_URL`` / ``SW_USERNAME`` /
``SW_PASSWORD`` / ``SW_INSECURE`` / ``SW_LOG_LEVEL`` and the transport-agnostic
``READ_ONLY``.

``READ_ONLY`` scope: it is enforced on the Zabbix side only, where it rejects
every JSON-RPC method that is not ``*.get``. The 16 SkyWalking tools issue read
queries by construction and have nothing to disable, so the flag is a no-op
there; it is still carried on :class:`Config` for parity and future write tools.

Values may live in a ``.env`` file so a single config is shared by every MCP
client (Claude Code, Cursor, Codex, ...) instead of each one embedding its own
``env`` block. The server auto-loads ``.env`` at startup; set ``ENV_FILE`` to
point at a different path. Loading uses ``override=False`` so any variable
already set by the launching client wins, and it is a no-op when no file exists.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

DEFAULT_SW_URL = "http://localhost:12800/graphql"

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """Populate os.environ from a .env file (idempotent, best-effort).

    ``ENV_FILE`` selects an explicit path; otherwise the nearest ``.env`` is
    discovered from the current working directory. Variables already present in
    the environment take precedence (override=False), so this is purely additive
    and safe when python-dotenv is absent or no .env file exists.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # dotenv optional; fall back to the raw environment
        return
    env_file = os.environ.get("ENV_FILE", "").strip()
    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(find_dotenv(usecwd=True), override=False)


def _expand_env(value: str) -> str:
    """Expand ${ENV_VAR} references, matching the Go flag behavior."""
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_oap_url(raw_url: str) -> str:
    """Ensure the OAP URL path ends with ``/graphql`` (port of NormalizeOAPURL).

    Raises ValueError on an unsupported scheme or a missing host, so a
    misconfiguration surfaces at startup rather than as an opaque request error.
    """
    u = urlparse(raw_url)
    if u.scheme not in ("http", "https"):
        raise ValueError(
            f"unsupported OAP URL scheme {u.scheme!r}: only http and https are allowed"
        )
    if not u.netloc:
        raise ValueError(f"invalid OAP URL {raw_url!r}: host is required")

    path = u.path
    if path in ("", "/"):
        path = "/graphql"
    elif not path.endswith("/graphql"):
        path = path.rstrip("/") + "/graphql"

    return urlunparse(u._replace(path=path))


@dataclass
class Config:
    url: str
    username: str
    password: str
    insecure: bool
    read_only: bool
    log_level: str

    @property
    def graphql_url(self) -> str:
        return normalize_oap_url(self.url)


@dataclass
class ZabbixConfig:
    """Zabbix JSON-RPC config. Empty ``url`` means Zabbix tools are disabled."""

    url: str
    user: str
    password: str
    verify_ssl: bool
    read_only: bool
    # Informational for parity with the standalone Zabbix MCP; this client never
    # enforces a version so the check is effectively always skipped on Zabbix 4.0.
    skip_version_check: bool

    @property
    def enabled(self) -> bool:
        return bool(self.url)


def load_config() -> Config:
    _load_dotenv_once()
    raw_url = os.environ.get("SW_URL", "").strip() or DEFAULT_SW_URL
    return Config(
        url=raw_url,
        username=_expand_env(os.environ.get("SW_USERNAME", "")),
        password=_expand_env(os.environ.get("SW_PASSWORD", "")),
        insecure=_truthy(os.environ.get("SW_INSECURE")),
        read_only=_truthy(os.environ.get("READ_ONLY")),
        log_level=os.environ.get("SW_LOG_LEVEL", "info").strip() or "info",
    )


def load_zabbix_config() -> ZabbixConfig:
    _load_dotenv_once()
    # VERIFY_SSL defaults to true; only an explicit false disables verification.
    verify = os.environ.get("VERIFY_SSL")
    return ZabbixConfig(
        url=os.environ.get("ZABBIX_URL", "").strip(),
        user=_expand_env(os.environ.get("ZABBIX_USER", "")),
        password=_expand_env(os.environ.get("ZABBIX_PASSWORD", "")),
        verify_ssl=True if verify is None else _truthy(verify),
        read_only=_truthy(os.environ.get("READ_ONLY")),
        skip_version_check=_truthy(os.environ.get("ZABBIX_SKIP_VERSION_CHECK")),
    )
