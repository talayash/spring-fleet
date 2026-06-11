#!/usr/bin/env python3
"""Scan a repos root and emit a draft spring-fleet config.

For each immediate subdirectory of --root that looks like a Spring Boot service
or a shared library, infer:
  - build tool (gradle vs maven)
  - server port and context path (from application.properties / application.yml)
  - whether it is a library (no bootRun-able application) vs a service

The result is a DRAFT. Topology edges and trace keys cannot be reliably
inferred mechanically and are left for the user to confirm.

Dependency-free (Python 3 stdlib only). Cross-platform.

Usage:
    python scan_repos.py --root /path/to/repos
    python scan_repos.py --root /path/to/repos --log-dir /path/to/repos/.spring-fleet-logs
"""
from __future__ import annotations

import argparse
import json
import os
import re

PORT_PROP_RE = re.compile(r"^\s*server\.port\s*[=:]\s*(\d+)", re.MULTILINE)
CTX_PROP_RE = re.compile(
    r"^\s*server\.servlet\.context-path\s*[=:]\s*(\S+)", re.MULTILINE
)
# Minimal YAML probes (avoids a yaml dependency): look for "port:" under server.
YAML_PORT_RE = re.compile(r"port:\s*(\d+)")
YAML_CTX_RE = re.compile(r"context-path:\s*(\S+)")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def find_app_config(repo_path):
    """Return text of the first application.{properties,yml,yaml} found."""
    for root, _dirs, files in os.walk(repo_path):
        # only look under src/main/resources to avoid test configs
        if "resources" not in root.replace("\\", "/"):
            continue
        for fn in files:
            if fn in ("application.properties", "application.yml", "application.yaml"):
                return fn, read_text(os.path.join(root, fn))
    return None, ""


def detect_build_tool(repo_path):
    if os.path.isfile(os.path.join(repo_path, "build.gradle")) or os.path.isfile(
        os.path.join(repo_path, "build.gradle.kts")
    ):
        return "gradle"
    if os.path.isfile(os.path.join(repo_path, "pom.xml")):
        return "maven"
    return None


def strip_comments(txt):
    """Remove // line comments, # line comments, and /* */ blocks so that a
    comment merely *mentioning* Spring Boot does not misclassify a library."""
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.DOTALL)
    out = []
    for line in txt.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        # drop trailing // comment
        line = re.sub(r"//.*$", "", line)
        out.append(line)
    return "\n".join(out)


# Tokens that indicate an independently runnable Spring Boot application,
# matched against build files with comments stripped.
BOOT_BUILD_TOKENS = (
    "org.springframework.boot",   # gradle plugin id / maven groupId
    "spring-boot-starter",        # any starter dependency
    "spring-boot-maven-plugin",   # maven packaging plugin
)

# Spring Boot plugin/parent version in build files. Matches the
# common gradle plugins{} form and the maven <parent> form.
SPRING_BOOT_VERSION_RE = re.compile(
    r"""
    (?:                                       # gradle plugin DSL
        id\s*['"]org\.springframework\.boot['"]
        \s*version\s*['"](?P<gv>\d+)\.\d+(?:\.\d+)?(?:[-\w.]+)?['"]
    )
    |
    (?:                                       # maven <parent><version>
        spring-boot-starter-parent.*?<version>\s*(?P<mv>\d+)\.\d+(?:\.\d+)?
    )
    """,
    re.VERBOSE | re.DOTALL,
)

JAVA_TOOLCHAIN_RE = re.compile(
    r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)"
    r"|<java\.version>\s*(\d+)\s*</java\.version>"
    r"|sourceCompatibility\s*=\s*['\"]?(\d+)"
)


def is_bootable(repo_path):
    """Heuristic: a service has a build file applying the Spring Boot plugin /
    declaring a starter, or a class annotated @SpringBootApplication."""
    for bf in ("build.gradle", "build.gradle.kts", "pom.xml"):
        txt = strip_comments(read_text(os.path.join(repo_path, bf)))
        if any(tok in txt for tok in BOOT_BUILD_TOKENS):
            return True
    for root, _dirs, files in os.walk(repo_path):
        for fn in files:
            if fn.endswith(".java"):
                if "@SpringBootApplication" in read_text(os.path.join(root, fn)):
                    return True
    return False


def _read_build_files(repo_path):
    """Concatenate all build file text in the repo (comments stripped)."""
    parts = []
    for bf in ("build.gradle", "build.gradle.kts", "pom.xml", "settings.gradle"):
        parts.append(strip_comments(read_text(os.path.join(repo_path, bf))))
    return "\n".join(parts)


