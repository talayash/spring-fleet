#!/usr/bin/env python3
"""Read-only fleet diagnostics. Relative paths follow the existing CLI's cwd semantics."""
import argparse
import json
import os
import shutil

import run_fleet
from validation import validate

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "spring-fleet.config.schema.json")


def diagnose(config):
    findings = []

    def add(level, code, message, fix):
        findings.append({"level": level, "code": code, "message": message, "fix": fix})

    def report():
        return {"ok": not any(f["level"] == "error" for f in findings),
                "findings": findings,
                "errors": sum(f["level"] == "error" for f in findings),
                "warnings": sum(f["level"] == "warning" for f in findings)}

    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    errors = validate(config, schema)
    for error in errors:
        add("error", "config.invalid", error, "Update the field to match spring-fleet.config.schema.json.")
    if errors:
        return report()
    for field in ("reposRoot", "logDir"):
        if not config[field].strip() or not os.path.isdir(config[field]):
            add("error" if field == "reposRoot" else "warning", "path.missing",
                "{} directory does not exist: {}".format(field, config[field]),
                "Set {} to an existing directory (relative paths use the working directory).".format(field))
    if not config.get("traceKeys"):
        add("warning", "trace.keys", "No traceKeys configured.", "Configure MDC keys used in your logs for exact matching.")
    names, ports, required = set(), {}, set()
    for svc in config["services"]:
        name = svc["name"]
        if not name.strip() or name in names:
            add("error", "service.name", "Empty or duplicate service name: {!r}".format(name),
                "Give each service a unique, non-empty name.")
        names.add(name)
        port = svc.get("port")
        if port is not None:
            if not 0 <= port <= 65535:
                add("error", "port.invalid", "{} has invalid port {}".format(name, port), "Use a port from 0 to 65535.")
            elif port and port in ports:
                add("error", "port.duplicate", "{} and {} use port {}".format(name, ports[port], port),
                    "Assign distinct local ports or run the services separately.")
            ports[port] = name
        repo = os.path.join(config["reposRoot"], svc["path"])
        if not svc["path"].strip() or not os.path.isdir(repo):
            add("error", "repo.missing", "{} repository is missing: {}".format(name, repo),
                "Clone the repository or correct its path.")
        log = os.path.join(config["logDir"], svc.get("logFile", name + ".log"))
        if not os.path.isfile(log):
            add("warning", "log.missing", "{} log is missing: {}".format(name, log),
                "Start the service with file logging or configure logFile/logDir.")
        step = run_fleet.plan_service(svc, config)
        required.add(step["command"][0])
        if step["mode"] != "compose":
            required.add("java")
    for lib in config.get("sharedLibs", []):
        path = os.path.join(config["reposRoot"], lib["path"])
        if not lib["path"].strip() or not os.path.isdir(path):
            add("error", "repo.missing", "Shared library {} is missing: {}".format(lib["name"], path),
                "Clone the shared library or correct its path.")
    if config.get("k8s"):
        required.add("kubectl")
    for executable in sorted(required):
        if shutil.which(executable) is None:
            add("error", "executable.missing", "{} is not on PATH.".format(executable),
                "Install {} and add it to PATH for the current /run or /logs command.".format(executable))
    topology = config.get("topology", {})
    referenced = set(topology.get("entry", []))
    for edge in topology.get("edges", []):
        referenced.update(edge)
    for name in sorted(referenced - names):
        add("error", "topology.unknown", "Topology references unknown service: {}".format(name),
            "Add the service or correct the topology reference.")
    return report()


def check_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return diagnose(json.load(fh))
    except (OSError, ValueError) as exc:
        return {"ok": False, "errors": 1, "warnings": 0, "findings": [{
            "level": "error", "code": "config.read", "message": str(exc),
            "fix": "Run /fleet-init or correct the config path and JSON syntax."}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="spring-fleet.config.json")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)
    result = check_file(args.config)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        for finding in result["findings"]:
            print("{level}: {message}\n  Fix: {fix}".format(**finding))
        print("Fleet doctor: {} error(s), {} warning(s).".format(result["errors"], result["warnings"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
