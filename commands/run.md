---
description: Plan or launch the fleet locally — compose-first per service, with stdout tee'd to logDir so /debug can read it later.
argument-hint: [service|all] [--execute]
allowed-tools: Bash, Read
---

Plan or launch the Spring Boot fleet locally.

Input: `$ARGUMENTS` — optional bare service name (default: all), plus optional
`--execute` to actually start the processes (default: print the plan only).

Per-service resolution (from `services[].stack` produced by `/fleet-init`):
- `dockerCompose=true` → `docker compose up -d` in the repo (Spring Boot
  Docker Compose support discovers `compose.yaml` and wires `@ServiceConnection`
  beans automatically — the modern local-dev default).
- otherwise → `gradle bootRun` or `mvn spring-boot:run`, with stdout/stderr
  tee'd to `<logDir>/<service>.log` so `/debug` and `/logs` work without any
  logback changes.

Steps:
1. Locate `spring-fleet.config.json` (cwd, else suggest `/fleet-init`).
2. **Plan first** (no `--execute`):
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/run_fleet.py" --config ./spring-fleet.config.json [--service NAME]
   ```
   Show the JSON plan. Each entry has: `service`, `cwd`, `mode` (compose / gradle / maven),
   `command`, `logPath`, and `tee` (whether stdout will be redirected).
3. **Confirm with the user** before executing — launching processes is not
   reversible and may bind to fleet ports already in use.
4. **Execute** with `--execute` when the user approves:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/run_fleet.py" --config ./spring-fleet.config.json --execute [--service NAME]
   ```
   Each spawned process is detached. Stop them with the usual OS tools (or
   `docker compose down` for compose-managed services).
5. After launch, suggest `/logs --follow` (or `tail_service_log` MCP tool)
   to confirm services are healthy.
