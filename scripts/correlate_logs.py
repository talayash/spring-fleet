#!/usr/bin/env python3
"""Correlate fleet logs by a trace key value into one cross-service timeline.

Reads text or JSON log events, matches a substring or exact trace-key value,
and merges the events into a UTC-ordered timeline with source citations.

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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

# Leading timestamp in common Spring Boot patterns:
#   2026-06-09 14:23:01.123   or   2026-06-09T14:23:01.123
TS_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)"
)
DEFAULT_TRACE_KEYS = ["trace_id", "span_id", "traceId", "spanId", "sessionId", "requestId", "trace.id", "span.id"]
CONTINUATION_RE = re.compile(r"^(?:\s+|Caused by:|Suppressed:|[\w.$]+(?:Exception|Error)(?::|$))")


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
    """Normalize the displayed timestamp's fractional separator."""
    return raw.replace(",", ".")


def timestamp_key(raw):
    """UTC epoch seconds, retaining nanoseconds. Naive timestamps assume UTC."""
    try:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            result = Decimal(str(raw))  # GELF epoch seconds
            return result if result.is_finite() else None
        raw = normalize_ts(raw)
        match = TS_RE.fullmatch(raw)
        if not match:
            return None
        fraction = re.search(r"\.(\d+)", raw)
        seconds = Decimal("0." + fraction.group(1)) if fraction else Decimal(0)
        whole = re.sub(r"\.\d+", "", raw).replace("Z", "+00:00")
        whole = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", whole)
        dt = datetime.fromisoformat(whole)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return Decimal(int(dt.timestamp())) + seconds
    except (ValueError, TypeError, AttributeError, OverflowError, InvalidOperation):
        return None


def json_field(data, key):
    """Handle flat ECS keys, nested fields, MDC containers and GELF prefixes."""
    for container in (data, data.get("mdc", {}), data.get("contextMap", {})):
        if not isinstance(container, dict):
            continue
        for candidate in (key, "_" + key):
            if candidate in container:
                return container[candidate]
        nested = container
        for part in key.split("."):
            nested = nested.get(part) if isinstance(nested, dict) else None
        if nested is not None:
            return nested
    return None


def matches_record(record, value, trace_keys=None):
    if trace_keys is None:
        return value in record["line"]
    data = record.get("_json")
    if data is not None:
        return any(json_field(data, key) == value for key in trace_keys)
    # Match complete key/value tokens, including quoted values. Never ABC1234
    # when looking for ABC123, or other_sessionId when looking for sessionId.
    for key in trace_keys:
        pattern = r'''(?<![\w.\-])['"]?%s['"]?\s*[=:]\s*(?:"([^"]*)"|'([^']*)'|([^\s,;\]\}]+))''' % re.escape(key)
        if any(value in m.groups() for m in re.finditer(pattern, record["line"].split("\n", 1)[0])):
            return True
    return False


def scan_file(service, path, value, trace_keys=None):
    """Yield log events, preserving continuation lines and source line numbers."""
    if not os.path.isfile(path):
        return
    pending = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.rstrip("\r\n")
            m = TS_RE.match(line)
            data = None
            if line.lstrip().startswith("{"):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        data = parsed
                except ValueError:
                    pass
            if not m and data is None and pending is not None and CONTINUATION_RE.match(line):
                pending["line"] += "\n" + line
                pending["endLineNo"] = lineno
                continue
            if pending is not None and matches_record(pending, value, trace_keys):
                pending.pop("_json", None)
                yield pending
            ts = m.group("ts") if m else ""
            if data is not None:
                ts = data.get("@timestamp", data.get("timestamp", ""))
            pending = {"ts": normalize_ts(str(ts)), "service": service,
                       "line": line, "file": path, "lineNo": lineno,
                       "endLineNo": lineno, "_json": data}
            key = timestamp_key(ts)
            pending["timestampUtc"] = str(key) if key is not None else None
    if pending is not None and matches_record(pending, value, trace_keys):
        pending.pop("_json", None)
        yield pending


def correlate(config, value, service_filter=None, match="substring", key=None):
    if not isinstance(value, str) or not value:
        raise ValueError("trace value must be a non-empty string")
    if match not in ("substring", "exact"):
        raise ValueError("match must be substring or exact")
    trace_keys = ([key] if key else config.get("traceKeys", DEFAULT_TRACE_KEYS)) if match == "exact" or key else None
    files = service_log_files(config)
    if service_filter:
        files = [(n, p) for (n, p) in files if n == service_filter]
        if not files:
            raise ValueError("unknown service: {}".format(service_filter))
    records = []
    missing = []
    for name, path in files:
        if not os.path.isfile(path):
            missing.append((name, path))
            continue
        records.extend(scan_file(name, path, value, trace_keys))
    # Records with a parsed timestamp sort first in UTC; others keep a stable
    # tail order so they are not silently dropped.
    records.sort(key=lambda r: (r["timestampUtc"] is None,
                               Decimal(r["timestampUtc"]) if r["timestampUtc"] is not None else Decimal(0)))
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
    ap.add_argument("--match", choices=["substring", "exact"], default="substring",
                    help="Exact mode matches configured traceKeys; default preserves text search.")
    ap.add_argument("--key", help="Match this trace key exactly (implies --match exact).")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args(argv)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print("ERROR: config not found: {}".format(args.config), file=sys.stderr)
        return 2

    try:
        records, missing = correlate(config, args.value, args.service, args.match, args.key)
    except ValueError as exc:
        ap.error(str(exc))

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
