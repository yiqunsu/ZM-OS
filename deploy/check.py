#!/usr/bin/env python3
"""Collect safe evidence from running containers; optionally compare an approved baseline."""

import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["local", "production"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = (
        [
            "--env-file",
            "deploy/local-auth/.env.local-auth",
            "-f",
            "docker-compose.yml",
            "-f",
            "compose.local-auth.yml",
        ]
        if args.mode == "local"
        else [
            "--env-file",
            os.environ.get("FILMOS_ENV_FILE", "deploy/production/.env.production"),
            "-f",
            os.environ.get("FILMOS_COMPOSE_FILE", "deploy/production/compose.yml"),
        ]
    )
    command = ["docker", "compose", *files]

    def run(*parts):
        result = subprocess.run(
            command + list(parts), cwd=root, capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError("Container check failed; inspect service status locally")
        return result.stdout

    backend = json.loads(
        run("exec", "-T", "backend", "python", "scripts/deployment_report.py")
    )
    result = {
        "backend": backend,
        "images": json.loads(run("images", "--format", "json")),
    }
    failures = []
    if backend["agent_enabled"]:
        worker = json.loads(
            run("exec", "-T", "agent-worker", "python", "scripts/deployment_report.py")
        )
        result["worker"] = worker
        if worker != backend:
            failures.append("Backend and Worker configuration differ")
        run(
            "exec",
            "-T",
            "agent-worker",
            "python",
            "-m",
            "app.agent.worker",
            "--healthcheck",
        )
    if not backend["key_configured"]:
        failures.append("Model key missing")
    if backend["revision"] == "unknown":
        failures.append("Unknown image revision")
    if args.mode == "production" and backend["revision"].endswith("-dirty"):
        failures.append("Production image was built from uncommitted source")
    for service in ("backend", "frontend", "agent-worker"):
        if service == "agent-worker" and not backend["agent_enabled"]:
            continue
        container = run("ps", "-q", service).strip()
        if not container:
            failures.append("Missing service: " + service)
            continue
        label = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                container,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if label != backend["revision"]:
            failures.append("Image revision differs: " + service)
    if args.baseline:
        approved = json.loads(args.baseline.read_text())["backend"]
        for key in sorted(approved.keys() | backend.keys()):
            if approved.get(key) != backend.get(key):
                failures.append("Baseline differs: " + key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for failure in failures:
        print(failure)
    print("Evidence saved. Real image and browser acceptance remain required.")
    return int(bool(failures))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.CalledProcessError):
        print("Deployment check failed; no environment or credentials were printed.")
        raise SystemExit(1) from None
