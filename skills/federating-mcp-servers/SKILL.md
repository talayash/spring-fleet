---
name: federating-mcp-servers
description: Use when a fleet service ships its own Spring AI MCP server - explains how to discover those servers from the spring-fleet config and federate them alongside the spring-fleet MCP tools so the agent has one unified tool surface across the fleet.
---

# Federating fleet-owned MCP servers

Spring AI 1.1 ships `spring-ai-starter-mcp-server-{webmvc,webflux,servlet}`,
so any Spring Boot service in the fleet can expose `@Tool`-annotated beans
(and selected actuator endpoints) as MCP tools. When that happens, the
right move is not to re-implement those tools inside spring-fleet — it is to
**federate** them: register each service's MCP server alongside the
spring-fleet MCP server so Claude sees one unified tool surface across the
whole fleet.

## When to use

`/fleet-init` records `services[].stack.springAiMcpServer = true` for any
repo whose build declares `spring-ai-starter-mcp-server`. That flag is your
signal.

## Procedure

1. **Discover the candidates.** Iterate `services[]` and collect every one
   with `stack.springAiMcpServer == true`. For each, you need:
   - the transport URL (Streamable HTTP is the recommended 2026 transport;
     SSE is being sunset). The default Spring AI MCP server endpoint is
     `http://<host>:<port><contextPath>/mcp`. Confirm from each service's
     `application.properties` if `spring.ai.mcp.server.base-path` is set.
   - any required auth header (often a bearer token from the team's IDP).

2. **Register them in the user's MCP client config.** Claude Code reads
   `.mcp.json`. Append one entry per federated server next to the existing
   `spring-fleet` entry, e.g.:
   ```json
   {
     "mcpServers": {
       "spring-fleet":      { "command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py"] },
       "fleet-inventory":   { "transport": "streamable-http", "url": "http://localhost:8083/inventory-v1/mcp" },
       "fleet-order":       { "transport": "streamable-http", "url": "http://localhost:8081/order-v1/mcp" }
     }
   }
   ```
   Always prefix the federated server name with `fleet-` so the namespace is
   readable and collisions with non-fleet MCP servers are unlikely.

3. **Confirm with the user before editing `.mcp.json`.** Federation changes
   the agent's effective tool surface and the data it can read — that's a
   shared-state change worth a quick confirmation. Show the proposed diff.

4. **Verify reachable.** After registration, ask Claude to list MCP tools
   (the IDE surfaces this) and confirm the federated tools appear with
   their service-prefixed names.

5. **Re-federate when topology changes.** Re-run `/fleet-init` (or just
   `scan_repos_root` via the MCP tool) whenever a service adopts or drops
   `spring-ai-starter-mcp-server`. The `stack.springAiMcpServer` flag is
   the source of truth.

## Notes

- The federated servers run alongside the user's services, so they only
  serve when those services are running. spring-fleet's own MCP server
  always works regardless of fleet runtime state.
- Authentication is per-service. If the team uses an OIDC-protected MCP
  endpoint, the `.mcp.json` entry needs an `Authorization` header — store
  the token in the user's secret manager and reference it through
  environment variables, never inline.
- Tool name collisions across federated servers are resolved by the MCP
  client by prefixing with the server name (e.g.
  `fleet-inventory.search_inventory`).
