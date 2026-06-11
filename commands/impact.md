---
description: Find every consumer of a shared-lib symbol, file, or API across the fleet's service repos — outputs an impact list with file:line citations.
argument-hint: <symbol | file | endpoint>
allowed-tools: Bash, Read, Grep, Glob, Task
---

Compute the cross-fleet blast radius of a change.

Input: `$ARGUMENTS` — one of:
  - a **symbol** (class, method, function, constant) from a shared lib
    — e.g. `OrderEntity`, `core-lib.util.RetryPolicy.retry`
  - a **file** path in a shared lib — e.g. `core-lib/src/main/java/.../RetryPolicy.java`
  - a **published API endpoint** owned by a service — e.g. `POST /payment-v1/charge`

Steps:
1. Locate `spring-fleet.config.json` (cwd, else suggest `/fleet-init`). Read
   `reposRoot`, `services`, `sharedLibs`, and `proxyLib` — these constrain
   where consumers can live.
2. Use the **tracing-across-services** skill (impact is the inverse of trace:
   you start from a shared symbol and fan *outward* through every consumer).
3. Dispatch the **impact-analyzer** agent with the config path and
   `$ARGUMENTS`. It searches every service repo (and the proxy-lib, if any)
   for usages and returns a grouped impact list.
4. Present a per-service consumer count plus the citation list. Highlight any
   service that calls the symbol in a hot path (controller, scheduler,
   event handler) and any consumer that touches a public API or persisted
   data shape — those carry the highest change cost.
