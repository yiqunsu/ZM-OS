from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_AUTH_ENV = REPO_ROOT / "deploy/local-auth/.env.local-auth.example"
PRODUCTION_ENV = REPO_ROOT / "deploy/production/.env.production.example"


def render_compose(
    *compose_files: str,
    env_file: Path,
    api_url: str | None = None,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment.pop("NEXT_PUBLIC_API_URL", None)
    environment["QWEN_API_KEY"] = "compose-render-test-key"
    if api_url is not None:
        environment["NEXT_PUBLIC_API_URL"] = api_url

    command = ["docker", "compose", "--env-file", str(env_file)]
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    command.extend(["config", "--no-env-resolution", "--format", "json"])
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def assert_api_build_chain(
    testcase: unittest.TestCase,
    dockerfile_path: Path,
    expected_default: str,
) -> None:
    dockerfile = dockerfile_path.read_text()
    arg = re.search(r"(?m)^ARG NEXT_PUBLIC_API_URL=([^\s]+)$", dockerfile)
    env = re.search(
        r"(?m)^ENV NEXT_PUBLIC_API_URL=\$\{NEXT_PUBLIC_API_URL\}$",
        dockerfile,
    )
    build = re.search(r"(?m)^RUN npm run build$", dockerfile)

    if arg is None or env is None or build is None:
        testcase.fail(
            f"{dockerfile_path} must pass NEXT_PUBLIC_API_URL from ARG to ENV "
            "before npm run build"
        )
        return

    testcase.assertEqual(arg.group(1), expected_default)
    testcase.assertLess(arg.start(), env.start())
    testcase.assertLess(env.start(), build.start())


class FrontendBuildConfigurationTests(unittest.TestCase):
    def test_dockerfiles_embed_api_base_during_next_build(self) -> None:
        cases = (
            (REPO_ROOT / "frontend/Dockerfile", "http://localhost:8000/api"),
            (REPO_ROOT / "deploy/production/frontend.Dockerfile", "/api"),
        )
        for dockerfile, expected_default in cases:
            with self.subTest(dockerfile=dockerfile):
                assert_api_build_chain(self, dockerfile, expected_default)

    def test_default_compose_renders_local_api_base_and_accepts_override(self) -> None:
        rendered = render_compose(
            "docker-compose.yml",
            env_file=LOCAL_AUTH_ENV,
        )
        custom = render_compose(
            "docker-compose.yml",
            env_file=LOCAL_AUTH_ENV,
            api_url="https://api.example.test/custom-api",
        )

        self.assertEqual(
            rendered["services"]["frontend"]["build"]["args"][
                "NEXT_PUBLIC_API_URL"
            ],
            "http://localhost:8000/api",
        )
        self.assertEqual(
            custom["services"]["frontend"]["build"]["args"][
                "NEXT_PUBLIC_API_URL"
            ],
            "https://api.example.test/custom-api",
        )

    def test_local_auth_merge_preserves_prefixed_api_base(self) -> None:
        rendered = render_compose(
            "docker-compose.yml",
            "compose.local-auth.yml",
            env_file=LOCAL_AUTH_ENV,
        )
        build_args = rendered["services"]["frontend"]["build"]["args"]

        self.assertEqual(
            build_args["NEXT_PUBLIC_API_URL"],
            "http://localhost:8000/api",
        )
        self.assertEqual(build_args["NEXT_PUBLIC_AUTH_PROVIDER"], "casdoor")

    def test_production_renders_same_origin_default_and_accepts_override(self) -> None:
        rendered = render_compose(
            "deploy/production/compose.yml",
            env_file=PRODUCTION_ENV,
        )
        custom = render_compose(
            "deploy/production/compose.yml",
            env_file=PRODUCTION_ENV,
            api_url="https://api.example.test/custom-api",
        )

        self.assertEqual(
            rendered["services"]["frontend"]["build"]["args"][
                "NEXT_PUBLIC_API_URL"
            ],
            "/api",
        )
        self.assertEqual(
            custom["services"]["frontend"]["build"]["args"][
                "NEXT_PUBLIC_API_URL"
            ],
            "https://api.example.test/custom-api",
        )


if __name__ == "__main__":
    unittest.main()
