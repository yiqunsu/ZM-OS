"""Exercise the real release script without Docker, network or business data."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def release(tmp_path):
    scripts = tmp_path / "deploy/production/scripts"
    scripts.mkdir(parents=True)
    for name in ("deploy.sh", "common.sh"):
        shutil.copy2(SCRIPTS / name, scripts / name)
    for name in ("validate-env.sh", "provision-casdoor.sh", "verify-casdoor.sh", "backup.sh"):
        helper = scripts / name
        helper.write_text(
            '#!/bin/bash\n'
            'name="${0##*/}"\n'
            'echo "$name" >> "$TEST_TRACE"\n'
            'if [[ "$TEST_FAIL" == "$name" ]]; then exit 9; fi\n'
        )
        helper.chmod(0o755)
    marker = tmp_path / ".data/casdoor/.initialized"
    marker.parent.mkdir(parents=True)
    marker.touch()
    (scripts.parent / ".env.production").write_text(
        "WEB_BIND_IP=127.0.0.1\nPOSTGRES_USER=test\nPOSTGRES_DB=test\n"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "a = sys.argv[1:]\n"
        "if a[0] == 'compose': a = a[5:]\n"
        "command = ' '.join(a)\n"
        "with open(os.environ['TEST_TRACE'], 'a') as f: f.write(command + '\\n')\n"
        "if command == os.environ['TEST_FAIL']: sys.exit(8)\n"
        "if a[:2] == ['ps', '-q']: print('fake-' + a[-1])\n"
        "elif a[0] == 'inspect': print('healthy')\n"
        "elif 'psql' in a: print('t')\n"
    )
    docker.chmod(0o755)
    git = binaries / "git"
    git.write_text(
        '#!/bin/bash\n'
        'case "$3" in\n'
        '  rev-parse) echo abc123;;\n'
        '  status) printf "%s" "$TEST_DIRTY";;\n'
        'esac\n'
    )
    git.chmod(0o755)

    def run(*, fail="", dirty="", agent="true"):
        trace = tmp_path / "trace"
        environment = {
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "TEST_TRACE": str(trace),
            "TEST_FAIL": fail,
            "TEST_DIRTY": dirty,
            "AGENT_V2_ENABLED": agent,
            "FILMOS_ENV_FILE": str(scripts.parent / ".env.production"),
            "FILMOS_COMPOSE_FILE": str(scripts.parent / "compose.yml"),
        }
        result = subprocess.run(
            ["bash", str(scripts / "deploy.sh")],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, trace.read_text().splitlines()

    return run


def test_release_builds_before_backup_and_migration_without_model_calls(release):
    result, events = release()
    assert result.returncode == 0, result.stderr
    expected = [
        "validate-env.sh",
        "build backend",
        "build frontend",
        "up -d postgres",
        "verify-casdoor.sh",
        "backup.sh",
        "run --rm backend alembic upgrade head",
        "up -d --remove-orphans backend frontend caddy",
        "up -d agent-worker",
        "exec -T backend alembic check",
    ]
    positions = [events.index(event) for event in expected]
    assert positions == sorted(positions)
    assert not any("image inspect" in event for event in events)
    assert not any("python scripts/" in event for event in events)
    assert "revision abc123" in result.stdout
    assert "No model API was called" in result.stdout


@pytest.mark.parametrize(
    "failure,forbidden",
    [
        ("validate-env.sh", "build backend"),
        ("build backend", "up -d postgres"),
        ("build frontend", "up -d postgres"),
        ("backup.sh", "run --rm backend alembic upgrade head"),
        ("run --rm backend alembic upgrade head", "up -d --remove-orphans backend frontend caddy"),
        ("exec -T backend alembic check", None),
    ],
)
def test_failure_stops_release_without_claiming_success(release, failure, forbidden):
    result, events = release(fail=failure)
    assert result.returncode != 0
    if forbidden:
        assert forbidden not in events
    assert "deployment is healthy" not in result.stdout


def test_dirty_worktree_is_labeled_without_discarding_changes(release):
    result, events = release(dirty=" M backend/app/main.py")
    assert result.returncode == 0, result.stderr
    assert "revision abc123-dirty" in result.stdout
    assert "WARNING" in result.stderr
    assert "build backend" in events


def test_disabled_agent_stops_worker(release):
    result, events = release(agent="false")
    assert result.returncode == 0, result.stderr
    assert "stop agent-worker" in events
    assert "up -d agent-worker" not in events
