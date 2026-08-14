#!/usr/bin/env bash

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

docker compose exec -T openclaw node -e \
  "fetch('http://127.0.0.1:18789/readyz').then(r => { if (!r.ok) process.exit(1) }).catch(() => process.exit(1))"

docker compose exec -T backend python - <<'PY'
import asyncio
import json
import os

import httpx


async def main() -> None:
    token = os.environ["OPENCLAW_GATEWAY_TOKEN"]
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            "http://openclaw:18789/v1/responses",
            headers={
                "Authorization": f"Bearer {token}",
                "x-openclaw-agent-id": "filmos-web",
            },
            json={
                "model": "openclaw/filmos-web",
                "input": "只回复：连接成功",
                "user": "filmos-smoke-test",
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            saw_delta = False
            completed = False
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                payload = json.loads(line[6:])
                if payload.get("type") == "response.output_text.delta":
                    saw_delta = True
                elif payload.get("type") == "response.completed":
                    completed = True
            if not saw_delta or not completed:
                raise RuntimeError("OpenClaw stream did not produce a complete text response")
    print("OpenClaw authenticated streaming response is healthy.")


asyncio.run(main())
PY
