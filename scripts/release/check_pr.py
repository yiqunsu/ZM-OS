"""Validate the exact base/head snapshot of a release PR; never trust its title as code."""

import json
import os
from pathlib import Path
import subprocess
from version import bump, check, ROOT


def validate(base, candidate, labels, head, same_repository):
    kinds = [
        label.removeprefix("version:")
        for label in labels
        if label.startswith("version:")
    ]
    if head != "development" or not same_repository:
        raise ValueError("main only accepts this repository's development branch")
    if len(kinds) != 1 or kinds[0] not in ("patch", "minor", "major"):
        raise ValueError(
            "Choose exactly one version:patch, version:minor or version:major label"
        )
    if candidate != bump(base, kinds[0]):
        raise ValueError("VERSION does not match the selected label and main version")


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr = event["pull_request"]

    def git(*args):
        return subprocess.check_output(["git", *args], text=True, cwd=ROOT).strip()

    sha = pr["base"]["sha"]
    try:
        base = git("show", f"{sha}:VERSION")
    except subprocess.CalledProcessError:
        if sha != git("rev-parse", "v1.0.0^{commit}"):
            raise ValueError("Missing main VERSION outside bootstrap release")
        base = "1.0.0"
    validate(
        base,
        check(ROOT),
        [x["name"] for x in pr["labels"]],
        pr["head"]["ref"],
        pr["head"]["repo"]["full_name"] == pr["base"]["repo"]["full_name"],
    )
    print("Release PR version and source branch are valid")


if __name__ == "__main__":
    main()
