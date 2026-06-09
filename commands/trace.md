---
description: Trace how an endpoint or feature flows across the fleet's service repos and shared libraries, with file:line citations.
argument-hint: <endpoint | controller | feature>
allowed-tools: Bash, Read, Grep, Glob, Task
---

Trace a flow across the Spring Boot fleet.

Input: `$ARGUMENTS` — an endpoint (`POST /order-v1/reserve`), a controller, or a
feature name.

Steps:
1. Locate `spring-fleet.config.json` (cwd, else suggest `/fleet-init`).
2. Use the **tracing-across-services** skill.
3. Dispatch the **fleet-explorer** agent with the config path and `$ARGUMENTS`
   to produce the ordered call chain across repos, following proxy-lib hops and
   noting shared-lib code touched.
4. Present the chain entry → … → leaf, each step cited `repo/File.java:line`,
   plus a short summary of participating services and shared-lib modules.
