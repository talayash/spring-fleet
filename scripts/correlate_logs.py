#!/usr/bin/env python3
"""Correlate fleet logs by a trace key value into one cross-service timeline.

Reads the spring-fleet config to locate the log directory and per-service log
files, greps every log for a trace value (e.g. a sessionId), tags each matching
line with its service, and merges everything into a single chronological stream.

Dependency-free (Python 3 stdlib only). Cross-platform.

Usage:
    python correlate_logs.py --config spring-fleet.config.json --value <traceValue>
    python correlate_logs.py --config <cfg> --value <v> --service payment --format json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Leading timestamp in common Spring Boot patterns:
#   2026-06-09 14:23:01.123   or   2026-06-09T14:23:01.123
TS_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?)"
)


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def service_log_files(config):
    """Return list of (service_name, absolute_log_path) from the config."""
    log_dir = config["logDir"]
    out = []
    for svc in config.get("services", []):
        name = svc["name"]
        log_file = svc.get("logFile", "{}.log".format(name))
        out.append((name, os.path.join(log_dir, log_file)))
    return out


def normalize_ts(raw):
    """Normalize a timestamp string to a sortable key. Comma -> dot."""
    return raw.replace(",", ".")


def scan_file(service, path, value):
    """Yield matching records from one log file."""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            if value not in line:
                continue
            line = line.rstrip("\n")
            m = TS_RE.match(line)
            ts = normalize_ts(m.group("ts")) if m else ""
            yield {
                "ts": ts,
                "service": service,
                "line": line,
                "file": path,
                "lineNo": lineno,
            }


def correlate(config, value, service_filter=None):
    files = service_log_files(config)
    if service_filter:
        files = [(n, p) for (n, p) in files if n == service_filter]
    records = []
    missing = []
    for name, path in files:
        if not os.path.isfile(path):
            missing.append((name, path))
            continue
        records.extend(scan_file(name, path, value))
    # Records with a timestamp sort first by ts; those without keep a stable
    # tail order so they are not silently dropped.
    records.sort(key=lambda r: (r["ts"] == "", r["ts"]))
    return records, missing


def format_text_line(record):
    """Render one record for text output as '<ts> [service] <message>'.

    The raw line already begins with its own timestamp; strip that leading copy
    so the printed timestamp is not duplicated.
    """
    if record["ts"]:
        message = TS_RE.sub("", record["line"], count=1).lstrip()
        ts = record["ts"]
    else:
        message = record["line"]
        ts = "?"
    return "{ts:<23} [{svc}] {line}".format(ts=ts, svc=record["service"], line=message)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Correlate fleet logs by trace value.")
    ap.add_argument("--config", required=True, help="Path to spring-fleet.config.json")
    ap.add_argument("--value", required=True, help="Trace value to correlate on (e.g. a sessionId)")
    ap.add_argument("--service", help="Limit to a single service name")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args(argv)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print("ERROR: config not found: {}".format(args.config), file=sys.stderr)
        return 2

    records, missing = correlate(config, args.value, args.service)

    if args.format == "json":
        print(json.dumps({"value": args.value, "count": len(records),
                          "records": records,
                          "missingLogs": [{"service": n, "path": p} for n, p in missing]},
                         indent=2))
    else:
        if missing:
            for n, p in missing:
                print("# (no log file for service '{}': {})".format(n, p), file=sys.stderr)
        if not records:
            print("# no log lines matched value '{}'".format(args.value))
        for r in records:
            print(format_text_line(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
