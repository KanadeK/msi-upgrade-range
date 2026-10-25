"""Read MSI metadata with native Windows Installer APIs, never install it."""

import ctypes
import os
from pathlib import Path

from .model import FORMAT, MAX_ROWS, PROPERTIES, ROW_KEYS, InputError, validate


class Database:
    def __init__(self, path):
        if os.name != "nt":
            raise InputError(
                "Native MSI reading requires Windows; use exported JSON on this platform"
            )
        # Fully-qualified system library path prevents current-directory DLL search.
        system = ctypes.WinDLL("kernel32", use_last_error=True)
        system.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        system.GetSystemDirectoryW.restype = ctypes.c_uint
        directory = ctypes.create_unicode_buffer(32768)
        length = system.GetSystemDirectoryW(directory, len(directory))
        if not 0 < length < len(directory):
            raise InputError("Cannot locate the Windows system directory")
        self.api = ctypes.WinDLL(str(Path(directory.value) / "msi.dll"), use_last_error=True)
        u = ctypes.c_uint
        h = ctypes.c_uint
        ptr = ctypes.POINTER
        signatures = {
            "MsiOpenDatabaseW": ([ctypes.c_wchar_p, ctypes.c_void_p, ptr(h)], u),
            "MsiDatabaseOpenViewW": ([h, ctypes.c_wchar_p, ptr(h)], u),
            "MsiViewExecute": ([h, h], u),
            "MsiViewFetch": ([h, ptr(h)], u),
            "MsiRecordGetStringW": ([h, u, ctypes.c_wchar_p, ptr(ctypes.c_ulong)], u),
            "MsiRecordIsNull": ([h, u], ctypes.c_int),
            "MsiCloseHandle": ([h], u),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes = args
            function.restype = result
        target = Path(path).absolute()
        if not target.is_file() or target.stat().st_size > 1024 * 1024 * 1024:
            raise InputError("MSI must be a regular local file of at most 1 GiB")
        self.handle = h()
        self.check(
            self.api.MsiOpenDatabaseW(str(target), None, ctypes.byref(self.handle)), "open database"
        )

    @staticmethod
    def check(code, operation):
        if code:
            raise InputError(f"Windows Installer {operation} failed (error {code})")

    def close(self):
        if self.handle.value:
            self.api.MsiCloseHandle(self.handle)
            self.handle.value = 0

    def query(self, sql, columns):
        view = ctypes.c_uint()
        self.check(self.api.MsiDatabaseOpenViewW(self.handle, sql, ctypes.byref(view)), "open view")
        try:
            self.check(self.api.MsiViewExecute(view, 0), "execute read-only view")
            result = []
            while True:
                record = ctypes.c_uint()
                code = self.api.MsiViewFetch(view, ctypes.byref(record))
                if code == 259:  # ERROR_NO_MORE_ITEMS
                    break
                self.check(code, "fetch metadata")
                try:
                    if len(result) >= MAX_ROWS:
                        raise InputError("metadata table exceeds 10000 rows")
                    values = []
                    for column in range(1, columns + 1):
                        if self.api.MsiRecordIsNull(record, column):
                            values.append(None)
                            continue
                        size = ctypes.c_ulong(4097)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        self.check(
                            self.api.MsiRecordGetStringW(
                                record, column, buffer, ctypes.byref(size)
                            ),
                            "read bounded field",
                        )
                        values.append(buffer.value)
                    result.append(values)
                finally:
                    self.api.MsiCloseHandle(record)
            return result
        finally:
            self.api.MsiCloseHandle(view)

    def tables(self):
        return {
            row[0]
            for row in self.query(
                "SELECT " + chr(96) + "Name" + chr(96) + " FROM " + chr(96) + "_Tables" + chr(96), 1
            )
        }


def read_msi(path):
    db = Database(path)
    try:
        tables = db.tables()
        if "Property" not in tables:
            raise InputError("MSI has no Property table")
        quote = chr(96)

        def query(table, fields):
            sql = "SELECT " + ", ".join(quote + field + quote for field in fields)
            sql += " FROM " + quote + table + quote
            return db.query(sql, len(fields))

        props = {
            key: value
            for key, value in query("Property", ("Property", "Value"))
            if key in PROPERTIES
        }
        rows = []
        if "Upgrade" in tables:
            for values in query("Upgrade", ROW_KEYS):
                row = dict(zip(ROW_KEYS, values, strict=True))
                try:
                    row["Attributes"] = int(row["Attributes"])
                except (TypeError, ValueError) as exc:
                    raise InputError("MSI Upgrade.Attributes is not an integer") from exc
                rows.append(row)
        sequence = []
        if "InstallExecuteSequence" in tables:
            for name, condition, number in query(
                "InstallExecuteSequence", ("Action", "Condition", "Sequence")
            ):
                try:
                    sequence.append(
                        {"Action": name, "Condition": condition, "Sequence": int(number)}
                    )
                except (TypeError, ValueError) as exc:
                    raise InputError("MSI Sequence is not an integer") from exc
        rows.sort(key=lambda row: json_key(row))
        sequence.sort(key=lambda row: (row["Sequence"], row["Action"]))
        return validate(
            {
                "format": FORMAT,
                "schema_version": 1,
                "properties": props,
                "upgrade_rows": rows,
                "execute_sequence": sequence,
            }
        )
    finally:
        db.close()


def json_key(row):
    return tuple("" if row[key] is None else str(row[key]) for key in ROW_KEYS)
