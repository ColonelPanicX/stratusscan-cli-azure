# Contributing to StratusScanCLI-Azure

Thanks for contributing. This document covers everything you need to get set up and submit work.

---

## Table of Contents

- [Getting Set Up](#getting-set-up)
- [Branch Workflow](#branch-workflow)
- [Commit Conventions](#commit-conventions)
- [Pull Request Process](#pull-request-process)
- [Writing an Exporter](#writing-an-exporter)
- [Code Style](#code-style)
- [Project Constraints](#project-constraints)

---

## Getting Set Up

```bash
git clone https://github.com/ColonelPanicX/stratusscan-cli-azure.git
cd stratusscan-cli-azure

# Dev tools + pinned runtime dependencies
pip install -e ".[dev]"
```

StratusScan is not shipped as a package — there are no console entry points, and
`python stratusscan.py` installs the pinned dependencies itself on first run. The
editable install above exists so `pytest` and `ruff` resolve the modules the same
way CI does. Python 3.10 or newer.

You'll need Azure credentials to run the tool. The easiest path is `az login` with the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), or just use [Azure Cloud Shell](https://shell.azure.com) where credentials are injected automatically.

`configure.py` is optional — `stratusscan.py` auto-detects the cloud and discovers
subscriptions on first run. Use the wizard only to narrow or persist a choice.

---

## Branch Workflow

```
main        ← release cuts only, never commit here directly
  └── dev   ← integration branch, all PRs target this
        └── feature/<slug>   your work branch
        └── fix/<slug>
```

**Always branch from `dev`:**

```bash
git checkout dev
git pull origin dev
git checkout -b feature/my-thing
```

**When your work is ready, open a PR from your branch into `dev`.** Never open PRs directly to `main`.

`main` only receives merges from `dev` when a release is being cut.

### Branch naming

| Prefix | Use for |
|---|---|
| `feature/<slug>` | New exporters or capabilities |
| `fix/<slug>` | Bug fixes |
| `refactor/<slug>` | Internal rework with no behavior change |
| `chore/<slug>` | Dependencies, tooling, config |
| `docs/<slug>` | Documentation only |
| `issue-<number>-<slug>` | When directly tied to a GitHub issue |

---

## Commit Conventions

Format: `<type>: <short summary in imperative mood>`

```
feat: add Cosmos DB exporter
fix: handle missing OS disk type on VM export
chore: bump azure-mgmt-compute to 30.1.0
docs: document Government cloud setup in README
refactor: extract NSG rule counter to shared helper
```

**Types:** `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `ci`

Rules:
- Summary line 50 characters or fewer, no trailing period
- Imperative mood: "add" not "added" or "adds"
- Reference issues in the body: `Closes #12`

---

## Pull Request Process

1. Open a PR from your branch into `dev`
2. Fill out the PR template — what changed, why, how it was tested
3. Link the issue it closes: `Closes #N`
4. **CI must be green** — the `Python 3.10`, `Python 3.12` and `Ruff` checks run on every PR
5. Request a review from the other contributor
6. Branch protection on `dev` requires one approval. A maintainer who cannot self-approve
   merges with `gh pr merge --admin` once CI is green; everything still lands on `dev`, never `main`
7. Delete the branch after merge

If you're unsure whether something is ready for review, open a **Draft PR** first. Draft PRs are visible but don't trigger review requests.

---

## Writing an Exporter

Every script in `scripts/` follows the same structure. Copy this pattern exactly:

```python
#!/usr/bin/env python3
"""StratusScanCLI-Azure — My Service Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()  # runner.run_exporter() configures logging — importing must write nothing


def collect_resources(subscription_id: str) -> list:
    client = utils.get_azure_client("myservice", subscription_id)
    log.info("Listing resources in subscription %s", subscription_id)
    return list(client.resource_type.list())  # Azure SDK iterators paginate automatically


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("myservice", environment):
        sys.exit(0)

    resources = collect_resources(subscription_id)
    if not resources:
        raise utils.NoResourcesFound("resources")  # runner prints "No resources found." and exits 3

    rows = []
    for r in resources:
        tags = r.tags or {}
        rows.append({
            "Name": r.name,
            "Resource Group": utils.extract_resource_group(r.id),
            "Location": r.location,
            "Provisioning State": utils.s(r.provisioning_state),
            # ... resource-specific fields ...
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "my-service", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="My Service")
    print(f"Exported {len(rows)} resource(s) → {filename}")
    log.info("Export complete: %d resources", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "my-service")
```

`runner.run_exporter` resolves the target subscription (`STRATUSSCAN_SUBSCRIPTION_ID`, else the configured default), calls `main`, maps the outcome to an exit code, and appends one line to `output/.run-manifest.jsonl`. Do not reintroduce a hand-written `__main__` block: the old form resolved the subscription itself and printed a stale "Run configure.py first" message.

| Exit code | Status | Meaning |
|---|---|---|
| 0 | OK | Workbook written |
| 1 | FAILED | An exception escaped `main` (typed Azure errors print one line and a hint; the traceback goes to `logs/`) |
| 2 | CONFIG | No subscription targeted, unrecognized `AZURE_ENVIRONMENT`, or missing package |
| 3 | EMPTY | `main` raised `utils.NoResourcesFound` — zero resources, no workbook |
| 4 | PARTIAL | Workbook written but at least one parent scope failed — see its `Errors` sheet |

Per-parent loops (containers per storage account, databases per server, …) catch `HttpResponseError` only, append `utils.error_record(scope, operation, exc)` to an `errors` list, and pass that list to `save_dataframe_to_excel(..., errors=errors)` and `utils.ExportResult(..., errors=errors)`. Never catch bare `Exception` around a primary listing: a failed listing must fail the run, not report an empty inventory.

### Key rules for exporters

- **Never call `azure-mgmt-*` clients directly.** Always use `utils.get_azure_client(service_name, subscription_id)`.
- **Importing must have no side effects.** No `setup_logging()`, no `pip`, no API calls at module level — `runner.run_exporter()` configures logging after it resolves the subscription. A test imports every module and fails if anything was written.
- **Never `str()` an SDK attribute.** Use `utils.s(value)` — hybrid SDK models return Enum members, and `str()` renders them as `DiskState.ATTACHED`. Use `utils.extract_resource_group(id)` rather than splitting on `"/resourceGroups/"`, whose casing varies.
- **Never assert a value you did not read.** A column with no data is blank, never a plausible-looking default.
- **Always guard with `is_service_available_in_environment()`** — some services aren't available in Azure US Government.
- **No `print()` or `input()` in `utils.py`.** Exporters and `runner.py` print; menus and prompts live in `cli_ui.py`. `utils.py` returns structured data only, and a test enforces it.
- **Azure `.list()` methods return lazy iterators** — wrap in `list()` to materialize, or iterate directly for large sets.
- **Tags always go last** in the column order.
- **Script filenames:** `lowercase_underscored.py`

### Where to put it

All exporter scripts live in `scripts/` (flat directory, no subdirs). Name the file `{resource_type}_export.py`.

After adding the script, register it in `stratusscan.py` under the appropriate tier (`TIER1_EXPORTERS`, `TIER2_EXPORTERS`, `GOVERNANCE_EXPORTERS`, or `MONITORING_EXPORTERS`).

---

## Code Style

The project uses [ruff](https://github.com/astral-sh/ruff) for linting and [black](https://github.com/psf/black) for formatting.

```bash
ruff check .    # must report zero findings; CI fails otherwise
black .
```

Config lives in `pyproject.toml`. Line length is 100. Annotations use PEP 604
(`X | None`, `list[str]`) — the floor is Python 3.10.

---

## Tests

The suite is offline: no Azure credentials, no network. Run it on **both**
supported interpreters, because the SDK resolves differently across them:

```bash
python3.10 -m pytest -q tests/
python3.12 -m pytest -q tests/
```

CI runs the same two plus ruff on every PR.

| File | Pins |
|---|---|
| `tests/test_sdk_contract.py` | Every client class, operation group and model attribute the exporters use. Skips when the SDK is absent. **Run this first when bumping an SDK cap.** |
| `tests/test_exporter_contract.py` | The exporter pattern in all 70 scripts, and `registry == disk` |
| `tests/test_exporter_smoke.py` | Every `main()` against an empty fake client; asserts importing writes nothing |
| `tests/test_runner.py`, `test_orchestrator.py` | Exit codes, run manifest, run report, timeout, Ctrl-C |

New exporter → it is picked up by the contract and smoke tests automatically once
registered. Add targeted tests for any column whose value is derived rather than
copied.

### Dependency policy

Every `azure-*` dependency is capped to a validated major (`>=X,<X+1`). The Azure
SDK is mid-migration to hybrid models, so an uncapped bump can silently blank a
column. To bump one: raise the cap, run `tests/test_sdk_contract.py` against it,
then the full suite on both interpreters. `azure-mgmt-monitor` is held `<7`
because 7.x dropped the `diagnostic_settings` operations.

No comments explaining what code does — name things well instead. A comment is only warranted when the *why* is non-obvious: a hidden constraint, a workaround for a specific SDK bug, or a subtle behavioral edge case.

---

## Project Constraints

These are non-negotiable and apply to all contributions:

**CloudShell-first** — the tool must work in a fresh Azure Cloud Shell session with nothing but `git clone` and `python stratusscan.py`. If a proposed change breaks this, it will be rejected.

**Minimal dependencies** — stick to `azure-identity`, `azure-mgmt-*` and `azure-keyvault-*` (per service), `pandas`, `openpyxl`. No heavy frameworks. No lockfiles. No build tools. A new dependency needs a reason in the PR.

**Subprocess architecture** — `stratusscan.py` launches exporters as subprocesses. It never calls Azure APIs directly. Don't break this boundary.

**CI mode** — every interactive prompt must check `utils.is_auto_run()` before displaying. `STRATUSSCAN_AUTO_RUN=1` must bypass all prompts.

**No print() in utils.py** — `utils.py` is a shared library. Functions return structured results. Console output lives in `stratusscan.py`, `configure.py`, `runner.py` and the exporters.

**Failure is never reported as empty** — a failed listing must fail the run. Per-parent failures are recorded in the `Errors` sheet and exit 4. Only a genuinely empty inventory exits 3.

When in doubt about any of these, open an issue and discuss before writing code.
