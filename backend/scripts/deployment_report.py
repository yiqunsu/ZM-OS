"""Allowlisted runtime evidence; never dump environment, credentials or business rows."""

import argparse
import asyncio
import hashlib
import json
import sys
from importlib.metadata import distributions
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def differences(left: dict, right: dict) -> list[str]:
    """Compare behavior, allowing identity endpoints and machine addresses to differ."""
    return [key for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)]


async def collect() -> dict:
    from sqlalchemy import text

    from app.agent.specialized.prompts import prompt_versions
    from app.core.config import settings
    from app.core.database import engine

    endpoint = urlsplit(settings.LLM_BASE_URL)
    packages = sorted((d.metadata["Name"], d.version) for d in distributions())
    async with engine.connect() as conn:
        migrations = sorted((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
    await engine.dispose()
    port = f":{endpoint.port}" if endpoint.port else ""
    source = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    paths = [p for directory in ("app", "scripts", "alembic") for p in (root / directory).rglob("*.py")]
    for path in sorted(paths):
        source.update(str(path.relative_to(root)).encode())
        source.update(path.read_bytes())
    return {
        "backend_source_sha256": source.hexdigest(),
        "report_schema": 1,
        "revision": settings.APP_REVISION,
        "auth_provider": settings.AUTH_PROVIDER,
        "agent_enabled": settings.AGENT_V2_ENABLED,
        "llm_endpoint": f"{endpoint.scheme}://{endpoint.hostname}{port}",
        "llm_route_sha256": hashlib.sha256(
            (endpoint.path.rstrip("/") + "?" + endpoint.query).encode()
        ).hexdigest(),
        "llm_model": settings.LLM_MODEL,
        "vision_model": settings.LLM_VISION_MODEL,
        "vision_thinking_configured": settings.LLM_VISION_THINKING,
        "vision_thinking_effective": settings.LLM_VISION_THINKING
        if endpoint.hostname == "api.deepseek.com"
        else "provider_default",
        "vision_max_tokens": settings.LLM_VISION_MAX_TOKENS,
        "model_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
        "key_configured": bool(settings.LLM_API_KEY.strip()),
        "prompt_versions": prompt_versions(),
        "database_revisions": migrations,
        "python_dependencies_sha256": hashlib.sha256(json.dumps(packages).encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs=2, metavar=("LOCAL_JSON", "CLOUD_JSON"))
    args = parser.parse_args()
    if args.compare:
        a, b = [json.loads(Path(p).read_text()) for p in args.compare]
        changed = differences(a, b)
        for key in changed:
            print(f"DIFFERENT: {key}")
        unknown = a.get("revision") in {None, "unknown"} or b.get("revision") in {None, "unknown"}
        if unknown:
            print("UNVERIFIED: image revision missing")
        if not changed and not unknown:
            print("MATCH: runtime configuration; business data and model outputs are not compared")
        return int(bool(changed) or unknown)
    print(json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
