# Contributing

Thanks for taking the time to contribute. Issues, bug reports and pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/ningjiabing/skywalking-zabbix-mcp.git
cd skywalking-zabbix-mcp
uv sync                 # installs runtime + dev dependencies
uv run pre-commit install
```

## Before you open a pull request

Everything CI enforces can be run locally:

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type-check
uv run pytest --cov          # tests + coverage
```

`pre-commit` runs ruff, a private-key check and gitleaks on every commit. Please keep it enabled — this project handles OAP and Zabbix credentials, and a leaked secret in git history is expensive to undo.

## Guidelines

- **Never commit credentials.** `.env`, `.env.*` and `.mcp.json` are git-ignored. Copy `.env.example` and fill in your own values.
- **No real hostnames or internal IPs** in code, tests or docs. Use RFC 5737 documentation addresses (`192.0.2.0/24`) and generic service names. `tests/test_packaging.py` scans every published file and fails on anything outside those ranges.
- **Keep dependencies minimal.** Runtime deps are `fastmcp` and `httpx`; adding a third needs a good reason in the PR description.
- **Cover behaviour with tests.** Pure logic goes in `tests/test_unit.py`; anything that talks HTTP should be mocked with `respx` (see `tests/test_http.py`).
- **Backend compatibility matters.** This server supports old and new OAP releases. If you add a GraphQL field that only exists in recent versions, gate it behind a capability probe in `backend.py` instead of sending it unconditionally.
- **License headers.** New files carry the Apache 2.0 header. Files derived from Apache SkyWalking keep the ASF header plus a NOTICE line describing the modification.

## Commit messages

Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`). Breaking changes get a `!` (`feat!:`) and an explanation in the body.

## Releasing (maintainers)

1. Bump `__version__` in `src/skywalking_zabbix_mcp/__init__.py` — it is the single source of truth, `pyproject.toml` reads it dynamically.
2. Mirror the new version into `server.json` (three `version` fields: the manifest and both packages).
3. Add the release section to `CHANGELOG.md`.
4. Run `uv run pytest tests/test_packaging.py` — it fails if step 2 or 3 was missed.
5. Tag `vX.Y.Z` and push. `release.yml` verifies the tag matches the package version, builds, publishes to PyPI via Trusted Publishing and creates the GitHub release.
