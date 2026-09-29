---
name: doctor
description: Check fleet configuration, repository paths, logs, port conflicts and required executables.
argument-hint: [--config PATH]
allowed-tools: Bash, Read
---

Run read-only diagnostics before debugging or launching the fleet:

```text
python "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --config ./spring-fleet.config.json --format json
```

If `$ARGUMENTS` specifies `--config PATH`, use that path. Otherwise use the
project's `spring-fleet.config.json`. Present errors first, then warnings,
with the suggested fix for each. Missing logs are warnings because services
may not have started yet. Exit code 1 means errors were found; 0 means no
errors. Do not install tools, edit configuration, or start services as part
of this diagnostic command.

## Outside Claude Code

- `${CLAUDE_PLUGIN_ROOT}` is the spring-fleet plugin root. Claude Code fills it in; in Codex it is the folder two directories above this SKILL.md.
- `$ARGUMENTS` is the text the user supplied with the request.
- spring-fleet MCP tools: pass `config_path` (absolute path of the project's `spring-fleet.config.json`). Codex starts the server outside the project, so it cannot find the config on its own.
