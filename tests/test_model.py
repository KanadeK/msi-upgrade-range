import copy
import json
import tempfile
import unittest
from pathlib import Path

from msi_upgrade_range.model import InputError, compare, load_json, match_row, validate, version

OLD_CODE = "{00000000-0000-0000-0000-000000000001}"
NEW_CODE = "{00000000-0000-0000-0000-000000000002}"
FAMILY = "{10000000-0000-0000-0000-000000000001}"


def snapshot(new=False):
    return {
        "format": "msi-upgrade-range",
        "schema_version": 1,
        "properties": {
            "ProductCode": NEW_CODE if new else OLD_CODE,
            "UpgradeCode": FAMILY,
            "ProductVersion": "2.0.0" if new else "1.0.0",
            "ProductLanguage": "1033",
            "ALLUSERS": "1",
            "SecureCustomProperties": "OLDPRODUCTS",
        },
        "upgrade_rows": [
            {
                "UpgradeCode": FAMILY,
                "VersionMin": "0.0.0",
                "VersionMax": "2.0.0",
                "Language": None,
                "Attributes": 256,
                "Remove": None,
                "ActionProperty": "OLDPRODUCTS",
            }
        ]
        if new
        else [],
        "execute_sequence": [
            {"Action": "FindRelatedProducts", "Condition": None, "Sequence": 200},
            {"Action": "RemoveExistingProducts", "Condition": None, "Sequence": 1450},
        ]
        if new
        else [],
    }


def codes(result):
    return {finding["code"] for finding in result["findings"]}


