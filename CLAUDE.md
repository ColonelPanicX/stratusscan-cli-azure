# StratusScanCLI-Azure — Agent Guide

## What This Is

A Python CLI tool that exports Azure resource inventories to Excel workbooks.
Sibling to `stratusscan-cli` (AWS). No shared runtime code — shared philosophy and patterns.

Primary use cases: infrastructure audits, FedRAMP evidence collection, cost optimization.

---

## Critical Design Constraints

Read these before touching any code. They are non-negotiable.

### 1. CloudShell-first
Must work in a fresh Azure Cloud Shell session with no extra setup beyond `pip install`.
If a proposed change breaks this, reject it.

### 2. subprocess architecture
`stratusscan.py` launches exporters as subprocesses. It never calls Azure APIs directly.
Exporters in `scripts/` are fully independent — they can also run directly.

### 3. No print() in utils.py
`utils.py` is a shared library. It must not emit console output. Return structured data.
Only the CLI scripts (stratusscan.py, configure.py, exporter scripts) print to console.

### 4. CI mode
`STRATUSSCAN_AUTO_RUN=1` bypasses all interactive prompts.
`STRATUSSCAN_SUBSCRIPTIONS=sub-id-1,sub-id-2` sets subscriptions non-interactively.
Every interactive prompt must check `utils.is_auto_run()` before displaying.

### 5. TUI-ready design
The North Star is a Textual TUI (v0.3.0+). Design as if something will consume exporter output.
No arbitrary prints in shared code.

---

## Project Structure

```
stratusscan.py              # main menu — launches exporters as subprocesses
configure.py              # subscription/environment config wizard
runner.py                 # exporter console adapter — exit codes + run manifest (may print)
utils.py                  # shared library — imported by every exporter
scripts/                  # all exporters — flat directory, no subdirs
  subscriptions_export.py
  resource_groups_export.py
  virtual_machines_export.py
  managed_disks_export.py
  aks_clusters_export.py
  app_service_export.py
  function_apps_export.py
  virtual_networks_export.py
  subnets_export.py
  network_security_groups_export.py
  public_ips_export.py
  load_balancers_export.py
  application_gateway_export.py
  azure_firewall_export.py
  firewall_policy_rules_export.py
  route_tables_export.py
  vnet_peerings_export.py
  storage_accounts_export.py
  azure_sql_export.py
  cosmos_db_export.py
  key_vault_export.py
  role_assignments_export.py
  policy_assignments_export.py
  management_groups_export.py
  defender_scores_export.py
  defender_assessments_export.py
  advisor_export.py
  metric_alerts_export.py
  action_groups_export.py
  log_analytics_export.py
output/                   # all .xlsx exports land here
logs/                     # per-run log files (14-day retention)
policies/                 # Azure RBAC read-only role definitions
tests/
pyproject.toml
```

---

## Authentication

`DefaultAzureCredential` from `azure-identity`. Auto-detects: Cloud Shell → Azure CLI → Service Principal → Managed Identity.

Never instantiate `azure-mgmt-*` clients directly. Always use `utils.get_azure_client(service_name, subscription_id)`.

Cloud detection order: `AZURE_ENVIRONMENT` env var (unrecognized value → `ValueError`) → explicit `environment` in `config.json` (`government` / `public`; `auto` or unset falls through) → active Azure CLI cloud → `public`.
`config.json` is untracked; `config-template.json` is the shipped shape.

To force government cloud: set `AZURE_ENVIRONMENT=AzureUSGovernment` or `environment: government` in `config.json`.

---

## Exporter Pattern

Every script in `scripts/` must follow this structure exactly:

```python
try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

utils.setup_logging("my-service-export")


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("myservice", environment):
        sys.exit(0)

    client = utils.get_azure_client("myservice", subscription_id)
    resources = list(client.resource_type.list())
    if not resources:
        raise utils.NoResourcesFound("resources")

    errors = []  # per-parent HttpResponseError → utils.error_record(scope, operation, exc)
    filename = utils.create_export_filename(subscription_name, "my-service", "all")
    utils.save_dataframe_to_excel(df, filename, errors=errors)
    return utils.ExportResult(rows=len(df), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "my-service")
```

