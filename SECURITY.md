# Security Policy

## Supported versions

The latest released version on the `main` branch receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through [GitHub Security Advisories](https://github.com/ningjiabing/skywalking-zabbix-mcp/security/advisories/new), or by email to meilijing.ning@gmail.com.

Include the affected version, reproduction steps and impact. You can expect an acknowledgement within 7 days and a status update as a fix progresses.

## Security model of this server

Worth understanding before you deploy it:

- **It holds credentials.** `SW_USERNAME`/`SW_PASSWORD` and `ZABBIX_USER`/`ZABBIX_PASSWORD` are read from the environment. Prefer `${ENV}` indirection over literals, and never commit `.env` or `.mcp.json`.
- **`READ_ONLY=true` is the safe default for Zabbix.** It rejects every JSON-RPC method that is not `*.get`. Without it, `zabbix_query` can call write methods — including ones that modify hosts, triggers and users — with whatever permissions the configured account has. Give the account the least privilege it needs.
- **The 16 SkyWalking tools are read-only queries** by construction; they cannot mutate OAP state.
- **The `sse` and `streamable` transports have no authentication.** They bind to `127.0.0.1` by default. If you bind elsewhere, put the server behind a reverse proxy that authenticates, or restrict access at the network level. Anyone who can reach the port can read everything the configured credentials can read, and, without `READ_ONLY`, write to Zabbix.
- **`SW_INSECURE=true` and `VERIFY_SSL=false` disable TLS verification.** Testing only.
- **Tool output reaches an LLM.** Traces, logs and alarms may contain user data or secrets from your systems; that content leaves your network if the model runs remotely. Scope the credentials accordingly.
