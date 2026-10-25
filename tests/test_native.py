"""Create actual MSI databases, without invoking any installation action."""

import ctypes
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from test_model import snapshot

from msi_upgrade_range.model import InputError, compare
from msi_upgrade_range.native import read_msi


def make_database(path, new=False):
    api = ctypes.WinDLL("msi.dll")
    handle = ctypes.c_uint()
    api.MsiOpenDatabaseW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    api.MsiDatabaseOpenViewW.argtypes = [
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    api.MsiViewExecute.argtypes = [ctypes.c_uint, ctypes.c_uint]
    api.MsiDatabaseCommit.argtypes = [ctypes.c_uint]
    api.MsiCloseHandle.argtypes = [ctypes.c_uint]

    def checked(code):
        if code:
            raise AssertionError(f"fixture MSI API failure {code}")

    checked(api.MsiOpenDatabaseW(str(path), ctypes.c_void_p(3), ctypes.byref(handle)))
    try:

        def execute(sql):
            view = ctypes.c_uint()
            checked(api.MsiDatabaseOpenViewW(handle, sql, ctypes.byref(view)))
            try:
                checked(api.MsiViewExecute(view, 0))
            finally:
                api.MsiCloseHandle(view)

        q = chr(96)

        def ident(name):
            return q + name + q

        def table(name, declaration):
            execute("CREATE TABLE " + ident(name) + " (" + declaration + ")")

        def insert(name, names, values):
            entries = [
                "NULL"
                if value is None
                else (
                    str(value) if isinstance(value, int) else "'" + value.replace("'", "''") + "'"
                )
                for value in values
            ]
            execute(
                "INSERT INTO "
                + ident(name)
                + " ("
                + ", ".join(map(ident, names))
                + ") VALUES ("
                + ", ".join(entries)
                + ")"
            )

        table(
            "Property",
            f"{ident('Property')} CHAR(72) NOT NULL, {ident('Value')} CHAR(0) LOCALIZABLE PRIMARY KEY {ident('Property')}",
        )
        data = snapshot(new)
        for key, value in data["properties"].items():
            insert("Property", ["Property", "Value"], [key, value])
        insert("Property", ["Property", "Value"], ["PRIVATE_TEST_VALUE", "must-not-be-exported"])
        if new:
            table(
                "Upgrade",
                ", ".join(
                    [
                        f"{ident('UpgradeCode')} CHAR(38) NOT NULL",
                        f"{ident('VersionMin')} CHAR(20)",
                        f"{ident('VersionMax')} CHAR(20)",
                        f"{ident('Language')} CHAR(255)",
                        f"{ident('Attributes')} SHORT NOT NULL",
                        f"{ident('Remove')} CHAR(255)",
                        f"{ident('ActionProperty')} CHAR(72) NOT NULL",
                    ]
                )
                + " PRIMARY KEY "
                + ", ".join(
                    map(
                        ident, ["UpgradeCode", "VersionMin", "VersionMax", "Language", "Attributes"]
                    )
                ),
            )
            for row in data["upgrade_rows"]:
                insert("Upgrade", list(row), list(row.values()))
            table(
                "InstallExecuteSequence",
                f"{ident('Action')} CHAR(72) NOT NULL, {ident('Condition')} CHAR(255), {ident('Sequence')} SHORT PRIMARY KEY {ident('Action')}",
            )
            for row in data["execute_sequence"]:
                insert("InstallExecuteSequence", list(row), list(row.values()))
        checked(api.MsiDatabaseCommit(handle))
    finally:
        api.MsiCloseHandle(handle)


@unittest.skipUnless(os.name == "nt", "Native MSI API requires Windows")
class NativeTests(unittest.TestCase):
    def test_real_database_export_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old.msi", Path(directory) / "new.msi"
            make_database(old)
            make_database(new, new=True)
            before = [hashlib.sha256(path.read_bytes()).digest() for path in (old, new)]
            old_snapshot, new_snapshot = read_msi(old), read_msi(new)
            self.assertEqual(old_snapshot, snapshot())
            self.assertEqual(new_snapshot, snapshot(True))
            self.assertTrue(compare(old_snapshot, new_snapshot)["ok"])
            self.assertEqual(
                before, [hashlib.sha256(path.read_bytes()).digest() for path in (old, new)]
            )

    def test_invalid_msi_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.msi"
            path.write_bytes(b"Not an MSI")
            with self.assertRaises(InputError):
                read_msi(path)


class PlatformTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Non-Windows error path")
    def test_non_windows_native_error(self):
        with self.assertRaisesRegex(InputError, "requires Windows"):
            read_msi("anything.msi")
