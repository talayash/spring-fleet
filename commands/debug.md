---
description: Debug a runtime failure across the fleet by correlating logs on an OTel trace_id / sessionId / requestId — or by reading a pasted Grafana / stack-trace screenshot — and mapping the failure back to source.
argument-hint: <trace_id | sessionId | "error snippet" | (or paste a screenshot)>
allowed-tools: Bash, Read, Grep, Glob, Task
---

Debug a cross-service runtime issue in the Spring Boot fleet.

Input: `$ARGUMENTS` — one of:
  - an OTel **trace_id** (32 lowercase hex chars) — preferred, modern path.
  - a legacy **sessionId** / **requestId** — fallback for older fleets.
  - a **pasted error or stack trace** — agent extracts a trace key from
    nearby log lines.
  - a **pasted screenshot** of a Grafana / Tempo / Jaeger / Kibana panel
    or an IDE / terminal stack — the model reads it directly (Claude is
    multimodal); extract the trace_id or service + timestamp from the image
    and use that as the correlation handle.

Steps:
1. Locate `spring-fleet.config.json` (cwd, else ask the user / suggest `/fleet-init`).
2. Use the **debugging-runtime-logs** skill.
3. **If the input is an image:** read it first. Look for a `trace_id` /
   `traceparent` value, a sessionId, a service name + timestamp window, or an
   exception class + message. Use whichever you find as the correlation
   handle (prefer trace_id). Quote what you extracted so the user can sanity-check it.
4. Dispatch the **log-correlator** agent with the config path and the
   resolved handle to build the cross-service timeline and isolate the failure
   origin. Prefer the `correlate_by_trace` MCP tool when available.
5. If the cause is cross-service, dispatch **fleet-explorer** to confirm the
   call path and map the failing hop to `file:line`.
6. Report: what happened, the timeline, failure origin (service + `file:line`),
   how it surfaced upstream, the **ROOT-CAUSE HYPOTHESIS** block from the
   log-correlator (WHAT / WHERE / WHY / CONFIDENCE / SUGGESTED FIX), and any
   service missing a log file.
