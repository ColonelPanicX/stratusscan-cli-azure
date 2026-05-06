# Contributing to StratusScan-Azure

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

# Install runtime dependencies (Cloud Shell preinstalls most of these)
pip install --user azure-identity azure-mgmt-resource azure-mgmt-resourcegraph \
    azure-mgmt-subscription azure-mgmt-authorization azure-mgmt-policyinsights \
    pandas openpyxl requests

# Or install everything including dev tools
pip install -e ".[dev]"
```

You'll need Azure credentials to run the tool. The easiest path is `az login` with the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), or just use [Azure Cloud Shell](https://shell.azure.com) where credentials are injected automatically.

Run the config wizard before first use:

```bash
python configure.py
```

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
feat: add Cost Management exporter
fix: handle missing tenant_id on older subscription models
chore: bump azure-mgmt-resourcegraph to 8.1.0
docs: document Government cloud setup in README
refactor: extract Graph pagination into sslib.graph
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
4. Request a review from the other contributor
5. **One approval is required before merging** (enforced by branch protection)
6. Merge with squash (`--squash`) to keep `dev` history clean
7. Delete the branch after merge

If you're unsure whether something is ready for review, open a **Draft PR** first. Draft PRs are visible but don't trigger review requests.

---

## Writing an Exporter

Every script in `scripts/` runs independently and follows the same shape. Copy this skeleton:

```python
#!/usr/bin/env python3
"""StratusScan-Azure — My Service Export."""

import logging
import sys
from pathlib import Path
from typing import Dict, List

# Allow running as a script from /scripts/
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sslib.auth import get_credential, quiet_azure_loggers
from sslib.cloud import detect_cloud
from sslib.config import load_config
from sslib.output import make_filename, save_dataframes
from sslib.subscriptions import list_subscriptions, filter_subscription_ids

logger = logging.getLogger(__name__)


def collect(credential, sub_ids: List[str]) -> Dict[str, "pd.DataFrame"]:
    import pandas as pd
    sheets: Dict[str, pd.DataFrame] = {}
    summary = []

    for sub_id in sub_ids:
        try:
            # ... pull rows for this subscription, append to a sheet ...
            summary.append({"Subscription": sub_id, "Rows": 0})
        except Exception as e:
            logger.error("Pull failed for %s: %s", sub_id, e)
            summary.append({"Subscription": sub_id, "Rows": f"ERROR: {e}"})

    sheets = {"Summary": pd.DataFrame(summary), **sheets}
    return sheets


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    quiet_azure_loggers()

    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        print("ERROR: pandas is required. Install with: pip install --user pandas openpyxl")
        return 1

    config = load_config()
    credential = get_credential()

    subs = list_subscriptions(credential)
    sub_ids = filter_subscription_ids(subs, config)
    if not sub_ids:
        print("No subscriptions in scope. Run configure.py to adjust.")
        return 1

    sheets = collect(credential, sub_ids)

    tenant = config.get("tenant_name", "AZURE-TENANT")
    filename = make_filename(tenant, "my-service", "all")
    return 0 if save_dataframes(sheets, filename) else 1


if __name__ == "__main__":
    sys.exit(main())
```

### Key rules for exporters

- **Use `sslib.auth.get_credential()`** for credentials — never instantiate Azure credential classes directly. The chain is Cloud-Shell-optimized.
- **Call `quiet_azure_loggers()` at the top of `main()`.** Otherwise the Azure SDK floods the terminal with INFO-level HTTP traces.
- **Multi-cloud-safe** — for Microsoft Graph access, use `graph_scope_for_cloud()` to pick the right `.default` scope.
- **No `print()` in `sslib/`.** Library functions return structured data and use module-scoped `logging`. Only exporter scripts and CLI scripts print to console.
- **Output via `make_filename()` + `save_dataframes()`** — never hardcode paths or filenames.
- **Always include a `Summary` sheet** as the first entry in the sheets dict — row counts per logical pull. Per-subscription errors record as a Summary row rather than crashing the whole exporter.
- **Tags column always last** in row schemas.
- **Azure `.list()` returns lazy iterators** — wrap in `list()` to materialize.
- **Filename convention:** `lowercase_underscored.py`.

### Where to put it

All exporters live flat under `scripts/` — they're tenant- or subscription-wide pulls, so categorizing by service type adds noise without value at this scale. If a future exporter genuinely needs subdirectory structure, propose it in the PR.

After adding the script, register it in `stratusscan_azure.py`'s `MENU` so it appears in the launcher and in "Run all":

```python
MENU = {
    "0": ("Configure StratusScan-Azure", _root / "configure.py"),
    "1": ("Resource Graph (full inventory)", SCRIPTS_DIR / "resource_graph_export.py"),
    # ...
    "N": ("My Service", SCRIPTS_DIR / "my_service_export.py"),  # ← add here
}
```

Update `tests/test_smoke.py`'s `EXPORTER_MODULES` list so the import-smoke test covers it.

---

## Code Style

The project uses [ruff](https://github.com/astral-sh/ruff) for linting and [black](https://github.com/psf/black) for formatting.

```bash
ruff check .
black .
```

Config lives in `pyproject.toml`. Line length is 100.

No comments explaining what code does — name things well instead. A comment is only warranted when the *why* is non-obvious: a hidden constraint, a workaround for a specific SDK bug, or a subtle behavioral edge case.

---

## Project Constraints

These are non-negotiable and apply to all contributions:

**Cloud Shell-first** — the tool must work in a fresh Azure Cloud Shell session with no extra setup beyond `pip install`. If a proposed change breaks this, it will be rejected.

**Minimal dependencies** — stick to `azure-identity`, `azure-mgmt-*` (per service), `pandas`, `openpyxl`, `requests`. No heavy frameworks. No lockfiles.

**Subprocess architecture** — `stratusscan_azure.py` launches exporters as subprocesses. It never calls Azure APIs directly. Don't break this boundary.

**No print() in `sslib/`** — `sslib/` is a shared package. Use module-scoped `logging` and return structured data. Only exporter scripts and CLI scripts print to console.

**Multi-cloud aware** — anything that hits Microsoft Graph must use `graph_scope_for_cloud()` to choose the right scope. Anything cloud-specific must read `detect_cloud()` rather than assume Public.

When in doubt about any of these, open an issue and discuss before writing code.
