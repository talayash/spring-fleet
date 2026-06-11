#!/usr/bin/env python3
"""Aggregate / tail fleet logs from the configured log directory.

Prints the last N lines of each service log (optionally one service, optionally
filtered by a substring), tagged by service. With --follow it polls for new
lines across all selected logs.

K8s fallback: if a service's file log is missing and the config has a `k8s`
block, this script can shell out to `kubectl logs` for that service. Enable
with --k8s or by setting the env var SPRING_FLEET_K8S=1. mirrord users get
this automatically — services running in-cluster log to stdout, and kubectl
reads them.

Dependency-free (Python 3 stdlib only). Cross-platform.

Usage:
    python tail_logs.py --config spring-fleet.config.json
    python tail_logs.py --config <cfg> --service payment --lines 100
    python tail_logs.py --config <cfg> --grep ERROR --follow
    python tail_logs.py --config <cfg> --service inventory --k8s   # fallback
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def selected_files(config, service_filter):
    log_dir = config["logDir"]
    out = []
    for svc in config.get("services", []):
        name = svc["name"]
        if service_filter and name != service_filter:
            continue
        log_file = svc.get("logFile", "{}.log".format(name))
        out.append((name, os.path.join(log_dir, log_file)))
    return out


def tail_lines(path, n):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.readlines()[-n:]


def matches(line, grep):
    return grep is None or grep in line


def kubectl_logs(config, service, lines):
    """Return the last N lines from kubectl for one service, or None if no
    `k8s` block is configured. Failures are surfaced as a stderr note rather
    than an exception so the caller can keep going on other services."""
    k8s = (config.get("k8s") or {})
    if not k8s:
        return None
    selector_tpl = k8s.get("podSelectorTemplate") or "app.kubernetes.io/name={service}"
    selector = selector_tpl.format(service=service)
    cmd = ["kubectl"]
    if k8s.get("context"):
        cmd += ["--context", k8s["context"]]
    if k8s.get("namespace"):
        cmd += ["-n", k8s["namespace"]]
    cmd += ["logs", "-l", selector, "--tail", str(lines), "--all-containers=true"]
    try:
        import subprocess  # local import keeps stdlib-only invariant explicit
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("# (kubectl logs failed for '{}': {})".format(service, exc), file=sys.stderr)
        return []
    if result.returncode != 0:
        print("# (kubectl logs rc={} for '{}': {})".format(
            result.returncode, service, result.stderr.strip()), file=sys.stderr)
        return []
    return result.stdout.splitlines()


def print_static(files, lines, grep, config=None, k8s_fallback=False):
    any_output = False
    for name, path in files:
        if os.path.isfile(path):
            for line in tail_lines(path, lines):
                line = line.rstrip("\n")
                if matches(line, grep):
                    print("[{}] {}".format(name, line))
                    any_output = True
            continue

        if k8s_fallback and config is not None:
            k8s_lines = kubectl_logs(config, name, lines)
            if k8s_lines is None:
                print("# (no log file for '{}': {})".format(name, path), file=sys.stderr)
                continue
            for raw in k8s_lines:
                line = raw.rstrip("\n")
                if matches(line, grep):
                    print("[{}/k8s] {}".format(name, line))
                    any_output = True
            continue

        print("# (no log file for '{}': {})".format(name, path), file=sys.stderr)
    if not any_output:
        print("# no matching log lines")


def follow(files, grep):
    # Seek to current end of each file, then poll for appended lines.
    handles = {}
    for name, path in files:
        if os.path.isfile(path):
            fh = open(path, "r", encoding="utf-8", errors="replace")
            fh.seek(0, os.SEEK_END)
            handles[name] = fh
    try:
        while True:
            wrote = False
            for name, fh in handles.items():
                line = fh.readline()
                while line:
                    line = line.rstrip("\n")
                    if matches(line, grep):
                        print("[{}] {}".format(name, line))
                        wrote = True
                    line = fh.readline()
            if not wrote:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for fh in handles.values():
            fh.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tail/aggregate fleet logs.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--service", help="Limit to a single service name")
    ap.add_argument("--grep", help="Only show lines containing this substring")
    ap.add_argument("--lines", type=int, default=50, help="Lines per service for static output")
    ap.add_argument("--follow", action="store_true", help="Stream new lines as they arrive")
    ap.add_argument("--k8s", action="store_true",
                    help="If a file log is missing and config has a 'k8s' block, fall back to `kubectl logs`.")
    args = ap.parse_args(argv)
    if os.environ.get("SPRING_FLEET_K8S") == "1":
        args.k8s = True

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print("ERROR: config not found: {}".format(args.config), file=sys.stderr)
        return 2

    files = selected_files(config, args.service)
    if not files:
        print("# no services matched", file=sys.stderr)
        return 1

    if args.follow:
        print_static(files, args.lines, args.grep, config=config, k8s_fallback=args.k8s)
        follow(files, args.grep)
    else:
        print_static(files, args.lines, args.grep, config=config, k8s_fallback=args.k8s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
