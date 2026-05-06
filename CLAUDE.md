# StratusScan-Azure — Agent Guide

## What This Is

A Python CLI tool that exports Azure resource inventories to Excel workbooks.
Sibling to `stratusscan-cli` (AWS). No shared runtime code — shared philosophy and patterns.

Primary use cases: infrastructure audits, FedRAMP evidence collection, cost optimization.

---

## Critical Design Constraints

Read these before touching any code. They are non-negotiable.

### 1. Cloud Shell-first
Must work in a fresh Azure Cloud Shell session with no extra setup beyond `pip install`.
If a proposed change breaks this, reject it.

### 2. Subprocess architecture
`stratusscan_azure.py` is a thin launcher that subprocesses individual exporter scripts. It never calls Azure APIs directly.
Exporters in `scripts/` are fully independent — they can also run directly via `python scripts/<name>.py`.

### 3. No print() in `sslib/`
The `sslib/` package is a shared library. It must not emit console output. Use module-scoped `logging` and return structured data.
Only the CLI scripts (`stratusscan_azure.py`, `configure.py`, exporter scripts) print to console.

### 4. Multi-cloud aware
Public, US Government, and China clouds are detected via `sslib.cloud.detect_cloud()` (which reads `az cloud show`). Microsoft Graph endpoints differ per cloud — exporters that hit Graph must use `graph_scope_for_cloud()` for the right `.default` scope.

### 5. TUI-ready design
The North Star is a Textual TUI (v1.0+). Design as if something will consume exporter output.
No arbitrary prints in shared code; structured logging only.

---

## Project Structure

```
stratusscan_azure.py     # main menu — launches exporter scripts as subprocesses
configure.py             # interactive config wizard
sslib/                   # shared library (no console output)
  auth.py                # credential chain (Cloud Shell → CLI → managed identity → SP)
  cloud.py               # active-cloud detection (Public/USGov/China) + Graph endpoints
  config.py              # config.json read/write
  output.py              # output paths, filename convention, multi-sheet xlsx writer
  subscriptions.py       # subscription/tenant enumeration + scope filtering
scripts/                 # exporters — each runs standalone
  resource_graph_export.py
  entra_id_export.py
  rbac_export.py
  policy_export.py
output/                  # .xlsx exports (or ~/clouddrive/stratusscan-azure/output/ in Cloud Shell)
config-template.json     # copy to config.json and customize
tests/test_smoke.py
pyproject.toml
```

---

## Authentication

`sslib.auth.get_credential()` returns a `ChainedTokenCredential` that prefers `AzureCliCredential` (instant in Cloud Shell and on `az login`-configured boxes) before falling back to `DefaultAzureCredential` (managed identity, env-var service principal, VS Code, etc.). The CLI-first ordering avoids the managed-identity probe timeout that bare `DefaultAzureCredential` adds.

For Microsoft Graph access (Entra ID exporter), call `get_graph_token(credential, graph_scope_for_cloud())` to get a bearer token scoped to the active cloud's Graph endpoint.

Never instantiate Azure credential classes directly — always go through `get_credential()`.

---

## Exporter Pattern

Every script in `scripts/` runs independently and follows this shape:

```python
import logging
import sys
from pathlib import Path

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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    quiet_azure_loggers()

    config = load_config()
    credential = get_credential()
    cloud = detect_cloud()

    subs = list_subscriptions(credential)
    sub_ids = filter_subscription_ids(subs, config)

    # ... pull data, build {sheet_name: DataFrame} ...
    sheets = {"Summary": summary_df, **data_sheets}

    tenant = config.get("tenant_name", "AZURE-TENANT")
    filename = make_filename(tenant, "my-export", "all")
    return 0 if save_dataframes(sheets, filename) else 1


if __name__ == "__main__":
    sys.exit(main())
```

