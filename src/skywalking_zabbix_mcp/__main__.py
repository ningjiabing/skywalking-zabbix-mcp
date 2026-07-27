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

"""Entry point. Transport is chosen by the first CLI argument (stdio | sse |
streamable), mirroring the Go server's subcommands. stdio is the default."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from .config import load_config
from .server import build_server


def _setup_logging(level: str) -> None:
    """Configure root logging from SW_LOG_LEVEL. Logs go to stderr because stdout
    is the stdio transport's MCP protocol channel and must not be polluted."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="skywalking-zabbix-mcp",
        description="Unified observability MCP server (SkyWalking + Zabbix)",
    )
    parser.add_argument(
        "transport",
        nargs="?",
        default="stdio",
        choices=["stdio", "sse", "streamable"],
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SW_MCP_HOST", "127.0.0.1"),
        help="bind address for sse/streamable (default: 127.0.0.1; these transports "
        "have no built-in authentication, do not expose them publicly)",
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("SW_MCP_PORT", "8000")))
    parser.add_argument("--path", default=os.environ.get("SW_MCP_PATH", "/mcp"))
    args = parser.parse_args()

    config = load_config()
    _setup_logging(config.log_level)
    log = logging.getLogger(__name__)
    log.info(
        "starting skywalking-zabbix-mcp %s (transport=%s)",
        __version__,
        args.transport,
    )
    mcp = build_server(config)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    # sse/streamable serve unauthenticated HTTP: warn loudly if bound off-loopback.
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "binding %s transport to %s: this server has no authentication layer, "
            "put it behind a reverse proxy or restrict access at the network level",
            args.transport,
            args.host,
        )
    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:  # streamable
        mcp.run(transport="streamable-http", host=args.host, port=args.port, path=args.path)


if __name__ == "__main__":
    main()
