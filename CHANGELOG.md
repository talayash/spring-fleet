# Changelog

All notable changes to **spring-fleet** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Streamable HTTP transport for the MCP server (current ships stdio only).
- An `/incident` command bundling `/debug` + `/impact` for postmortem-style writeups.
- Optional GitHub PR comment integration (Vercel Agent / Sentry Seer style).

## [0.2.0] — 2026-06-11

### Added — MCP-first, OTel-native, AI-era
- **MCP server** (`scripts/mcp_server.py`, pure stdlib JSON-RPC over stdio) exposing six typed tools — `list_services`, `get_topology`, `correlate_by_trace`, `tail_service_log`, `scan_repos_root`, `find_service_log_path`. Wired via `.mcp.json`.
- **OpenTelemetry trace_id / span_id as first-class trace keys.** Default `traceKeys` is now `["trace_id","span_id","sessionId","requestId"]`; logback template emits all four; correlator recognizes W3C 32-hex trace IDs and 16-hex span IDs.
- **`/impact <symbol|file|endpoint>`** — cross-fleet blast-radius analysis with a new `impact-analyzer` agent. Classifies consumers as direct / proxyLib-mediated / test-only and flags contract-critical call sites.
- **`/run [service] [--execute]`** — compose-first local fleet launch (Spring Boot Docker Compose support) with gradle/maven fallback. `scripts/run_fleet.py` is plan-only by default; `--execute` actually starts processes and tees stdout to `<logDir>/<service>.log`.
- **SessionStart hook** (`hooks/session_start.py`) injects fleet topology into Claude's context at session start so the model doesn't re-read the config every turn.
- **SubagentStop hook** (`hooks/subagent_stop.py`) persists fleet-agent output to `<logDir>/.spring-fleet-handoff.log` for handoff between specialists.
- **Status-line script** (`hooks/statusline.py`) summarises `[fleet: N svc · otel:M/N · entry:<svc>]`.
- **`fleet-narrator` output style** for on-call-writeup-shaped trace/debug reports.
- **Spring Boot 4 / Java 21+ / virtual threads / GraalVM native / `compose.yaml` / Testcontainers / OpenTelemetry / Spring AI MCP server** detection in `scan_repos.py`, surfaced under each `services[].stack`.
- **Backstage `catalog-info.yaml` ingestion** — owner / system / lifecycle lifted into `services[].backstage`; `dependsOn: component:*` folded into `topology.edges`; components with no inbound dependency promoted into `topology.entry`.
- **`/debug` accepts pasted screenshots** (Grafana / Tempo / Jaeger / Kibana / stack-trace images). The log-correlator agent extracts the trace_id from the image and quotes it.
- **Code-grounded RCA narrative.** `log-correlator` now emits a required `ROOT-CAUSE HYPOTHESIS` block (WHAT / WHERE / WHY / CONFIDENCE / SUGGESTED FIX / ALTERNATIVES) — the OSS, repo-aware analogue of Sentry Seer / Datadog Bits.
- **K8s mode for `/logs`** — `--k8s` flag (or `SPRING_FLEET_K8S=1`) falls back to `kubectl logs -l <selector>` when a file-based log is missing. Schema gains a top-level `k8s` block. mirrord-friendly by design.
- **`federating-mcp-servers` skill** — workflow for plugging each fleet service's own Spring AI MCP server into `.mcp.json` so spring-fleet becomes a meta-MCP over the user's fleet.
- **CI** — GitHub Actions workflow runs the unittest suite on every push.
- Marketplace keywords refreshed: `observability`, `opentelemetry`, `mcp`, `spring-ai`, `backstage`, `spring-boot-4`.

### Changed
- Default `traceKeys` is OTel-first.
- Logback template embeds `trace_id` / `span_id` as well as `sessionId` / `requestId`.
- `log-correlator` and `debugging-runtime-logs` skill prefer `trace_id`, prefer the `correlate_by_trace` MCP tool over CLI, and require the code-grounded RCA hypothesis block.
- `scan_repos.py` derives `topology` from Backstage when available instead of always emitting an empty placeholder.
- Schema gains `services[].stack`, `services[].backstage`, top-level `k8s`.

### Tests
- 48 tests, up from 11. Covers MCP protocol + every tool, both hooks, the run planner, OTel/legacy correlation, stack detection, Backstage ingestion, status line.

## [0.1.1] — 2026-06-09

## [0.1.1] — 2026-06-09

### Fixed
- `correlate_logs.py` text output no longer duplicates the timestamp (the raw log
  line already begins with one). JSON output was unaffected. Added a regression test.

## [0.1.0] — 2026-06-09

First public release.

### Added
- **`/trace <endpoint|feature>`** — cross-repo call chain with `file:line` citations, following inter-service proxy-lib hops (`fleet-explorer` agent).
- **`/debug <sessionId|error>`** — correlate logs across every service by a trace key into one chronological timeline, isolate the failing hop, and map it back to source (`log-correlator` agent).
- **`/logs [service|all]`** — tail/aggregate fleet logs (`--grep`, `--lines`, `--follow`).
- **`/fleet-init [reposRoot]`** — scan repos and generate `spring-fleet.config.json` (auto-detects build tool, services vs shared libs, ports, context paths).
- **Skills**: `tracing-across-services`, `debugging-runtime-logs`, `spring-fleet-logging-setup`.
- **logback convention** template so every service writes `<logDir>/<service>.log` with trace keys in the pattern.
- **Config**: JSON schema (`spring-fleet.config.schema.json`) + example (`spring-fleet.config.example.json`).
- Dependency-free Python 3 scripts: `correlate_logs.py`, `scan_repos.py`, `tail_logs.py`.
- 11-test `unittest` suite over a bundled fixture fleet.
- Plugin + marketplace manifests, logo, `/debug` demo graphic, README, CONTRIBUTING, MIT license.

### Security / privacy
- Real `spring-fleet.config.json` is git-ignored by default; the plugin contains no environment-specific paths, ports, or service names.

[Unreleased]: https://github.com/talayash/spring-fleet/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/talayash/spring-fleet/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/talayash/spring-fleet/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/talayash/spring-fleet/releases/tag/v0.1.0
