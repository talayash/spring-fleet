#!/usr/bin/env python3
"""Aggregate / tail fleet logs from the configured log directory.

Prints the last N lines of each service log (optionally one service, optionally
filtered by a substring), tagged by service. With --follow it polls for new
lines across all selected logs.

Dependency-free (Python 3 stdlib only). Cross-platform.

Usage:
    python tail_logs.py --config spring-fleet.config.json
    python tail_logs.py --config <cfg> --service payment --lines 100
    python tail_logs.py --config <cfg> --grep ERROR --follow
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


def print_static(files, lines, grep):
    any_output = False
    for name, path in files:
        if not os.path.isfile(path):
            print("# (no log file for '{}': {})".format(name, path), file=sys.stderr)
            continue
        for line in tail_lines(path, lines):
            line = line.rstrip("\n")
            if matches(line, grep):
                print("[{}] {}".format(name, line))
                any_output = True
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
    args = ap.parse_args(argv)

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
        print_static(files, args.lines, args.grep)
        follow(files, args.grep)
    else:
        print_static(files, args.lines, args.grep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
