<p align="center">
  <img src="assets/logo.svg" alt="spring-fleet" width="560"/>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-6db33f.svg" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/Spring%20Boot-3.x%20%2F%204.x-6db33f.svg?logo=springboot&logoColor=white" alt="Spring Boot 3.x / 4.x"/>
  <img src="https://img.shields.io/badge/Java-17%2B-orange.svg?logo=openjdk&logoColor=white" alt="Java 17+"/>
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776ab.svg?logo=python&logoColor=white" alt="Python 3.8+"/>
  <img src="https://img.shields.io/badge/MCP-server%20included-7c3aed.svg" alt="MCP server included"/>
  <img src="https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg" alt="Claude Code plugin"/>
  <img src="https://img.shields.io/badge/tests-48%20passing-brightgreen.svg" alt="Tests"/>
</p>

# spring-fleet

**A Claude Code plugin that makes a fleet of Spring Boot microservices feel
like a single codebase.**

If you maintain more than a handful of Spring services spread across separate
repos, you know the pain:

- A request fails → which service was last to touch it?
- A bug report says "session ABC123 broke" → whose logs?
- You're refactoring a shared lib → who actually uses this class?

spring-fleet teaches Claude your fleet's shape — repos, ports, services, who
calls whom — and gives you a few commands that handle the cross-repo legwork
for you.

---

## What it does

| You ask | spring-fleet does |
|---|---|
| **"Where does this request go?"** | Follows the call chain across every repo and proxy-lib, with `file:line` citations at every hop. |
| **"Why did this break?"** | Merges every service's logs into one timeline by trace key, finds the failing hop, and explains the root cause — with a suggested fix and the exact file to edit. |
| **"What breaks if I change this?"** | Lists every consumer of a shared class, file, or endpoint across the fleet, flagged by risk. |
| **"How do I start the fleet locally?"** | Plans (or runs) `docker compose up` or `bootRun` per service, with logs landing where the debugger can find them. |

You stay in Claude Code — no new dashboard, no agent to deploy, no SaaS account.

---

## See it work (30 seconds, no install)

The repo ships a tiny three-service "fleet" you can correlate logs against
right now:

```bash
git clone https://github.com/talayash/spring-fleet
cd spring-fleet
python scripts/correlate_logs.py --config fixtures/fleet.config.json --value ABC123
```

You'll see something like:

```
2026-06-09 14:23:01.100 [orchestrator] received reserve request
2026-06-09 14:23:01.220 [order]        create order
2026-06-09 14:23:01.450 [order]        order created id=9001
2026-06-09 14:23:01.600 [payment]      charge requested amount=120.00
2026-06-09 14:23:02.200 [payment]      ERROR upstream gateway timeout after 600ms
2026-06-09 14:23:02.300 [payment]      ERROR returning 502 Bad Gateway
2026-06-09 14:23:02.350 [orchestrator] ERROR payment-api returned 502, aborting reserve
```

One trace key, three services' logs interleaved chronologically, the failing
hop visible. That's what `/debug` does in Claude Code — plus a "here's the
root cause and where to fix it" writeup at the end.

<p align="center">
  <img src="assets/debug-demo.svg" alt="spring-fleet /debug correlating logs across three services" width="820"/>
</p>

---

## Install (2 minutes)

