# msi-upgrade-range

Explain why a new Windows MSI will or will not **include an older product in its
declared major-upgrade range**, before running an installer.

A candidate may build successfully while its exclusive upper version boundary
excludes the old release. Another trap is changing only the fourth ProductVersion
field: Windows Installer ignores that field. This tool evaluates the compiled
Upgrade table against old package properties and explains each failed match.

Python 3.11+, no runtime dependencies. Native MSI reading requires Windows;
exported JSON comparisons work on Windows, Linux and macOS.
[中文说明](README.zh-CN.md) · [Model and limitations](docs/DESIGN.md)

## Install

~~~sh
git clone https://github.com/KanadeK/msi-upgrade-range.git
cd msi-upgrade-range
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install .
.venv/bin/msi-upgrade-range --version
# Windows PowerShell:
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/msi-upgrade-range.exe --version
~~~

The release wheel can also be installed with pip. This project is not published
to PyPI. From a checkout, python -m msi_upgrade_range works without installation.

## Complete example

Run the checked-in synthetic metadata comparison from the checkout:

~~~sh
python -m msi_upgrade_range check --old examples/old.json --new examples/new.json --json
python examples/demo.py
~~~

The first command exits **0**. The demonstration checks that a valid major-upgrade
range passes, then changes its upper boundary to exclude the old version and
requires exit **1**. It removes its temporary files.

On Windows, inspect real packages directly; no installer actions run:

~~~sh
msi-upgrade-range check --old app-1.0.msi app-1.5.msi --new app-2.0.msi --json
msi-upgrade-range export app-2.0.msi -o app-2.0.metadata.json
~~~

Export the old packages too to compare on another operating system. Existing
export files are refused. Exports contain selected MSI properties and the Upgrade
and InstallExecuteSequence tables, without cabinet payloads or source filesystem
paths. Review metadata before sharing it.

## Results

Each old product has a result containing every new Upgrade row and four explicit
matching decisions: upgrade code, minimum, maximum and language. The report also
distinguishes detection-only rows, removal rows and rows with a null Remove column
(declared full removal).

Checks include:

- Inclusive/exclusive version endpoints, null and empty bounds, ignored fourth fields.
- Language allow/exclude lists and case-insensitive UpgradeCode comparison.
- ProductCode changes, effective version increase and declared installation context.
- OnlyDetect, runtime feature-removal lists, empty version ranges.
- Public and unique ActionProperty names, SecureCustomProperties membership.
- Positive execution-sequence entries for FindRelatedProducts and
  RemoveExistingProducts, their order and unresolved conditions.

Exit **0**: the limited static checks found no issue. Exit **1**: review findings.
Exit **2**: invalid/unreadable/unsupported/over-budget input; no complete check.
JSON reports use schema version 1. Text output escapes untrusted metadata.
All findings fail the check, including uncertain runtime conditions.

## Boundaries

This is a **static range preflight**, not a promise that installation or removal
will succeed. Test real upgrades in disposable machines and run WiX/ICE validation.
It does not model transforms, command-line property overrides, runtime conditions,
installed-product registry state, permissions, custom actions, component rules,
patches, feature selection, launch conditions or the full legal sequencing of
RemoveExistingProducts. Package ProductLanguage may differ from a transformed
installed product. ALLUSERS=2 is reported for runtime review.

The loader opens MSI databases in read-only mode. It never installs, extracts,
executes custom actions, invokes msiexec, reads installed-product registry state,
or contacts the network. A metadata reader is not a sandbox for hostile native
database files.

Limits: 1 GiB per MSI, 8 MiB per JSON snapshot, 10,000 rows per table,
4,096 characters per field and 100 old packages per call. JSON is strict and
duplicate keys are rejected. Versions accept three numeric fields and an optional
ignored numeric fourth field, with MSI limits on the first three.

## Development and evidence

~~~sh
python -m unittest discover -s tests -v
python -m pip install ruff==0.14.2 build==1.3.0
python -m ruff check .
python -m ruff format --check .
python -m build
~~~

Windows tests create actual small MSI databases using Windows Installer APIs,
read them back, and assert their bytes remain unchanged. They do not install a
product. Non-Windows CI tests portable comparisons; native tests are explicitly
skipped there. CI has read-only repository permissions and never commits.

The rules follow Microsoft's [Upgrade table documentation](https://learn.microsoft.com/en-us/windows/win32/msi/upgrade-table)
and [major upgrade guidance](https://learn.microsoft.com/en-us/windows/win32/msi/major-upgrades).
WiX/Orca and VM tests cover broader authoring and execution concerns; this tool
adds a repeatable comparison against specific old release artifacts.

## Cleanup

Uninstall with the virtual environment's python -m pip uninstall msi-upgrade-range.
The program creates no cache or background process. Delete exported metadata you
no longer need, and remove the disposable virtual environment if desired.
MIT licensed; see [LICENSE](LICENSE).

