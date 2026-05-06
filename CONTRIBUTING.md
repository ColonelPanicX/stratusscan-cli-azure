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

# Install runtime dependencies
pip install azure-identity azure-mgmt-resource azure-mgmt-compute azure-mgmt-network \
    azure-mgmt-storage azure-mgmt-keyvault azure-mgmt-authorization \
    azure-mgmt-containerservice azure-mgmt-web azure-mgmt-sql azure-mgmt-cosmosdb \
    pandas openpyxl python-dateutil questionary

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
4. Request a review from the other contributor
5. **One approval is required before merging** (enforced by branch protection)
6. Merge with squash (`--squash`) to keep `dev` history clean
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
    sys.path.append(str(Path(__file__).parent.parent))  # adjust depth for subdirs
    import utils

import pandas as pd

utils.setup_logging("my-service-export")
utils.log_script_start("my_service_export.py", "Azure My Service Export")

log = utils.get_logger()


def collect_resources(subscription_id: str) -> list:
    client = utils.get_azure_client("myservice", subscription_id)
    log.info("Listing resources in subscription %s", subscription_id)
    return list(client.resource_type.list())  # Azure SDK iterators paginate automatically


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("myservice", environment):
        sys.exit(0)

    resources = collect_resources(subscription_id)
    if not resources:
        print("No resources found.")
        return

    rows = []
    for r in resources:
        rg = r.id.split("/resourceGroups/")[1].split("/")[0] if r.id else ""
        tags = r.tags or {}
        rows.append({
            "Name": r.name,
            "Resource Group": rg,
            "Location": r.location,
            # ... resource-specific fields ...
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "my-service", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="My Service")
    print(f"Exported {len(rows)} resource(s) → {filename}")
    log.info("Export complete: %d resources", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
```

### Key rules for exporters

- **Never call `azure-mgmt-*` clients directly.** Always use `utils.get_azure_client(service_name, subscription_id)`.
- **Always call `utils.setup_logging()` at the top.** Before any logic, before any API calls.
- **Always guard with `is_service_available_in_environment()`** — some services aren't available in Azure US Government.
- **No `print()` in `utils.py`.** Only exporter scripts and CLI scripts print to console. `utils.py` returns structured data only.
- **Azure `.list()` methods return lazy iterators** — wrap in `list()` to materialize, or iterate directly for large sets.
- **Tags always go last** in the column order.
- **Script filenames:** `lowercase_underscored.py`

### Where to put it

| Service category | Directory |
|---|---|
| VMs, disks, AKS, App Service, Functions | `scripts/compute/` |
| VNets, subnets, NSGs, firewalls, load balancers | `scripts/network/` |
| Storage accounts, blobs | `scripts/storage/` |
| SQL, Cosmos DB, other databases | `scripts/databases/` |
| Key Vault, RBAC, Defender, Policy | `scripts/security/` |
| Subscription-level, resource groups | `scripts/` (root) |

After adding the script, register it in `azurescan.py` under the appropriate tier (`TIER1_EXPORTERS` or `TIER2_EXPORTERS`).

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

**CloudShell-first** — the tool must work in a fresh Azure Cloud Shell session with no extra setup beyond `pip install`. If a proposed change breaks this, it will be rejected.

**Minimal dependencies** — stick to `azure-identity`, `azure-mgmt-*` (per service), `pandas`, `openpyxl`, `python-dateutil`, `questionary`. No heavy frameworks. No lockfiles. No build tools.

**Subprocess architecture** — `azurescan.py` launches exporters as subprocesses. It never calls Azure APIs directly. Don't break this boundary.

**CI mode** — every interactive prompt must check `utils.is_auto_run()` before displaying. `AZURESCAN_AUTO_RUN=1` must bypass all prompts.

**No print() in utils.py** — `utils.py` is a shared library. Functions return structured results. Only CLI scripts print.

When in doubt about any of these, open an issue and discuss before writing code.
