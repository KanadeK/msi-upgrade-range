"""A synthetic metadata fixture, with a good upgrade then an exclusive-boundary bug."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix="msi-upgrade-demo-") as directory:
        new = Path(directory) / "new.json"
        old = HERE / "old.json"
        candidate = json.loads((HERE / "new.json").read_text(encoding="utf-8"))
        new.write_text(json.dumps(candidate), encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "msi_upgrade_range",
            "check",
            "--old",
            str(old),
            "--new",
            str(new),
            "--json",
        ]
        passing = subprocess.run(command, capture_output=True, text=True, check=False)
        if passing.returncode != 0:
            raise RuntimeError(passing.stderr or passing.stdout)
        candidate["upgrade_rows"][0]["VersionMax"] = "1.0.0"
        new.write_text(json.dumps(candidate), encoding="utf-8")
        failing = subprocess.run(command, capture_output=True, text=True, check=False)
        if failing.returncode != 1:
            raise RuntimeError(
                "Expected excluded boundary to fail: " + failing.stdout + failing.stderr
            )
        codes = {x["code"] for x in json.loads(failing.stdout)["comparisons"][0]["findings"]}
        if "old-product-not-detected" not in codes:
            raise RuntimeError("Missing non-detection finding")
        print(
            "PASS: valid upgrade accepted; exclusive upper boundary rejected; temporary data cleaned."
        )


if __name__ == "__main__":
    main()
