# Changelog

All notable changes to **spring-fleet** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- `/run` — launch services and tee stdout to `logDir` (for services that can't be reconfigured).
- `/impact <symbol|file>` — find every consumer of shared-lib code across the fleet.
- Optional SessionStart hook to load fleet topology into context automatically.

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

[Unreleased]: https://github.com/talayash/spring-fleet/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/talayash/spring-fleet/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/talayash/spring-fleet/releases/tag/v0.1.0
