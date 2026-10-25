import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .model import InputError, compare, load_json
from .native import read_msi


def load(path):
    return read_msi(path) if Path(path).suffix.lower() == ".msi" else load_json(path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check MSI major-upgrade range coverage without installing."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser(
        "export", help="Read Windows MSI metadata into a portable JSON snapshot."
    )
    export.add_argument("msi")
    export.add_argument("-o", "--output", required=True)
    check = commands.add_parser(
        "check", help="Check a candidate against one or more older MSI/JSON files."
    )
    check.add_argument("--new", required=True)
    check.add_argument("--old", nargs="+", required=True)
    check.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            data = read_msi(args.msi)
            encoded = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
            with Path(args.output).open("x", encoding="utf-8", newline="\n") as output:
                output.write(encoded)
            print("Exported portable MSI metadata.")
            return 0
        if len(args.old) > 100:
            raise InputError("at most 100 old packages per check")
        new = load(args.new)
        results = [compare(load(path), new) for path in args.old]
        ok = all(result["ok"] for result in results)
        if args.json:
            print(json.dumps({"schema_version": 1, "ok": ok, "comparisons": results}, indent=2))
        else:
            for result in results:
                identity = json.dumps(result["old_product"], ensure_ascii=True)
                print(("PASS " if result["ok"] else "REVIEW ") + identity)
                for finding in result["findings"]:
                    print(json.dumps(finding, ensure_ascii=True))
        return 0 if ok else 1
    except (InputError, OSError, ValueError, RecursionError) as exc:
        print(
            json.dumps({"error": str(exc), "complete": False}, ensure_ascii=True), file=sys.stderr
        )
        return 2
