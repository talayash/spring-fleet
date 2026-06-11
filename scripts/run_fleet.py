#!/usr/bin/env python3
"""Plan how to launch the fleet locally and (optionally) execute that plan.

Resolution order *per service*:
    1. `stack.dockerCompose=true`           → `docker compose up -d` in the repo
    2. otherwise the configured buildTool   → `gradle bootRun` / `mvn spring-boot:run`,
       with stdout teed to <logDir>/<service>.log so /debug can read it later.

By default this script only *plans* (prints the launch commands as JSON) so the
caller can inspect them. Pass --execute to actually run them; in that mode each
service is started as a background process and its stdout is tee'd to its
service log file. Pass --service to limit to one service.

Dependency-free (Python 3 stdlib only). Cross-platform.

Usage:
    python run_fleet.py --config spring-fleet.config.json                 # plan
    python run_fleet.py --config <cfg> --service order                    # plan one
    python run_fleet.py --config <cfg> --execute                          # run all
    python run_fleet.py --config <cfg> --service inventory --execute      # run one
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def compose_file_in(repo_path):
    for fn in ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"):
        p = os.path.join(repo_path, fn)
        if os.path.isfile(p):
            return p
    return None


def plan_service(svc, config):
    """Return a dict describing how to launch one service. Does not execute."""
    repos_root = config.get("reposRoot", "")
    log_dir = config.get("logDir", "")
    name = svc["name"]
    repo_path = os.path.join(repos_root, svc.get("path", name))
    log_file = svc.get("logFile") or (name + ".log")
    log_path = os.path.join(log_dir, log_file)

    stack = svc.get("stack") or {}
    if stack.get("dockerCompose") and compose_file_in(repo_path):
        return {
            "service": name,
            "cwd": repo_path,
            "mode": "compose",
            "command": ["docker", "compose", "up", "-d"],
            "logPath": log_path,
            "tee": False,
            "note": "Service ships a compose.yaml — `docker compose logs -f` for output.",
        }

    build_tool = (config.get("buildTool") or {}).get("type", "gradle")
    run_task = (config.get("buildTool") or {}).get("run") or (
        "bootRun" if build_tool == "gradle" else "spring-boot:run"
    )
    if build_tool == "gradle":
        cmd = ["gradle", run_task]
    else:
        cmd = ["mvn", run_task]
    return {
        "service": name,
        "cwd": repo_path,
        "mode": build_tool,
        "command": cmd,
        "logPath": log_path,
        "tee": True,
        "note": "stdout/stderr will be tee'd to logPath so /debug can read it.",
    }


def plan_fleet(config, service_filter=None):
    services = config.get("services", [])
    if service_filter:
        services = [s for s in services if s["name"] == service_filter]
    return [plan_service(s, config) for s in services]


def _ensure_log_dir(log_path):
    parent = os.path.dirname(log_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def execute(plan):
    """Spawn each planned command as a background process, tee'ing stdout to
    logPath when requested. Returns a list of (service, pid, log_path, mode)
    tuples. Caller is responsible for stopping the processes (this script
    intentionally does not babysit — the caller's editor will."""
    started = []
    for step in plan:
        _ensure_log_dir(step["logPath"])
        if not os.path.isdir(step["cwd"]):
            print("# (skip {}: cwd not found {})".format(step["service"], step["cwd"]),
                  file=sys.stderr)
            continue
        if step["tee"]:
            log_fh = open(step["logPath"], "ab", buffering=0)
            proc = subprocess.Popen(
                step["command"], cwd=step["cwd"],
                stdout=log_fh, stderr=subprocess.STDOUT,
            )
        else:
            proc = subprocess.Popen(step["command"], cwd=step["cwd"])
        started.append({
            "service": step["service"], "pid": proc.pid,
            "logPath": step["logPath"], "mode": step["mode"],
            "command": " ".join(shlex.quote(c) for c in step["command"]),
        })
    return started


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan/launch the Spring Boot fleet locally.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--service", help="Limit to a single service name.")
    ap.add_argument("--execute", action="store_true",
                    help="Actually start the planned processes (default: print plan only).")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print("ERROR: config not found: {}".format(args.config), file=sys.stderr)
        return 2

    plan = plan_fleet(cfg, args.service)
    if not plan:
        print("# no services matched", file=sys.stderr)
        return 1

    if not args.execute:
        print(json.dumps({"plan": plan}, indent=2))
        return 0

    started = execute(plan)
    print(json.dumps({"started": started}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
