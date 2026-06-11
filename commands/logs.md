---
description: Tail or aggregate logs from the fleet's services — file-based when present, kubectl-based when the config has a k8s block (for mirrord / in-cluster runs).
argument-hint: [service|all] [--grep TEXT] [--lines N] [--follow] [--k8s]
allowed-tools: Bash, Read
---

Show fleet logs.

Input: `$ARGUMENTS` — optional service name (default: all), plus optional
`--grep`, `--lines`, `--follow`, `--k8s`.

Steps:
1. Locate `spring-fleet.config.json` (cwd, else suggest `/fleet-init`).
2. Run the aggregator, passing through the relevant flags:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/tail_logs.py" --config ./spring-fleet.config.json [--service NAME] [--grep TEXT] [--lines N] [--follow] [--k8s]
   ```
   - If a bare service name was given in `$ARGUMENTS`, pass it as `--service`.
   - `all` or empty → all services.
   - `--k8s` falls back to `kubectl logs -l <podSelectorTemplate>` for any
     service whose file-based log is missing. Requires a `k8s` block in the
     config (namespace + optional context + podSelectorTemplate). mirrord
     users get this for free: the local service runs against the shared
     cluster, the other services log to stdout in-cluster, kubectl reads
     them.
3. Present the tagged, aggregated output (`[service/k8s]` for kubectl-sourced
   lines). For `--follow`, stream until interrupted.
