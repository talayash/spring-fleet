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
3. The draft pre-fills `traceKeys` with the modern OTel-first default
   (`trace_id`, `span_id`, `sessionId`, `requestId`) and seeds `topology`
   from any Backstage `catalog-info.yaml` files it finds at repo roots
   (each `dependsOn: component:*` becomes a `[from, to]` edge; components
   with no inbound dependency become entries). Ask the user to confirm:
   - **traceKeys**: which MDC keys actually identify a request/session in
     their fleet (drop entries that are never emitted).
   - **topology**: confirm or amend the Backstage-derived entries and edges;
     for fleets without Backstage, fill these in manually.
   Pre-fill from any existing `spring-fleet.config.json` if present.
4. Validate the result against `${CLAUDE_PLUGIN_ROOT}/spring-fleet.config.schema.json`
   (required fields, types).
5. Write `spring-fleet.config.json` to the user's project root. Remind them it is
   `.gitignore`d and must never be committed.
6. If logs are console-only or scattered, suggest the **spring-fleet-logging-setup**
   skill so `/debug` has stable per-service logs.
