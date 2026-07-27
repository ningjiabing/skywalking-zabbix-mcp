## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## Why

<!-- The problem behind the change. -->

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy` passes
- [ ] `uv run pytest` passes, and new behaviour is covered by a test
- [ ] No credentials, real hostnames or internal IPs in the diff
- [ ] New GraphQL fields that only exist on recent OAP are gated behind a capability probe
- [ ] `CHANGELOG.md` updated under `Unreleased` for user-visible changes
- [ ] Docs updated in both `README.md` and `README.en.md` if behaviour or configuration changed
