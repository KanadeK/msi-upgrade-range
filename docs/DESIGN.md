# Scope, model and acceptance

Target user: a maintainer publishing MSI major upgrades with a history of old
release artifacts. Acceptance: export actual MSI tables without changing the
database; an intended range passes and an excluded boundary fails with an
explanation; malformed data fails visibly.

The portable schema is illustrated by examples/old.json and examples/new.json.
It has exactly format, schema_version, properties, upgrade_rows, execute_sequence.
Rows use MSI column names. JSON null preserves a missing database field.
An empty string remains distinct in portable inputs. Native MSI's own string
storage and MsiRecordIsNull determine what is exported.

Architecture: native.py uses typed ctypes bindings to msi.dll; model.py validates
portable snapshots and evaluates ranges; cli.py controls bounded file input,
exclusive export creation and exit codes. No subprocess or package execution is
used by the product. Tests and the demonstration invoke our own CLI.

Comparison assumes candidate major-upgrade intent, not a minor update or deliberate
downgrade. A different candidate UpgradeCode property is allowed when its Upgrade
table explicitly targets the old family. Individual row GUID comparison is
case-insensitive. A fourth numeric version field is reported even when harmless.

The result lists all matching rows rather than selecting one. Any matched row with
OnlyDetect clear is a removal candidate. Null Remove means declared full removal;
a non-null field requires runtime review. These are metadata facts, not proof of
execution. The two relevant execute actions must be positively sequenced in order.
Other standard action ordering constraints are delegated to ICE and execution tests.

All rows, not only matched ones, undergo structural policy checks. All findings
cause exit 1; there is no suppression mechanism in v0.1.0. Input schema errors,
unknown flags or I/O failures cause exit 2. Reports are deterministic for identical
snapshots and do not include clock times or input paths.

Safety review: fixed SELECT statements only; read-only database mode; explicit
field/row/size limits; system-directory DLL path; closed handles even on errors;
no input-driven SQL; no network or registry reads; JSON duplicate-key rejection.
The Windows database parser is outside this program's implementation. Do not
treat this tool as a hostile-MSI isolation boundary.

No source code, fixture or binary from a third-party project is vendored. All
fixtures are original synthetic metadata. Runtime depends only on Python and,
for MSI export, the Windows Installer API. Build/development tools are separate
dependencies and are not redistributed as program code.