def _read_resource_configs(repo_path):
    """Concatenate application.properties / application.yml text."""
    parts = []
    for root, _dirs, files in os.walk(repo_path):
        if "resources" not in root.replace("\\", "/"):
            continue
        for fn in files:
            if fn in ("application.properties", "application.yml", "application.yaml"):
                parts.append(read_text(os.path.join(root, fn)))
    return "\n".join(parts)


def _walk_java_text(repo_path, limit_bytes=2_000_000):
    """Concatenate src/main + src/test java contents up to a soft byte cap.
    The cap keeps the scan O(repo) on huge codebases — we only need to detect
    annotations, not parse code."""
    parts = []
    total = 0
    for root, _dirs, files in os.walk(repo_path):
        for fn in files:
            if not fn.endswith(".java"):
                continue
            txt = read_text(os.path.join(root, fn))
            parts.append(txt)
            total += len(txt)
            if total >= limit_bytes:
                return "\n".join(parts)
    return "\n".join(parts)


def parse_catalog_info(repo_path):
    """Parse a Backstage `catalog-info.yaml` if present at the repo root.
    Returns a dict with `name`, `owner`, `system`, `lifecycle`, and a list of
    `dependsOnComponents` (the component names this component depends on),
    or None if no catalog file exists. Does a minimal line-oriented parse so
    we keep zero non-stdlib dependencies — only handles the flat fields and
    the dependsOn list that catalog files actually use in practice."""
    for fn in ("catalog-info.yaml", "catalog-info.yml"):
        path = os.path.join(repo_path, fn)
        if os.path.isfile(path):
            break
    else:
        return None

    text = read_text(path)
    result = {
        "name": None,
        "owner": None,
        "system": None,
        "lifecycle": None,
        "type": None,
        "dependsOnComponents": [],
    }

    in_metadata = False
    in_spec = False
    in_depends_on = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        # Top-level keys reset section flags.
        if not line.startswith(" "):
            in_metadata = stripped.startswith("metadata:")
            in_spec = stripped.startswith("spec:")
            in_depends_on = False
            continue
        if in_metadata and stripped.startswith("name:"):
            result["name"] = stripped.split(":", 1)[1].strip().strip('"\'')
        elif in_spec:
            if stripped.startswith("owner:"):
                result["owner"] = stripped.split(":", 1)[1].strip().strip('"\'')
            elif stripped.startswith("system:"):
                result["system"] = stripped.split(":", 1)[1].strip().strip('"\'')
            elif stripped.startswith("lifecycle:"):
                result["lifecycle"] = stripped.split(":", 1)[1].strip().strip('"\'')
            elif stripped.startswith("type:"):
                result["type"] = stripped.split(":", 1)[1].strip().strip('"\'')
            elif stripped.startswith("dependsOn:"):
                in_depends_on = True
            elif in_depends_on and stripped.startswith("-"):
                item = stripped.lstrip("-").strip().strip('"\'')
                if item.lower().startswith("component:"):
                    result["dependsOnComponents"].append(item.split(":", 1)[1])
            elif in_depends_on and not stripped.startswith("-"):
                in_depends_on = False
    return result


def detect_stack(repo_path):
    """Return a dict describing the modern-stack features present in this
    service repo. Absence is reported as False so downstream tools can branch
    deterministically on `stack.get("dockerCompose")`."""
    build = _read_build_files(repo_path)
    props = _read_resource_configs(repo_path)
    java_text = _walk_java_text(repo_path)

    boot_major = None
    m = SPRING_BOOT_VERSION_RE.search(build)
    if m:
        boot_major = int(m.group("gv") or m.group("mv"))

    java_version = None
    jm = JAVA_TOOLCHAIN_RE.search(build)
    if jm:
        java_version = int(next(g for g in jm.groups() if g))

    virtual_threads = (
        "spring.threads.virtual.enabled=true" in props.replace(" ", "")
        or "spring.threads.virtual.enabled: true" in props.replace(" ", "")
        or "virtual-threads:" in props
        and "true" in props.split("virtual-threads:", 1)[1].splitlines()[0]
    )

    graal_native = (
        "org.graalvm.buildtools.native" in build
        or "native-maven-plugin" in build
    )

    docker_compose = any(
        os.path.isfile(os.path.join(repo_path, fn))
        for fn in ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
    )

    testcontainers = (
        "@ServiceConnection" in java_text
        or "spring-boot-testcontainers" in build
        or "org.testcontainers" in build
    )

    opentelemetry = (
        "spring-boot-starter-opentelemetry" in build
        or "micrometer-tracing-bridge-otel" in build
        or "io.opentelemetry" in build
    )

    return {
        "springBootMajor": boot_major,
        "java": java_version,
        "virtualThreads": bool(virtual_threads),
        "graalNative": bool(graal_native),
        "dockerCompose": bool(docker_compose),
        "testcontainers": bool(testcontainers),
        "opentelemetry": bool(opentelemetry),
    }


