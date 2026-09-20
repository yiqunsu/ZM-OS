"""Playwright-owned local stack with a random, disposable PostgreSQL database.

Uses only the repository's local development PostgreSQL credentials; never reads
a database URL from .env. App processes receive explicit isolated configuration.
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import asyncpg
from model_server import model_server

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
DATABASE = f"filmos_agent_e2e_{uuid4().hex}"
ADMIN = {"host": "127.0.0.1", "port": 5432, "user": "filmos", "password": "filmos", "database": "postgres"}
STOP = threading.Event()


async def database(create: bool) -> None:
    assert DATABASE.startswith("filmos_agent_e2e_") and DATABASE.removeprefix("filmos_agent_e2e_").isalnum()
    conn = await asyncpg.connect(**ADMIN)
    try:
        await conn.execute(
            f'CREATE DATABASE "{DATABASE}"'
            if create
            else f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'
        )
    finally:
        await conn.close()


async def seed() -> None:
    from app.core.database import async_session, engine
    from app.core.security import hash_password
    from app.models import (
        Customer,
        Machine,
        MachineCategory,
        Product,
        ProductCategory,
        User,
        UserRole,
    )

    async with async_session() as db:
        db.add_all(
            [
                User(
                    id="e2e-owner",
                    email="owner@e2e.filmos.local",
                    password_hash=hash_password("e2e-only-password"),
                    role=UserRole.OWNER,
                ),
                User(
                    id="e2e-other",
                    email="other@e2e.filmos.local",
                    password_hash=hash_password("e2e-only-password"),
                    role=UserRole.OWNER,
                ),
                Customer(id="e2e-customer", company="联调客户", contact="测试联系人"),
                ProductCategory(id="e2e-category", name="联调薄膜"),
                Machine(id="e2e-machine", name="联调设备", min_width=100, max_width=1200),
            ]
        )
        await db.flush()
        db.add_all(
            [
                Product(id="e2e-product", name="透明膜", category_id="e2e-category"),
                MachineCategory(machine_id="e2e-machine", category_id="e2e-category"),
            ]
        )
        await db.commit()
    await engine.dispose()


def main() -> None:
    for port in (3131, 8131, 8132):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))  # Refuse to reuse/stop an existing service.
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    processes: list[subprocess.Popen] = []
    logs = ROOT / "frontend" / "test-results" / "fullstack-logs"
    logs.mkdir(parents=True, exist_ok=True)
    handles = []
    provider = model_server(8132)
    created = False
    with tempfile.TemporaryDirectory(prefix="filmos-agent-e2e-") as directory:
        env = {
            **os.environ,
            "DATABASE_URL": f"postgresql+asyncpg://filmos:filmos@127.0.0.1:5432/{DATABASE}",
            "AUTH_PROVIDER": "local",
            "NEXT_PUBLIC_AUTH_PROVIDER": "local",
            "ENVIRONMENT": "development",
            "AUTH_SECRET": uuid4().hex + uuid4().hex,
            "AUTH_TRUST_HOST": "true",
            "AUTH_URL": "http://127.0.0.1:3131",
            "AGENT_V2_ENABLED": "true",
            "LLM_BASE_URL": "http://127.0.0.1:8132/v1",
            "LLM_API_KEY": "e2e-only-key",
            "LLM_MODEL": "filmos-test-model",
            "LLM_VISION_MODEL": "filmos-test-model",
            "PHOENIX_ENABLED": "false",
            "SENTRY_DSN": "",
            "CHAT_ATTACHMENT_DIR": directory,
            "BACKEND_INTERNAL_URL": "http://127.0.0.1:8131",
            "NEXT_PUBLIC_API_URL": "http://127.0.0.1:8131/api",
            "CORS_ORIGINS": '["http://127.0.0.1:3131"]',
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
        # Every HTTP dependency is local. A workstation proxy must not receive
        # this test's synthetic screenshots or change its model responses.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(name, None)
            os.environ.pop(name, None)
        os.environ.update(env)
        sys.path.insert(0, str(BACKEND))
        try:
            asyncio.run(database(True))
            created = True
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                env=env,
                check=True,
                timeout=60,
            )
            asyncio.run(seed())
            threading.Thread(target=provider.serve_forever, daemon=True).start()

            def launch(name: str, args: list[str], cwd: Path) -> None:
                handle = (logs / f"{name}.log").open("w")
                handles.append(handle)
                processes.append(
                    subprocess.Popen(
                        args,
                        cwd=cwd,
                        env=env,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                )

            launch(
                "api",
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8131"],
                BACKEND,
            )
            launch("worker", [sys.executable, "-m", "app.agent.worker"], BACKEND)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not STOP.is_set():
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8131/health", timeout=1):
                        break
                except OSError:
                    STOP.wait(0.2)
            else:
                raise RuntimeError("Isolated API did not start; see frontend/test-results/fullstack-logs")
            launch(
                "frontend",
                ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3131"],
                ROOT / "frontend",
            )
            print("Isolated Agent stack started; logs: frontend/test-results/fullstack-logs", flush=True)
            while not STOP.wait(0.5):
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("An integration service exited; see fullstack logs")
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process in reversed(processes):
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            provider.server_close()
            for handle in handles:
                handle.close()
            if created:
                asyncio.run(database(False))
                print("Isolated Agent database removed", flush=True)


if __name__ == "__main__":
    main()
