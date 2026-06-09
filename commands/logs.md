---
description: Tail or aggregate logs from the fleet's services in the configured log directory.
argument-hint: [service|all] [--grep TEXT] [--lines N] [--follow]
allowed-tools: Bash, Read
---

Show fleet logs.

Input: `$ARGUMENTS` — optional service name (default: all), plus optional
`--grep`, `--lines`, `--follow`.

Steps:
1. Locate `spring-fleet.config.json` (cwd, else suggest `/fleet-init`).
2. Run the aggregator, passing through the relevant flags:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/tail_logs.py" --config ./spring-fleet.config.json [--service NAME] [--grep TEXT] [--lines N] [--follow]
   ```
   - If a bare service name was given in `$ARGUMENTS`, pass it as `--service`.
   - `all` or empty → all services.
3. Present the tagged, aggregated output. For `--follow`, stream until interrupted.
