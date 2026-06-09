---
description: Scan a repos directory and generate (or update) spring-fleet.config.json for the fleet.
argument-hint: [reposRoot]
allowed-tools: Bash, Read, Write, Edit, Glob
---

Initialize or refresh the fleet config.

Input: `$ARGUMENTS` — optional repos root path. If omitted, ask the user (or use
an existing config's `reposRoot`).

Steps:
1. Determine the repos root. Confirm it exists.
2. Run the scanner to produce a draft:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/scan_repos.py" --root <reposRoot>
   ```
   It detects build tool, services vs shared libs, ports, and context paths.
3. The draft cannot infer two things mechanically — ask the user to confirm:
   - **traceKeys**: which MDC keys identify a request/session (e.g. `sessionId`).
   - **topology**: the entry services and the `[from, to]` call edges.
   Pre-fill from any existing `spring-fleet.config.json` if present.
4. Validate the result against `${CLAUDE_PLUGIN_ROOT}/spring-fleet.config.schema.json`
   (required fields, types).
5. Write `spring-fleet.config.json` to the user's project root. Remind them it is
   `.gitignore`d and must never be committed.
6. If logs are console-only or scattered, suggest the **spring-fleet-logging-setup**
   skill so `/debug` has stable per-service logs.
