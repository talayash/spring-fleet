<p align="center">
  <img src="assets/logo.svg" alt="spring-fleet" width="560"/>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-6db33f.svg" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/Spring%20Boot-3.x%20%2F%204.x-6db33f.svg?logo=springboot&logoColor=white" alt="Spring Boot 3.x / 4.x"/>
  <img src="https://img.shields.io/badge/Java-17%2B%20(21%2F25%20ready)-orange.svg?logo=openjdk&logoColor=white" alt="Java 17+ (21/25 ready)"/>
  <img src="https://img.shields.io/badge/Python-3.8%2B%20(stdlib%20only)-3776ab.svg?logo=python&logoColor=white" alt="Python 3.8+"/>
  <img src="https://img.shields.io/badge/OpenTelemetry-W3C%20traceparent-blueviolet.svg" alt="OpenTelemetry W3C traceparent"/>
  <img src="https://img.shields.io/badge/MCP-server%20included-7c3aed.svg" alt="MCP server included"/>
  <img src="https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg" alt="Claude Code plugin"/>
  <img src="https://img.shields.io/badge/tests-48%20passing-brightgreen.svg" alt="Tests"/>
</p>

# spring-fleet

The **OpenTelemetry-native, MCP-first** [Claude Code](https://claude.com/claude-code)
plugin for navigating, tracing, and debugging a **fleet of multi-repo
Spring Boot microservices**.

It does three things well:

- **🔍 Trace** — follow a request or feature across many service repos and shared
  libraries, with `file:line` citations, including inter-service (proxy-lib) hops.
- **🐞 Debug** — correlate logs across every service by an OTel `trace_id` (or
  legacy `sessionId`), reconstruct one cross-service timeline, isolate the
  failing hop, and produce a code-grounded **root-cause hypothesis** with
  `file:line` and a suggested fix — the open-source analogue of Sentry Seer /
  Datadog Bits, but repo-aware.
- **💥 Impact** — fan outward from a shared-lib symbol or service endpoint and
  list every consumer across the fleet, classified by call kind and contract risk.

Under the hood it ships an **MCP server** so Claude calls typed tools instead of
parsing CLI output, a **SessionStart hook** that loads your topology
automatically, and **Backstage `catalog-info.yaml` ingestion** so multi-repo
fleets initialize with one command.

The plugin is **generic**. Everything specific to *your* environment — repo
paths, ports, service names, trace keys — lives in one private config file that
is **git-ignored and never committed**.

## `/debug` in action

One trace key, every service's logs merged into a single timeline, the failing
hop isolated and explained — across repos:

<p align="center">
  <img src="assets/debug-demo.svg" alt="spring-fleet /debug correlating logs across three services" width="820"/>
</p>

> The output above is the real correlator running against the bundled
> [`fixtures/`](fixtures/) fleet — reproduce it with the [demo command](#try-the-demo-no-setup).

---

## How it works

```
spring-fleet (this plugin — generic, shareable)   your machine (private)
├── commands/   /fleet-init /trace /debug /logs    spring-fleet.config.json
├── skills/     the know-how                         ├─ reposRoot, buildTool
├── agents/     fleet-explorer, log-correlator       ├─ services[] (name,port,path)
├── scripts/    correlate_logs / scan_repos / tail   ├─ sharedLibs[], proxyLib
└── logback/    drop-in logging convention           ├─ topology (the call chain)
                                                      ├─ traceKeys ["sessionId"]
                                                      └─ logDir
```

The plugin reads your config at runtime — no paths, ports, or names are ever
hard-coded into the plugin itself.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.8+ (standard library only — no third-party packages)
- A fleet of Spring Boot services built with Gradle or Maven

## Install

Two steps, **in order** — you must add the marketplace *before* installing, or
you'll get `Plugin "spring-fleet" not found in any marketplace`:

```
# 1. Register the marketplace (clones this repo)
/plugin marketplace add talayash/spring-fleet

# 2. Install the plugin from it
/plugin install spring-fleet@spring-fleet
```

`spring-fleet@spring-fleet` is `plugin@marketplace` — this repo's marketplace and
plugin share the name. Once the marketplace is added, plain
`/plugin install spring-fleet` also works.

> Already added it and seeing a stale version? Refresh from GitHub with
> `/plugin marketplace update spring-fleet`.

## Quickstart

1. **Generate your config** (scans your repos, infers ports/context paths,
   detects services vs shared libs):
   ```
   /fleet-init C:/path/to/your/repos
   ```
   Confirm the two things it can't infer — your `traceKeys` and the `topology`
   (who calls whom). The result is written to `spring-fleet.config.json` in your
   project root.

2. **Make sure logs land somewhere stable** (only if they're console-only or
   scattered): the `spring-fleet-logging-setup` skill installs a logback
   convention so every service writes `<logDir>/<service>.log` with your trace
   keys in the pattern.

3. **Use it:**
   ```
   /trace POST /order-v1/reserve
   /debug ABC123                 # a sessionId from a failed request
   /debug "NullPointerException at PaymentController.charge"
   /logs payment --grep ERROR --follow
   ```

## Commands

| Command | What it does |
|---|---|
| `/fleet-init [reposRoot]` | Scan repos → generate/update `spring-fleet.config.json` (detects Spring Boot major, Java toolchain, virtual threads, GraalVM native, `compose.yaml`, Testcontainers, OTel, Spring AI MCP server; ingests Backstage `catalog-info.yaml`). |
| `/trace <endpoint\|feature>` | Cross-repo call chain with `file:line` citations. |
| `/debug <trace_id \| sessionId \| error \| screenshot>` | Cross-service log timeline → failure origin → **root-cause hypothesis** with `file:line` and suggested fix. Accepts pasted Grafana / stack-trace images. |
| `/impact <symbol \| file \| endpoint>` | Fan outward: every consumer across the fleet, classified by call kind and contract risk. |
| `/run [service\|all] [--execute]` | Plan or launch the fleet locally — compose-first per service, gradle/maven fallback, stdout tee'd to `<logDir>`. |
| `/logs [service\|all] [--grep --lines --follow --k8s]` | Tail/aggregate fleet logs; `--k8s` falls back to `kubectl logs` (mirrord-friendly). |

## MCP tools

`.mcp.json` registers a stdlib MCP server that exposes the fleet operations as
typed tools so Claude (and any other MCP-aware client) can call them
deterministically:

- `list_services` — services + stack + sharedLibs + traceKeys
- `get_topology` — entry services + `[from, to]` edges
- `correlate_by_trace` — cross-service timeline for a trace value
- `tail_service_log` — last N lines of one or more service logs
- `scan_repos_root` — draft config from a repos directory
- `find_service_log_path` — resolve a service name to its log path

Fleets whose services ship their own Spring AI MCP server (Spring AI 1.1+) can
federate those servers alongside spring-fleet's — see the
`federating-mcp-servers` skill.

## Configuration

Copy `spring-fleet.config.example.json` to `spring-fleet.config.json` and edit,
or let `/fleet-init` generate it. The schema is documented in
`spring-fleet.config.schema.json`. Key fields:

- `reposRoot` — directory containing all your repos
- `services[]` — `{ name, path, port, contextPath, logFile }`
- `sharedLibs[]`, `proxyLib` — for cross-repo tracing
- `topology` — `entry` services and `[from, to]` call edges
- `traceKeys` — MDC keys that correlate a request (e.g. `["sessionId"]`)
- `logDir` — where per-service logs are collected

> **⚠️ Privacy:** your real `spring-fleet.config.json` contains private paths,
> ports, and service names. It is `.gitignore`d by default. **Never commit it.**
> Share the example file, not your config.

## Try the demo (no setup)

The repo ships a tiny fake fleet under `fixtures/`:

```
python scripts/correlate_logs.py --config fixtures/fleet.config.json --value ABC123
```

You'll see a three-service timeline reconstruct a failed reserve, with the
payment gateway timeout surfaced as the root cause.

## Development

```
python -m unittest discover -s tests -v
```

Tests run the deterministic scripts against the `fixtures/` fleet — no network,
no third-party deps.

## Roadmap

- Streamable HTTP transport for the MCP server (current ships stdio only).
- `/incident` — bundles `/debug` + `/impact` into a postmortem-style writeup.
- Optional GitHub PR comment integration (Vercel Agent / Sentry Seer style).

See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT © Tal Ayash
