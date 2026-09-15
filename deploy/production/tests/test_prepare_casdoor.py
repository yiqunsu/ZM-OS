from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "deploy/production/scripts/prepare-casdoor.py"
VALIDATOR = REPO_ROOT / "deploy/production/scripts/validate-env.sh"


def base_environment(runtime_dir: Path) -> dict[str, str]:
    return {
        "CASDOOR_RUNTIME_DIR": str(runtime_dir),
        "CASDOOR_ISSUER": "https://auth.zmorder.cn",
        "CASDOOR_DB_USER": "casdoor",
        "CASDOOR_DB_PASSWORD": "database-password-for-test-only",
        "CASDOOR_DB": "casdoor",
        "CASDOOR_OWNER_NAME": "owner",
        "CASDOOR_OWNER_EMAIL": "owner@zmorder.cn",
        "CASDOOR_OWNER_PASSWORD": "owner-password-for-test-only",
        "APP_PUBLIC_URL": "https://app.zmorder.cn",
        "CASDOOR_REDIRECT_URI": "https://app.zmorder.cn/api/auth/callback/casdoor",
        "CASDOOR_CLIENT_ID": "filmos-client-id-for-test",
        "CASDOOR_CLIENT_SECRET": "filmos-client-secret-for-test",
        "CASDOOR_ADMIN_PASSWORD": "admin-password-for-test-only",
        "CASDOOR_ADMIN_EMAIL": "admin@zmorder.cn",
    }


