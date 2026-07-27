# skywalking-zabbix-mcp

[![CI](https://github.com/ningjiabing/skywalking-zabbix-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ningjiabing/skywalking-zabbix-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/skywalking-zabbix-mcp.svg)](https://pypi.org/project/skywalking-zabbix-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/skywalking-zabbix-mcp.svg)](https://pypi.org/project/skywalking-zabbix-mcp/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

简体中文 | [English](README.en.md)

一个 MCP Server，把 **SkyWalking（应用 APM）** 和 **Zabbix（主机监控）** 接进同一个进程，让 AI 助手能在一次对话里既看应用指标、又看机器指标，并把两者关联起来。

**它解决什么问题？** 排障时你通常要开两个系统：SkyWalking 看服务慢在哪、Zabbix 看机器是不是扛不住了，然后人脑对时间线判断「是机器先炸拖垮了应用，还是应用自己的 bug」。这个 server 把这一步交给 AI——你问一句「payment-service 怎么了」，它自动拉齐应用侧和机器侧两份数据给出结论。

**为什么能自动关联？** SkyWalking 的服务名格式是 `<IP>::<服务名>`（如 `192.0.2.11::payment-service`），其中的 IP 段正好就是 Zabbix 里的主机名。两边天然用 IP 对齐，**不需要维护任何服务↔主机映射表**。

<p align="center">
  <img src="docs/demo.svg" alt="diagnose_service 与 correlate_incident 的实际输出" width="100%">
</p>

<p align="center">
  <sub>真实的 server 代码跑在 <a href="docs/demo/">mock 后端</a> 上，数据为合成数据。用 <code>uv run python docs/demo/run_demo.py</code> 可自行复现。</sub>
</p>

---

## 两种运行形态

| 配置 | 得到的 server |
|---|---|
| 只配 `SW_*` | **纯 SkyWalking**：16 个工具 + 10 prompts + 4 resources |
| 加配 `ZABBIX_URL` 等 | **应用 + 机器一体**：上面 16 个 + Zabbix 2 个 + 跨栈关联 2 个 = **20 工具** |

换句话说：**配了 `ZABBIX_URL` 才会注册 Zabbix 和关联相关的 4 个工具**，否则退化为纯 SkyWalking server。

---

## 快速上手

### 1. 安装（三选一）

**A. uvx —— 不用 clone，一行跑起来（推荐）**

```bash
uvx skywalking-zabbix-mcp --version
```

**B. Docker**

```bash
docker run --rm -i \
  -e SW_URL=http://<oap-host>:12800 \
  ghcr.io/ningjiabing/skywalking-zabbix-mcp
```

**C. 源码（要改代码就用这个）**

```bash
git clone https://github.com/ningjiabing/skywalking-zabbix-mcp.git
cd skywalking-zabbix-mcp
uv sync
uv run skywalking-zabbix-mcp --version
```

### 2. 接入 AI 客户端

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add obs -s user \
  -e SW_URL=http://<oap-host>:12800 \
  -e ZABBIX_URL=http://<zabbix-host>/zabbix/api_jsonrpc.php \
  -e ZABBIX_USER=<用户> -e ZABBIX_PASSWORD='${MY_ZBX_PWD}' \
  -e READ_ONLY=true \
  -- uvx skywalking-zabbix-mcp
```
</details>

<details>
<summary><b>Claude Desktop</b>（<code>claude_desktop_config.json</code>）</summary>

```json
{
  "mcpServers": {
    "obs": {
      "command": "uvx",
      "args": ["skywalking-zabbix-mcp"],
      "env": {
        "SW_URL": "http://<oap-host>:12800",
        "ZABBIX_URL": "http://<zabbix-host>/zabbix/api_jsonrpc.php",
        "ZABBIX_USER": "<用户>",
        "ZABBIX_PASSWORD": "${MY_ZBX_PWD}",
        "READ_ONLY": "true"
      }
    }
  }
}
```
</details>

<details>
<summary><b>Cursor</b>（<code>.cursor/mcp.json</code> 或全局 <code>~/.cursor/mcp.json</code>）</summary>

```json
{
  "mcpServers": {
    "obs": {
      "command": "uvx",
      "args": ["skywalking-zabbix-mcp"],
      "env": {
        "SW_URL": "http://<oap-host>:12800",
        "READ_ONLY": "true"
      }
    }
  }
}
```
</details>

<details>
<summary><b>Codex CLI</b>（<code>~/.codex/config.toml</code>）</summary>

```toml
[mcp_servers.obs]
command = "uvx"
args = ["skywalking-zabbix-mcp"]

[mcp_servers.obs.env]
SW_URL = "http://<oap-host>:12800"
ZABBIX_URL = "http://<zabbix-host>/zabbix/api_jsonrpc.php"
ZABBIX_USER = "<用户>"
READ_ONLY = "true"
```

等价的命令行写法：

```bash
codex mcp add obs -- uvx skywalking-zabbix-mcp
```

注意 Codex 的配置是 TOML、键名是 `mcp_servers`（下划线），跟 Claude/Cursor 的 JSON `mcpServers` 不一样。口令建议留在 shell 环境变量里，由 Codex 进程继承，不要写进 `config.toml`。
</details>

<details>
<summary><b>VS Code</b>（<code>.vscode/mcp.json</code>）</summary>

```json
{
  "servers": {
    "obs": {
      "type": "stdio",
      "command": "uvx",
      "args": ["skywalking-zabbix-mcp"],
      "env": {
        "SW_URL": "http://<oap-host>:12800",
        "READ_ONLY": "true"
      }
    }
  }
}
```
</details>

<details>
<summary><b>源码方式</b>（把 <code>uvx skywalking-zabbix-mcp</code> 换成绝对路径）</summary>

```json
{
  "command": "uv",
  "args": ["--directory", "/绝对路径/skywalking-zabbix-mcp", "run", "skywalking-zabbix-mcp"]
}
```
</details>

> 凭据一律用 `${ENV}` 引用（见[配置](#配置)），别写进命令行或配置文件明文。全部变量见 `.env.example`。

### 3. 直接跑（stdio / HTTP）

```bash
uvx skywalking-zabbix-mcp                                  # stdio，默认
uvx skywalking-zabbix-mcp sse --port 8000
uvx skywalking-zabbix-mcp streamable --port 8000 --path /mcp
```

> ⚠️ **sse / streamable 没有任何鉴权**，默认只绑 `127.0.0.1`。绑到其它地址等于把 OAP 和 Zabbix 的读权限（没开 `READ_ONLY` 时还有写权限）暴露给能连上这个端口的任何人。要对外必须挡一层带认证的反向代理，或在网络层限制。详见 [SECURITY.md](SECURITY.md)。

### 4. 试一句

> 「诊断一下 `192.0.2.11::payment-service`」

server 会用 `diagnose_service` 一次返回该服务的应用指标（cpm / 响应时间 / SLA + 告警）和承载主机的 Zabbix 数据（CPU / 内存 / IO + 当前 problem）。

---

## 工具一览

### SkyWalking（16 个，任何配置都有）

| 类别 | 工具 | 作用 |
|---|---|---|
| **元数据** | `list_layers` `list_services` `list_instances` `list_endpoints` `list_processes` | 列出层 / 服务 / 实例 / 端点 / 进程 |
| **拓扑** | `query_services_topology` `query_instances_topology` `query_endpoints_topology` `query_processes_topology` | 四个粒度的调用拓扑 |
| **链路** | `query_traces` | 查 trace，支持 summary / errors_only / full 三视图，v1/v2 协议自动选 |
| **指标** | `execute_mqe_expression` `list_mqe_metrics` `get_mqe_metric_type` | 跑 MQE 表达式、列可用指标、查指标类型 |
| **告警/事件/日志** | `query_alarms` `query_events` `query_logs` | 查告警、事件、日志 |

### Zabbix（2 个，配 `ZABBIX_URL` 才启用）

| 工具 | 作用 |
|---|---|
| `zabbix_query` | 执行任意 Zabbix JSON-RPC 方法（`host.get` / `item.get` / `problem.get` / `history.get`…）。只读模式下仅放行 `*.get` |
| `zabbix_list` | 列常用方法 + 实时探测 API 版本 |

### 跨栈关联（2 个，配 `ZABBIX_URL` 才启用）

| 工具 | 作用 |
|---|---|
| `diagnose_service` | 传 SkyWalking 服务名，一次拿回**应用侧**（cpm / resp_time / sla + 告警）+ **机器侧**（该 IP 主机的 CPU/内存/IO + 当前 problem） |
| `correlate_incident` | 对齐两侧时间窗内的告警，判断「机器先炸」还是「应用先炸」 |

### 另外还有

- **10 个 prompts**（排查引导）：`analyze-performance` `compare-services` `top-services` `investigate-traces` `trace-deep-dive` `analyze-logs` `explore-service-topology` `generate_duration` `build-mqe-query` `explore-metrics`
- **4 个 resources**（MQE 文档）：`mqe://docs/syntax`、`mqe://docs/examples`、`mqe://docs/ai_prompt`（静态），`mqe://metrics/available`（动态，实时列后端指标）

---

## 配置

全部通过环境变量。凭据类支持 `${ENV}` 展开（如 `SW_PASSWORD=${MY_SW_PWD}`），避免明文。示例见 `.env.example`。

| 变量 | 说明 | 默认 |
|---|---|---|
| `SW_URL` | OAP 地址，自动补 `/graphql` | `http://localhost:12800/graphql` |
| `SW_USERNAME` / `SW_PASSWORD` | SkyWalking Basic Auth | 空 |
| `SW_INSECURE` | 跳过 TLS 校验（仅测试用） | `false` |
| `SW_LOG_LEVEL` | 日志级别 | `info` |
| `ZABBIX_URL` | Zabbix `api_jsonrpc.php` 全路径。**配了才启用 Zabbix + 关联工具** | 空（禁用） |
| `ZABBIX_USER` / `ZABBIX_PASSWORD` | Zabbix 账号 | 空 |
| `READ_ONLY` | 只读守卫：对 Zabbix 拦截一切非 `*.get` 写方法 | `false` |
| `VERIFY_SSL` | Zabbix TLS 校验 | `true` |
| `ZABBIX_SKIP_VERSION_CHECK` | 兼容占位（本客户端不强制版本，实为 no-op） | `false` |

> **`ZABBIX_URL` 路径别配错**：装在子路径的形如 `http://host/zabbix/api_jsonrpc.php`，装在根路径的形如 `http://host:port/api_jsonrpc.php`。配错直接 404。

完整 JSON 写法见上面[接入 AI 客户端](#2-接入-ai-客户端)一节。

---

## 典型用法

| 场景 | 怎么做 |
|---|---|
| **一句话看服务全景** | `diagnose_service("192.0.2.11::payment-service")`——应用指标 + 告警 + 承载主机的机器指标 + problem，一次到手 |
| **判断谁先炸** | `correlate_incident(时间窗)`——两侧告警按时间对齐，机器故障 vs 应用异常 |
| **链路下钻找瓶颈** | `query_traces` 拉慢/错 trace，配 `trace-deep-dive` prompt 定位耗时 span |
| **跑指标表达式** | `execute_mqe_expression`；不会写就先读 `mqe://docs/syntax` 或用 `build-mqe-query` prompt |

---

## 兼容性

**新旧 OAP 通吃**——启动时自动探测后端版本与 schema 能力，按实际支持裁剪查询：

- 版本探测（`version` → major.minor）：metadata / endpoints / trace 按版本走 v1 或 v2 查询。
- schema 能力探测（introspection）：alarm / MQE 按后端实际字段裁剪 selection set，避免旧版校验报错。
- MQE 老语法自动改写：`service_percentile{p='50,90'}` → `{_='0,2'}`，返回结果再还原成 `p` 标签。
- `coldStage` 仅在请求 cold 数据时才下发（旧版 OAP 无此字段）。

**Zabbix 4.0 兼容**——PHP 污染响应去噪、`user` 登录参数、body `auth` 字段、`/zabbix/` 子路径，全部自动处理。

**安全**——SkyWalking 的 16 个工具本就是只读查询；开 `READ_ONLY=true` 后 Zabbix 侧也只放行 `*.get`，拦截一切写方法。部署前请读 [SECURITY.md](SECURITY.md)：凭据管理、HTTP 传输无鉴权、工具输出会流向 LLM，这三点都要按你的环境评估。

**依赖极简**——只有 `fastmcp` + `httpx`。

---

## 开发

```bash
uv sync                      # 装运行时 + 开发依赖
uv run pre-commit install    # ruff / 私钥检测 / gitleaks
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

测试覆盖 GraphQL 客户端鉴权与错误面、后端版本/能力探测与缓存、trace v1/v2 协议选择与三种视图、MQE 老语法改写、Zabbix 登录/重登/只读守卫/PHP 污染去噪、跨栈关联两个工具的端到端路径，以及「纯 SkyWalking 16 工具、加 Zabbix 变 20 工具」这个契约本身。

贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

Apache License 2.0，见 [`LICENSE`](LICENSE) / [`NOTICE`](NOTICE)。变更记录见 [CHANGELOG.md](CHANGELOG.md)。SkyWalking 相关查询文本源自 Apache SkyWalking 项目，跨语言移植保留原始许可。