Azure SDK `.list()` methods return lazy iterators — wrap in `list()` to materialize.

**Failure ≠ empty.** Never wrap a primary listing in `except Exception → []`: a failed call must fail the run. Per-parent loops catch `HttpResponseError` only and record the scope in `errors`, which becomes an `Errors` sheet and exit code 4.

| Exit code | Status | Meaning |
|---|---|---|
| 0 | OK | Workbook written |
| 1 | FAILED | Exception escaped `main` — one console line + hint, traceback in `logs/` |
| 2 | CONFIG | No subscription targeted / bad `AZURE_ENVIRONMENT` / missing package |
| 3 | EMPTY | `utils.NoResourcesFound` — zero resources, no workbook |
| 4 | PARTIAL | Workbook written, ≥1 scope failed — see `Errors` sheet |

`runner.py` appends every outcome to `output/.run-manifest.jsonl` (keyed by `STRATUSSCAN_RUN_ID`); `stratusscan.py` builds `output/run-report-{label}-{run_id}.xlsx` from it and zips only that run's files. Auto-run exits 1 when any exporter is FAILED / TIMEOUT / PARTIAL / CONFIG (EMPTY is fine).

---

## Key utils.py Functions

| Function | Purpose |
|---|---|
| `get_azure_client(service, sub_id)` | Client factory — never call mgmt clients directly |
| `list_subscription_wide(ops, *names)` | First existing subscription-wide list method on an operation group (`list` / `list_by_subscription` naming drifts across majors); raises `AttributeError` naming every method tried — never fall back to a per-RG scan |
| `detect_environment()` | Returns `'public'` or `'government'` |
| `is_service_available_in_environment(svc, env)` | Guard for gov-restricted services |
| `setup_logging(script_name)` | Call once at script start |
| `get_current_timestamp()` | Returns `MM.DD.YYYY` |
| `create_export_filename(sub_name, resource_type, suffix)` | Builds output path |
| `save_dataframe_to_excel(df, filename, errors=None)` | Single-sheet write + column autofit; non-empty `errors` appends an `Errors` sheet |
| `save_multiple_dataframes_to_excel(sheets, filename, errors=None)` | Multi-sheet write; same `Errors` sheet rule |
| `NoResourcesFound(noun)` / `ExportResult(rows, filename, errors)` | Exporter outcome contract consumed by `runner.py` |
| `error_record(scope, operation, exc)` | One `Errors` sheet row (Scope, Operation, Error Code, Message) |
| `record_run_result(**fields)` / `read_run_results(run_id)` | Append / read `output/.run-manifest.jsonl` |
| `archive_outputs(label, run_id=None)` | Zip exports; with `run_id`, only that run's files + report |
| `get_config()` | Thread-safe config.json singleton |
| `is_auto_run()` | CI mode check |
| `get_auto_subscriptions()` | Reads STRATUSSCAN_SUBSCRIPTIONS env var |
| `list_subscriptions()` | Lists all accessible subscriptions |

---

## Output Format

Filename: `{SUBSCRIPTION-NAME}-{resource-type}-{suffix}-export-{MM.DD.YYYY}.xlsx`
All files land in `output/`.

---

## Conventions

- Script filenames: `lowercase_underscored.py`
- Timestamps: `MM.DD.YYYY` via `utils.get_current_timestamp()`
- No comments on what code does — name things well instead
- Output dir: always via `utils.create_export_filename()`, never hardcoded
- Subscription name in filenames: always from config/arg, never hardcoded

---

## Version Roadmap

| Version | Scope |
|---|---|
| v0.1.0 (current) | 21 exporters, Public + Government environments, subscription selector |
| v0.2.0 | Resource Graph Smart Scan, Entra ID exporters (Graph SDK), pricing data |
| v0.3.0+ | Multi-tenant scanning, Textual TUI |

---

## Explicitly Out of Scope for v0.1.0

- Identity/Entra ID exporters (requires Microsoft Graph SDK — separate integration)
- Resource Graph / Smart Scan engine
- Pricing data / cost columns
- Multi-tenant scanning
- Textual TUI
