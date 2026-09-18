# StratusScanCLI-Azure — Agent Guide

## What This Is

A Python CLI tool that exports Azure resource inventories to Excel workbooks.
Sibling to `stratusscan-cli` (AWS). No shared runtime code — shared philosophy and patterns.

Primary use cases: infrastructure audits, FedRAMP evidence collection, cost optimization.

---

## Critical Design Constraints

Read these before touching any code. They are non-negotiable.

### 1. CloudShell-first
Must work in a fresh Azure Cloud Shell session with nothing but `git clone` + `python stratusscan.py`
(`bootstrap.py` installs the pinned dependencies on first run). Not a pip-installed package —
no console entry points. If a proposed change breaks this, reject it.

### 2. subprocess architecture
`stratusscan.py` launches exporters as subprocesses. It never calls Azure APIs directly.
Exporters in `scripts/` are fully independent — they can also run directly.

### 3. No print() in utils.py
`utils.py` is a shared library. It must not emit console output. Return structured data.
Console output belongs in `stratusscan.py`, `configure.py`, `runner.py`, `cli_ui.py` and the
exporter scripts. `utils.py` contains no `print()` and no `input()` — a test asserts it.

### 3a. Importing must have no side effects
Importing any module must not install packages, write files, or call Azure.
`bootstrap.ensure_dependencies()` and `utils.setup_logging()` belong inside `main()`;
`runner.run_exporter()` configures logging once it has resolved the subscription.
A test imports every module and asserts nothing was written.

### 4. CI mode
`STRATUSSCAN_AUTO_RUN=1` bypasses all interactive prompts.
`STRATUSSCAN_SUBSCRIPTIONS=sub-id-1,sub-id-2` sets subscriptions non-interactively.
Every interactive prompt must check `utils.is_auto_run()` before displaying.

### 5. TUI-ready design
The North Star is a Textual TUI (v0.3.0+). Design as if something will consume exporter output.
No arbitrary prints in shared code.

### 6. Pinned SDK majors
Every `azure-*` dependency is capped to a validated major (`>=X,<X+1`). The Azure SDK is mid-migration
to hybrid models; an uncapped bump silently blanks columns or changes enum rendering. To bump one:
raise the cap, run `tests/test_sdk_contract.py` against it, then the full suite on 3.10 and 3.12.
`azure-mgmt-monitor` is held `<7` — 7.x dropped the `diagnostic_settings` operations.

---

## Project Structure

