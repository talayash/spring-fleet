---
name: spring-fleet-logging-setup
description: Use when fleet logs are console-only or scattered and cross-service correlation needs a stable location - installs a logback convention so every service writes <logDir>/<service>.log with OTel trace_id / span_id and legacy sessionId / requestId in the pattern.
---

# Fleet Logging Setup (logback convention)

Cross-service log correlation needs two things: every service writing to one
known directory, and trace keys (`trace_id`, `span_id`, `sessionId`, …) present
in each line. This skill installs a logback convention that guarantees both. It
is idempotent and opt-in per service.

## What trace keys to use (2026)

- **Primary: OpenTelemetry / Micrometer Observation.** Add the
  `spring-boot-starter-actuator` + `micrometer-tracing-bridge-otel` (or, on
  Spring Boot 4, the dedicated `spring-boot-starter-opentelemetry`). The W3C
  `traceparent` header is auto-propagated across HTTP/gRPC, and the
  Observation API automatically populates MDC keys `trace_id` (32-char hex)
  and `span_id` (16-char hex). These are the modern, framework-default keys.
- **Fallback / legacy: sessionId, requestId.** Keep them in the pattern for
  fleets that pre-date the Observation API or that propagate an application-
  level session id (auth, X-Request-Id) the user wants to correlate on.

## When to use

- `/debug` reports missing log files, or logs only go to the IDE console.
- Logs exist but lack a trace key, so correlation falls back to timestamps.

## Procedure

1. **Read the config** for `logDir` and `traceKeys`.

2. **Start from the template:** `${CLAUDE_PLUGIN_ROOT}/logback/logback-spring.xml`.
   For each service you want covered, place it at
   `<service-repo>/src/main/resources/logback-spring.xml` (or merge its appender
   + pattern into the existing one), then customize three things:
   - `SERVICE_NAME` → the service's `name` from the config (used as the log file
     base name, so `/debug` can find it).
   - The `%X{...}` keys in `FLEET_PATTERN` → one per entry in `traceKeys`.
   - `SPRING_FLEET_LOG_DIR` → the config `logDir`, or set that env var when
     launching the service.

3. **Ensure the trace keys are in MDC.** A pattern can only print `%X{trace_id}`
   if something put `trace_id` into the MDC.
   - **trace_id / span_id**: come for free once Micrometer Tracing or the OTel
     starter is on the classpath — Spring Boot wires the Observation API which
     populates MDC automatically. Verify by hitting any endpoint and tailing the
     log; the keys should already be there.
   - **sessionId / requestId (legacy)**: usually require a filter/interceptor
     that reads the incoming header (or generates the id), calls `MDC.put(...)`,
     and clears it in a `finally`. If propagation across services is missing,
     the same id must be forwarded as a header on outbound proxy-lib calls.
     (Modern fleets should rely on W3C `traceparent` instead and treat
     sessionId as a business id, not a correlation id.)

4. **Verify.** Run the service, exercise one request, then:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/tail_logs.py" \
     --config ./spring-fleet.config.json --service <name> --lines 20
   ```
   Confirm lines land in `<logDir>/<service>.log` and carry the trace key.

## Notes

- Keep the **same pattern** across services so timestamps sort cleanly when
  merged. The template's `yyyy-MM-dd HH:mm:ss.SSS` prefix is what the correlator
  parses.
- The template also keeps a `CONSOLE` appender, so IDE output is unchanged.
- For services you will not modify, prefer the (future) `/run` tee approach
  instead of editing their logback config.
