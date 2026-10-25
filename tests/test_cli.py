import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_model import snapshot
from test_native import make_database


class CLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "msi_upgrade_range", *map(str, args)],
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_core_flow_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old.json", Path(directory) / "new.json"
            old.write_text(json.dumps(snapshot()), encoding="utf-8")
            new.write_text(json.dumps(snapshot(True)), encoding="utf-8")
            result = self.run_cli("check", "--new", new, "--old", old, "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])
            data = snapshot(True)
            data["upgrade_rows"][0]["VersionMax"] = "0.5.0"
            new.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_cli("check", "--new", new, "--old", old, "--json")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])
            new.write_text("null", encoding="utf-8")
            result = self.run_cli("check", "--new", new, "--old", old, "--json")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stderr)["complete"])

    @unittest.skipUnless(os.name == "nt", "Native export requires Windows")
    def test_export_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            msi, output = Path(directory) / "new.msi", Path(directory) / "new.json"
            make_database(msi, new=True)
            result = self.run_cli("export", msi, "-o", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text()), snapshot(True))
            initial = output.read_bytes()
            self.assertEqual(self.run_cli("export", msi, "-o", output).returncode, 2)
            self.assertEqual(initial, output.read_bytes())

    def test_missing_file(self):
        result = self.run_cli("check", "--new", "nonexistent.json", "--old", "old.json")
        self.assertEqual(result.returncode, 2)

    def test_version(self):
        result = self.run_cli("--version")
        self.assertEqual(result.stdout.strip(), "0.1.0")
        self.assertEqual(result.returncode, 0)