class ModelTests(unittest.TestCase):
    def test_valid_major_upgrade(self):
        result = compare(snapshot(), snapshot(True))
        self.assertTrue(result["ok"])
        self.assertEqual(result["full_removal_rows"], [1])

    def test_no_mutation(self):
        old, new = snapshot(), snapshot(True)
        original = copy.deepcopy((old, new))
        compare(old, new)
        self.assertEqual((old, new), original)

    def test_endpoints_exhaustive(self):
        new = snapshot(True)
        row = new["upgrade_rows"][0]
        row.update(VersionMin="1.0.0", VersionMax="1.0.2")
        for low_in in (False, True):
            for high_in in (False, True):
                row["Attributes"] = 256 * low_in + 512 * high_in
                for build in range(4):
                    old = snapshot()["properties"]
                    old["ProductVersion"] = f"1.0.{build}"
                    expected = (build > 0 or low_in) and (build < 2 or (build == 2 and high_in))
                    with self.subTest(low_in=low_in, high_in=high_in, build=build):
                        self.assertEqual(match_row(old, row)["matched"], expected)

    def test_null_boundaries_ignore_flags(self):
        row = snapshot(True)["upgrade_rows"][0]
        row.update(VersionMin=None, VersionMax="1.0.0", Attributes=512)
        self.assertTrue(match_row(snapshot()["properties"], row)["matched"])
        row.update(VersionMin="1.0.0", VersionMax=None, Attributes=256)
        self.assertTrue(match_row(snapshot()["properties"], row)["matched"])

    def test_empty_boundary_is_zero(self):
        row = snapshot(True)["upgrade_rows"][0]
        row.update(VersionMin="", VersionMax="1.0.0", Attributes=512)
        old = snapshot()["properties"]
        old["ProductVersion"] = "0.0.0"
        self.assertFalse(match_row(old, row)["matched"])
        row["VersionMin"] = None
        self.assertTrue(match_row(old, row)["matched"])

    def test_language_inclusion_exclusion_and_empty(self):
        row = snapshot(True)["upgrade_rows"][0]
        row["Language"] = "1033, 1041"
        self.assertTrue(match_row(snapshot()["properties"], row)["matched"])
        row["Attributes"] |= 1024
        self.assertFalse(match_row(snapshot()["properties"], row)["matched"])
        for value in ("", None):
            row["Language"] = value
            self.assertTrue(match_row(snapshot()["properties"], row)["matched"])

    def test_different_upgrade_code_explanation(self):
        new = snapshot(True)
        new["upgrade_rows"][0]["UpgradeCode"] = NEW_CODE
        result = compare(snapshot(), new)
        self.assertIn("old-product-not-detected", codes(result))
        self.assertFalse(result["rows"][0]["checks"]["upgrade_code"])
        self.assertTrue(result["rows"][0]["checks"]["minimum"])

    def test_guid_case_is_insensitive(self):
        old, new = snapshot(), snapshot(True)
        old["properties"]["UpgradeCode"] = "{ABCDEF00-0000-0000-0000-000000000001}"
        new["upgrade_rows"][0]["UpgradeCode"] = old["properties"]["UpgradeCode"].lower()
        self.assertTrue(compare(old, new)["ok"])

    def test_new_upgradecode_can_migrate_an_old_family(self):
        new = snapshot(True)
        new["properties"]["UpgradeCode"] = NEW_CODE
        self.assertTrue(compare(snapshot(), new)["ok"])

    def test_only_detect_is_not_removal(self):
        new = snapshot(True)
        new["upgrade_rows"][0]["Attributes"] |= 2
        result = compare(snapshot(), new)
        self.assertEqual(result["matched_rows"], [1])
        self.assertEqual(result["removal_rows"], [])
        self.assertIn("detect-only", codes(result))

    def test_feature_list_is_runtime_not_full_removal(self):
        for value in ("", "[REMOVE_FEATURES]", "Core"):
            new = snapshot(True)
            new["upgrade_rows"][0]["Remove"] = value
            result = compare(snapshot(), new)
            self.assertIn("runtime-removal-scope", codes(result))
            self.assertEqual(result["full_removal_rows"], [])

    def test_fourth_field_ignored(self):
        old, new = snapshot(), snapshot(True)
        old["properties"]["ProductVersion"] = "1.0.0.1"
        new["properties"]["ProductVersion"] = "1.0.0.99"
        new["upgrade_rows"][0]["VersionMax"] = "1.0.0.99"
        result = compare(old, new)
        self.assertIn("ignored-fourth-field", codes(result))
        self.assertIn("version-not-increased", codes(result))
        self.assertIn("old-product-not-detected", codes(result))

    def test_invalid_version_limits(self):
        for value in ("256.0.0", "0.256.0", "0.0.65536", "1.2", "1.2.3-rc", "1.2.3.4.5"):
            with self.subTest(value=value), self.assertRaises(InputError):
                version(value)

    def test_same_product_code(self):
        new = snapshot(True)
        new["properties"]["ProductCode"] = OLD_CODE
        self.assertIn("same-product-code", codes(compare(snapshot(), new)))

    def test_context_change_and_runtime(self):
        new = snapshot(True)
        del new["properties"]["ALLUSERS"]
        self.assertIn("install-context-changed", codes(compare(snapshot(), new)))
        new["properties"]["ALLUSERS"] = "2"
        self.assertIn("runtime-install-context", codes(compare(snapshot(), new)))

    def test_unbounded_and_inverted_rows(self):
        new = snapshot(True)
        new["upgrade_rows"][0].update(VersionMin=None, VersionMax=None)
        self.assertIn("unbounded-row", codes(compare(snapshot(), new)))
        new["upgrade_rows"][0].update(VersionMin="3.0.0", VersionMax="2.0.0")
        self.assertIn("empty-version-range", codes(compare(snapshot(), new)))

    def test_missing_or_conditional_sequence(self):
        new = snapshot(True)
        new["execute_sequence"] = []
        self.assertIn("missing-execute-action", codes(compare(snapshot(), new)))
        new = snapshot(True)
        new["execute_sequence"][1]["Condition"] = "CUSTOM=1"
        self.assertIn("conditional-execute-action", codes(compare(snapshot(), new)))

    def test_action_order(self):
        new = snapshot(True)
        new["execute_sequence"][0]["Sequence"] = 2000
        self.assertIn("action-order", codes(compare(snapshot(), new)))

    def test_action_properties(self):
        new = snapshot(True)
        new["upgrade_rows"].append(copy.deepcopy(new["upgrade_rows"][0]))
        self.assertIn("reused-action-property", codes(compare(snapshot(), new)))
        new["upgrade_rows"][0]["ActionProperty"] = "Private"
        result = compare(snapshot(), new)
        self.assertIn("private-action-property", codes(result))
        self.assertIn("unsecured-action-property", codes(result))

    def test_strict_schema(self):
        for modify in (
            lambda d: d.update(schema_version=True),
            lambda d: d.update(extra=1),
            lambda d: d["properties"].update(ProductLanguage="-1"),
            lambda d: d["properties"].update(ProductCode="not-guid"),
            lambda d: d["properties"].update(Secret="not allowed"),
            lambda d: d["upgrade_rows"][0].update(Attributes=True),
            lambda d: d["upgrade_rows"][0].update(Attributes=8),
            lambda d: d["upgrade_rows"][0].update(Language="1033,"),
            lambda d: d["execute_sequence"][0].update(Sequence=True),
            lambda d: d["execute_sequence"].append(copy.deepcopy(d["execute_sequence"][0])),
        ):
            data = snapshot(True)
            modify(data)
            with self.assertRaises(InputError):
                validate(data)

    def test_duplicate_json_keys_and_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"format":"a","format":"b"}', encoding="utf-8")
            with self.assertRaises(InputError):
                load_json(path)
            path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
            with self.assertRaises(InputError):
                load_json(path)

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.json"
            path.write_text(json.dumps(snapshot(True)), encoding="utf-8")
            self.assertEqual(load_json(path), snapshot(True))
