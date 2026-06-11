---
name: debugging-runtime-logs
description: Use when debugging a runtime failure in a locally-running fleet of Spring Boot microservices - correlates logs across services by a trace key, reconstructs the cross-service timeline, isolates the failing hop, and maps it back to source.
---

# Debugging Runtime Logs Across a Service Fleet

When something breaks in a multi-service dev run, the symptom usually appears in
one service while the cause lives in another. This skill correlates logs across
the whole fleet and ties the failure back to code.

## Prerequisites

- A `spring-fleet.config.json` exists (else run `/fleet-init`).
- Services write to the configured `logDir` (see the `spring-fleet-logging-setup`
  skill if logs are scattered or console-only).

## Procedure

1. **Get a correlation handle.** Best case: an OTel `trace_id` (32-char hex)
   from the user's APM dashboard or a `traceparent` header, or a legacy
   `sessionId` / `X-Request-Id` from a failed request. Otherwise, start from
   the error message/stack the user pasted — extract a key from a nearby log
   line, preferring `trace_id` over `sessionId`.

2. **Dispatch the `log-correlator` agent** with the config path and the trace
   value (or error snippet). It runs `scripts/correlate_logs.py` and returns one
   chronological cross-service timeline plus a failure-origin analysis.

   Run directly if you prefer:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/correlate_logs.py" \
     --config ./spring-fleet.config.json --value <traceValue>
   ```

3. **Read the timeline as a story.** Follow the request hop by hop. The first
   ERROR/exception in time order is the likely origin; everything after it is
   usually propagation. Watch the time gaps — a long gap before an error often
   means a timeout.

4. **Map the origin to code.** Take the failing service + class from the log and
   open the source. For a cross-service cause, dispatch the `fleet-explorer`
   agent (or use the `tracing-across-services` skill) to confirm the call path.

5. **Report.** State: what the user did, the cross-service timeline, the failure
   origin (service + `file:line`), how it surfaced upstream, and a
   **ROOT-CAUSE HYPOTHESIS** block — what the fault is, where in code to fix
   it, why the timeline supports that, your confidence, and a concrete
   suggested fix (snippet or behavior). Always include alternatives the
   evidence does not rule out. Call out any service with **no log file** —
   a missing log can hide the real cause.

## Fallbacks

- **No trace key in logs:** correlate by timestamp window + endpoint and say so.
- **Console-only logs:** point the user at `spring-fleet-logging-setup` to get
  stable per-service log files (or, later, the `/run` tee command).
- **Empty result:** the value may be wrong, or the request never reached the
  fleet. Widen with `/logs --grep` around the timeframe.
