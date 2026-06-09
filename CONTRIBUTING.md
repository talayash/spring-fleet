# Contributing to spring-fleet

Thanks for your interest! spring-fleet aims to stay **generic and dependency-free**.

## Ground rules

- **Never commit a real `spring-fleet.config.json`.** It contains private paths,
  ports, and service names. Only `spring-fleet.config.example.json` (fake values)
  belongs in the repo. The real config is `.gitignore`d — keep it that way.
- **No company- or fleet-specific names** in plugin code, skills, commands, or
  fixtures. Use generic placeholders (`order-api`, `core-lib`, `${logDir}`,
  `<sessionId>`).
- **Standard library only.** Scripts must run on Python 3.8+ with no third-party
  packages, on Windows, macOS, and Linux.

## Project layout

```
.claude-plugin/   plugin + marketplace manifests
commands/         slash commands (thin — delegate to skills/agents/scripts)
skills/           reusable know-how (one folder per skill, SKILL.md inside)
agents/           subagents (fleet-explorer, log-correlator)
scripts/          deterministic Python (correlate_logs, scan_repos, tail_logs)
logback/          logging convention template
fixtures/         tiny fake fleet used by tests and the demo
tests/            unittest suite over the fixtures
docs/specs/       design spec
```

## Tests

```
python -m unittest discover -s tests -v
```

Add a test in `tests/` for any change to the scripts. Extend `fixtures/` rather
than relying on real data. Keep the design doc in `docs/specs/` updated when
behavior changes.

## Pull requests

- Keep commands thin; put logic in scripts (testable) or skills (instructional).
- Update the README command table and the schema if you add config fields.
- One focused change per PR.