```
stratusscan.py            # main menu + Run All — launches exporters as subprocesses, writes the run report
configure.py              # optional subscription/environment wizard (zero-config is the default path)
runner.py                 # exporter console adapter — flags, exit codes, run manifest (may print)
cli_ui.py                 # menus, prompts, status panel — the only input() in the project
utils.py                  # shared library — print-free
bootstrap.py              # stdlib-only dependency installer, called from main()
config-template.json      # shipped config shape; config.json itself is untracked
scripts/                  # all 70 exporters — flat directory, no subdirs
  # Tier 1 (13)
  subscriptions_export.py
  resource_groups_export.py
  virtual_machines_export.py
  vmss_export.py
  managed_disks_export.py
  virtual_networks_export.py
  subnets_export.py
  network_security_groups_export.py
  public_ips_export.py
  storage_accounts_export.py
  key_vault_export.py
  key_vault_objects_export.py
  role_assignments_export.py
  # Tier 2 (41)
  aks_clusters_export.py
  container_registry_export.py
  container_apps_export.py
  container_instances_export.py
  app_service_export.py
  function_apps_export.py
  azure_sql_export.py
  sql_managed_instance_export.py
  cosmos_db_export.py
  postgresql_flexible_export.py
  mysql_flexible_export.py
  redis_cache_export.py
  load_balancers_export.py
  dns_zones_export.py
  front_door_export.py
  traffic_manager_export.py
  event_hubs_export.py
  service_bus_export.py
  api_management_export.py
  logic_apps_export.py
  application_gateway_export.py
  azure_firewall_export.py
  firewall_policy_rules_export.py
  route_tables_export.py
  vnet_peerings_export.py
  snapshots_export.py
  availability_sets_export.py
  private_endpoints_export.py
  nat_gateways_export.py
  bastion_hosts_export.py
  vpn_gateways_export.py
  expressroute_export.py
  virtual_wan_export.py
  ddos_protection_export.py
  network_watchers_export.py
  service_endpoints_export.py
  blob_containers_export.py
  file_shares_export.py
  automation_accounts_export.py
  batch_accounts_export.py
  recovery_services_vaults_export.py
  # Governance (11)
  policy_assignments_export.py
  management_groups_export.py
  defender_scores_export.py
  defender_assessments_export.py
  advisor_export.py
  resource_locks_export.py
  resource_tags_export.py
  policy_definitions_export.py
  policy_compliance_export.py
  managed_identities_export.py
  cost_management_export.py
  # Monitoring (5)
  metric_alerts_export.py
  action_groups_export.py
  log_analytics_export.py
  diagnostic_settings_export.py
  application_insights_export.py
output/                   # .xlsx exports, .run-manifest.jsonl, run-report-*.xlsx, exports-*.zip
logs/                     # per-run log files (14-day retention)
policies/                 # Azure RBAC read-only role definition + usage notes
docs/                     # philosophy / design notes
.github/workflows/        # CI — pytest on 3.10 + 3.12, ruff
tests/                    # ~840 offline tests; see below
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

log = utils.get_logger()  # runner.run_exporter() configures logging; importing must write nothing


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
| `setup_logging(script_name, log_to_file=True, subscription_id=None)` | Called by `runner.py`, not by exporters |
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
| `list_subscriptions()` | Lists all accessible subscriptions; raises `AzureAccessError` on auth/HTTP failure — an empty list always means zero subscriptions |
| `resolve_target_subscription()` | `(id, name)` from the env vars the orchestrator injects, else the config default |
| `extract_resource_group(resource_id)` | Case-insensitive; never split on `"/resourceGroups/"` yourself |
| `s(value)` | Cell-safe string: `None` → `""`, Enum → `.value`. Never `str()` an SDK attribute |
| `get_credential()` | Shared credential for data-plane SDKs (Key Vault keys/secrets/certs) — the one exception to "never instantiate clients directly" |
| `detect_azure_cloud()` | Active cloud from the Azure CLI config, or `None` |
| `save_config(data)` / `reload_config()` | Write `config.json` / drop the cached copy |
| `get_subscription_name(sub_id)` / `get_version()` | Display helpers |
| `AzureAccessError` | Raised when Azure refuses or cannot be reached; carries the SDK error as `__cause__` plus a `.hint` |
| `output_dir()` | Resolved output directory — `--output-dir` / `STRATUSSCAN_OUTPUT_DIR` / config / `output/` |
| `is_subscription_id(value)` | GUID shape check for user-supplied subscription IDs |
| `set_console_level(level)` | Backs `--verbose` |

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
- Annotations use PEP 604 (`X | None`, `list[str]`) — the floor is Python 3.10 and `ruff check .` must stay at 0
- Tests are offline and need no credentials. Run the suite on **both** 3.10 and 3.12; CI does the same and also runs ruff.
  `tests/test_sdk_contract.py` pins the SDK call shapes the exporters rely on, `tests/test_exporter_contract.py` pins the
  exporter pattern and `registry == disk == 70`, `tests/test_exporter_smoke.py` runs every `main()` against an empty client
  and asserts importing writes nothing.

---

## Version Roadmap

| Version | Scope |
|---|---|
| v0.1.0 (current) | 70 exporters, Public + Government environments, subscription selector |
| v0.2.0 | Resource Graph Smart Scan, Entra ID exporters (Graph SDK), pricing data |
| v0.3.0+ | Multi-tenant scanning, Textual TUI |

---

## Explicitly Out of Scope for v0.1.0

- Identity/Entra ID exporters (requires Microsoft Graph SDK — separate integration)
- Resource Graph / Smart Scan engine
- Pricing data / cost columns
- Multi-tenant scanning
- Textual TUI
