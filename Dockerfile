# syntax=docker/dockerfile:1

# ---- build ------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve from the lockfile first so a source-only change does not
# invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime ----------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="skywalking-zabbix-mcp" \
      org.opencontainers.image.description="Unified observability MCP server: SkyWalking (OAP GraphQL) + Zabbix, with cross-stack correlation." \
      org.opencontainers.image.source="https://github.com/ningjiabing/skywalking-zabbix-mcp" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN useradd --create-home --uid 10001 mcp
COPY --from=build --chown=mcp:mcp /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SW_MCP_HOST=0.0.0.0 \
    SW_MCP_PORT=8000

USER mcp
WORKDIR /app
EXPOSE 8000

# Default to stdio (how MCP clients spawn it). For HTTP:
#   docker run -p 8000:8000 ghcr.io/ningjiabing/skywalking-zabbix-mcp streamable
# The HTTP transports are unauthenticated — do not publish the port to an
# untrusted network without a proxy in front. See SECURITY.md.
ENTRYPOINT ["skywalking-zabbix-mcp"]
CMD ["stdio"]
