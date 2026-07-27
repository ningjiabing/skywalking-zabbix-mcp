# Demo

The image in the project README is generated from a real run of this server. The
server, the MCP client and every tool are the real thing — only the backend is a
stand-in.

**Why a mock backend?** Because a screenshot taken against a live monitoring
stack would publish that stack's hostnames, addresses and service names. The mock
returns synthetic data using RFC 5737 documentation addresses (`192.0.2.0/24`)
and generic service names, so nothing real can leak into a published image.

## Regenerate

```bash
uv run python docs/demo/run_demo.py | uv run python docs/demo/render_svg.py > docs/demo.svg
```

## Files

| File | What it does |
|---|---|
| `mock_backend.py` | A stdlib HTTP server speaking the slice of OAP GraphQL and Zabbix JSON-RPC the demo touches. Also runnable on its own: `python docs/demo/mock_backend.py` |
| `run_demo.py` | Boots the mock, builds the real server, drives it through a real `fastmcp` client, prints an ANSI transcript |
| `render_svg.py` | Converts that ANSI transcript into `docs/demo.svg` |

## Point a client at the mock

Useful for trying the tools without any real infrastructure:

```bash
python docs/demo/mock_backend.py &
SW_URL=http://127.0.0.1:18800 \
ZABBIX_URL=http://127.0.0.1:18800/zabbix/api_jsonrpc.php \
ZABBIX_USER=demo ZABBIX_PASSWORD=demo READ_ONLY=true \
  uv run skywalking-zabbix-mcp
```

The mock answers `diagnose_service`, `correlate_incident`, `list_layers`,
`list_services` and MQE expressions. Anything else returns a GraphQL error
naming the query it could not handle — extend `_graphql` / `_zabbix` if you need
more.