You need [Claude Code](https://claude.com/claude-code) and Python 3.8+.

```text
# 1. Tell Claude Code where the marketplace lives:
/plugin marketplace add talayash/spring-fleet

# 2. Install the plugin from it:
/plugin install spring-fleet@spring-fleet
```

> **Why two steps?** The marketplace is the catalog; the plugin is the entry
> inside it. They happen to share the same name in this repo. If you skip
> step 1, you'll get `Plugin "spring-fleet" not found`.
>
> Already installed but seeing a stale version?
> `/plugin marketplace update spring-fleet`.

---

## First use (5 minutes)

### 1. Describe your fleet to the plugin

```text
/fleet-init C:/path/to/your/repos
```

This scans every repo under that directory and writes a draft config
(`spring-fleet.config.json`) into your project root. It auto-detects:

- which repos are services vs shared libraries
- each service's port, context path, build tool
- modern stack features: Spring Boot 4, Java 21+, virtual threads,
  GraalVM native, `compose.yaml`, Testcontainers, OpenTelemetry,
  Spring AI MCP server
- Backstage `catalog-info.yaml` files (used to seed topology)

Two things it **can't** infer mechanically — Claude will ask you:

- **`traceKeys`** — which MDC keys identify a request in your logs.
  Modern fleets: keep the defaults (`trace_id`, `span_id`).
  Legacy fleets: add your own (`sessionId`, `requestId`, etc.).
- **`topology`** — who calls whom. If you have Backstage catalogs,
  most of this is filled in for you.

> 🔒 **`spring-fleet.config.json` is `.gitignore`d by default.** It contains
> your private paths and service names. Never commit it. Share the
> `*.example.json` file instead.

### 2. Use it

```text
/trace POST /order-v1/reserve
/debug 4bf92f3577b34da6a3ce929d0e0e4736       # paste an OTel trace_id
/debug ABC123                                 # or a legacy sessionId
/debug "NullPointerException at PaymentController.charge"
/debug                                        # then paste a Grafana screenshot
/impact core-lib/util/RetryPolicy.java
/run                                          # plan the fleet launch
/run --execute                                # actually start it
/logs payment --grep ERROR --follow
```

### 3. (Optional) Fix log scattering

If `/debug` reports missing log files, your services aren't writing to a
common place yet. Ask Claude:

> Use the `spring-fleet-logging-setup` skill to install the logback
> convention.

It drops a small `logback-spring.xml` into each service so every service
writes `<logDir>/<service>.log` with trace keys in the pattern.

---

## Commands

| Command | What you type | What you get |
|---|---|---|
| `/fleet-init` | `/fleet-init [path/to/repos]` | Draft config from your repos. Run once per project. |
| `/trace` | `/trace POST /order-v1/reserve` | Ordered call chain across repos, with `file:line` for every hop. |
| `/debug` | `/debug <trace_id\|sessionId\|"error"\|screenshot>` | Cross-service log timeline + a root-cause hypothesis (what / where in code / why / suggested fix / alternatives). |
| `/impact` | `/impact OrderEntity` | Every consumer across the fleet, classified by call kind and contract risk. |
| `/run` | `/run [service] [--execute]` | Plans (or launches) the local fleet — `docker compose up` first, `bootRun` / `mvn spring-boot:run` as fallback. |
| `/logs` | `/logs payment --grep ERROR --follow` | Tail / aggregate logs. `--k8s` falls back to `kubectl logs` (mirrord-friendly). |

Each command also runs deterministic Python scripts under the hood
(`correlate_logs.py`, `scan_repos.py`, `tail_logs.py`, `run_fleet.py`) — you
can call them directly without Claude if you want.

---

## How it works

```
spring-fleet (this plugin — generic, shareable)        your machine (private)
├── commands/        /fleet-init /trace /debug          spring-fleet.config.json
│                    /impact /run /logs                   ├─ reposRoot
├── agents/          fleet-explorer · log-correlator      ├─ logDir, traceKeys
│                    impact-analyzer                      ├─ services[] (name, port, path, stack)
├── skills/          tracing · debugging · logging-setup  ├─ sharedLibs[], proxyLib
│                    federating-mcp-servers               └─ topology (entry, edges)
├── hooks/           SessionStart · SubagentStop ·
│                    statusLine
├── scripts/         deterministic Python (stdlib only)
├── mcp_server.py    typed MCP tools (in scripts/)
├── output-styles/   fleet-narrator
└── logback/         drop-in logging convention
```

The plugin is **generic and shareable** — it has zero knowledge of your
specific repos. Everything environment-specific lives in your local
`spring-fleet.config.json`, which is git-ignored.

When you start a Claude Code session in a project with that config, the
**SessionStart hook** preloads your fleet topology so Claude doesn't need
to re-read it each turn. The **MCP server** (`scripts/mcp_server.py`)
exposes six typed tools so Claude calls them deterministically instead of
parsing CLI output.

---

## MCP tools (for power users)

If you're already using MCP, spring-fleet ships a stdlib MCP server you can
call from any MCP-aware client:

| Tool | Purpose |
|---|---|
| `list_services` | Services + ports + detected stack + shared libs |
| `get_topology` | Entry services and `[from, to]` edges |
| `correlate_by_trace` | Cross-service timeline for a trace value |
| `tail_service_log` | Last N lines of one or more service logs |
| `scan_repos_root` | Draft config from a repos directory |
| `find_service_log_path` | Resolve a service name → its log file path |

The server speaks JSON-RPC 2.0 over stdio. `.mcp.json` registers it
automatically with Claude Code. Fleets whose services ship their own
Spring AI MCP server (Spring AI 1.1+) can federate them alongside —
see the `federating-mcp-servers` skill.

---

## Configuration

Run `/fleet-init` to generate `spring-fleet.config.json`, or copy
`spring-fleet.config.example.json` and edit by hand. The complete JSON Schema
lives in `spring-fleet.config.schema.json`. Most-used fields:

| Field | What it is |
|---|---|
| `reposRoot` | The directory under which all your service + lib repos live. |
| `services[]` | Each service: `{ name, path, port, contextPath, logFile, stack, backstage }`. |
| `sharedLibs[]`, `proxyLib` | Cross-repo libraries — used by `/trace` and `/impact`. |
| `topology` | `entry` services + `[from, to]` call edges. Seeded from Backstage when available. |
| `traceKeys` | MDC keys for log correlation. Defaults: `["trace_id", "span_id", "sessionId", "requestId"]`. |
| `logDir` | Where per-service logs land. `/debug` and `/logs` read from here. |
| `k8s` *(optional)* | `{ namespace, context, podSelectorTemplate }` — enables `kubectl logs` fallback. |

---

## FAQ

**Do I need OpenTelemetry?**
No. spring-fleet works with whatever MDC keys your services already emit
(`sessionId`, `requestId`, your own). If you do have OTel — great, `trace_id`
is the default correlation key.

**Does it work with Spring Boot 3?**
Yes. spring-fleet supports Spring Boot 3.x and 4.x side-by-side. `/fleet-init`
records the major version per service so commands can branch on it.

**Does it support Maven?**
Yes. `buildTool.type` is `gradle` or `maven`; `/run` and the templates adapt.

**My services run in Kubernetes — does this still work?**
Yes. Add a `k8s` block to your config and pass `--k8s` to `/logs` (or set
`SPRING_FLEET_K8S=1`). spring-fleet shells out to `kubectl logs` when a
file-based log is missing. Works great with [mirrord](https://mirrord.dev/).

**Does any of this leave my machine?**
No. spring-fleet runs locally; Claude reads your logs and source through
the plugin. Your `spring-fleet.config.json` is `.gitignore`d by default.

**What if I don't use Claude Code?**
The Python scripts (`correlate_logs.py`, `scan_repos.py`, `tail_logs.py`,
`run_fleet.py`) are usable as a standalone CLI. The MCP server is callable
from any MCP-aware client.

---

## Try the demo without installing

You don't need Claude Code to see what the correlator does:

```bash
python scripts/correlate_logs.py --config fixtures/fleet.config.json --value ABC123
```

The bundled `fixtures/` fleet reconstructs a failed reserve across three
services and surfaces the payment gateway timeout as the root cause.

To see it correlate by **OTel trace_id** instead:

```bash
python scripts/correlate_logs.py --config fixtures/fleet.config.json --value 4bf92f3577b34da6a3ce929d0e0e4736
```

Same timeline, modern key.

---

## Development

```bash
python -m unittest discover -s tests -v
```

48 tests across `tests/test_scripts.py`, `tests/test_mcp.py`,
`tests/test_hooks.py`, `tests/test_run_fleet.py`. No network, no third-party
dependencies, runs on Python 3.8+. CI executes on Linux / Windows / macOS
against Python 3.8 and 3.12 (see `.github/workflows/ci.yml`).

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Roadmap

- **Streamable HTTP** transport for the MCP server (currently stdio-only).
- **`/incident`** — bundles `/debug` + `/impact` into a postmortem-style writeup.
- **GitHub PR comment integration** (Vercel Agent / Sentry Seer style).

See [CHANGELOG.md](CHANGELOG.md) for what shipped when.

---

## License

MIT © Tal Ayash
