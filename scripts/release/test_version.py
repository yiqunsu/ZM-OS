import json
from pathlib import Path
import tempfile
import unittest
from version import bump, check, prepare


class Versions(unittest.TestCase):
    def test_semver(self):
        for kind, expected in [
            ("patch", "1.1.2"),
            ("minor", "1.2.0"),
            ("major", "2.0.0"),
        ]:
            self.assertEqual(bump("1.1.1", kind), expected)
        for value in ["01.2.3", "1.2", "v1.2.3", "1.2.3-rc1"]:
            with self.assertRaises(ValueError):
                bump(value, "patch")

    def test_prepare_is_repeatable_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend").mkdir()
            (root / "frontend/package.json").write_text('{"version":"0.1.0"}')
            lock = {"version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}
            (root / "frontend/package-lock.json").write_text(json.dumps(lock))
            self.assertEqual(prepare(root, "1.0.0", "minor"), "1.1.0")
            self.assertEqual(prepare(root, "1.0.0", "minor"), "1.1.0")
            (root / "VERSION").write_text("2.0.0\n")
            with self.assertRaises(ValueError):
                check(root)


class ReleasePolicy(unittest.TestCase):
    def test_labels_and_source(self):
        from check_pr import validate

        validate(
            "1.0.0", "1.1.0", ["version:minor", "enhancement"], "development", True
        )
        for labels, version, head, same in [
            ([], "1.1.0", "development", True),
            (["version:minor", "version:patch"], "1.1.0", "development", True),
            (["version:major"], "1.1.0", "development", True),
            (["version:minor"], "1.1.0", "feature", True),
            (["version:minor"], "1.1.0", "development", False),
        ]:
            with self.assertRaises(ValueError):
                validate("1.0.0", version, labels, head, same)


if __name__ == "__main__":
    unittest.main()