class PrepareCasdoorTests(unittest.TestCase):
    def run_generator(
        self,
        runtime_dir: Path,
        additions: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(base_environment(runtime_dir))
        environment.update(additions or {})
        return subprocess.run(
            ["python3", str(SCRIPT)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_wechat_disabled_preserves_password_only_login(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "runtime"
            result = self.run_generator(runtime_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            init_data = json.loads((runtime_dir / "init_data.json").read_text())
            application = init_data["applications"][0]
            self.assertEqual(init_data["providers"], [])
            self.assertEqual(application["providers"], [])
            self.assertEqual(
                application["signinMethods"],
                [{"name": "Password", "displayName": "密码", "rule": "All"}],
            )

    def test_wechat_enabled_generates_invite_only_web_provider(self) -> None:
        app_secret = "0123456789abcdef0123456789abcdef"
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "runtime"
            result = self.run_generator(
                runtime_dir,
                {
                    "WECHAT_LOGIN_ENABLED": "true",
                    "WECHAT_OPEN_APP_ID": "wx0123456789abcdef",
                    "WECHAT_OPEN_APP_SECRET": app_secret,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(app_secret, result.stdout)
            self.assertNotIn(app_secret, result.stderr)
            init_path = runtime_dir / "init_data.json"
            init_data = json.loads(init_path.read_text())
            provider = init_data["providers"][0]
            self.assertEqual(provider["type"], "WeChat")
            self.assertEqual(provider["subType"], "Web")
            self.assertEqual(provider["clientId"], "wx0123456789abcdef")
            self.assertEqual(provider["clientSecret"], app_secret)

            application = init_data["applications"][0]
            self.assertFalse(application["enableSignUp"])
            self.assertEqual(
                application["providers"],
                [
                    {
                        "owner": "admin",
                        "name": "provider-wechat-web",
                        "canSignUp": False,
                        "canSignIn": True,
                        "canUnlink": True,
                        "bindingRule": [],
                        "prompted": False,
                        "signupGroup": "",
                        "rule": "None",
                    }
                ],
            )
            self.assertEqual(
                [method["name"] for method in application["signinMethods"]],
                ["Password", "WeChat"],
            )
            self.assertEqual(stat.S_IMODE(init_path.stat().st_mode), 0o600)

    def test_wechat_enabled_requires_both_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "runtime"
            result = self.run_generator(
                runtime_dir,
                {
                    "WECHAT_LOGIN_ENABLED": "true",
                    "WECHAT_OPEN_APP_ID": "wx0123456789abcdef",
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WECHAT_OPEN_APP_SECRET is required", result.stderr)

    def test_wechat_flag_rejects_ambiguous_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "runtime"
            result = self.run_generator(
                runtime_dir,
                {"WECHAT_LOGIN_ENABLED": "yes"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WECHAT_LOGIN_ENABLED must be true or false", result.stderr)

    def test_wechat_secret_is_not_part_of_frontend_configuration(self) -> None:
        frontend_boundaries = [
            REPO_ROOT / "frontend/auth.ts",
            REPO_ROOT / "frontend/Dockerfile",
            REPO_ROOT / "deploy/production/frontend.Dockerfile",
            REPO_ROOT / "deploy/production/compose.yml",
        ]
        for path in frontend_boundaries:
            with self.subTest(path=path):
                self.assertNotIn("WECHAT_OPEN_APP_SECRET", path.read_text())


class ValidateEnvironmentTests(unittest.TestCase):
    def run_validator(
        self,
        temporary: str,
        *,
        public: bool,
        wechat_enabled: str,
        include_wechat_secret: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        root = Path(temporary)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake_docker = fake_bin / "docker"
        fake_docker.write_text("#!/bin/sh\nexit 0\n")
        fake_docker.chmod(0o700)

        if public:
            addresses = {
                "WEB_BIND_IP": "0.0.0.0",
                "APP_SITE_ADDRESS": "app.zmorder.cn",
                "AUTH_SITE_ADDRESS": "auth.zmorder.cn",
                "APP_PUBLIC_URL": "https://app.zmorder.cn",
                "NEXTAUTH_URL": "https://app.zmorder.cn",
                "CASDOOR_ISSUER": "https://auth.zmorder.cn",
                "CASDOOR_REDIRECT_URI": "https://app.zmorder.cn/api/auth/callback/casdoor",
            }
        else:
            addresses = {
                "WEB_BIND_IP": "127.0.0.1",
                "APP_SITE_ADDRESS": "http://app.filmos.test",
                "AUTH_SITE_ADDRESS": "http://auth.filmos.test",
                "APP_PUBLIC_URL": "http://app.filmos.test:8080",
                "NEXTAUTH_URL": "http://app.filmos.test:8080",
                "CASDOOR_ISSUER": "http://auth.filmos.test:8080",
                "CASDOOR_REDIRECT_URI": "http://app.filmos.test:8080/api/auth/callback/casdoor",
            }

        values = {
            **addresses,
            "POSTGRES_USER": "filmos",
            "POSTGRES_PASSWORD": "a" * 48,
            "POSTGRES_DB": "filmos",
            "AUTH_SECRET": "b" * 64,
            "CASDOOR_DB_USER": "casdoor",
            "CASDOOR_DB_PASSWORD": "c" * 48,
            "CASDOOR_DB": "casdoor",
            "CASDOOR_CLIENT_ID": "d" * 32,
            "CASDOOR_CLIENT_SECRET": "e" * 64,
            "CASDOOR_ADMIN_EMAIL": "admin@zmorder.cn",
            "CASDOOR_ADMIN_PASSWORD": "f" * 24,
            "CASDOOR_OWNER_NAME": "owner",
            "CASDOOR_OWNER_EMAIL": "owner@zmorder.cn",
            "CASDOOR_OWNER_PASSWORD": "g" * 24,
            "LLM_API_KEY": "model-test-key",
            "WECHAT_LOGIN_ENABLED": wechat_enabled,
            "WECHAT_OPEN_APP_ID": "wx0123456789abcdef",
            "WECHAT_OPEN_APP_SECRET": (
                "0123456789abcdef0123456789abcdef" if include_wechat_secret else ""
            ),
        }
        env_file = root / "production.env"
        env_file.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        env_file.chmod(0o600)

        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["FILMOS_ENV_FILE"] = str(env_file)
        return subprocess.run(
            ["bash", str(VALIDATOR)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_disabled_wechat_is_valid_in_private_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_validator(
                temporary,
                public=False,
                wechat_enabled="false",
                include_wechat_secret=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_enabled_wechat_requires_public_https_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_validator(
                temporary,
                public=False,
                wechat_enabled="true",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires public HTTPS mode", result.stderr)

    def test_enabled_wechat_requires_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_validator(
                temporary,
                public=True,
                wechat_enabled="true",
                include_wechat_secret=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WECHAT_OPEN_APP_SECRET must be set", result.stderr)

    def test_enabled_wechat_is_valid_in_public_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_validator(
                temporary,
                public=True,
                wechat_enabled="true",
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
