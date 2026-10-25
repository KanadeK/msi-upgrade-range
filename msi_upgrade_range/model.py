"""Strict portable metadata and documented Windows Installer range semantics."""

import json
import re
from pathlib import Path

FORMAT = "msi-upgrade-range"
MAX_JSON = 8 * 1024 * 1024
MAX_ROWS = 10_000
PROPERTIES = (
    "ProductCode",
    "UpgradeCode",
    "ProductVersion",
    "ProductLanguage",
    "ALLUSERS",
    "MSIINSTALLPERUSER",
    "SecureCustomProperties",
)
ROW_KEYS = (
    "UpgradeCode",
    "VersionMin",
    "VersionMax",
    "Language",
    "Attributes",
    "Remove",
    "ActionProperty",
)
GUID = re.compile(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?")
KNOWN_FLAGS = 1 | 2 | 4 | 256 | 512 | 1024


class InputError(ValueError):
    """Input is incomplete, unsupported, malformed, or over budget."""


def text(value, label, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or len(value) > 4096 or "\0" in value:
        raise InputError(f"{label} must be a string of at most 4096 characters without NUL")


def guid(value, label):
    text(value, label)
    if not GUID.fullmatch(value):
        raise InputError(f"{label} must be a braced GUID")
    return value.upper()


def version(value, boundary=False):
    text(value, "version")
    if boundary and value == "":
        return (0, 0, 0)
    if len(value) > 64 or not VERSION.fullmatch(value):
        raise InputError("version must be major.minor.build with an optional numeric fourth field")
    parts = [int(x) for x in value.split(".")[:3]]
    if parts[0] > 255 or parts[1] > 255 or parts[2] > 65535:
        raise InputError("MSI version limits are 255.255.65535")
    return tuple(parts)


def language(value):
    text(value, "language")
    if not re.fullmatch(r"[0-9]{1,5}", value) or int(value) > 65535:
        raise InputError("language must be a numeric LANGID from 0 through 65535")
    return int(value)


def languages(value):
    if value is None or value == "":
        return None
    return {language(x.strip()) for x in value.split(",")}


def validate(data):
    if not isinstance(data, dict) or set(data) != {
        "format",
        "schema_version",
        "properties",
        "upgrade_rows",
        "execute_sequence",
    }:
        raise InputError("snapshot must contain exactly the five documented top-level fields")
    if (
        data["format"] != FORMAT
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise InputError("unsupported snapshot format or schema version")
    props = data["properties"]
    if not isinstance(props, dict) or not set(props) <= set(PROPERTIES):
        raise InputError("properties must contain only the documented metadata properties")
    for key, value in props.items():
        text(value, key)
    for key in PROPERTIES[:4]:
        if key not in props:
            raise InputError(f"missing property: {key}")
    guid(props["ProductCode"], "ProductCode")
    guid(props["UpgradeCode"], "UpgradeCode")
    version(props["ProductVersion"])
    language(props["ProductLanguage"])
    rows = data["upgrade_rows"]
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise InputError("upgrade_rows must be an array of at most 10000 rows")
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(ROW_KEYS):
            raise InputError("Upgrade row must have exactly the seven documented columns")
        guid(row["UpgradeCode"], "Upgrade.UpgradeCode")
        for key in ("VersionMin", "VersionMax", "Language", "Remove"):
            text(row[key], key, nullable=True)
        for key in ("VersionMin", "VersionMax"):
            if row[key] is not None:
                version(row[key], boundary=True)
        languages(row["Language"])
        bits = row["Attributes"]
        if type(bits) is not int or bits < 0 or bits & ~KNOWN_FLAGS:
            raise InputError("unsupported Upgrade.Attributes bits")
        text(row["ActionProperty"], "ActionProperty")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", row["ActionProperty"]):
            raise InputError("ActionProperty must be an MSI Identifier")
    sequence = data["execute_sequence"]
    if not isinstance(sequence, list) or len(sequence) > MAX_ROWS:
        raise InputError("execute_sequence must be an array of at most 10000 rows")
    seen = set()
    for action in sequence:
        if not isinstance(action, dict) or set(action) != {"Action", "Condition", "Sequence"}:
            raise InputError("sequence rows require Action, Condition, Sequence")
        text(action["Action"], "Action")
        text(action["Condition"], "Condition", nullable=True)
        if not action["Action"] or action["Action"] in seen:
            raise InputError("sequence Action must be nonempty and unique")
        seen.add(action["Action"])
        if type(action["Sequence"]) is not int or not -32767 <= action["Sequence"] <= 32767:
            raise InputError("Sequence must be an integer in the MSI SHORT range")
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise InputError("snapshot exceeds 8 MiB")
    try:
        return validate(json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError(f"invalid snapshot JSON: {exc}") from exc


def match_row(properties, row):
    """Return an explanation, evaluating all axes independently."""
    bits = row["Attributes"]
    installed = version(properties["ProductVersion"])
    minimum = version(row["VersionMin"], True) if row["VersionMin"] is not None else None
    maximum = version(row["VersionMax"], True) if row["VersionMax"] is not None else None
    allowed = languages(row["Language"])
    checks = {
        "upgrade_code": guid(properties["UpgradeCode"], "UpgradeCode")
        == guid(row["UpgradeCode"], "UpgradeCode"),
        "minimum": minimum is None
        or installed > minimum
        or (installed == minimum and bool(bits & 256)),
        "maximum": maximum is None
        or installed < maximum
        or (installed == maximum and bool(bits & 512)),
        "language": allowed is None
        or ((language(properties["ProductLanguage"]) in allowed) != bool(bits & 1024)),
    }
    matched = all(checks.values())
    removal = "none" if bits & 2 else ("all" if row["Remove"] is None else "runtime-feature-list")
    return {
        "matched": matched,
        "checks": checks,
        "only_detect": bool(bits & 2),
        "removal_scope": removal,
        "action_property": row["ActionProperty"],
    }


def compare(old, new):
    validate(old)
    validate(new)
    before, after = old["properties"], new["properties"]
    findings = []

    def add(code, message, **details):
        findings.append({"code": code, "message": message, **details})

    if guid(before["ProductCode"], "ProductCode") == guid(after["ProductCode"], "ProductCode"):
        add("same-product-code", "A major upgrade requires a different ProductCode.")
    if version(after["ProductVersion"]) <= version(before["ProductVersion"]):
        add(
            "version-not-increased",
            "The candidate is not newer under MSI's three-field version comparison.",
        )
    for side, props in (("old", before), ("new", after)):
        if len(props["ProductVersion"].split(".")) == 4:
            add("ignored-fourth-field", "MSI ignores the fourth ProductVersion field.", source=side)

    # ALLUSERS=2 is decided at runtime; do not guess from package defaults.
    def context(props):
        value = props.get("ALLUSERS", "")
        return "machine" if value == "1" else ("user" if value == "" else "runtime")

    contexts = {"old": context(before), "new": context(after)}
    if "runtime" in contexts.values():
        add(
            "runtime-install-context",
            "ALLUSERS requires runtime context verification.",
            contexts=contexts,
        )
    elif contexts["old"] != contexts["new"]:
        add(
            "install-context-changed",
            "Major upgrades cannot cross user/machine installation contexts.",
            contexts=contexts,
        )

    secure = set(after.get("SecureCustomProperties", "").split(";"))
    used = set()
    evaluated = []
    for index, row in enumerate(new["upgrade_rows"]):
        number = index + 1
        action = row["ActionProperty"]
        if action in used:
            add(
                "reused-action-property",
                "Upgrade rows must use unique ActionProperty values.",
                row=number,
            )
        used.add(action)
        if action.upper() != action:
            add("private-action-property", "ActionProperty must be public (uppercase).", row=number)
        if action not in secure:
            add(
                "unsecured-action-property",
                "ActionProperty is absent from SecureCustomProperties.",
                row=number,
            )
        minimum, maximum = row["VersionMin"], row["VersionMax"]
        if minimum is None and maximum is None:
            add("unbounded-row", "VersionMin and VersionMax may not both be null.", row=number)
        if minimum is not None and maximum is not None:
            lo, hi = version(minimum, True), version(maximum, True)
            inclusive = (row["Attributes"] & (256 | 512)) == (256 | 512)
            if lo > hi or (lo == hi and not inclusive):
                add("empty-version-range", "This Upgrade row cannot match any version.", row=number)
        for field in ("VersionMin", "VersionMax"):
            if row[field] and len(row[field].split(".")) == 4:
                add(
                    "ignored-fourth-field",
                    "MSI ignores the fourth boundary field.",
                    row=number,
                    source=field,
                )
        evaluated.append({"row": number, **match_row(before, row)})

    matched = [item for item in evaluated if item["matched"]]
    removing = [item["row"] for item in matched if not item["only_detect"]]
    full = [item["row"] for item in matched if item["removal_scope"] == "all"]
    if not matched:
        add(
            "old-product-not-detected",
            "No Upgrade row includes the old product's code, version and language.",
        )
    elif not removing:
        add("detect-only", "All matching rows have OnlyDetect; none schedules removal.")
    elif not full:
        add(
            "runtime-removal-scope",
            "Matching removal rows use feature lists or formatted text; full removal is unproven.",
        )

    actions = {item["Action"]: item for item in new["execute_sequence"]}
    for name in ("FindRelatedProducts", "RemoveExistingProducts"):
        action = actions.get(name)
        if action is None or action["Sequence"] <= 0:
            add(
                "missing-execute-action",
                "Action must be scheduled positively in InstallExecuteSequence.",
                action=name,
            )
        elif action["Condition"]:
            add(
                "conditional-execute-action",
                "The action has a runtime condition this checker does not evaluate.",
                action=name,
            )
    find = actions.get("FindRelatedProducts")
    remove = actions.get("RemoveExistingProducts")
    if find and remove and find["Sequence"] >= remove["Sequence"]:
        add("action-order", "FindRelatedProducts must precede RemoveExistingProducts.")
    return {
        "schema_version": 1,
        "ok": not findings,
        "old_product": {key: before[key] for key in PROPERTIES[:4]},
        "new_product": {key: after[key] for key in PROPERTIES[:4]},
        "rows": evaluated,
        "matched_rows": [item["row"] for item in matched],
        "removal_rows": removing,
        "full_removal_rows": full,
        "findings": findings,
    }
