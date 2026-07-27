# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-27

Initial public release.

### Added

- SkyWalking tools (16): metadata (`list_layers`, `list_services`, `list_instances`, `list_endpoints`, `list_processes`), topology at four granularities, `query_traces`, MQE (`execute_mqe_expression`, `list_mqe_metrics`, `get_mqe_metric_type`), and `query_alarms` / `query_events` / `query_logs`.
- Zabbix tools (2): `zabbix_query`, `zabbix_list`, registered only when `ZABBIX_URL` is set.
- Cross-stack correlation (2): `diagnose_service` and `correlate_incident`, joining SkyWalking and Zabbix on the IP embedded in a `<IP>::<service>` service name — no mapping table required.
- 10 investigation prompts and 4 MQE documentation resources.
- Old/new OAP compatibility: version detection, schema capability probing, legacy MQE label-key rewriting, conditional `coldStage`.
- Zabbix 4.0 compatibility: PHP-polluted response de-noising, `user` login parameter, body-level `auth` field, `/zabbix/` sub-path.
- `READ_ONLY` guard rejecting every non-`*.get` Zabbix method.
- stdio, SSE and streamable-HTTP transports; `--version` flag.

[Unreleased]: https://github.com/ningjiabing/skywalking-zabbix-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ningjiabing/skywalking-zabbix-mcp/releases/tag/v0.1.0
