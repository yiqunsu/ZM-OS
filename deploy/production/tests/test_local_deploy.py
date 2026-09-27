"""Validate local boot order without touching Docker, databases or model APIs."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_frontend_build_config import LOCAL_AUTH_ENV, render_compose


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("casdoor", [False, True])
@pytest.mark.parametrize("phoenix", [False, True])
def test_local_service_contract(casdoor, phoenix):
    files = ["deploy/local/docker-compose.yml"]
    if casdoor:
        files.append("deploy/local/compose.local-auth.yml")
    if phoenix:
        files.append("deploy/local/compose.phoenix.yml")
    services = render_compose(*files, env_file=LOCAL_AUTH_ENV)["services"]
    expected = {"postgres", "backend", "agent-worker", "frontend"}
    if casdoor:
        expected |= {"casdoor", "casdoor-db-init", "casdoor-config"}
    if phoenix:
        expected.add("phoenix")
    assert set(services) == expected
    assert services["backend"]["image"] == services["agent-worker"]["image"]
    for name in ["backend", "agent-worker"]:
        assert "phoenix" not in services[name]["depends_on"]
        assert services[name]["depends_on"]["postgres"]["condition"] == "service_healthy"
        assert "REDIS_URL" not in services[name]["environment"]
    assert services["backend"]["environment"]["PHOENIX_ENABLED"] == "false"
    assert services["agent-worker"]["environment"]["PHOENIX_ENABLED"] == str(phoenix).lower()
    assert services["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"
    if casdoor:
        assert services["frontend"]["environment"]["BACKEND_INTERNAL_URL"] == "http://backend:8000"
        assert "BACKEND_API_URL" not in services["frontend"]["environment"]


@pytest.fixture
def local_release(tmp_path):
    for relative in ["deploy/local/up.sh"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (tmp_path / "deploy/local/.env").write_text("CASDOOR_OWNER_EMAIL=local@test.invalid\n")
    (tmp_path / ".data/local-casdoor").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[2:]\n"
        "files = []\n"
        "while args and args[0].startswith('-'):\n"
        "    if args[0] == '-f': files.append(os.path.basename(args[1]))\n"
        "    args = args[2:]\n"
        "command = ' '.join(args)\n"
        "if command == 'config --environment': print('AGENT_V2_ENABLED=' + os.environ['TEST_AGENT'])\n"
        "with open(os.environ['TEST_TRACE'], 'a') as f:\n"
        "    f.write(json.dumps({'command': command, 'files': files}) + '\\n')\n"
        "if command == os.environ.get('TEST_FAIL'): sys.exit(9)\n"
    )
    docker.chmod(0o755)
    git = binaries / "git"
    git.write_text('#!/bin/bash\nif [[ "$3" == "rev-parse" ]]; then echo test-revision; fi\n')
    git.chmod(0o755)

    def run(*, casdoor=False, phoenix=False, fail="", agent="true"):
        trace = tmp_path / "trace"
        args = ["bash", str(tmp_path / "deploy/local/up.sh")]
        args += ["--casdoor"] if casdoor else []
        args += ["--phoenix"] if phoenix else []
        environment = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
                       "TEST_TRACE": str(trace), "TEST_FAIL": fail, "TEST_AGENT": agent}
        environment.pop("FILMOS_LOCAL_ENV_FILE", None)
        result = subprocess.run(args, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10)
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        return result, events

    return run


@pytest.mark.parametrize("casdoor", [False, True])
@pytest.mark.parametrize("phoenix", [False, True])
def test_boot_migrates_before_starting_applications(local_release, casdoor, phoenix):
    result, events = local_release(casdoor=casdoor, phoenix=phoenix)
    assert result.returncode == 0, result.stderr
    commands = [event["command"] for event in events]
    expected = ["config --quiet", "build backend frontend", "up -d --wait postgres",
                "stop frontend backend agent-worker", "run --rm --no-deps backend alembic upgrade head",
                "up -d --wait backend frontend agent-worker", "exec -T backend alembic check"]
    positions = [commands.index(command) for command in expected]
    assert positions == sorted(positions)
    assert ("run --rm --no-deps casdoor-db-init" in commands) == casdoor
    assert ("up -d phoenix" in commands) == phoenix
    for event in events:
        assert ("compose.local-auth.yml" in event["files"]) == casdoor
        assert ("compose.phoenix.yml" in event["files"]) == phoenix
    assert not any("down" in command or "seed_" in command for command in commands)


@pytest.mark.parametrize("casdoor", [False, True])
@pytest.mark.parametrize("failure", ["config --quiet", "build backend frontend", "up -d --wait postgres",
                                    "run --rm --no-deps backend alembic upgrade head"])
def test_failed_preparation_never_starts_api_or_worker(local_release, casdoor, failure):
    result, events = local_release(casdoor=casdoor, fail=failure)
    assert result.returncode != 0
    commands = [event["command"] for event in events]
    assert "up -d --wait backend frontend agent-worker" not in commands
    assert "Local services are ready" not in result.stdout


def test_collector_failure_does_not_block_core_startup(local_release):
    result, events = local_release(phoenix=True, fail="up -d phoenix")
    assert result.returncode == 0
    assert "WARNING" in result.stderr
    assert "exec -T backend alembic check" in [event["command"] for event in events]


def test_disabled_agent_keeps_worker_stopped(local_release):
    result, events = local_release(agent="false")
    assert result.returncode == 0, result.stderr
    commands = [event["command"] for event in events]
    assert "stop frontend backend agent-worker" in commands
    assert "up -d --wait backend frontend" in commands
    assert "up -d --wait backend frontend agent-worker" not in commands


@pytest.mark.parametrize("failure", ["up -d --wait backend frontend agent-worker", "exec -T backend alembic check"])
def test_unhealthy_applications_do_not_report_success(local_release, failure):
    result, _ = local_release(fail=failure)
    assert result.returncode != 0
    assert "Local services are ready" not in result.stdout


def test_local_casdoor_and_production_share_application_contracts():
    from test_frontend_build_config import PRODUCTION_ENV

    local = render_compose("deploy/local/docker-compose.yml", "deploy/local/compose.local-auth.yml", env_file=LOCAL_AUTH_ENV)["services"]
    production = render_compose("deploy/production/compose.yml", env_file=PRODUCTION_ENV)["services"]
    for name in ["backend", "frontend"]:
        # Different build settings must still use the same application source.
        assert local[name]["build"]["context"] == production[name]["build"]["context"]
    for services in [local, production]:
        api, worker = services["backend"], services["agent-worker"]
        assert api["image"] == worker["image"]
        assert worker["command"] == ["python", "-m", "app.agent.worker"]
        assert api["environment"] == worker["environment"]
        assert api["volumes"] == worker["volumes"]
        for name in ["backend", "agent-worker", "frontend"]:
            assert services[name]["environment"]["AUTH_PROVIDER"] == "casdoor"
            assert services[name]["environment"]["AGENT_V2_ENABLED"] == "true"
        assert services["frontend"]["build"]["args"]["NEXT_PUBLIC_AUTH_PROVIDER"] == "casdoor"
        assert services["frontend"]["environment"]["BACKEND_INTERNAL_URL"] == "http://backend:8000"
    assert "LLM_API_KEY" not in local["frontend"]["environment"]
    assert "CASDOOR_DB_PASSWORD" not in local["frontend"]["environment"]
    assert "CASDOOR_ADMIN_PASSWORD" not in local["backend"]["environment"]
    assert local["casdoor"]["image"] == production["casdoor"]["image"]
    # Local settings come from the example env; production forwards the same defaults explicitly.
    local_defaults = dict(
        line.split("=", 1) for line in (ROOT / "deploy/local/.env.example").read_text().splitlines()
        if line.startswith("LLM_")
    )
    for key, value in local_defaults.items():
        if key != "LLM_API_KEY":
            assert production["backend"]["environment"][key] == value
