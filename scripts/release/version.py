"""Single-source release version preparation and validation (standard library only)."""

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def bump(version: str, kind: str) -> str:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("Expected a stable MAJOR.MINOR.PATCH version")
    major, minor, patch = map(int, version.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError("Choose patch, minor or major")


def check(root: Path) -> str:
    version = (root / "VERSION").read_text().strip()
    bump(version, "patch")
    package = json.loads((root / "frontend/package.json").read_text())
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    if any(
        value != version
        for value in (
            package["version"],
            lock["version"],
            lock["packages"][""]["version"],
        )
    ):
        raise ValueError("Frontend version metadata must match VERSION")
    return version


def prepare(root: Path, base: str, kind: str) -> str:
    version = bump(base, kind)
    files = {}
    for filename in ("package.json", "package-lock.json"):
        path = root / "frontend" / filename
        data = json.loads(path.read_text())
        data["version"] = version
        if filename == "package-lock.json":
            data["packages"][""]["version"] = version
        files[path] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for path, data in files.items():
        path.write_text(data)
    (root / "VERSION").write_text(version + "\n")
    return check(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "prepare"])
    parser.add_argument("kind", nargs="?", choices=["patch", "minor", "major"])
    args = parser.parse_args()
    if args.command == "check":
        print(check(ROOT))
        return
    if not args.kind:
        parser.error("prepare requires patch, minor or major")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    if git("branch", "--show-current") != "development":
        raise SystemExit("Prepare releases on development")
    subprocess.run(["git", "fetch", "origin", "main", "--tags"], cwd=ROOT, check=True)
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=ROOT
    ).returncode:
        raise SystemExit("Merge origin/main into development first")
    try:
        base = git("show", "origin/main:VERSION")
    except subprocess.CalledProcessError:
        # Bootstrap: v1.0.0 intentionally points to the already deployed commit.
        if git("rev-parse", "origin/main") != git("rev-parse", "v1.0.0^{commit}"):
            raise SystemExit("main has no VERSION and is not the v1.0.0 baseline")
        base = "1.0.0"
    print(prepare(ROOT, base, args.kind))
    print(
        f"Commit the version changes; open development -> main with label version:{args.kind}."
    )


if __name__ == "__main__":
    main()
