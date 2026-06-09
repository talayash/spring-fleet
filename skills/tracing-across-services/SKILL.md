---
name: tracing-across-services
description: Use when you need to understand how a request, endpoint, or feature flows across multiple Spring Boot service repos and shared libraries - produces an ordered call chain with file:line citations, following inter-service proxy-lib calls.
---

# Tracing a Flow Across a Service Fleet

A single feature often crosses several repos: an entry controller calls
downstream services (usually through a generated proxy/client library), each of
which leans on shared libraries. This skill reconstructs that chain.

## Prerequisites

- A `spring-fleet.config.json` exists (else run `/fleet-init`). It provides the
  `reposRoot`, services, `sharedLibs`, `proxyLib`, and `topology`.

## Procedure

1. **Identify the target.** An endpoint (`POST /order-v1/reserve`), a controller,
   or a feature name. If ambiguous, locate candidate entry points first and
   confirm with the user.

2. **Dispatch the `fleet-explorer` agent** with the config path and the target.
   It knows the flow spans many repos, follows `proxyLib` client calls across
   service boundaries using `topology.edges`, and returns an ordered call chain
   with `file:line` citations and the shared-lib code each hop touches.

3. **Read the chain critically.** Confirm each hop's downstream target matches
   the topology. Where a hop is dynamic (reflection, event bus, conditional
   routing), the explorer marks it — resolve it by reading the dispatch site
   rather than guessing.

4. **Present the result.** Give the ordered chain entry → … → leaf, each step
   cited, plus a short summary of which services and shared-lib modules
   participate. Highlight the hops most relevant to the user's goal (e.g. where a
   change must be made, or where a failure could originate).

## Tips

- The `proxyLib` is the seam between services — grep it for the client class to
  find who calls whom when the topology is unclear.
- Contract changes ripple through the `proxyLib`: if a hop's request/response
  shape changes, the generated client (and every caller) is affected.
- For "what breaks if I change this shared-lib code?", trace consumers outward
  from the shared module instead of inward from an endpoint.