Rules:
- `quiet_azure_loggers()` at the top of `main()` — the Azure SDK's per-request HTTP logging is INFO-level by default and otherwise floods the terminal.
- Always make `Summary` the first sheet — row counts per logical pull, with errors recorded as a row rather than a crash.
- Read scope from `config.json` via `load_config()` and let `filter_subscription_ids()` resolve the active subscription list.
- Azure SDK `.list()` methods return lazy iterators — wrap in `list()` to materialize.

---

## Key sslib Functions

| Function | Module | Purpose |
|---|---|---|
| `get_credential()` | `auth` | Cloud-Shell-friendly chained credential |
| `get_graph_token(cred, scope)` | `auth` | Bearer token for Microsoft Graph |
| `quiet_azure_loggers()` | `auth` | Silence `azure.*` / `msal` INFO chatter |
| `detect_cloud()` | `cloud` | `{name, graph_endpoint}` from `az cloud show` |
| `graph_scope_for_cloud()` | `cloud` | `.default` scope URL for active cloud |
| `is_government_cloud()` | `cloud` | Gov-cloud check |
| `load_config()` / `save_config()` | `config` | Read / atomic-write `config.json` |
| `get_subscription_label(cfg, sub_id, fallback)` | `config` | Friendly-name lookup |
| `list_subscriptions(credential)` | `subscriptions` | `[{id, name, tenant_id, state}]` for accessible subs |
| `list_tenants(credential)` | `subscriptions` | Tenants the identity can see |
| `filter_subscription_ids(subs, config)` | `subscriptions` | Apply `default_scope` (`all` / `selected`) |
| `is_cloud_shell()` | `output` | True when `ACC_CLOUD` is set |
| `get_output_dir()` | `output` | `~/clouddrive/.../output` in Cloud Shell, else `./output` |
| `make_filename(scope, type, suffix)` | `output` | `{SCOPE}-{type}-{suffix}-export-{MM.DD.YYYY}.xlsx` (handles same-day collisions with `-v2`, `-v3`) |
| `save_dataframes(sheets, filename)` | `output` | Multi-sheet write with column autofit |

---

## Output Format

Filename: `{SCOPE}-{exporter}-{suffix}-export-{MM.DD.YYYY}.xlsx`
`{SCOPE}` is the tenant label (for tenant-wide exporters) or subscription friendly name.

Files land in `~/clouddrive/stratusscan-azure/output/` in Cloud Shell (persistent across session timeouts) or `<project>/output/` elsewhere. Same-day re-runs append `-v2`, `-v3`, … so previous exports aren't clobbered.

Each xlsx is multi-sheet — one sheet per Resource Graph table or Microsoft Graph endpoint, plus a `Summary` sheet with row counts.

---

## Conventions

- Script filenames: `lowercase_underscored.py`
- Timestamps: `MM.DD.YYYY` baked into `make_filename()`
- No comments on what code does — name things well instead. Comments only for non-obvious *why*.
- Output paths: always via `make_filename()` + `save_dataframes()`, never hardcoded.
- Tenant/subscription labels in filenames: from `config.json`, never hardcoded.
- Tags column always last in row schemas.

---

## Version Roadmap

| Version | Scope |
|---|---|
| v0.1.0-alpha (current) | Resource Graph, Entra ID, RBAC, Policy — Public + USGov + China detection |
| v0.2 | Cost Management, Defender for Cloud (full), Activity Log, Smart Scan orchestration, NSG flat-rule export, Storage encryption deep-dive |
| v0.3 | Concurrent subscription scanning, Management Group scope, pivot-friendly sheet splits |
| v1.0 | Textual TUI matching the AWS-side roadmap, per-service Reader-role policy bundles |

See `README.md` for the detailed list.

---

## Explicitly Out of Scope (v0.1.0-alpha)

- Cost Management / pricing data
- Defender for Cloud full alerts beyond what Resource Graph exposes
- Activity Log + Diagnostic Settings audit
- Smart Scan engine (discover-then-export auto-orchestration)
- Concurrent / multi-tenant scanning
- Textual TUI