def parse_port_ctx(cfg_name, cfg_text):
    port = None
    ctx = None
    if cfg_name and cfg_name.endswith(".properties"):
        m = PORT_PROP_RE.search(cfg_text)
        if m:
            port = int(m.group(1))
        m = CTX_PROP_RE.search(cfg_text)
        if m:
            ctx = m.group(1)
    elif cfg_name:
        m = YAML_PORT_RE.search(cfg_text)
        if m:
            port = int(m.group(1))
        m = YAML_CTX_RE.search(cfg_text)
        if m:
            ctx = m.group(1)
    return port, ctx


def scan(root, log_dir):
    services = []
    shared_libs = []
    for name in sorted(os.listdir(root)):
        repo_path = os.path.join(root, name)
        if not os.path.isdir(repo_path) or name.startswith("."):
            continue
        build_tool = detect_build_tool(repo_path)
        if build_tool is None:
            continue
        if is_bootable(repo_path):
            cfg_name, cfg_text = find_app_config(repo_path)
            port, ctx = parse_port_ctx(cfg_name, cfg_text)
            svc = {"name": name, "path": name}
            if port is not None:
                svc["port"] = port
            if ctx is not None:
                svc["contextPath"] = ctx
            svc["logFile"] = "{}.log".format(name)
            svc["stack"] = detect_stack(repo_path)
            catalog = parse_catalog_info(repo_path)
            if catalog:
                # The Backstage component name is authoritative if present;
                # otherwise fall back to the directory name. The directory
                # name remains the `path` (used to resolve repo dirs).
                if catalog["name"]:
                    svc["name"] = catalog["name"]
                svc["backstage"] = {
                    k: v for k, v in catalog.items()
                    if k != "dependsOnComponents" and v is not None
                }
                svc["_dependsOnComponents"] = catalog["dependsOnComponents"]
            services.append(svc)
        else:
            shared_libs.append({"name": name, "path": name, "modules": []})

    topology = _topology_from_backstage(services)
    # Strip the private _dependsOnComponents marker now that topology is built.
    for svc in services:
        svc.pop("_dependsOnComponents", None)

    return {
        "reposRoot": root,
        "buildTool": detect_default_build_tool(services, root),
        "logDir": log_dir or os.path.join(root, ".spring-fleet-logs"),
        "traceKeys": ["trace_id", "span_id", "sessionId", "requestId"],
        "sharedLibs": shared_libs,
        "services": services,
        "topology": topology,
        "_note": "DRAFT generated by scan_repos.py. Confirm traceKeys and fill in topology.entry / topology.edges.",
    }


def _topology_from_backstage(services):
    """Build entry + edges from each service's _dependsOnComponents. Edge
    direction follows Backstage: a service that dependsOn X is an upstream of
    X. We model that as caller -> callee, i.e. the depending service calls
    the depended-on one (matching the existing spring-fleet edge semantics
    used by /trace). Services with no inbound edge are entry candidates."""
    names = {s["name"] for s in services}
    edges = []
    has_inbound = set()
    for svc in services:
        deps = svc.get("_dependsOnComponents") or []
        for dep in deps:
            if dep in names:
                edges.append([svc["name"], dep])
                has_inbound.add(dep)
    if not edges:
        return {"entry": [], "edges": []}
    entry = sorted(n for n in names if n not in has_inbound)
    return {"entry": entry, "edges": edges}


def detect_default_build_tool(services, root):
    # use whatever the first repo uses
    for entry in sorted(os.listdir(root)):
        bt = detect_build_tool(os.path.join(root, entry))
        if bt == "gradle":
            return {"type": "gradle", "moduleFlag": "-p {module}", "run": "bootRun", "test": "test"}
        if bt == "maven":
            return {"type": "maven", "moduleFlag": "-pl {module}", "run": "spring-boot:run", "test": "test"}
    return {"type": "gradle", "moduleFlag": "-p {module}", "run": "bootRun", "test": "test"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan repos root into a draft spring-fleet config.")
    ap.add_argument("--root", required=True, help="Path to the directory containing all repos")
    ap.add_argument("--log-dir", help="Override the log directory (default: <root>/.spring-fleet-logs)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        print("ERROR: not a directory: {}".format(args.root))
        return 2

    draft = scan(args.root, args.log_dir)
    print(json.dumps(draft, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
