---
description: Debug a runtime failure across the fleet by correlating logs on a trace key (sessionId, requestId) and mapping the failure back to source.
argument-hint: <sessionId | requestId | "error snippet">
allowed-tools: Bash, Read, Grep, Glob, Task
---

Debug a cross-service runtime issue in the Spring Boot fleet.

Input: `$ARGUMENTS` — a trace value (e.g. a `sessionId`) or a pasted error/stack.

Steps:
1. Locate `spring-fleet.config.json` (cwd, else ask the user / suggest `/fleet-init`).
2. Use the **debugging-runtime-logs** skill.
3. Dispatch the **log-correlator** agent with the config path and `$ARGUMENTS`
   to build the cross-service timeline and isolate the failure origin.
4. If the cause is cross-service, dispatch **fleet-explorer** to confirm the call
   path and map the failing hop to `file:line`.
5. Report: what happened, the timeline, failure origin (service + `file:line`),
   how it surfaced upstream, likely cause, and a concrete fix. Note any service
   missing a log file.
